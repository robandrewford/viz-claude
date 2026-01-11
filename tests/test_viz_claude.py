"""Tests for viz-claude."""

from __future__ import annotations

import asyncio
from io import StringIO

import pytest

from viz_claude.core import (
    Classification,
    ClassificationState,
    UserPreferences,
    VizTemplate,
)
from viz_claude.core.classifier import (
    ClassificationStateMachine,
    HeuristicClassifier,
)
from viz_claude.core.events import CommandParser, EventType, OutputParser
from viz_claude.core.protocol import (
    TriggerMessage,
    decode_message,
    encode_message,
)
from viz_claude.render import (
    AnimationEngine,
    Cell,
    FrameBuffer,
    ParticleSystem,
    Terminal,
    resolve_color,
    sanitize_output,
)
from viz_claude.templates import BUILTIN_TEMPLATES, TemplateLoader, get_loader


# =============================================================================
# Core Model Tests
# =============================================================================


class TestClassification:
    """Tests for Classification model."""

    def test_basic_classification(self) -> None:
        c = Classification(
            category="ml--training",
            confidence=0.85,
            signals=["torch", "train"],
        )
        assert c.category == "ml--training"
        assert c.confidence == 0.85
        assert len(c.signals) == 2

    def test_get_parent(self) -> None:
        c = Classification(category="ml--training", confidence=0.8, signals=[])
        assert c.get_parent() == "ml"

        c2 = Classification(category="code", confidence=0.8, signals=[])
        assert c2.get_parent() == "code"

    def test_confidence_bounds(self) -> None:
        with pytest.raises(ValueError):
            Classification(category="test", confidence=1.5, signals=[])

        with pytest.raises(ValueError):
            Classification(category="test", confidence=-0.1, signals=[])


class TestVizTemplate:
    """Tests for VizTemplate validation."""

    def test_valid_template(self) -> None:
        data = BUILTIN_TEMPLATES["ml--training"]
        template = VizTemplate.model_validate(data)
        assert template.category == "ml--training"
        assert "default" in template.compositions

    def test_missing_default_composition(self) -> None:
        data = {
            "schema_version": "1.0.0",
            "category": "test",
            "metadata": {"name": "Test", "metaphor": "Test"},
            "palette": {"primary": "white", "background": "black"},
            "layers": [{"id": "test", "z": 0, "type": "static", "frames": ["f1"]}],
            "frames": {"f1": {"content": ["x"]}},
            "compositions": {
                "other": {"layers": ["test"], "rows": 1, "cols": 1}
            },  # Missing 'default'
        }
        with pytest.raises(ValueError, match="default"):
            VizTemplate.model_validate(data)

    def test_missing_palette_colors(self) -> None:
        data = {
            "schema_version": "1.0.0",
            "category": "test",
            "metadata": {"name": "Test", "metaphor": "Test"},
            "palette": {"secondary": "blue"},  # Missing primary, background
            "layers": [{"id": "test", "z": 0, "type": "static", "frames": ["f1"]}],
            "frames": {"f1": {"content": ["x"]}},
            "compositions": {"default": {"layers": ["test"], "rows": 1, "cols": 1}},
        }
        with pytest.raises(ValueError, match="primary"):
            VizTemplate.model_validate(data)


# =============================================================================
# Classifier Tests
# =============================================================================


class TestHeuristicClassifier:
    """Tests for heuristic classifier."""

    def test_tool_based_classification(self) -> None:
        classifier = HeuristicClassifier()
        classifier.add_tool_use("bash", "docker build -t myapp .")
        classifier.add_tool_use("bash", "kubectl apply -f deployment.yaml")

        result = classifier.classify()
        assert result.category == "cloud--compute"
        assert result.confidence > 0.3  # Heuristic gives 0.34 for 2 tool matches

    def test_ml_classification(self) -> None:
        classifier = HeuristicClassifier()
        classifier.add_tool_use("bash", "pip install torch")
        classifier.add_tool_use("bash", "python train.py --epochs 100")
        classifier.add_content("training the model with backpropagation")

        result = classifier.classify()
        assert result.category == "ml--training"

    def test_fallback_classification(self) -> None:
        classifier = HeuristicClassifier()
        # No signals
        result = classifier.classify()
        assert result.category == "conversation--casual"
        assert result.confidence < 0.5

    def test_preference_avoidance(self) -> None:
        prefs = UserPreferences(avoid_categories=["ml--*"])
        classifier = HeuristicClassifier(preferences=prefs)
        classifier.add_tool_use("bash", "pip install torch")
        classifier.add_content("training neural network")

        result = classifier.classify()
        # Should avoid ml categories
        assert not result.category.startswith("ml--")


