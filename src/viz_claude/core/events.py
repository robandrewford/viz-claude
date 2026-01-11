"""Event types and parsing from Claude Code output."""

from __future__ import annotations

import re
import time
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of events detected from Claude Code output."""

    THINKING_START = "thinking_start"
    THINKING_END = "thinking_end"
    TOOL_USE = "tool_use"
    RESPONSE_START = "response_start"
    RESPONSE_END = "response_end"
    TOKEN = "token"
    ERROR = "error"
    USER_MESSAGE = "user_message"
    IDLE = "idle"


class Event(BaseModel):
    """Base event from wrapper to agent."""

    type: EventType
    timestamp: float = Field(default_factory=time.time)


class ThinkingStartEvent(Event):
    """Claude started thinking."""

    type: Literal[EventType.THINKING_START] = EventType.THINKING_START


class ThinkingEndEvent(Event):
    """Claude finished thinking."""

    type: Literal[EventType.THINKING_END] = EventType.THINKING_END


class ToolUseEvent(Event):
    """Claude called a tool."""

    type: Literal[EventType.TOOL_USE] = EventType.TOOL_USE
    tool: str
    snippet: str = ""  # First 200 chars of tool input for classification


class ResponseStartEvent(Event):
    """Claude started streaming response."""

    type: Literal[EventType.RESPONSE_START] = EventType.RESPONSE_START


class ResponseEndEvent(Event):
    """Claude finished response."""

    type: Literal[EventType.RESPONSE_END] = EventType.RESPONSE_END
    content: str = ""  # Full response for classification


class TokenEvent(Event):
    """Token received (throttled)."""

    type: Literal[EventType.TOKEN] = EventType.TOKEN
    chunk: str


class ErrorEvent(Event):
    """Error occurred."""

    type: Literal[EventType.ERROR] = EventType.ERROR
    message: str


class UserMessageEvent(Event):
    """User sent a message."""

    type: Literal[EventType.USER_MESSAGE] = EventType.USER_MESSAGE
    content: str


class IdleEvent(Event):
    """Idle state change."""

    type: Literal[EventType.IDLE] = EventType.IDLE
    active: bool


AnyEvent = (
    ThinkingStartEvent
    | ThinkingEndEvent
    | ToolUseEvent
    | ResponseStartEvent
    | ResponseEndEvent
    | TokenEvent
    | ErrorEvent
    | UserMessageEvent
    | IdleEvent
)


class OutputParser:
    """
    Parse Claude Code CLI output to detect events.
    
    Claude Code output patterns (approximate, may vary by version):
    - Thinking block: starts with dimmed text or specific markers
    - Tool calls: "⏺ tool:name" or similar
    - Streaming: character-by-character output
    """

    # Patterns to detect in output
    THINKING_START_PATTERNS = [
        re.compile(r"^╭─", re.MULTILINE),  # Box drawing start
        re.compile(r"^\s*thinking", re.IGNORECASE | re.MULTILINE),
        re.compile(r"\x1b\[2m"),  # Dim text often used for thinking
    ]

    THINKING_END_PATTERNS = [
        re.compile(r"^╰─", re.MULTILINE),  # Box drawing end
        re.compile(r"\x1b\[22m"),  # Normal intensity (end dim)
    ]

    TOOL_PATTERNS = [
        re.compile(r"⏺\s*(\w+):", re.MULTILINE),  # ⏺ tool_name:
        re.compile(r"tool[:\s]+(\w+)", re.IGNORECASE),
        re.compile(r"Running\s+(\w+)", re.IGNORECASE),
    ]

    ERROR_PATTERNS = [
        re.compile(r"error:", re.IGNORECASE),
        re.compile(r"exception:", re.IGNORECASE),
        re.compile(r"failed:", re.IGNORECASE),
        re.compile(r"\x1b\[31m"),  # Red text
    ]

    def __init__(self) -> None:
        self._in_thinking = False
        self._in_response = False
        self._buffer = ""
        self._last_token_time = 0.0
        self._token_throttle = 0.1  # 100ms between token events

    def parse(self, chunk: str) -> list[AnyEvent]:
        """
        Parse a chunk of output and return detected events.
        
        Args:
            chunk: Raw output chunk from Claude Code
            
        Returns:
            List of detected events (may be empty)
        """
        events: list[AnyEvent] = []
        self._buffer += chunk

        # Check for thinking transitions
        if not self._in_thinking:
            for pattern in self.THINKING_START_PATTERNS:
                if pattern.search(self._buffer):
                    self._in_thinking = True
                    self._in_response = False
                    events.append(ThinkingStartEvent())
                    break
        else:
            for pattern in self.THINKING_END_PATTERNS:
                if pattern.search(self._buffer):
                    self._in_thinking = False
                    events.append(ThinkingEndEvent())
                    break

        # Check for tool usage
        for pattern in self.TOOL_PATTERNS:
            match = pattern.search(self._buffer)
            if match:
                tool_name = match.group(1).lower()
                # Extract snippet around match
                start = max(0, match.start() - 50)
                end = min(len(self._buffer), match.end() + 150)
                snippet = self._buffer[start:end]
                events.append(ToolUseEvent(tool=tool_name, snippet=snippet))

        # Check for errors
        for pattern in self.ERROR_PATTERNS:
            match = pattern.search(self._buffer)
            if match:
                # Extract error context
                start = max(0, match.start() - 20)
                end = min(len(self._buffer), match.end() + 100)
                msg = self._buffer[start:end].strip()
                events.append(ErrorEvent(message=msg))
                break

        # Detect response streaming
        now = time.time()
        if not self._in_thinking and chunk and not self._in_response:
            # First non-thinking output is response start
            self._in_response = True
            events.append(ResponseStartEvent())

        # Throttled token events
        if self._in_response and chunk:
            if now - self._last_token_time >= self._token_throttle:
                events.append(TokenEvent(chunk=chunk))
                self._last_token_time = now

        # Keep buffer bounded
        if len(self._buffer) > 10000:
            self._buffer = self._buffer[-5000:]

        return events

    def end_response(self, full_content: str) -> ResponseEndEvent:
        """Call when response is complete."""
        self._in_response = False
        self._buffer = ""
        return ResponseEndEvent(content=full_content[-2000:])  # Last 2k chars

    def reset(self) -> None:
        """Reset parser state."""
        self._in_thinking = False
        self._in_response = False
        self._buffer = ""


class CommandParser:
    """Parse /viz commands from user input."""

    COMMAND_PATTERN = re.compile(r"^/viz\s*(.*)$", re.IGNORECASE)

    @classmethod
    def parse(cls, line: str) -> tuple[str, list[str]] | None:
        """
        Parse a /viz command.
        
        Args:
            line: User input line
            
        Returns:
            Tuple of (command, args) or None if not a viz command
        """
        match = cls.COMMAND_PATTERN.match(line.strip())
        if not match:
            return None

        parts = match.group(1).split()
        if not parts:
            return ("toggle", [])

        cmd = parts[0].lower()
        args = parts[1:]

        return (cmd, args)
