"""Template loading with validation and built-in defaults."""

from __future__ import annotations

import json
import logging
from importlib import resources
from typing import Any

from ..core import VizTemplate
from ..storage import get_storage

logger = logging.getLogger(__name__)


# =============================================================================
# Built-in Templates (embedded in package)
# =============================================================================


FALLBACK_TEMPLATE: dict[str, Any] = {
    "schema_version": "1.0.0",
    "category": "_fallback",
    "version": "v1.0.0",
    "metadata": {
        "name": "Minimal",
        "metaphor": "Simple activity indicator",
        "author": "system",
    },
    "palette": {
        "primary": "white",
        "secondary": "gray",
        "accent": "cyan",
        "background": "black",
        "muted": "240",
    },
    "layers": [
        {
            "id": "spinner",
            "z": 0,
            "type": "loop",
            "frames": ["spin_0", "spin_1", "spin_2", "spin_3"],
            "frame_duration_ms": 100,
            "trigger": "always",
        },
        {
            "id": "activity",
            "z": 1,
            "type": "transition",
            "frames": ["idle", "active"],
            "trigger": "thinking",
        },
    ],
    "frames": {
        "spin_0": {"content": ["⠋"], "anchor": {"row": 0, "col": 0}, "color_map": {"⠋": "accent"}},
        "spin_1": {"content": ["⠙"], "anchor": {"row": 0, "col": 0}, "color_map": {"⠙": "accent"}},
        "spin_2": {"content": ["⠹"], "anchor": {"row": 0, "col": 0}, "color_map": {"⠹": "accent"}},
        "spin_3": {"content": ["⠸"], "anchor": {"row": 0, "col": 0}, "color_map": {"⠸": "accent"}},
        "idle": {"content": ["○"], "anchor": {"row": 0, "col": 2}, "color_map": {"○": "muted"}},
        "active": {"content": ["●"], "anchor": {"row": 0, "col": 2}, "color_map": {"●": "primary"}},
    },
    "emitters": {},
    "triggers": {},
    "compositions": {
        "default": {"layers": ["spinner", "activity"], "rows": 1, "cols": 4},
    },
}


ML_TRAINING_TEMPLATE: dict[str, Any] = {
    "schema_version": "1.0.0",
    "category": "ml--training",
    "version": "v1.0.0",
    "metadata": {
        "name": "Forge",
        "metaphor": "Metalworking forge with flames and sparks",
        "author": "system",
        "tags": ["fire", "metal", "transformation"],
    },
    "palette": {
        "primary": "196",
        "secondary": "208",
        "accent": "226",
        "background": "black",
        "muted": "240",
        "highlight": "231",
        "ember": "202",
    },
    "layers": [
        {
            "id": "background",
            "z": 0,
            "type": "static",
            "frames": ["forge_bg"],
        },
        {
            "id": "flames",
            "z": 1,
            "type": "loop",
            "frames": ["flame_1", "flame_2", "flame_3", "flame_4"],
            "frame_duration_ms": 120,
            "trigger": "idle",
        },
        {
            "id": "sparks",
            "z": 2,
            "type": "particle",
            "emitter": "spark_emitter",
            "trigger": "tool_use",
        },
        {
            "id": "metal",
            "z": 3,
            "type": "transition",
            "frames": ["metal_cold", "metal_warm", "metal_hot", "metal_white"],
            "trigger": "thinking",
        },
    ],
    "frames": {
        "forge_bg": {
            "content": [
                "╔════════════════════════╗",
                "║                        ║",
                "║                        ║",
                "║                        ║",
                "║                        ║",
                "╚════════════════════════╝",
                "▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀▀",
            ],
            "anchor": {"row": 0, "col": 0},
            "color_map": {"╔╗╚╝═║": "muted", "▀": "ember"},
        },
        "flame_1": {
            "content": [
                "   (  )   ",
                "  (    )  ",
                " (  ()  ) ",
                "  (    )  ",
            ],
            "anchor": {"row": 1, "col": 8},
            "color_map": {"(": "accent", ")": "primary"},
        },
        "flame_2": {
            "content": [
                "  (    )  ",
                " (  ()  ) ",
                "  (    )  ",
                "   (  )   ",
            ],
            "anchor": {"row": 1, "col": 8},
            "color_map": {"(": "primary", ")": "secondary"},
        },
        "flame_3": {
            "content": [
                " (  ()  ) ",
                "  (    )  ",
                "   (  )   ",
                "  (    )  ",
            ],
            "anchor": {"row": 1, "col": 8},
            "color_map": {"(": "secondary", ")": "accent"},
        },
        "flame_4": {
            "content": [
                "  (    )  ",
                "   (  )   ",
                "  (    )  ",
                " (  ()  ) ",
            ],
            "anchor": {"row": 1, "col": 8},
            "color_map": {"(": "accent", ")": "primary"},
        },
        "metal_cold": {
            "content": ["▓▓▓▓"],
            "anchor": {"row": 3, "col": 11},
            "color_map": {"▓": "muted"},
        },
        "metal_warm": {
            "content": ["▓▓▓▓"],
            "anchor": {"row": 3, "col": 11},
            "color_map": {"▓": "primary"},
        },
        "metal_hot": {
            "content": ["▓▓▓▓"],
            "anchor": {"row": 3, "col": 11},
            "color_map": {"▓": "secondary"},
        },
        "metal_white": {
            "content": ["▓▓▓▓"],
            "anchor": {"row": 3, "col": 11},
            "color_map": {"▓": "highlight"},
        },
    },
    "emitters": {
        "spark_emitter": {
            "chars": ["*", "·", ".", "'", "`"],
            "spawn_rate": 8,
            "lifetime_frames": 15,
            "velocity": {"x": [-2.0, 2.0], "y": [-3.0, -0.5]},
            "origin": {"row": 3, "col": 13},
            "spread": {"row": 1, "col": 2},
            "color": "accent",
            "fade": True,
            "gravity": 0.15,
            "intensity_map": {"bash": 2.0, "edit": 1.5, "read": 0.5},
        },
    },
    "triggers": {
        "idle": {"description": "No activity"},
        "thinking": {"description": "Claude processing"},
        "tool_use": {"description": "Tool call"},
    },
    "compositions": {
        "default": {
            "layers": ["background", "flames", "metal"],
            "rows": 7,
            "cols": 26,
        },
        "active": {
            "layers": ["background", "flames", "sparks", "metal"],
            "rows": 7,
            "cols": 26,
        },
        "minimal": {
            "layers": ["flames"],
            "rows": 4,
            "cols": 10,
        },
    },
}


