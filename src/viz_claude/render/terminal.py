"""Terminal rendering with ANSI escape codes and sanitization."""

from __future__ import annotations

import re
import sys
from typing import TextIO


# =============================================================================
# ANSI Color Codes
# =============================================================================


# Standard 16 colors
COLORS_16: dict[str, int] = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
    "bright_black": 8,
    "bright_red": 9,
    "bright_green": 10,
    "bright_yellow": 11,
    "bright_blue": 12,
    "bright_magenta": 13,
    "bright_cyan": 14,
    "bright_white": 15,
    # Aliases
    "gray": 8,
    "grey": 8,
    "orange": 208,  # 256-color
    "pink": 13,
    "purple": 5,
}

# Extended semantic colors for templates
SEMANTIC_COLORS: dict[str, int] = {
    "muted": 242,
    "dim": 240,
    "subtle": 245,
    "accent": 214,
    "highlight": 226,
    "success": 82,
    "warning": 214,
    "error": 196,
    "info": 75,
    # Fire palette
    "flame_core": 226,
    "flame_mid": 214,
    "flame_edge": 196,
    "ember": 202,
    "ash": 240,
    # Water palette
    "water_deep": 24,
    "water_mid": 33,
    "water_light": 45,
    "foam": 159,
    # Metal palette
    "metal_cold": 245,
    "metal_warm": 180,
    "metal_hot": 214,
    "metal_white": 231,
}


def resolve_color(name: str) -> int:
    """
    Resolve color name to 256-color code.
    
    Args:
        name: Color name or numeric string
        
    Returns:
        256-color code (0-255)
    """
    # Direct numeric
    if name.isdigit():
        return min(255, max(0, int(name)))

    # Lookup in tables
    name_lower = name.lower().replace("-", "_").replace(" ", "_")
    
    if name_lower in COLORS_16:
        return COLORS_16[name_lower]
    
    if name_lower in SEMANTIC_COLORS:
        return SEMANTIC_COLORS[name_lower]

    # Default to white
    return 15


# =============================================================================
# Escape Sequence Sanitization
# =============================================================================


# Safe ANSI sequences we allow
SAFE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\x1b\[\d+(?:;\d+)*m"),        # SGR (colors, styles)
    re.compile(r"\x1b\[\d+;\d+[Hf]"),          # CUP (cursor position)
    re.compile(r"\x1b\[[ABCD]"),               # Cursor movement
    re.compile(r"\x1b\[\d*[ABCD]"),            # Cursor movement with count
    re.compile(r"\x1b\[2?J"),                   # Clear screen
    re.compile(r"\x1b\[[012]?K"),               # Clear line
    re.compile(r"\x1b\[\?25[hl]"),              # Cursor visibility
    re.compile(r"\x1b\[\?1049[hl]"),            # Alternate screen
    re.compile(r"\x1b[78]"),                    # Save/restore cursor
    re.compile(r"\x1b\[s"),                     # Save cursor (alternative)
    re.compile(r"\x1b\[u"),                     # Restore cursor (alternative)
]

# Dangerous sequences we always strip
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\x1b\]52;"),                  # Clipboard access
    re.compile(r"\x1b\]0;"),                   # Window title (could be phishing)
    re.compile(r"\x1b\]10;"),                  # Text foreground color
    re.compile(r"\x1b\]11;"),                  # Text background color
    re.compile(r"\x1b\]1337;"),                # iTerm2 proprietary (some risky)
    re.compile(r"\x1b\]133;"),                 # Shell integration
    re.compile(r"\x1bP"),                      # DCS sequences
    re.compile(r"\x1b\\"),                     # ST (string terminator)
]


def sanitize_output(text: str) -> str:
    """
    Sanitize text by removing potentially dangerous escape sequences.
    
    Args:
        text: Raw text possibly containing escape sequences
        
    Returns:
        Sanitized text with only safe sequences
    """
    result: list[str] = []
    i = 0
    
    while i < len(text):
        if text[i] == "\x1b":
            # Check for dangerous sequences first
            is_dangerous = False
            for pattern in DANGEROUS_PATTERNS:
                match = pattern.match(text[i:])
                if match:
                    # Skip the dangerous sequence
                    # Find end of sequence (ST or BEL)
                    end = i + len(match.group())
                    while end < len(text) and text[end] not in ("\x07", "\x1b"):
                        end += 1
                    if end < len(text) and text[end] == "\x1b" and end + 1 < len(text) and text[end + 1] == "\\":
                        end += 2
                    elif end < len(text) and text[end] == "\x07":
                        end += 1
                    i = end
                    is_dangerous = True
                    break
            
            if is_dangerous:
                continue
            
            # Check for safe sequences
            is_safe = False
            for pattern in SAFE_PATTERNS:
                match = pattern.match(text[i:])
                if match:
                    result.append(match.group())
                    i += len(match.group())
                    is_safe = True
                    break
            
            if not is_safe:
                # Unknown escape, skip the ESC character
                i += 1
        else:
            result.append(text[i])
            i += 1
    
    return "".join(result)


# =============================================================================
# Terminal Renderer
# =============================================================================


