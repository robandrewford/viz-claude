"""CLI utility commands."""

from __future__ import annotations

import sys

from ..storage import get_storage
from ..templates import get_loader, BUILTIN_TEMPLATES


def run_install() -> int:
    """Set up viz-claude configuration."""
    print("Setting up viz-claude...")

    # Initialize storage (creates directories)
    storage = get_storage()

    # Create default profile
    profile = storage.get_or_create_profile()
    print(f"  Profile: {storage.base_path / 'profile.json'}")

    # Copy built-in templates to local storage
    loader = get_loader()
    for category in loader.list_builtin():
        template = loader.load(category)
        storage.save_template(template)
        print(f"  Template: {category}")

    print()
    print("Installation complete!")
    print()
    print("Usage:")
    print("  1. Start the visualization agent:")
    print("     $ viz-agent &")
    print()
    print("  2. Open a new terminal and start the renderer:")
    print("     $ viz-renderer")
    print()
    print("  3. In your main terminal, use Claude with viz wrapper:")
    print("     $ viz claude")
    print()
    print("Or run without agent (no classification):")
    print("     $ claude  # (no visualization)")
    print()

    return 0


def run_status() -> int:
    """Check viz-agent status."""
    import asyncio
    from ..core.protocol import SocketClient, get_socket_path

    async def check() -> dict | None:
        client = SocketClient()
        if await client.connect(timeout=1.0):
            await client.send({"msg": "command", "name": "status", "args": []})
            response = await client.receive()
            await client.close()
            return response
        return None

    response = asyncio.run(check())

    if response:
        running = response.get("running", False)
        category = response.get("category", "none")
        confidence = response.get("confidence")
        composition = response.get("composition", "default")

        print(f"viz-agent: running")
        print(f"  Category: {category}", end="")
        if confidence is not None:
            print(f" ({confidence:.0%})")
        else:
            print()
        print(f"  Composition: {composition}")
        print(f"  Socket: {get_socket_path()}")
    else:
        print("viz-agent: not running")
        print()
        print("Start with: viz-agent")

    return 0


def run_templates(category: str | None) -> int:
    """List available templates."""
    storage = get_storage()
    loader = get_loader()

    print("Built-in templates:")
    for cat in loader.list_builtin():
        if category and category not in cat:
            continue
        template = loader.load(cat)
        print(f"  {cat}: {template.metadata.name}")
        print(f"    {template.metadata.metaphor}")

    print()
    print("User templates:")
    user_templates = storage.list_templates(category)
    if user_templates:
        for t in user_templates:
            print(f"  {t['category']}/{t['name']}")
    else:
        print("  (none)")
        print(f"  Add templates to: {storage.base_path / 'templates/'}")

    return 0


def run_categories() -> int:
    """List available categories."""
    from ..core.classifier import HeuristicClassifier

    print("Categories (with detection signals):")
    print()

    # Group by parent
    categories: dict[str, list[str]] = {}

    for cat in BUILTIN_TEMPLATES.keys():
        if cat == "_fallback":
            continue
        if "--" in cat:
            parent = cat.split("--")[0]
        else:
            parent = cat
        if parent not in categories:
            categories[parent] = []
        categories[parent].append(cat)

    for parent, cats in sorted(categories.items()):
        print(f"{parent}/")
        for cat in sorted(cats):
            template = BUILTIN_TEMPLATES.get(cat, {})
            metadata = template.get("metadata", {})
            name = metadata.get("name", "")
            print(f"  {cat.split('--')[-1]}: {name}")

    print()
    print("Detection is based on:")
    print("  - Tool usage (bash, edit, read, web_search)")
    print("  - Content keywords")
    print("  - User preferences")

    return 0
