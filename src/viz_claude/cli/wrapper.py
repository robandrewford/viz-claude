"""Wrapper for Claude Code CLI that emits events to viz-agent."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
from typing import Any

from ..core.events import CommandParser, OutputParser, UserMessageEvent
from ..core.protocol import (
    CommandMessage,
    EventMessage,
    SocketClient,
    get_socket_path,
)

logger = logging.getLogger(__name__)


class ClaudeWrapper:
    """
    Wrapper for Claude Code CLI.
    
    - Spawns claude as subprocess
    - Passes through stdin/stdout/stderr
    - Parses output for events
    - Sends events to viz-agent
    """

    def __init__(self, claude_args: list[str]):
        self.claude_args = claude_args
        self.socket = SocketClient()
        self.output_parser = OutputParser()
        self.command_parser = CommandParser()
        self.process: asyncio.subprocess.Process | None = None
        self.running = False
        self._response_buffer = ""

    async def run(self) -> int:
        """
        Run the wrapper.
        
        Returns:
            Exit code from claude process
        """
        # Find claude executable
        claude_path = shutil.which("claude")
        if not claude_path:
            print("Error: 'claude' command not found in PATH", file=sys.stderr)
            return 1

        # Connect to agent (optional - viz works without agent)
        agent_connected = await self.socket.connect(timeout=1.0)
        if agent_connected:
            logger.debug("Connected to viz-agent")
        else:
            logger.debug("viz-agent not running, visualization disabled")

        # Start claude process
        self.process = await asyncio.create_subprocess_exec(
            claude_path,
            *self.claude_args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self.running = True

        # Handle signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # Run tasks
        try:
            await asyncio.gather(
                self._read_stdout(),
                self._read_stderr(),
                self._handle_stdin(),
            )
        except asyncio.CancelledError:
            pass
        finally:
            self.running = False
            if self.socket.connected:
                await self.socket.close()

        # Wait for process and return exit code
        if self.process:
            await self.process.wait()
            return self.process.returncode or 0

        return 0

    def _handle_signal(self) -> None:
        """Handle interrupt signals."""
        self.running = False
        if self.process:
            self.process.terminate()

    async def _read_stdout(self) -> None:
        """Read and process stdout from claude."""
        if not self.process or not self.process.stdout:
            return

        while self.running:
            try:
                chunk = await self.process.stdout.read(1024)
                if not chunk:
                    break

                # Decode
                text = chunk.decode("utf-8", errors="replace")

                # Pass through to user
                sys.stdout.write(text)
                sys.stdout.flush()

                # Buffer for response tracking
                self._response_buffer += text

                # Parse for events
                events = self.output_parser.parse(text)

                # Send events to agent
                if self.socket.connected:
                    for event in events:
                        await self._send_event(event)

            except Exception as e:
                logger.debug(f"stdout read error: {e}")
                break

    async def _read_stderr(self) -> None:
        """Read and pass through stderr from claude."""
        if not self.process or not self.process.stderr:
            return

        while self.running:
            try:
                chunk = await self.process.stderr.read(1024)
                if not chunk:
                    break

                # Pass through
                sys.stderr.write(chunk.decode("utf-8", errors="replace"))
                sys.stderr.flush()

            except Exception as e:
                logger.debug(f"stderr read error: {e}")
                break

    async def _handle_stdin(self) -> None:
        """Read stdin and pass to claude, intercepting /viz commands."""
        if not self.process or not self.process.stdin:
            return

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        # Connect stdin to reader
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while self.running:
            try:
                line = await reader.readline()
                if not line:
                    break

                text = line.decode("utf-8", errors="replace")

                # Check for /viz command
                cmd = self.command_parser.parse(text.strip())
                if cmd:
                    await self._handle_viz_command(cmd[0], cmd[1])
                    continue

                # Pass to claude
                self.process.stdin.write(line)
                await self.process.stdin.drain()

                # Record user message
                if self.socket.connected:
                    await self._send_event(UserMessageEvent(content=text))

            except Exception as e:
                logger.debug(f"stdin read error: {e}")
                break

    async def _handle_viz_command(self, command: str, args: list[str]) -> None:
        """Handle a /viz command."""
        if not self.socket.connected:
            print("viz-agent not running. Start with: viz-agent", file=sys.stderr)
            return

        # Send command to agent
        msg = CommandMessage(name=command, args=args)
        await self.socket.send(msg)

        # Wait for response
        try:
            response = await asyncio.wait_for(self.socket.receive(), timeout=2.0)
            if response:
                self._print_command_response(response)
        except asyncio.TimeoutError:
            print("viz-agent did not respond", file=sys.stderr)

    def _print_command_response(self, response: dict[str, Any]) -> None:
        """Print response from agent."""
        msg_type = response.get("msg", "")

        if msg_type == "status":
            running = response.get("running", False)
            category = response.get("category", "none")
            confidence = response.get("confidence", 0)
            print(f"viz: {'running' if running else 'stopped'}, category={category} ({confidence:.0%})")

        elif msg_type == "error":
            print(f"viz error: {response.get('message', 'unknown')}", file=sys.stderr)

        elif msg_type == "ok":
            print(f"viz: {response.get('message', 'ok')}")

        else:
            # Generic response
            for key, value in response.items():
                if key != "msg":
                    print(f"  {key}: {value}")

    async def _send_event(self, event: Any) -> None:
        """Send event to agent."""
        if not self.socket.connected:
            return

        try:
            msg = EventMessage(
                event_type=event.type.value if hasattr(event.type, "value") else str(event.type),
                data=event.model_dump(exclude={"type", "timestamp"}),
            )
            await self.socket.send(msg)
        except Exception as e:
            logger.debug(f"Failed to send event: {e}")


def run_wrapper(claude_args: list[str]) -> int:
    """
    Entry point for wrapper.
    
    Args:
        claude_args: Arguments to pass to claude
        
    Returns:
        Exit code
    """
    wrapper = ClaudeWrapper(claude_args)
    return asyncio.run(wrapper.run())