class Terminal:
    """Terminal rendering utilities with escape code generation."""

    def __init__(self, output: TextIO | None = None, sanitize: bool = True):
        """
        Initialize terminal renderer.
        
        Args:
            output: Output stream (defaults to stdout)
            sanitize: Whether to sanitize output for safety
        """
        self.output = output or sys.stdout
        self.sanitize = sanitize
        self._current_fg: int | None = None
        self._current_bg: int | None = None

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------

    def write(self, text: str) -> None:
        """Write text to output, optionally sanitizing."""
        if self.sanitize:
            text = sanitize_output(text)
        self.output.write(text)
        self.output.flush()

    def writeln(self, text: str = "") -> None:
        """Write text followed by newline."""
        self.write(text + "\n")

    # -------------------------------------------------------------------------
    # Colors (256-color mode)
    # -------------------------------------------------------------------------

    def fg(self, color: str | int) -> str:
        """Set foreground color."""
        code = color if isinstance(color, int) else resolve_color(color)
        return f"\x1b[38;5;{code}m"

    def bg(self, color: str | int) -> str:
        """Set background color."""
        code = color if isinstance(color, int) else resolve_color(color)
        return f"\x1b[48;5;{code}m"

    def reset(self) -> str:
        """Reset all attributes."""
        self._current_fg = None
        self._current_bg = None
        return "\x1b[0m"

    def styled(self, text: str, fg: str | int | None = None, bg: str | int | None = None) -> str:
        """Return text with color codes."""
        parts = []
        if fg is not None:
            parts.append(self.fg(fg))
        if bg is not None:
            parts.append(self.bg(bg))
        parts.append(text)
        parts.append(self.reset())
        return "".join(parts)

    # -------------------------------------------------------------------------
    # Cursor Control
    # -------------------------------------------------------------------------

    def cursor_pos(self, row: int, col: int) -> str:
        """Move cursor to position (1-indexed)."""
        return f"\x1b[{row};{col}H"

    def cursor_home(self) -> str:
        """Move cursor to home position (1,1)."""
        return "\x1b[H"

    def cursor_up(self, n: int = 1) -> str:
        """Move cursor up n rows."""
        return f"\x1b[{n}A"

    def cursor_down(self, n: int = 1) -> str:
        """Move cursor down n rows."""
        return f"\x1b[{n}B"

    def cursor_forward(self, n: int = 1) -> str:
        """Move cursor forward n columns."""
        return f"\x1b[{n}C"

    def cursor_back(self, n: int = 1) -> str:
        """Move cursor back n columns."""
        return f"\x1b[{n}D"

    def cursor_save(self) -> str:
        """Save cursor position."""
        return "\x1b7"

    def cursor_restore(self) -> str:
        """Restore cursor position."""
        return "\x1b8"

    def cursor_hide(self) -> str:
        """Hide cursor."""
        return "\x1b[?25l"

    def cursor_show(self) -> str:
        """Show cursor."""
        return "\x1b[?25h"

    # -------------------------------------------------------------------------
    # Screen Control
    # -------------------------------------------------------------------------

    def clear_screen(self) -> str:
        """Clear entire screen."""
        return "\x1b[2J"

    def clear_line(self) -> str:
        """Clear current line."""
        return "\x1b[2K"

    def clear_to_end(self) -> str:
        """Clear from cursor to end of screen."""
        return "\x1b[J"

    def alternate_screen_on(self) -> str:
        """Switch to alternate screen buffer."""
        return "\x1b[?1049h"

    def alternate_screen_off(self) -> str:
        """Switch back to main screen buffer."""
        return "\x1b[?1049l"

    # -------------------------------------------------------------------------
    # Text Styles
    # -------------------------------------------------------------------------

    def bold(self) -> str:
        """Enable bold."""
        return "\x1b[1m"

    def dim(self) -> str:
        """Enable dim."""
        return "\x1b[2m"

    def italic(self) -> str:
        """Enable italic."""
        return "\x1b[3m"

    def underline(self) -> str:
        """Enable underline."""
        return "\x1b[4m"

    def blink(self) -> str:
        """Enable blink."""
        return "\x1b[5m"

    def reverse(self) -> str:
        """Enable reverse video."""
        return "\x1b[7m"

    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------

    def fill_rect(
        self,
        row: int,
        col: int,
        width: int,
        height: int,
        char: str = " ",
        fg: str | int | None = None,
        bg: str | int | None = None,
    ) -> str:
        """Generate escape codes to fill a rectangle."""
        parts = []
        line = char * width

        for r in range(height):
            parts.append(self.cursor_pos(row + r, col))
            if fg is not None:
                parts.append(self.fg(fg))
            if bg is not None:
                parts.append(self.bg(bg))
            parts.append(line)

        parts.append(self.reset())
        return "".join(parts)

    def draw_box(
        self,
        row: int,
        col: int,
        width: int,
        height: int,
        fg: str | int = "white",
        title: str = "",
    ) -> str:
        """Draw a box with optional title."""
        parts = []

        # Box drawing characters
        tl, tr, bl, br = "┌", "┐", "└", "┘"
        h, v = "─", "│"

        # Top border
        parts.append(self.cursor_pos(row, col))
        parts.append(self.fg(fg))

        if title:
            title_display = f" {title[:width-4]} "
            left_pad = (width - 2 - len(title_display)) // 2
            right_pad = width - 2 - len(title_display) - left_pad
            parts.append(tl + h * left_pad + title_display + h * right_pad + tr)
        else:
            parts.append(tl + h * (width - 2) + tr)

        # Sides
        for r in range(1, height - 1):
            parts.append(self.cursor_pos(row + r, col))
            parts.append(v)
            parts.append(self.cursor_pos(row + r, col + width - 1))
            parts.append(v)

        # Bottom border
        parts.append(self.cursor_pos(row + height - 1, col))
        parts.append(bl + h * (width - 2) + br)

        parts.append(self.reset())
        return "".join(parts)