CODE_CRAFT_TEMPLATE: dict[str, Any] = {
    "schema_version": "1.0.0",
    "category": "code--craft",
    "version": "v1.0.0",
    "metadata": {
        "name": "Workshop",
        "metaphor": "Woodworking workshop with tools",
        "author": "system",
        "tags": ["tools", "craft", "build"],
    },
    "palette": {
        "primary": "180",
        "secondary": "137",
        "accent": "215",
        "background": "black",
        "muted": "240",
        "wood": "130",
        "metal": "250",
    },
    "layers": [
        {
            "id": "bench",
            "z": 0,
            "type": "static",
            "frames": ["workbench"],
        },
        {
            "id": "sawdust",
            "z": 1,
            "type": "particle",
            "emitter": "dust_emitter",
            "trigger": "tool_use",
        },
        {
            "id": "progress",
            "z": 2,
            "type": "transition",
            "frames": ["progress_0", "progress_1", "progress_2", "progress_3"],
            "trigger": "thinking",
        },
    ],
    "frames": {
        "workbench": {
            "content": [
                "┌──────────────────┐",
                "│  ╭──╮    ╭───╮   │",
                "│  │░░│    │▒▒▒│   │",
                "│  ╰──╯    ╰───╯   │",
                "├──────────────────┤",
                "│▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓│",
                "└──────────────────┘",
            ],
            "anchor": {"row": 0, "col": 0},
            "color_map": {
                "┌┐└┘─│├┤": "muted",
                "╭╮╰╯": "metal",
                "░▒": "wood",
                "▓": "primary",
            },
        },
        "progress_0": {
            "content": ["[          ]"],
            "anchor": {"row": 3, "col": 3},
            "color_map": {"[": "muted", "]": "muted"},
        },
        "progress_1": {
            "content": ["[███       ]"],
            "anchor": {"row": 3, "col": 3},
            "color_map": {"█": "accent", "[": "muted", "]": "muted"},
        },
        "progress_2": {
            "content": ["[██████    ]"],
            "anchor": {"row": 3, "col": 3},
            "color_map": {"█": "accent", "[": "muted", "]": "muted"},
        },
        "progress_3": {
            "content": ["[██████████]"],
            "anchor": {"row": 3, "col": 3},
            "color_map": {"█": "accent", "[": "muted", "]": "muted"},
        },
    },
    "emitters": {
        "dust_emitter": {
            "chars": [".", "·", "°"],
            "spawn_rate": 5,
            "lifetime_frames": 20,
            "velocity": {"x": [-1.0, 1.0], "y": [0.5, 1.5]},
            "origin": {"row": 2, "col": 10},
            "spread": {"row": 0, "col": 3},
            "color": "primary",
            "fade": True,
            "gravity": 0.05,
        },
    },
    "triggers": {},
    "compositions": {
        "default": {
            "layers": ["bench", "progress"],
            "rows": 7,
            "cols": 20,
        },
        "active": {
            "layers": ["bench", "sawdust", "progress"],
            "rows": 7,
            "cols": 20,
        },
    },
}


