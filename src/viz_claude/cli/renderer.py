"""viz-renderer - standalone visualization window."""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys

from ..core.protocol import SocketClient
from ..render import AnimationEngine, Terminal
from ..templates import get_loader

logger = logging.getLogger(__name__)


class VizRenderer:
    """
    Standalone renderer process.
    
    Connects to viz-agent and renders animations based on triggers.
    Runs in a separate terminal window/tab.
    """

    def __init__(self) -> None:
        self.socket = SocketClient()
        self.terminal = Terminal(sanitize=True)
        self.template_loader = get_loader()
        self.engine: AnimationEngine | None = None
        self.trigger_queue: asyncio.Queue = asyncio.Queue()
        self.running = False

    async def start(self) -> None:
        """Start the renderer."""
        self.running = True

        # Handle signals
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_signal)

        # Connect to agent
        connected = await self.socket.connect(timeout=10.0)
        if not connected:
            print("Could not connect to viz-agent. Start it with: viz-agent", file=sys.stderr)
            return

        # Send hello
        await self.socket.send({"msg": "renderer_hello"})

        # Load default template
        template = self.template_loader.load("_fallback")
        self.engine = AnimationEngine(template, self.terminal)

        # Start tasks
        try:
            await asyncio.gather(
                self._receive_messages(),
                self._run_animation(),
            )
        except asyncio.CancelledError:
            pass
        finally:
            await self.socket.close()

    def _handle_signal(self) -> None:
        """Handle interrupt."""
        self.running = False
        if self.engine:
            self.engine.stop()

    async def _receive_messages(self) -> None:
        """Receive messages from agent."""
        async for msg in self.socket.iter_messages():
            if not self.running:
                break

            await self._handle_message(msg)

    async def _handle_message(self, msg: dict) -> None:
        """Handle message from agent."""
        msg_type = msg.get("msg", "")

        if msg_type == "trigger":
            # Forward to animation engine
            await self.trigger_queue.put(msg)

        elif msg_type == "template":
            # Load new template
            template_data = msg.get("data", {})
            if template_data and self.engine:
                self.engine.load_template(template_data)

        elif msg_type == "category":
            # Category changed - template should follow
            category = msg.get("value", "")
            confidence = msg.get("confidence", 0)
            logger.debug(f"Category: {category} ({confidence:.0%})")

        elif msg_type == "composition":
            # Switch composition
            composition = msg.get("value", "default")
            if self.engine:
                self.engine.set_composition(composition)

        elif msg_type == "shutdown":
            # Agent shutting down
            self.running = False
            if self.engine:
                self.engine.stop()

        elif msg_type == "status":
            # Initial status
            category = msg.get("category")
            if category and self.engine:
                template = self.template_loader.load(category)
                self.engine.load_template(template.model_dump())

    async def _run_animation(self) -> None:
        """Run the animation loop."""
        if not self.engine:
            return

        await self.engine.run(self.trigger_queue)


def spawn_renderer_window() -> bool:
    """
    Spawn a new terminal window for the renderer.
    
    Returns:
        True if spawned successfully
    """
    import shutil
    import subprocess

    # Check for iTerm
    if sys.platform == "darwin":
        # Try AppleScript for iTerm
        script = '''
        tell application "iTerm"
            activate
            tell current window
                create tab with default profile
                tell current session
                    write text "viz-renderer"
                end tell
            end tell
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

        # Try Terminal.app
        script = '''
        tell application "Terminal"
            activate
            do script "viz-renderer"
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # Linux - try common terminal emulators
    terminals = [
        ("gnome-terminal", ["gnome-terminal", "--", "viz-renderer"]),
        ("konsole", ["konsole", "-e", "viz-renderer"]),
        ("xterm", ["xterm", "-e", "viz-renderer"]),
    ]

    for name, cmd in terminals:
        if shutil.which(cmd[0]):
            try:
                subprocess.Popen(cmd)
                return True
            except Exception:
                continue

    return False


def main() -> int:
    """Entry point for viz-renderer."""
    logging.basicConfig(
        level=logging.WARNING,  # Quiet by default
        format="%(message)s",
    )

    renderer = VizRenderer()

    try:
        asyncio.run(renderer.start())
    except KeyboardInterrupt:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