class TestClassificationStateMachine:
    """Tests for classification state machine."""

    def test_initial_state(self) -> None:
        sm = ClassificationStateMachine()
        assert sm.state == ClassificationState.UNCLASSIFIED
        assert sm.should_classify() is False  # Need 3 messages first

    def test_state_transitions(self) -> None:
        sm = ClassificationStateMachine()

        # Add messages until threshold
        for _ in range(3):
            sm.on_message()
        assert sm.should_classify()

        # High confidence -> LOCKED
        sm.on_classification(Classification(
            category="ml--training",
            confidence=0.85,
            signals=["torch"],
        ))
        assert sm.state == ClassificationState.LOCKED
        assert sm.should_classify() is False

        # Need 10 messages to reclassify when LOCKED
        for _ in range(10):
            sm.on_message()
        assert sm.should_classify()

    def test_low_confidence_fallback(self) -> None:
        sm = ClassificationStateMachine()
        for _ in range(3):
            sm.on_message()

        sm.on_classification(Classification(
            category="test",
            confidence=0.3,
            signals=[],
        ))
        assert sm.state == ClassificationState.FALLBACK


# =============================================================================
# Event Parser Tests
# =============================================================================


class TestOutputParser:
    """Tests for Claude output parser."""

    def test_thinking_detection(self) -> None:
        parser = OutputParser()

        events = parser.parse("Starting analysis...\n╭─ Thinking")
        assert any(e.type == EventType.THINKING_START for e in events)

    def test_tool_detection(self) -> None:
        parser = OutputParser()

        events = parser.parse("⏺ bash: ls -la")
        tool_events = [e for e in events if e.type == EventType.TOOL_USE]
        assert len(tool_events) == 1
        assert tool_events[0].tool == "bash"

    def test_error_detection(self) -> None:
        parser = OutputParser()

        events = parser.parse("Error: file not found")
        assert any(e.type == EventType.ERROR for e in events)


class TestCommandParser:
    """Tests for /viz command parser."""

    def test_basic_command(self) -> None:
        result = CommandParser.parse("/viz set ml--training")
        assert result == ("set", ["ml--training"])

    def test_toggle_command(self) -> None:
        result = CommandParser.parse("/viz")
        assert result == ("toggle", [])

    def test_not_command(self) -> None:
        result = CommandParser.parse("help me with code")
        assert result is None


# =============================================================================
# Protocol Tests
# =============================================================================


class TestProtocol:
    """Tests for socket protocol."""

    def test_encode_decode(self) -> None:
        msg = TriggerMessage(name="thinking", active=True)
        encoded = encode_message(msg)
        assert encoded.endswith(b"\n")

        decoded = decode_message(encoded)
        assert decoded["msg"] == "trigger"
        assert decoded["name"] == "thinking"
        assert decoded["active"] is True


# =============================================================================
# Render Tests
# =============================================================================


class TestTerminal:
    """Tests for terminal renderer."""

    def test_color_resolution(self) -> None:
        assert resolve_color("red") == 1
        assert resolve_color("bright_green") == 10
        assert resolve_color("208") == 208
        assert resolve_color("muted") == 242

    def test_escape_sanitization(self) -> None:
        # Safe sequences should pass
        safe = "\x1b[31m\x1b[42mHello\x1b[0m"
        assert "\x1b[31m" in sanitize_output(safe)

        # Dangerous sequences should be stripped
        dangerous = "\x1b]52;c;SGVsbG8=\x07"  # Clipboard access
        result = sanitize_output(dangerous)
        assert "\x1b]52" not in result

    def test_terminal_output(self) -> None:
        output = StringIO()
        term = Terminal(output=output)

        term.write(term.fg("red") + "Hello" + term.reset())

        result = output.getvalue()
        assert "\x1b[38;5;1m" in result  # Red
        assert "Hello" in result
        assert "\x1b[0m" in result  # Reset


