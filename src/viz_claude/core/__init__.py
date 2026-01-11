"""Core data models - all Pydantic for consistency."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


def _utc_now() -> datetime:
    """Get current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


# =============================================================================
# Classification Models
# =============================================================================


class ClassificationState(str, Enum):
    """State machine states for classification."""

    UNCLASSIFIED = "unclassified"
    TENTATIVE = "tentative"
    FALLBACK = "fallback"
    ACCEPTED = "accepted"
    LOCKED = "locked"


class Classification(BaseModel):
    """Result of conversation classification."""

    category: str
    confidence: Annotated[float, Field(ge=0.0, le=1.0)]
    signals: list[str] = Field(default_factory=list)
    alternative: str | None = None

    def get_parent(self) -> str:
        """Get parent category (before the --)."""
        if "--" in self.category:
            return self.category.split("--")[0]
        return self.category


class UserPreferences(BaseModel):
    """User preferences for visualization."""

    prefer_categories: list[str] = Field(default_factory=list)
    avoid_categories: list[str] = Field(default_factory=list)
    default_composition: str = "default"
    animation_speed: Annotated[float, Field(ge=0.1, le=3.0)] = 1.0


class UserProfile(BaseModel):
    """Complete user profile."""

    user_id: str
    created_at: datetime = Field(default_factory=_utc_now)
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    template_selections: dict[str, str] = Field(default_factory=dict)
    total_sessions: int = 0
    category_counts: dict[str, int] = Field(default_factory=dict)


# =============================================================================
# Animation Models
# =============================================================================


class Particle(BaseModel):
    """A single particle in a particle system."""

    x: float
    y: float
    vx: float
    vy: float
    char: str
    color: str
    lifetime: int
    age: int = 0

    model_config = {"frozen": False}


class AnimationState(BaseModel):
    """Current state of the animation engine."""

    current_composition: str = "default"
    layer_frame_indices: dict[str, int] = Field(default_factory=dict)
    particles: list[Particle] = Field(default_factory=list)
    transition_progress: dict[str, float] = Field(default_factory=dict)
    active_triggers: set[str] = Field(default_factory=set)
    frame_count: int = 0

    model_config = {"frozen": False}


# =============================================================================
# Template Schema
# =============================================================================


class Anchor(BaseModel):
    """Position anchor for frames."""

    row: int = 0
    col: int = 0


class Frame(BaseModel):
    """A single animation frame."""

    content: list[str]
    anchor: Anchor = Field(default_factory=Anchor)
    color_map: dict[str, str] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Frame content cannot be empty")
        return v


class Velocity(BaseModel):
    """Velocity range for particles."""

    x: tuple[float, float]
    y: tuple[float, float]

    @field_validator("x", "y")
    @classmethod
    def validate_range(cls, v: tuple[float, float]) -> tuple[float, float]:
        if v[0] > v[1]:
            raise ValueError("Min must be <= max")
        return v


class Emitter(BaseModel):
    """Particle emitter configuration."""

    chars: list[str] = Field(min_length=1)
    spawn_rate: Annotated[int, Field(ge=1, le=50)]
    lifetime_frames: Annotated[int, Field(ge=1, le=120)]
    velocity: Velocity
    origin: Anchor
    spread: Anchor = Field(default_factory=Anchor)
    color: str
    fade: bool = False
    gravity: float = 0.1
    intensity_map: dict[str, float] = Field(default_factory=dict)


LayerType = Literal["static", "loop", "oneshot", "transition", "particle"]


class Layer(BaseModel):
    """A single animation layer."""

    id: str
    z: int
    type: LayerType
    frames: list[str] | None = None
    frame_duration_ms: Annotated[int, Field(ge=16, le=2000)] = 100
    trigger: str | None = None
    emitter: str | None = None
    direction: Literal["forward", "backward"] = "forward"

    @field_validator("frames")
    @classmethod
    def validate_frames_for_type(cls, v: list[str] | None, info) -> list[str] | None:
        layer_type = info.data.get("type")
        if layer_type in ("static", "loop", "oneshot", "transition") and not v:
            raise ValueError(f"Layer type '{layer_type}' requires frames")
        return v


class Composition(BaseModel):
    """A named composition of layers."""

    layers: list[str] = Field(min_length=1)
    rows: Annotated[int, Field(ge=1, le=100)]
    cols: Annotated[int, Field(ge=1, le=200)]


class TemplateMetadata(BaseModel):
    """Metadata about a template."""

    name: str
    metaphor: str
    author: str = "system"
    created_at: datetime = Field(default_factory=_utc_now)
    tags: list[str] = Field(default_factory=list)


class TriggerConfig(BaseModel):
    """Configuration for a trigger type."""

    description: str = ""


class VizTemplate(BaseModel):
    """Complete visualization template schema."""

    schema_version: str = "1.0.0"
    category: str
    version: str = "v1.0.0"
    metadata: TemplateMetadata
    palette: dict[str, str]
    layers: list[Layer] = Field(min_length=1)
    frames: dict[str, Frame]
    emitters: dict[str, Emitter] = Field(default_factory=dict)
    triggers: dict[str, TriggerConfig] = Field(default_factory=dict)
    compositions: dict[str, Composition]

    @field_validator("compositions")
    @classmethod
    def validate_default_composition(cls, v: dict[str, Composition]) -> dict[str, Composition]:
        if "default" not in v:
            raise ValueError("Template must have a 'default' composition")
        return v

    @field_validator("palette")
    @classmethod
    def validate_required_colors(cls, v: dict[str, str]) -> dict[str, str]:
        required = {"primary", "background"}
        missing = required - set(v.keys())
        if missing:
            raise ValueError(f"Palette missing required colors: {missing}")
        return v


# =============================================================================
# Session Models
# =============================================================================


class CategoryHistoryEntry(BaseModel):
    """A single entry in category history."""

    category: str | None
    confidence: float | None = None
    at_message: int | None = None
    changed_at: datetime = Field(default_factory=_utc_now)
    reason: str = "auto"


class SessionMetadata(BaseModel):
    """Session metadata for persistence."""

    session_id: str
    user_id: str
    started_at: datetime = Field(default_factory=_utc_now)
    ended_at: datetime | None = None
    category: str | None = None
    category_confidence: float | None = None
    category_signals: list[str] = Field(default_factory=list)
    category_history: list[CategoryHistoryEntry] = Field(default_factory=list)
    template_used: str | None = None
    composition: str = "default"
    trigger_counts: dict[str, int] = Field(default_factory=dict)
    tool_use_breakdown: dict[str, int] = Field(default_factory=dict)
    message_count: int = 0


# =============================================================================
# Taxonomy Models
# =============================================================================


class CategoryMeta(BaseModel):
    """Metadata for a single category."""

    metaphor: str
    description: str = ""
    parent: str | None = None
    signals: list[str] = Field(default_factory=list)


class Taxonomy(BaseModel):
    """Complete category taxonomy."""

    version: str = "v1.0.0"
    updated_at: datetime = Field(default_factory=_utc_now)
    categories: dict[str, CategoryMeta]
