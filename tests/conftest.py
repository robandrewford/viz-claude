"""Pytest configuration and fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()
