"""Frame buffer with dirty rectangle tracking for efficient rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .terminal import Terminal


@dataclass
class Cell:
    """A single cell in the frame buffer."""

    char: str = " "
    fg: str = "white"
    bg: str = "black"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Cell):
            return False
        return self.char == other.char and self.fg == other.fg and self.bg == other.bg

    def copy(self) -> "Cell":
        return Cell(char=self.char, fg=self.fg, bg=self.bg)


@dataclass
class FrameBuffer:
    """
    Double-buffered frame buffer with dirty tracking.
    
    Maintains current and previous frame state to minimize
    terminal output by only rendering changed cells.
    """

    rows: int
    cols: int
    background: str = "black"
    _current: list[list[Cell]] = field(default_factory=list)
    _previous: list[list[Cell]] = field(default_factory=list)
    _dirty: set[tuple[int, int]] = field(default_factory=set)
    _full_redraw: bool = True

    def __post_init__(self) -> None:
        """Initialize buffers."""
        self._current = [
            [Cell(bg=self.background) for _ in range(self.cols)]
            for _ in range(self.rows)
        ]
        self._previous = [
            [Cell(bg=self.background) for _ in range(self.cols)]
            for _ in range(self.rows)
        ]

    def resize(self, rows: int, cols: int) -> None:
        """Resize the buffer, clearing all content."""
        self.rows = rows
        self.cols = cols
        self._current = [
            [Cell(bg=self.background) for _ in range(cols)]
            for _ in range(rows)
        ]
        self._previous = [
            [Cell(bg=self.background) for _ in range(cols)]
            for _ in range(rows)
        ]
        self._dirty.clear()
        self._full_redraw = True

    def clear(self) -> None:
        """Clear the buffer to background color."""
        for r in range(self.rows):
            for c in range(self.cols):
                cell = self._current[r][c]
                if cell.char != " " or cell.fg != "white" or cell.bg != self.background:
                    cell.char = " "
                    cell.fg = "white"
                    cell.bg = self.background
                    self._dirty.add((r, c))

    def set(
        self,
        row: int,
        col: int,
        char: str,
        fg: str | None = None,
        bg: str | None = None,
    ) -> None:
        """
        Set a cell value.
        
        Args:
            row: Row index (0-based)
            col: Column index (0-based)
            char: Character to display (first char used if string)
            fg: Foreground color (None keeps current)
            bg: Background color (None keeps current)
        """
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            return

        cell = self._current[row][col]
        changed = False

        # Use first character only
        new_char = char[0] if char else " "
        if cell.char != new_char:
            cell.char = new_char
            changed = True

        if fg is not None and cell.fg != fg:
            cell.fg = fg
            changed = True

        if bg is not None and cell.bg != bg:
            cell.bg = bg
            changed = True

        if changed:
            self._dirty.add((row, col))

    def get(self, row: int, col: int) -> Cell | None:
        """Get cell at position."""
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self._current[row][col]
        return None

    def blit(
        self,
        content: list[str],
        row: int,
        col: int,
        fg: str | None = None,
        bg: str | None = None,
        color_map: dict[str, str] | None = None,
        transparent_char: str = " ",
    ) -> None:
        """
        Copy content to buffer at position.
        
        Args:
            content: List of strings (one per row)
            row: Starting row
            col: Starting column
            fg: Default foreground color
            bg: Background color
            color_map: Map of characters to colors (overrides fg)
            transparent_char: Character to treat as transparent
        """
        for r, line in enumerate(content):
            for c, char in enumerate(line):
                # Skip transparent
                if char == transparent_char:
                    continue

                # Determine color
                char_fg = fg
                if color_map:
                    for chars, color in color_map.items():
                        if char in chars:
                            char_fg = color
                            break

                self.set(row + r, col + c, char, fg=char_fg, bg=bg)

    def render_full(self, terminal: "Terminal") -> str:
        """
        Render entire buffer (for initial draw or after resize).
        
        Returns:
            Escape code string to write to terminal
        """
        parts: list[str] = []
        parts.append(terminal.cursor_home())

        current_fg: str | None = None
        current_bg: str | None = None

        for r in range(self.rows):
            if r > 0:
                parts.append("\n")

            for c in range(self.cols):
                cell = self._current[r][c]

                # Update colors if changed
                if cell.fg != current_fg:
                    parts.append(terminal.fg(cell.fg))
                    current_fg = cell.fg
                if cell.bg != current_bg:
                    parts.append(terminal.bg(cell.bg))
                    current_bg = cell.bg

                parts.append(cell.char)

                # Copy to previous buffer
                self._previous[r][c] = cell.copy()

        parts.append(terminal.reset())
        self._dirty.clear()
        self._full_redraw = False

        return "".join(parts)

    def render_dirty(self, terminal: "Terminal") -> str:
        """
        Render only changed cells.
        
        Returns:
            Escape code string to write to terminal
        """
        if self._full_redraw:
            return self.render_full(terminal)

        if not self._dirty:
            return ""

        parts: list[str] = []

        # Sort for more efficient cursor movement
        sorted_dirty = sorted(self._dirty)

        for row, col in sorted_dirty:
            cell = self._current[row][col]
            prev = self._previous[row][col]

            # Skip if unchanged (shouldn't happen but safety check)
            if cell == prev:
                continue

            # Position cursor (1-indexed)
            parts.append(terminal.cursor_pos(row + 1, col + 1))
            parts.append(terminal.fg(cell.fg))
            parts.append(terminal.bg(cell.bg))
            parts.append(cell.char)

            # Update previous
            self._previous[row][col] = cell.copy()

        if parts:
            parts.append(terminal.reset())

        self._dirty.clear()
        return "".join(parts)

    def force_full_redraw(self) -> None:
        """Force next render to be a full redraw."""
        self._full_redraw = True

    @property
    def dirty_count(self) -> int:
        """Number of dirty cells."""
        return len(self._dirty)

    @property
    def needs_redraw(self) -> bool:
        """Whether any cells need redrawing."""
        return self._full_redraw or bool(self._dirty)


@dataclass
class LayeredBuffer:
    """
    Buffer that composites multiple layers by z-order.
    
    Each layer has a z-index; higher z renders on top.
    Transparent cells (space with default colors) show through.
    """

    rows: int
    cols: int
    background: str = "black"
    _layers: dict[int, FrameBuffer] = field(default_factory=dict)
    _composite: FrameBuffer = field(init=False)

    def __post_init__(self) -> None:
        """Initialize composite buffer."""
        self._composite = FrameBuffer(
            rows=self.rows,
            cols=self.cols,
            background=self.background,
        )

    def get_layer(self, z: int) -> FrameBuffer:
        """Get or create layer at z-index."""
        if z not in self._layers:
            self._layers[z] = FrameBuffer(
                rows=self.rows,
                cols=self.cols,
                background=self.background,
            )
        return self._layers[z]

    def clear_layer(self, z: int) -> None:
        """Clear a specific layer."""
        if z in self._layers:
            self._layers[z].clear()

    def clear_all(self) -> None:
        """Clear all layers."""
        for layer in self._layers.values():
            layer.clear()

    def composite(self) -> FrameBuffer:
        """
        Composite all layers into output buffer.
        
        Layers are composited in z-order (low to high).
        Non-space characters overwrite lower layers.
        
        Returns:
            Composited frame buffer ready for rendering
        """
        # Clear composite
        self._composite.clear()

        # Get sorted z-indices
        z_order = sorted(self._layers.keys())

        # Composite each layer
        for z in z_order:
            layer = self._layers[z]
            for r in range(self.rows):
                for c in range(self.cols):
                    cell = layer.get(r, c)
                    if cell and cell.char != " ":
                        self._composite.set(r, c, cell.char, fg=cell.fg, bg=cell.bg)

        return self._composite

    def resize(self, rows: int, cols: int) -> None:
        """Resize all buffers."""
        self.rows = rows
        self.cols = cols
        for layer in self._layers.values():
            layer.resize(rows, cols)
        self._composite.resize(rows, cols)
