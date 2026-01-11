"""Socket protocol for IPC between wrapper, agent, and renderer."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def get_socket_path() -> Path:
    """Get the Unix socket path for this user."""
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR", f"/tmp/viz-claude-{os.getuid()}")
    path = Path(runtime_dir) / "viz-claude.sock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


# =============================================================================
# Protocol Messages
# =============================================================================


class TriggerMessage(BaseModel):
    """Trigger activation message to renderer."""

    msg: str = "trigger"
    name: str
    active: bool = True
    tool: str | None = None
    intensity: float = 1.0


class CategoryMessage(BaseModel):
    """Category change message to renderer."""

    msg: str = "category"
    value: str
    confidence: float


class TemplateMessage(BaseModel):
    """Full template data to renderer."""

    msg: str = "template"
    data: dict[str, Any]


class CompositionMessage(BaseModel):
    """Composition change message."""

    msg: str = "composition"
    value: str


class CommandMessage(BaseModel):
    """User command from wrapper to agent."""

    msg: str = "command"
    name: str
    args: list[str] = Field(default_factory=list)


class EventMessage(BaseModel):
    """Event from wrapper to agent."""

    msg: str = "event"
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)


class StatusMessage(BaseModel):
    """Status response from agent."""

    msg: str = "status"
    running: bool
    category: str | None
    confidence: float | None
    composition: str


class ShutdownMessage(BaseModel):
    """Shutdown signal."""

    msg: str = "shutdown"


ProtocolMessage = (
    TriggerMessage
    | CategoryMessage
    | TemplateMessage
    | CompositionMessage
    | CommandMessage
    | EventMessage
    | StatusMessage
    | ShutdownMessage
)


def encode_message(msg: ProtocolMessage) -> bytes:
    """Encode a message for transmission."""
    return (msg.model_dump_json() + "\n").encode("utf-8")


def decode_message(data: bytes) -> dict[str, Any]:
    """Decode a message from bytes."""
    return json.loads(data.decode("utf-8").strip())


# =============================================================================
# Async Socket Client
# =============================================================================


class SocketClient:
    """Async Unix socket client."""

    def __init__(self, path: Path | None = None):
        self.path = path or get_socket_path()
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connected = False

    async def connect(self, timeout: float = 5.0) -> bool:
        """
        Connect to the socket server.
        
        Args:
            timeout: Connection timeout in seconds
            
        Returns:
            True if connected successfully
        """
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_unix_connection(str(self.path)),
                timeout=timeout,
            )
            self._connected = True
            logger.debug(f"Connected to {self.path}")
            return True
        except (ConnectionRefusedError, FileNotFoundError, asyncio.TimeoutError) as e:
            logger.debug(f"Connection failed: {e}")
            self._connected = False
            return False

    async def send(self, msg: ProtocolMessage) -> None:
        """Send a message to the server."""
        if not self._writer or not self._connected:
            raise ConnectionError("Not connected")
        
        data = encode_message(msg)
        self._writer.write(data)
        await self._writer.drain()

    async def receive(self) -> dict[str, Any] | None:
        """Receive a single message."""
        if not self._reader or not self._connected:
            return None
        
        try:
            line = await self._reader.readline()
            if not line:
                self._connected = False
                return None
            return decode_message(line)
        except Exception as e:
            logger.error(f"Receive error: {e}")
            self._connected = False
            return None

    async def iter_messages(self) -> AsyncIterator[dict[str, Any]]:
        """Iterate over incoming messages."""
        while self._connected:
            msg = await self.receive()
            if msg is None:
                break
            yield msg

    async def close(self) -> None:
        """Close the connection."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        self._connected = False
        self._reader = None
        self._writer = None

    @property
    def connected(self) -> bool:
        return self._connected


# =============================================================================
# Async Socket Server
# =============================================================================


class SocketServer:
    """Async Unix socket server."""

    def __init__(self, path: Path | None = None):
        self.path = path or get_socket_path()
        self._server: asyncio.Server | None = None
        self._clients: list[asyncio.StreamWriter] = []
        self._running = False

    async def start(self, handler: Any) -> None:
        """
        Start the server.
        
        Args:
            handler: Async callback(reader, writer) for new connections
        """
        # Remove stale socket
        if self.path.exists():
            self.path.unlink()

        self._server = await asyncio.start_unix_server(
            self._wrap_handler(handler),
            path=str(self.path),
        )
        self._running = True
        logger.info(f"Server listening on {self.path}")

    def _wrap_handler(self, handler: Any) -> Any:
        """Wrap handler to track clients."""
        async def wrapped(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            self._clients.append(writer)
            try:
                await handler(reader, writer)
            finally:
                self._clients.remove(writer)
                writer.close()
                await writer.wait_closed()
        return wrapped

    async def broadcast(self, msg: ProtocolMessage) -> None:
        """Send message to all connected clients."""
        data = encode_message(msg)
        dead_clients = []

        for writer in self._clients:
            try:
                writer.write(data)
                await writer.drain()
            except Exception:
                dead_clients.append(writer)

        for writer in dead_clients:
            self._clients.remove(writer)

    async def stop(self) -> None:
        """Stop the server."""
        self._running = False

        # Close all clients
        for writer in self._clients:
            writer.close()
        self._clients.clear()

        # Stop server
        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Remove socket file
        if self.path.exists():
            self.path.unlink()

    @property
    def running(self) -> bool:
        return self._running

    @property
    def client_count(self) -> int:
        return len(self._clients)
