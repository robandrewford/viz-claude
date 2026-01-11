"""viz-agent daemon - manages classification, state, and renderer communication."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from ..core import SessionMetadata, UserPreferences
from ..core.classifier import ClassificationStateMachine, HeuristicClassifier
from ..core.protocol import (
    CategoryMessage,
    CompositionMessage,
    ShutdownMessage,
    SocketServer,
    StatusMessage,
    TemplateMessage,
    TriggerMessage,
)
from ..storage import get_storage
from ..templates import get_loader

logger = logging.getLogger(__name__)


class VizAgent:
    """
    Central agent daemon.
    
    Responsibilities:
    - Receive events from wrapper
    - Classify conversations
    - Send triggers to renderer
    - Manage session state
    - Persist data
    """

    def __init__(self) -> None:
        self.server = SocketServer()
        self.storage = get_storage()
        self.template_loader = get_loader()

        # Classification
        self.classifier = HeuristicClassifier()
        self.state_machine = ClassificationStateMachine()

        # Session state
        self.session_id = str(uuid.uuid4())
        self.session_start = datetime.now(timezone.utc)
        self.current_category: str | None = None
        self.current_template: dict[str, Any] | None = None
        self.composition = "default"
        self.message_count = 0
        self.trigger_counts: dict[str, int] = {}
        self.tool_use_breakdown: dict[str, int] = {}

        # Control
        self.running = False
        self._renderer_connected = False

    async def start(self) -> None:
        """Start the agent."""
        self.running = True

        # Load user preferences
        profile = self.storage.get_or_create_profile()
        self.classifier = HeuristicClassifier(preferences=profile.preferences)

        # Start socket server
        await self.server.start(self._handle_client)

        logger.info(f"viz-agent started, session {self.session_id}")

        # Handle signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Run until stopped
        while self.running:
            await asyncio.sleep(1)

            # Periodic classification check
            if self.state_machine.should_classify():
                await self._classify()

    async def stop(self) -> None:
        """Stop the agent and save session."""
        self.running = False

        # Save session
        self._save_session()

        # Notify renderer
        await self.server.broadcast(ShutdownMessage())

        # Stop server
        await self.server.stop()

        logger.info("viz-agent stopped")

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a client connection (wrapper or renderer)."""
        client_type = "unknown"

        try:
            async for line in reader:
                if not line:
                    break

                import json
                msg = json.loads(line.decode("utf-8").strip())
                msg_type = msg.get("msg", "")

                # Determine client type from first message
                if client_type == "unknown":
                    if msg_type == "event":
                        client_type = "wrapper"
                        logger.debug("Wrapper connected")
                    elif msg_type == "renderer_hello":
                        client_type = "renderer"
                        self._renderer_connected = True
                        logger.debug("Renderer connected")
                        # Send current template
                        if self.current_template:
                            await self._send_to_writer(
                                writer,
                                TemplateMessage(data=self.current_template),
                            )

                # Handle message
                response = await self._handle_message(msg, client_type)

                # Send response if any
                if response:
                    await self._send_to_writer(writer, response)

        except Exception as e:
            logger.debug(f"Client error: {e}")

        finally:
            if client_type == "renderer":
                self._renderer_connected = False

    async def _send_to_writer(self, writer: asyncio.StreamWriter, msg: Any) -> None:
        """Send message to a specific writer."""
        from ..core.protocol import encode_message
        writer.write(encode_message(msg))
        await writer.drain()

    async def _handle_message(
        self,
        msg: dict[str, Any],
        client_type: str,
    ) -> Any | None:
        """Handle incoming message and return response if needed."""
        msg_type = msg.get("msg", "")

        if msg_type == "event":
            await self._handle_event(msg)
            return None

        elif msg_type == "command":
            return await self._handle_command(msg)

        elif msg_type == "renderer_hello":
            # Send current state
            return StatusMessage(
                running=True,
                category=self.current_category,
                confidence=self.state_machine.current_classification.confidence
                    if self.state_machine.current_classification else None,
                composition=self.composition,
            )

        return None

    async def _handle_event(self, msg: dict[str, Any]) -> None:
        """Handle event from wrapper."""
        event_type = msg.get("event_type", "")
        data = msg.get("data", {})

        # Track triggers
        if event_type in ("thinking_start", "tool_use", "response_start", "error"):
            self.trigger_counts[event_type] = self.trigger_counts.get(event_type, 0) + 1

        # Handle specific events
        if event_type == "thinking_start":
            await self.server.broadcast(TriggerMessage(name="thinking", active=True))

        elif event_type == "thinking_end":
            await self.server.broadcast(TriggerMessage(name="thinking", active=False))

        elif event_type == "tool_use":
            tool = data.get("tool", "unknown")
            snippet = data.get("snippet", "")

            # Track for classification
            self.classifier.add_tool_use(tool, snippet)
            self.tool_use_breakdown[tool] = self.tool_use_breakdown.get(tool, 0) + 1

            # Get intensity from emitter config
            intensity = 1.0
            if self.current_template:
                for emitter in self.current_template.get("emitters", {}).values():
                    intensity = emitter.get("intensity_map", {}).get(tool, 1.0)
                    break

            await self.server.broadcast(TriggerMessage(
                name="tool_use",
                active=True,
                tool=tool,
                intensity=intensity,
            ))

        elif event_type == "response_start":
            await self.server.broadcast(TriggerMessage(name="response_start", active=True))

        elif event_type == "response_end":
            content = data.get("content", "")
            self.classifier.add_content(content)
            self.message_count += 1
            self.state_machine.on_message()
            await self.server.broadcast(TriggerMessage(name="response_start", active=False))

        elif event_type == "user_message":
            content = data.get("content", "")
            self.classifier.add_content(content)
            self.message_count += 1
            self.state_machine.on_message()

        elif event_type == "error":
            await self.server.broadcast(TriggerMessage(name="error", active=True))

        elif event_type == "idle":
            await self.server.broadcast(TriggerMessage(name="idle", active=data.get("active", True)))

    async def _handle_command(self, msg: dict[str, Any]) -> Any:
        """Handle command from wrapper."""
        command = msg.get("name", "")
        args = msg.get("args", [])

        if command == "toggle":
            # Toggle viz on/off
            return StatusMessage(
                running=self.running,
                category=self.current_category,
                confidence=self.state_machine.current_classification.confidence
                    if self.state_machine.current_classification else None,
                composition=self.composition,
            )

        elif command == "set" and args:
            # Force category
            category = args[0]
            await self._set_category(category, confidence=1.0, reason="user_override")
            return {"msg": "ok", "message": f"Category set to {category}"}

        elif command == "reclassify":
            # Force immediate reclassification
            self.state_machine.force_reclassify()
            result = await self._classify()
            return {
                "msg": "ok",
                "category": result.category,
                "confidence": result.confidence,
            }

        elif command in ("default", "active", "minimal"):
            # Set composition
            self.composition = command
            await self.server.broadcast(CompositionMessage(value=command))
            return {"msg": "ok", "message": f"Composition set to {command}"}

        elif command == "status":
            return StatusMessage(
                running=self.running,
                category=self.current_category,
                confidence=self.state_machine.current_classification.confidence
                    if self.state_machine.current_classification else None,
                composition=self.composition,
            )

        elif command == "off":
            # Disable viz
            await self.server.broadcast(ShutdownMessage())
            return {"msg": "ok", "message": "Visualization disabled"}

        else:
            return {"msg": "error", "message": f"Unknown command: {command}"}

    async def _classify(self) -> Any:
        """Run classification and update state."""
        result = self.classifier.classify()
        self.state_machine.on_classification(result)

        # Check for category change
        if result.category != self.current_category:
            await self._set_category(
                result.category,
                confidence=result.confidence,
                reason="auto_classify",
            )

        return result

    async def _set_category(
        self,
        category: str,
        confidence: float,
        reason: str,
    ) -> None:
        """Set current category and load template."""
        self.current_category = category

        # Load template
        template = self.template_loader.load(category)
        self.current_template = template.model_dump()

        # Notify renderer
        await self.server.broadcast(CategoryMessage(value=category, confidence=confidence))
        await self.server.broadcast(TemplateMessage(data=self.current_template))

        logger.info(f"Category changed to {category} ({confidence:.0%}, {reason})")

    def _save_session(self) -> None:
        """Save current session to storage."""
        session = SessionMetadata(
            session_id=self.session_id,
            user_id="local",
            started_at=self.session_start,
            ended_at=datetime.now(timezone.utc),
            category=self.current_category,
            category_confidence=self.state_machine.current_classification.confidence
                if self.state_machine.current_classification else None,
            category_signals=self.state_machine.current_classification.signals
                if self.state_machine.current_classification else [],
            trigger_counts=self.trigger_counts,
            tool_use_breakdown=self.tool_use_breakdown,
            message_count=self.message_count,
        )

        self.storage.save_session(session)
        logger.debug(f"Session {self.session_id} saved")


def main() -> int:
    """Entry point for viz-agent."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    agent = VizAgent()

    try:
        asyncio.run(agent.start())
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
