"""Main CLI entry point for viz-claude."""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    """Main entry point for `viz` command."""
    parser = argparse.ArgumentParser(
        prog="viz",
        description="Terminal visualization companion for Claude Code",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # viz claude - wrap claude command
    claude_parser = subparsers.add_parser(
        "claude",
        help="Run Claude Code with visualization",
    )
    claude_parser.add_argument(
        "args",
        nargs="*",
        help="Arguments to pass to claude",
    )

    # viz install - setup
    install_parser = subparsers.add_parser(
        "install",
        help="Set up viz-claude configuration",
    )

    # viz status - check daemon
    status_parser = subparsers.add_parser(
        "status",
        help="Check viz-agent status",
    )

    # viz templates - list templates
    templates_parser = subparsers.add_parser(
        "templates",
        help="List available templates",
    )
    templates_parser.add_argument(
        "--category",
        "-c",
        help="Filter by category",
    )

    # viz categories - list categories
    categories_parser = subparsers.add_parser(
        "categories",
        help="List available categories",
    )

    # Parse args
    args = parser.parse_args()

    if args.command == "claude":
        from .wrapper import run_wrapper
        return run_wrapper(args.args)

    elif args.command == "install":
        from .commands import run_install
        return run_install()

    elif args.command == "status":
        from .commands import run_status
        return run_status()

    elif args.command == "templates":
        from .commands import run_templates
        return run_templates(args.category)

    elif args.command == "categories":
        from .commands import run_categories
        return run_categories()

    else:
        parser.print_help()
        return 0


if __name__ == "__main__":
    sys.exit(main())
