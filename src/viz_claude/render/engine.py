"""Animation engine with frame timing and layer compositing."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .buffer import FrameBuffer
from .particles import ParticleSystem
from .terminal import Terminal

if TYPE_CHECKING:
    from ..core import Emitter, VizTemplate

logger = logging.getLogger(__name__)


@dataclass
class LayerState:
    """Runtime state for a single layer."""

    layer_id: str
    layer_type: str
    frame_index: int = 0
    last_frame_time: float = 0.0
    active: bool = True
    transition_progress: float = 0.0


@dataclass
class AnimationState:
    """Complete animation state."""

    composition: str = "default"
    layers: dict[str, LayerState] = field(default_factory=dict)
    active_triggers: set[str] = field(default_factory=set)
    frame_count: int = 0
    last_activity_time: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        self.active_triggers.add("idle")


class AnimationEngine:
    """
    Main animation engine.
    
    Manages:
    - Frame timing and skipping
    - Layer state and transitions
    - Particle systems
    - Trigger handling
    - Buffer compositing
    """

    def __init__(
        self,
        template: "VizTemplate | dict[str, Any]",
        terminal: Terminal | None = None,
        target_fps: int = 15,
    ):
        """
        Initialize animation engine.
        
        Args:
            template: Visualization template
            terminal: Terminal renderer (created if None)
            target_fps: Target frames per second
        """
        # Handle both Pydantic model and dict
        if hasattr(template, "model_dump"):
            self.template: dict[str, Any] = template.model_dump()
        else:
            self.template = template

        self.terminal = terminal or Terminal()
        self.target_fps = target_fps
        self.frame_duration = 1.0 / target_fps

        # Get composition size
        comp = self._get_composition("default")
        self.rows = comp.get("rows", 12)
        self.cols = comp.get("cols", 44)

        # Initialize state
        self.state = AnimationState()
        self._init_layer_states()

        # Initialize buffers
        self.buffer = FrameBuffer(
            rows=self.rows,
            cols=self.cols,
            background=self.template.get("palette", {}).get("background", "black"),
        )

        # Initialize particle system
        self.particles = ParticleSystem(
            gravity=0.1,
        )

        # Control flags
        self.running = False
        self._frame_target_time = 0.0

    def _get_composition(self, name: str) -> dict[str, Any]:
        """Get composition by name with fallback."""
        comps = self.template.get("compositions", {})
        if name in comps:
            return comps[name]
        if "default" in comps:
            return comps["default"]
        # Absolute fallback
        return {"rows": 12, "cols": 44, "layers": []}

    def _init_layer_states(self) -> None:
        """Initialize state for all layers."""
        for layer in self.template.get("layers", []):
            layer_id = layer.get("id", "")
            self.state.layers[layer_id] = LayerState(
                layer_id=layer_id,
                layer_type=layer.get("type", "static"),
            )

    # -------------------------------------------------------------------------
    # Trigger Handling
    # -------------------------------------------------------------------------

    def trigger(self, name: str, active: bool = True, **kwargs: Any) -> None:
        """
        Activate or deactivate a trigger.
        
        Args:
            name: Trigger name (e.g., "thinking", "tool_use")
            active: Whether trigger is active
            **kwargs: Additional trigger data (e.g., tool name, intensity)
        """
        if active:
            self.state.active_triggers.add(name)
            self.state.active_triggers.discard("idle")
            self.state.last_activity_time = time.time()

            # Handle special triggers
            if name == "tool_use":
                self._on_tool_use(kwargs)
            elif name == "response_start":
                self._trigger_oneshot("token_stream_start")

        else:
            self.state.active_triggers.discard(name)

    def _on_tool_use(self, data: dict[str, Any]) -> None:
        """Handle tool use trigger."""
        tool = data.get("tool", "unknown")
        intensity = data.get("intensity", 1.0)

        # Find particle layers triggered by tool_use
        for layer in self.template.get("layers", []):
            if layer.get("type") != "particle":
                continue
            if layer.get("trigger") != "tool_use":
                continue

            emitter_name = layer.get("emitter")
            emitters = self.template.get("emitters", {})
            if emitter_name and emitter_name in emitters:
                emitter = emitters[emitter_name]

                # Get tool-specific intensity multiplier
                intensity_map = emitter.get("intensity_map", {})
                tool_intensity = intensity_map.get(tool, 1.0) * intensity

                # Spawn particles
                self._spawn_from_emitter(emitter, tool_intensity)

    def _trigger_oneshot(self, trigger_name: str) -> None:
        """Start a oneshot animation."""
        for layer in self.template.get("layers", []):
            if layer.get("type") != "oneshot":
                continue
            if layer.get("trigger") != trigger_name:
                continue

            layer_id = layer.get("id", "")
            if layer_id in self.state.layers:
                self.state.layers[layer_id].frame_index = 0
                self.state.layers[layer_id].active = True

    def _spawn_from_emitter(self, emitter_data: dict[str, Any], intensity: float) -> None:
        """Spawn particles from emitter data."""
        from ..core import Anchor, Emitter, Velocity

        # Convert dict to Emitter model
        try:
            emitter = Emitter(
                chars=emitter_data.get("chars", ["*"]),
                spawn_rate=emitter_data.get("spawn_rate", 5),
                lifetime_frames=emitter_data.get("lifetime_frames", 20),
                velocity=Velocity(
                    x=tuple(emitter_data.get("velocity", {}).get("x", [-1, 1])),
                    y=tuple(emitter_data.get("velocity", {}).get("y", [-2, 0])),
                ),
                origin=Anchor(**emitter_data.get("origin", {"row": 0, "col": 0})),
                spread=Anchor(**emitter_data.get("spread", {"row": 0, "col": 0})),
                color=emitter_data.get("color", "white"),
                fade=emitter_data.get("fade", False),
                gravity=emitter_data.get("gravity", 0.1),
            )
            self.particles.spawn(emitter, intensity)
        except Exception as e:
            logger.warning(f"Failed to spawn particles: {e}")

    def _check_idle(self) -> None:
        """Check for transition to idle state."""
        if not self.state.active_triggers - {"idle"}:
            return

        idle_threshold = 2.0  # seconds
        if time.time() - self.state.last_activity_time > idle_threshold:
            self.state.active_triggers.clear()
            self.state.active_triggers.add("idle")

    # -------------------------------------------------------------------------
    # Animation Loop
    # -------------------------------------------------------------------------

    async def run(self, trigger_queue: asyncio.Queue[dict[str, Any]]) -> None:
        """
        Main animation loop.
        
        Args:
            trigger_queue: Queue of trigger events
        """
        self.running = True
        self._frame_target_time = time.monotonic()

        # Setup terminal
        self.terminal.write(self.terminal.alternate_screen_on())
        self.terminal.write(self.terminal.cursor_hide())
        self.terminal.write(self.terminal.clear_screen())

        try:
            while self.running:
                frame_start = time.monotonic()

                # Process triggers (non-blocking)
                await self._process_triggers(trigger_queue)

                # Check idle state
                self._check_idle()

                # Update animation state
                self._tick()

                # Render frame
                self._render()

                # Frame timing with skip logic
                await self._frame_timing(frame_start)

        finally:
            # Cleanup
            self.terminal.write(self.terminal.cursor_show())
            self.terminal.write(self.terminal.alternate_screen_off())

    async def _process_triggers(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """Process all pending triggers from queue."""
        while True:
            try:
                msg = queue.get_nowait()
                self._handle_trigger_message(msg)
            except asyncio.QueueEmpty:
                break

    def _handle_trigger_message(self, msg: dict[str, Any]) -> None:
        """Handle a trigger message from the queue."""
        msg_type = msg.get("msg", msg.get("type", ""))

        if msg_type == "trigger":
            self.trigger(
                msg.get("name", ""),
                msg.get("active", True),
                tool=msg.get("tool"),
                intensity=msg.get("intensity", 1.0),
            )

        elif msg_type == "composition":
            self.set_composition(msg.get("value", "default"))

        elif msg_type == "template":
            self.load_template(msg.get("data", {}))

        elif msg_type == "shutdown":
            self.stop()

    async def _frame_timing(self, frame_start: float) -> None:
        """Handle frame timing with skip logic."""
        now = time.monotonic()
        elapsed = now - frame_start

        # Update target time
        self._frame_target_time += self.frame_duration

        # If we're behind, skip frames
        if now > self._frame_target_time:
            frames_behind = int((now - self._frame_target_time) / self.frame_duration)
            if frames_behind > 0:
                logger.debug(f"Skipping {frames_behind} frames")
                self._frame_target_time = now

        # Sleep until target
        sleep_time = self._frame_target_time - now
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)

    def stop(self) -> None:
        """Stop the animation loop."""
        self.running = False

    # -------------------------------------------------------------------------
    # State Updates
    # -------------------------------------------------------------------------

    def _tick(self) -> None:
        """Update all animation state for one frame."""
        self.state.frame_count += 1
        now = time.monotonic()

        for layer in self.template.get("layers", []):
            layer_id = layer.get("id", "")
            layer_type = layer.get("type", "static")
            trigger = layer.get("trigger", "idle")
            layer_state = self.state.layers.get(layer_id)

            if not layer_state:
                continue

            # Check if layer's trigger is active
            trigger_active = trigger in self.state.active_triggers or trigger == "always"

            if layer_type == "loop":
                if trigger_active:
                    duration_ms = layer.get("frame_duration_ms", 100)
                    if now - layer_state.last_frame_time >= duration_ms / 1000:
                        frames = layer.get("frames", [])
                        if frames:
                            layer_state.frame_index = (layer_state.frame_index + 1) % len(frames)
                        layer_state.last_frame_time = now

            elif layer_type == "oneshot":
                if layer_state.active:
                    duration_ms = layer.get("frame_duration_ms", 100)
                    if now - layer_state.last_frame_time >= duration_ms / 1000:
                        frames = layer.get("frames", [])
                        if frames:
                            layer_state.frame_index += 1
                            if layer_state.frame_index >= len(frames):
                                layer_state.frame_index = 0
                                layer_state.active = False
                        layer_state.last_frame_time = now

            elif layer_type == "transition":
                if trigger_active:
                    # Progress forward
                    layer_state.transition_progress = min(
                        1.0, layer_state.transition_progress + 0.05
                    )
                else:
                    # Regress backward
                    layer_state.transition_progress = max(
                        0.0, layer_state.transition_progress - 0.03
                    )

        # Update particles
        self.particles.tick()

    # -------------------------------------------------------------------------
    # Rendering
    # -------------------------------------------------------------------------

    def _render(self) -> None:
        """Render current frame to terminal."""
        # Clear buffer
        self.buffer.clear()

        # Get current composition
        comp = self._get_composition(self.state.composition)
        active_layers = set(comp.get("layers", []))

        # Render layers in z-order
        layers = sorted(
            [l for l in self.template.get("layers", []) if l.get("id") in active_layers],
            key=lambda l: l.get("z", 0),
        )

        for layer in layers:
            self._render_layer(layer)

        # Render particles on top
        palette = self.template.get("palette", {})
        self.particles.render_to_buffer(self.buffer, palette)

        # Output to terminal
        output = self.buffer.render_dirty(self.terminal)
        if output:
            self.terminal.write(output)

    def _render_layer(self, layer: dict[str, Any]) -> None:
        """Render a single layer to the buffer."""
        layer_id = layer.get("id", "")
        layer_type = layer.get("type", "static")
        layer_state = self.state.layers.get(layer_id)

        if not layer_state:
            return

        frames_dict = self.template.get("frames", {})
        palette = self.template.get("palette", {})

        if layer_type == "static":
            frame_names = layer.get("frames", [])
            if frame_names:
                self._blit_frame(frames_dict.get(frame_names[0], {}), palette)

        elif layer_type in ("loop", "oneshot"):
            frame_names = layer.get("frames", [])
            if frame_names:
                idx = layer_state.frame_index % len(frame_names)
                self._blit_frame(frames_dict.get(frame_names[idx], {}), palette)

        elif layer_type == "transition":
            frame_names = layer.get("frames", [])
            if frame_names:
                # Map progress (0-1) to frame index
                idx = int(layer_state.transition_progress * (len(frame_names) - 1))
                idx = max(0, min(idx, len(frame_names) - 1))
                self._blit_frame(frames_dict.get(frame_names[idx], {}), palette)

        # Particle layers are handled separately

    def _blit_frame(self, frame: dict[str, Any], palette: dict[str, str]) -> None:
        """Copy frame content to buffer."""
        content = frame.get("content", [])
        if not content:
            return

        anchor = frame.get("anchor", {})
        row = anchor.get("row", 0)
        col = anchor.get("col", 0)
        color_map = frame.get("color_map", {})

        # Resolve colors through palette
        resolved_map = {}
        for chars, color_name in color_map.items():
            resolved_map[chars] = palette.get(color_name, color_name)

        self.buffer.blit(
            content=content,
            row=row,
            col=col,
            fg=palette.get("primary", "white"),
            color_map=resolved_map,
        )

    # -------------------------------------------------------------------------
    # Template Management
    # -------------------------------------------------------------------------

    def set_composition(self, name: str) -> None:
        """Switch to a different composition."""
        if name in self.template.get("compositions", {}):
            self.state.composition = name
            comp = self._get_composition(name)

            # Resize if needed
            new_rows = comp.get("rows", self.rows)
            new_cols = comp.get("cols", self.cols)
            if new_rows != self.rows or new_cols != self.cols:
                self.rows = new_rows
                self.cols = new_cols
                self.buffer.resize(new_rows, new_cols)
                self.buffer.force_full_redraw()

    def load_template(self, template: dict[str, Any]) -> None:
        """Load a new template."""
        self.template = template
        self._init_layer_states()

        # Get new composition size
        comp = self._get_composition(self.state.composition)
        self.rows = comp.get("rows", 12)
        self.cols = comp.get("cols", 44)

        # Resize buffer
        self.buffer.resize(self.rows, self.cols)
        self.buffer.background = template.get("palette", {}).get("background", "black")
        self.buffer.force_full_redraw()

        # Clear particles
        self.particles.clear()