DATA_FLOW_TEMPLATE: dict[str, Any] = {
    "schema_version": "1.0.0",
    "category": "data--flow",
    "version": "v1.0.0",
    "metadata": {
        "name": "River",
        "metaphor": "Flowing water and pipes",
        "author": "system",
        "tags": ["water", "flow", "pipes"],
    },
    "palette": {
        "primary": "39",
        "secondary": "33",
        "accent": "51",
        "background": "black",
        "muted": "240",
        "deep": "24",
    },
    "layers": [
        {
            "id": "pipes",
            "z": 0,
            "type": "static",
            "frames": ["pipe_bg"],
        },
        {
            "id": "flow",
            "z": 1,
            "type": "loop",
            "frames": ["flow_1", "flow_2", "flow_3", "flow_4"],
            "frame_duration_ms": 150,
            "trigger": "always",
        },
        {
            "id": "droplets",
            "z": 2,
            "type": "particle",
            "emitter": "drop_emitter",
            "trigger": "tool_use",
        },
    ],
    "frames": {
        "pipe_bg": {
            "content": [
                "╔══════╗",
                "║      ╠════╗",
                "║      ║    ║",
                "╚══════╝    ║",
                "        ╔═══╝",
                "        ║    ",
            ],
            "anchor": {"row": 0, "col": 0},
            "color_map": {"╔╗╚╝═║╠╣": "muted"},
        },
        "flow_1": {
            "content": ["~≈~", "≈~≈", "~≈~"],
            "anchor": {"row": 1, "col": 2},
            "color_map": {"~": "primary", "≈": "accent"},
        },
        "flow_2": {
            "content": ["≈~≈", "~≈~", "≈~≈"],
            "anchor": {"row": 1, "col": 2},
            "color_map": {"~": "accent", "≈": "primary"},
        },
        "flow_3": {
            "content": ["~≈~", "≈~≈", "~≈~"],
            "anchor": {"row": 1, "col": 2},
            "color_map": {"~": "secondary", "≈": "primary"},
        },
        "flow_4": {
            "content": ["≈~≈", "~≈~", "≈~≈"],
            "anchor": {"row": 1, "col": 2},
            "color_map": {"~": "primary", "≈": "secondary"},
        },
    },
    "emitters": {
        "drop_emitter": {
            "chars": ["○", "•", "·"],
            "spawn_rate": 3,
            "lifetime_frames": 25,
            "velocity": {"x": [0.2, 0.5], "y": [0.3, 0.8]},
            "origin": {"row": 3, "col": 6},
            "spread": {"row": 0, "col": 1},
            "color": "accent",
            "fade": True,
            "gravity": 0.08,
        },
    },
    "triggers": {},
    "compositions": {
        "default": {
            "layers": ["pipes", "flow"],
            "rows": 6,
            "cols": 13,
        },
        "active": {
            "layers": ["pipes", "flow", "droplets"],
            "rows": 6,
            "cols": 13,
        },
    },
}