class TestFrameBuffer:
    """Tests for frame buffer."""

    def test_basic_operations(self) -> None:
        buf = FrameBuffer(rows=5, cols=10)

        buf.set(0, 0, "X", fg="red")
        cell = buf.get(0, 0)
        assert cell is not None
        assert cell.char == "X"
        assert cell.fg == "red"

    def test_dirty_tracking(self) -> None:
        buf = FrameBuffer(rows=5, cols=10)

        assert buf.dirty_count == 0
        buf.set(0, 0, "A")
        assert buf.dirty_count == 1

        buf.set(0, 0, "A")  # Same value
        assert buf.dirty_count == 1  # No change

        buf.set(0, 0, "B")  # Different value
        assert buf.dirty_count == 1  # Still 1, same cell

    def test_blit(self) -> None:
        buf = FrameBuffer(rows=5, cols=10)
        content = ["AB", "CD"]

        buf.blit(content, row=1, col=1)

        assert buf.get(1, 1).char == "A"
        assert buf.get(1, 2).char == "B"
        assert buf.get(2, 1).char == "C"
        assert buf.get(2, 2).char == "D"

    def test_bounds_checking(self) -> None:
        buf = FrameBuffer(rows=5, cols=10)

        # Out of bounds should not raise
        buf.set(-1, 0, "X")
        buf.set(100, 0, "X")
        buf.set(0, -1, "X")
        buf.set(0, 100, "X")

        # Should have no dirty cells
        assert buf.dirty_count == 0


class TestParticleSystem:
    """Tests for particle system."""

    def test_spawn_and_tick(self) -> None:
        from viz_claude.core import Anchor, Emitter, Velocity

        system = ParticleSystem()
        emitter = Emitter(
            chars=["*"],
            spawn_rate=5,
            lifetime_frames=10,
            velocity=Velocity(x=(-1, 1), y=(-1, 0)),
            origin=Anchor(row=5, col=5),
            spread=Anchor(row=0, col=0),
            color="white",
        )

        system.spawn(emitter)
        assert system.count == 5

        # Tick until all dead
        for _ in range(15):
            system.tick()

        assert system.count == 0

    def test_max_particles(self) -> None:
        from viz_claude.core import Anchor, Emitter, Velocity

        system = ParticleSystem(max_particles=10)
        emitter = Emitter(
            chars=["*"],
            spawn_rate=20,  # More than max
            lifetime_frames=100,
            velocity=Velocity(x=(0, 0), y=(0, 0)),
            origin=Anchor(row=0, col=0),
            spread=Anchor(row=0, col=0),
            color="white",
        )

        system.spawn(emitter)
        assert system.count == 10  # Capped at max


# =============================================================================
# Template Tests
# =============================================================================


class TestTemplateLoader:
    """Tests for template loading."""

    def test_load_builtin(self) -> None:
        loader = TemplateLoader()
        template = loader.load("ml--training")

        assert template.category == "ml--training"
        assert template.metadata.name == "Forge"

    def test_load_fallback(self) -> None:
        loader = TemplateLoader()
        template = loader.load("nonexistent--category")

        assert template.category == "_fallback"

    def test_validate(self) -> None:
        loader = TemplateLoader()

        # Valid template
        template = loader.validate(BUILTIN_TEMPLATES["code--craft"])
        assert template.category == "code--craft"

        # Invalid template
        with pytest.raises(ValueError):
            loader.validate({"invalid": "data"})


# =============================================================================
# Integration Tests
# =============================================================================


class TestAnimationEngine:
    """Integration tests for animation engine."""

    def test_engine_initialization(self) -> None:
        template = BUILTIN_TEMPLATES["ml--training"]
        engine = AnimationEngine(template)

        assert engine.rows == 7
        assert engine.cols == 26
        assert engine.running is False

    def test_trigger_handling(self) -> None:
        template = BUILTIN_TEMPLATES["ml--training"]
        engine = AnimationEngine(template)

        # Trigger thinking
        engine.trigger("thinking", active=True)
        assert "thinking" in engine.state.active_triggers
        assert "idle" not in engine.state.active_triggers

        # End thinking
        engine.trigger("thinking", active=False)
        assert "thinking" not in engine.state.active_triggers

    def test_composition_switching(self) -> None:
        template = BUILTIN_TEMPLATES["ml--training"]
        engine = AnimationEngine(template)

        engine.set_composition("minimal")
        assert engine.state.composition == "minimal"
        assert engine.rows == 4
        assert engine.cols == 10


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_template() -> dict:
    """Return a minimal test template."""
    return {
        "schema_version": "1.0.0",
        "category": "test",
        "version": "v1.0.0",
        "metadata": {"name": "Test", "metaphor": "Test metaphor", "author": "test"},
        "palette": {"primary": "white", "background": "black"},
        "layers": [
            {"id": "main", "z": 0, "type": "static", "frames": ["frame1"]}
        ],
        "frames": {"frame1": {"content": ["###", "# #", "###"]}},
        "compositions": {"default": {"layers": ["main"], "rows": 3, "cols": 3}},
    }
