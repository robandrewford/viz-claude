# viz-claude

Terminal visualization companion for Claude Code sessions.

ASCII art animations that respond to Claude's activity—thinking, tool use, responses—with visual metaphors matched to your conversation's domain.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Terminal                          │
│                                                                 │
│  Tab 1: viz claude                    Tab 2: viz-renderer       │
│  ┌─────────────────────────────┐     ┌────────────────────────┐ │
│  │ $ viz claude                │     │     ╔═══════════╗      │ │
│  │ > help me train a model     │     │     ║  (  )  (  ║      │ │
│  │ [claude output streams]     │     │     ║   ▓▓▓▓    ║      │ │
│  └──────────────┬──────────────┘     │     ╚═══════════╝      │ │
│                 │                     └────────────────────────┘ │
└─────────────────┼───────────────────────────────────────────────┘
                  │ Unix Socket
                  ▼
        ┌─────────────────────┐
        │     viz-agent       │
        │  • Classification   │
        │  • State machine    │
        │  • Template loading │
        └─────────────────────┘
```

**Components:**

1. **viz-wrapper** (`viz claude`) - Wraps Claude Code CLI, parses output stream, emits events
2. **viz-agent** (`viz-agent`) - Background daemon managing classification and state
3. **viz-renderer** (`viz-renderer`) - Standalone animation renderer in separate terminal

## Installation

```bash
pip install viz-claude
viz install
```

## Usage

### Quick Start

```bash
# Terminal 1: Start the agent
viz-agent &

# Terminal 2: Start the renderer
viz-renderer

# Terminal 3: Use Claude with visualization
viz claude
```

### Commands

Type `/viz` commands in your Claude session:

| Command | Description |
|---------|-------------|
| `/viz` | Toggle visualization on/off |
| `/viz set <category>` | Force category (e.g., `ml--training`) |
| `/viz reclassify` | Force immediate re-classification |
| `/viz default` | Switch to default composition |
| `/viz active` | Switch to active composition (more particles) |
| `/viz minimal` | Switch to minimal composition |
| `/viz status` | Show current state |
| `/viz off` | Disable visualization |

### CLI Commands

```bash
viz status      # Check if agent is running
viz templates   # List available templates
viz categories  # List available categories
viz install     # Set up configuration
```

## Categories

Conversations are automatically classified into visual metaphors:

| Category | Metaphor | Triggers |
|----------|----------|----------|
| `ml--training` | Forge with flames | pytorch, tensorflow, training |
| `code--craft` | Woodworking workshop | refactoring, debugging |
| `data--flow` | Flowing water pipes | ETL, pipelines |
| `cloud--compute` | Engines and turbines | docker, kubernetes, aws |
| `conversation--casual` | Cozy campfire | General chat |

Classification uses local heuristics based on:
- Tool usage patterns (strongest signal)
- Content keywords
- User preferences

## Templates

Templates define the visual appearance for each category:

```json
{
  "category": "ml--training",
  "palette": {
    "primary": "196",
    "accent": "226",
    "background": "black"
  },
  "layers": [
    {"id": "flames", "type": "loop", "trigger": "idle"},
    {"id": "sparks", "type": "particle", "trigger": "tool_use"},
    {"id": "metal", "type": "transition", "trigger": "thinking"}
  ],
  "compositions": {
    "default": {"layers": ["flames", "metal"], "rows": 7, "cols": 26},
    "active": {"layers": ["flames", "sparks", "metal"], "rows": 7, "cols": 26}
  }
}
```

### Layer Types

| Type | Behavior |
|------|----------|
| `static` | Single frame, never changes |
| `loop` | Cycles through frames continuously |
| `oneshot` | Plays once when triggered |
| `transition` | Progress-based frame selection |
| `particle` | Spawns particles from emitter |

### Custom Templates

Add templates to `~/.viz-claude/templates/{category}/`:

```bash
~/.viz-claude/templates/ml--training/custom.json
```

## Configuration

User preferences in `~/.viz-claude/profile.json`:

```json
{
  "preferences": {
    "prefer_categories": ["ml--*"],
    "avoid_categories": [],
    "default_composition": "default",
    "animation_speed": 1.0
  }
}
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

## Technical Details

### Event Flow

1. User types in `viz claude` wrapper
2. Wrapper forwards to `claude` subprocess
3. Wrapper parses output for patterns (thinking, tools, responses)
4. Events sent to `viz-agent` via Unix socket
5. Agent classifies conversation, manages state
6. Agent sends triggers to `viz-renderer`
7. Renderer updates animation

### Socket Protocol

Newline-delimited JSON over Unix socket at `/tmp/viz-claude-{uid}.sock`:

```json
{"msg": "trigger", "name": "thinking", "active": true}
{"msg": "category", "value": "ml--training", "confidence": 0.85}
{"msg": "template", "data": {...}}
```

### Frame Rendering

- Target: 15 FPS
- Dirty rectangle tracking for minimal terminal output
- Frame skipping when behind
- Bounded particle system (max 200)
- ANSI 256-color mode

## Troubleshooting

**Agent not responding:**
```bash
viz status  # Check if running
viz-agent   # Start if needed
```

**No visualization:**
- Ensure `viz-renderer` is running in a separate terminal
- Check socket exists: `ls /tmp/viz-claude-*.sock`

**Wrong category:**
```
/viz set ml--training  # Force category
/viz reclassify        # Re-run classification
```

## License

MIT