CONVERSATION_CASUAL_TEMPLATE: dict[str, Any] = {
    "schema_version": "1.0.0",
    "category": "conversation--casual",
    "version": "v1.0.0",
    "metadata": {
        "name": "Campfire",
        "metaphor": "Cozy campfire with flickering light",
        "author": "system",
        "tags": ["fire", "cozy", "warm"],
    },
    "palette": {
        "primary": "208",
        "secondary": "202",
        "accent": "220",
        "background": "black",
        "muted": "240",
        "glow": "223",
    },
    "layers": [
        {
            "id": "fire",
            "z": 0,
            "type": "loop",
            "frames": ["fire_1", "fire_2", "fire_3"],
            "frame_duration_ms": 200,
            "trigger": "always",
        },
    ],
    "frames": {
        "fire_1": {
            "content": [
                "   )  ",
                "  ( ) ",
                " (   )",
                "  ) ( ",
                " ▄▄▄▄▄",
            ],
            "anchor": {"row": 0, "col": 0},
            "color_map": {"(": "accent", ")": "primary", "▄": "secondary"},
        },
        "fire_2": {
            "content": [
                "  ( ) ",
                " (   )",
                "  ) ( ",
                " (   )",
                " ▄▄▄▄▄",
            ],
            "anchor": {"row": 0, "col": 0},
            "color_map": {"(": "primary", ")": "accent", "▄": "secondary"},
        },
        "fire_3": {
            "content": [
                " (   )",
                "  ) ( ",
                " (   )",
                "  ( ) ",
                " ▄▄▄▄▄",
            ],
            "anchor": {"row": 0, "col": 0},
            "color_map": {"(": "accent", ")": "secondary", "▄": "secondary"},
        },
    },
    "emitters": {},
    "triggers": {},
    "compositions": {
        "default": {
            "layers": ["fire"],
            "rows": 5,
            "cols": 6,
        },
    },
}


# Map of category to built-in template
BUILTIN_TEMPLATES: dict[str, dict[str, Any]] = {
    "_fallback": FALLBACK_TEMPLATE,
    "ml--training": ML_TRAINING_TEMPLATE,
    "code--craft": CODE_CRAFT_TEMPLATE,
    "data--flow": DATA_FLOW_TEMPLATE,
    "conversation--casual": CONVERSATION_CASUAL_TEMPLATE,
}


# =============================================================================
# Template Loader
# =============================================================================


class TemplateLoader:
    """Load and validate templates with fallback chain."""

    def __init__(self) -> None:
        self._cache: dict[str, VizTemplate] = {}

    def load(self, category: str) -> VizTemplate:
        """
        Load template for a category.
        
        Resolution order:
        1. User template from ~/.viz-claude/templates/
        2. Built-in template for category
        3. Built-in template for parent category
        4. Fallback template
        
        Args:
            category: Category name (e.g., "ml--training")
            
        Returns:
            Validated template
        """
        # Check cache
        if category in self._cache:
            return self._cache[category]

        template = None

        # Try user template
        try:
            storage = get_storage()
            user_template = storage.get_template(category)
            if user_template:
                template = user_template
                logger.debug(f"Loaded user template for {category}")
        except Exception as e:
            logger.debug(f"No user template for {category}: {e}")

        # Try built-in
        if template is None and category in BUILTIN_TEMPLATES:
            try:
                template = VizTemplate.model_validate(BUILTIN_TEMPLATES[category])
                logger.debug(f"Loaded built-in template for {category}")
            except Exception as e:
                logger.warning(f"Invalid built-in template for {category}: {e}")

        # Try parent category
        if template is None and "--" in category:
            parent = category.split("--")[0]
            parent_full = f"{parent}--*"  # Check for any subcategory
            for key in BUILTIN_TEMPLATES:
                if key.startswith(parent + "--"):
                    try:
                        template = VizTemplate.model_validate(BUILTIN_TEMPLATES[key])
                        logger.debug(f"Using template {key} for {category}")
                        break
                    except Exception:
                        continue

        # Ultimate fallback
        if template is None:
            template = VizTemplate.model_validate(FALLBACK_TEMPLATE)
            logger.debug(f"Using fallback template for {category}")

        # Cache and return
        self._cache[category] = template
        return template

    def load_raw(self, category: str) -> dict[str, Any]:
        """Load template as raw dict (for serialization)."""
        template = self.load(category)
        return template.model_dump()

    def validate(self, data: dict[str, Any]) -> VizTemplate:
        """
        Validate template data.
        
        Args:
            data: Raw template dict
            
        Returns:
            Validated template
            
        Raises:
            ValueError: If template is invalid
        """
        return VizTemplate.model_validate(data)

    def clear_cache(self) -> None:
        """Clear template cache."""
        self._cache.clear()

    def list_builtin(self) -> list[str]:
        """List built-in template categories."""
        return [k for k in BUILTIN_TEMPLATES.keys() if k != "_fallback"]


# =============================================================================
# Singleton
# =============================================================================


_loader: TemplateLoader | None = None


def get_loader() -> TemplateLoader:
    """Get the global template loader."""
    global _loader
    if _loader is None:
        _loader = TemplateLoader()
    return _loader
