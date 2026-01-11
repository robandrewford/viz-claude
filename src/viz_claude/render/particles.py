"""Particle system with physics simulation."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import Emitter


MAX_PARTICLES = 200


@dataclass
class Particle:
    """A single particle with physics properties."""

    x: float
    y: float
    vx: float
    vy: float
    char: str
    color: str
    lifetime: int
    age: int = 0
    fade: bool = False

    def tick(self, gravity: float = 0.1) -> bool:
        """
        Update particle for one frame.
        
        Args:
            gravity: Gravity acceleration (positive = down)
            
        Returns:
            True if particle is still alive
        """
        self.age += 1
        if self.age >= self.lifetime:
            return False

        # Apply physics
        self.x += self.vx
        self.y += self.vy
        self.vy += gravity

        return True

    @property
    def alive(self) -> bool:
        return self.age < self.lifetime

    @property
    def opacity(self) -> float:
        """Get opacity based on age (1.0 = full, 0.0 = invisible)."""
        if not self.fade:
            return 1.0
        # Linear fade in last 30% of lifetime
        remaining_ratio = 1.0 - (self.age / self.lifetime)
        if remaining_ratio > 0.3:
            return 1.0
        return remaining_ratio / 0.3

    def get_display_color(self, palette: dict[str, str]) -> str:
        """Get color to render, potentially dimmed for fading."""
        base_color = palette.get(self.color, self.color)
        
        if not self.fade or self.opacity > 0.7:
            return base_color
        elif self.opacity > 0.4:
            return "muted"
        else:
            return "dim"


@dataclass
class ParticleSystem:
    """
    Manages a collection of particles with spawning and physics.
    
    Maintains a bounded pool to prevent memory issues.
    """

    max_particles: int = MAX_PARTICLES
    gravity: float = 0.1
    _particles: list[Particle] = field(default_factory=list)

    def spawn(
        self,
        emitter: "Emitter",
        intensity: float = 1.0,
    ) -> int:
        """
        Spawn particles from an emitter.
        
        Args:
            emitter: Emitter configuration
            intensity: Multiplier for spawn rate
            
        Returns:
            Number of particles spawned
        """
        count = int(emitter.spawn_rate * intensity)

        # Cull oldest if at capacity
        space_needed = max(0, len(self._particles) + count - self.max_particles)
        if space_needed > 0:
            # Remove oldest particles (they're at the front)
            self._particles = self._particles[space_needed:]

        spawned = 0
        for _ in range(count):
            if len(self._particles) >= self.max_particles:
                break

            # Random position within spread
            x = emitter.origin.col + random.uniform(
                -emitter.spread.col, emitter.spread.col
            )
            y = emitter.origin.row + random.uniform(
                -emitter.spread.row, emitter.spread.row
            )

            # Random velocity within range
            vx = random.uniform(emitter.velocity.x[0], emitter.velocity.x[1])
            vy = random.uniform(emitter.velocity.y[0], emitter.velocity.y[1])

            # Random character
            char = random.choice(emitter.chars)

            particle = Particle(
                x=x,
                y=y,
                vx=vx,
                vy=vy,
                char=char,
                color=emitter.color,
                lifetime=emitter.lifetime_frames,
                fade=emitter.fade,
            )

            self._particles.append(particle)
            spawned += 1

        return spawned

    def spawn_burst(
        self,
        x: float,
        y: float,
        count: int,
        chars: list[str],
        color: str,
        velocity_range: tuple[float, float] = (-2.0, 2.0),
        lifetime: int = 20,
        fade: bool = True,
    ) -> int:
        """
        Spawn a burst of particles at a point.
        
        Args:
            x: X position
            y: Y position
            count: Number of particles
            chars: Characters to use
            color: Particle color
            velocity_range: Min/max velocity
            lifetime: Particle lifetime in frames
            fade: Whether particles should fade
            
        Returns:
            Number spawned
        """
        # Cull if needed
        space_needed = max(0, len(self._particles) + count - self.max_particles)
        if space_needed > 0:
            self._particles = self._particles[space_needed:]

        spawned = 0
        for _ in range(count):
            if len(self._particles) >= self.max_particles:
                break

            vx = random.uniform(velocity_range[0], velocity_range[1])
            vy = random.uniform(velocity_range[0], velocity_range[1])
            char = random.choice(chars)

            particle = Particle(
                x=x,
                y=y,
                vx=vx,
                vy=vy,
                char=char,
                color=color,
                lifetime=lifetime,
                fade=fade,
            )

            self._particles.append(particle)
            spawned += 1

        return spawned

    def tick(self) -> int:
        """
        Update all particles for one frame.
        
        Returns:
            Number of particles remaining
        """
        alive: list[Particle] = []

        for particle in self._particles:
            if particle.tick(self.gravity):
                alive.append(particle)

        self._particles = alive
        return len(self._particles)

    def render_to_buffer(
        self,
        buffer: "FrameBuffer",  # type: ignore[name-defined]
        palette: dict[str, str],
        bounds: tuple[int, int, int, int] | None = None,
    ) -> int:
        """
        Render particles to a frame buffer.
        
        Args:
            buffer: Target frame buffer
            palette: Color palette for color resolution
            bounds: Optional (min_row, min_col, max_row, max_col) bounds
            
        Returns:
            Number of particles rendered
        """
        from .buffer import FrameBuffer  # Avoid circular import

        if bounds:
            min_row, min_col, max_row, max_col = bounds
        else:
            min_row, min_col = 0, 0
            max_row, max_col = buffer.rows, buffer.cols

        rendered = 0
        for particle in self._particles:
            row = int(particle.y)
            col = int(particle.x)

            # Bounds check
            if not (min_row <= row < max_row and min_col <= col < max_col):
                continue

            # Skip nearly invisible particles
            if particle.opacity < 0.1:
                continue

            color = particle.get_display_color(palette)
            buffer.set(row, col, particle.char, fg=color)
            rendered += 1

        return rendered

    def clear(self) -> None:
        """Remove all particles."""
        self._particles.clear()

    @property
    def count(self) -> int:
        """Current number of particles."""
        return len(self._particles)

    @property
    def particles(self) -> list[Particle]:
        """Access to particle list (read-only intent)."""
        return self._particles
