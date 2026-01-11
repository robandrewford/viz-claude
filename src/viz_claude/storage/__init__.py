"""Local file storage for viz-claude data."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core import SessionMetadata, Taxonomy, UserProfile, VizTemplate

logger = logging.getLogger(__name__)


def get_data_dir() -> Path:
    """Get the data directory for viz-claude."""
    # Check environment variable first
    if env_dir := os.environ.get("VIZ_CLAUDE_DATA"):
        return Path(env_dir)

    # Default to ~/.viz-claude
    return Path.home() / ".viz-claude"


class LocalStorage:
    """
    Local filesystem storage for viz-claude.
    
    Directory structure:
    ~/.viz-claude/
    ├── config.json          # Global configuration
    ├── profile.json         # User profile
    ├── taxonomy.json        # Category taxonomy
    ├── templates/           # Custom templates
    │   └── {category}/
    │       └── {name}.json
    └── sessions/            # Session history
        └── {session_id}.json
    """

    def __init__(self, base_path: Path | str | None = None):
        """
        Initialize local storage.
        
        Args:
            base_path: Base directory (defaults to ~/.viz-claude)
        """
        if base_path is None:
            self.base_path = get_data_dir()
        else:
            self.base_path = Path(base_path)

        # Ensure directories exist
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        """Create required directories."""
        dirs = [
            self.base_path,
            self.base_path / "templates",
            self.base_path / "sessions",
        ]
        for d in dirs:
            d.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        """Read JSON file, returning None if not found."""
        try:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read {path}: {e}")
        return None

    def _write_json(self, path: Path, data: dict[str, Any]) -> bool:
        """Write JSON file."""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )
            return True
        except OSError as e:
            logger.error(f"Failed to write {path}: {e}")
            return False

    # -------------------------------------------------------------------------
    # Profile
    # -------------------------------------------------------------------------

    def get_profile(self) -> UserProfile | None:
        """Get user profile."""
        data = self._read_json(self.base_path / "profile.json")
        if data:
            try:
                return UserProfile.model_validate(data)
            except Exception as e:
                logger.warning(f"Invalid profile data: {e}")
        return None

    def save_profile(self, profile: UserProfile) -> bool:
        """Save user profile."""
        return self._write_json(
            self.base_path / "profile.json",
            profile.model_dump(mode="json"),
        )

    def get_or_create_profile(self, user_id: str = "local") -> UserProfile:
        """Get existing profile or create new one."""
        profile = self.get_profile()
        if profile is None:
            profile = UserProfile(user_id=user_id)
            self.save_profile(profile)
        return profile

    # -------------------------------------------------------------------------
    # Taxonomy
    # -------------------------------------------------------------------------

    def get_taxonomy(self) -> Taxonomy | None:
        """Get category taxonomy."""
        data = self._read_json(self.base_path / "taxonomy.json")
        if data:
            try:
                return Taxonomy.model_validate(data)
            except Exception as e:
                logger.warning(f"Invalid taxonomy data: {e}")
        return None

    def save_taxonomy(self, taxonomy: Taxonomy) -> bool:
        """Save category taxonomy."""
        return self._write_json(
            self.base_path / "taxonomy.json",
            taxonomy.model_dump(mode="json"),
        )

    # -------------------------------------------------------------------------
    # Templates
    # -------------------------------------------------------------------------

    def get_template(self, category: str, name: str = "default") -> VizTemplate | None:
        """
        Get a template by category and name.
        
        Args:
            category: Category (e.g., "ml--training")
            name: Template name (default: "default")
            
        Returns:
            Template or None if not found
        """
        # Sanitize category for filesystem
        safe_category = category.replace("/", "--").replace(":", "--")
        path = self.base_path / "templates" / safe_category / f"{name}.json"

        data = self._read_json(path)
        if data:
            try:
                return VizTemplate.model_validate(data)
            except Exception as e:
                logger.warning(f"Invalid template {path}: {e}")
        return None

    def save_template(self, template: VizTemplate, name: str = "default") -> bool:
        """Save a template."""
        safe_category = template.category.replace("/", "--").replace(":", "--")
        path = self.base_path / "templates" / safe_category / f"{name}.json"
        return self._write_json(path, template.model_dump(mode="json"))

    def list_templates(self, category: str | None = None) -> list[dict[str, str]]:
        """
        List available templates.
        
        Args:
            category: Filter by category (None for all)
            
        Returns:
            List of {"category": ..., "name": ...} dicts
        """
        templates = []
        templates_dir = self.base_path / "templates"

        if not templates_dir.exists():
            return templates

        for cat_dir in templates_dir.iterdir():
            if not cat_dir.is_dir():
                continue

            cat_name = cat_dir.name
            if category and cat_name != category.replace("/", "--").replace(":", "--"):
                continue

            for template_file in cat_dir.glob("*.json"):
                templates.append({
                    "category": cat_name,
                    "name": template_file.stem,
                    "path": str(template_file),
                })

        return templates

    # -------------------------------------------------------------------------
    # Sessions
    # -------------------------------------------------------------------------

    def get_session(self, session_id: str) -> SessionMetadata | None:
        """Get session by ID."""
        path = self.base_path / "sessions" / f"{session_id}.json"
        data = self._read_json(path)
        if data:
            try:
                return SessionMetadata.model_validate(data)
            except Exception as e:
                logger.warning(f"Invalid session {path}: {e}")
        return None

    def save_session(self, session: SessionMetadata) -> bool:
        """Save session metadata."""
        path = self.base_path / "sessions" / f"{session.session_id}.json"
        return self._write_json(path, session.model_dump(mode="json"))

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        """
        List recent sessions.
        
        Args:
            limit: Maximum number to return
            
        Returns:
            List of session summaries, newest first
        """
        sessions_dir = self.base_path / "sessions"
        if not sessions_dir.exists():
            return []

        # Get all session files with mtime
        session_files = []
        for path in sessions_dir.glob("*.json"):
            try:
                mtime = path.stat().st_mtime
                session_files.append((mtime, path))
            except OSError:
                continue

        # Sort by mtime descending
        session_files.sort(reverse=True)

        # Load summaries
        sessions = []
        for _, path in session_files[:limit]:
            data = self._read_json(path)
            if data:
                sessions.append({
                    "session_id": data.get("session_id"),
                    "category": data.get("category"),
                    "started_at": data.get("started_at"),
                    "message_count": data.get("message_count", 0),
                })

        return sessions

    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        path = self.base_path / "sessions" / f"{session_id}.json"
        try:
            if path.exists():
                path.unlink()
                return True
        except OSError as e:
            logger.error(f"Failed to delete session: {e}")
        return False

    # -------------------------------------------------------------------------
    # Config
    # -------------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        """Get global configuration."""
        return self._read_json(self.base_path / "config.json") or {}

    def save_config(self, config: dict[str, Any]) -> bool:
        """Save global configuration."""
        return self._write_json(self.base_path / "config.json", config)

    def update_config(self, updates: dict[str, Any]) -> bool:
        """Update configuration values."""
        config = self.get_config()
        config.update(updates)
        return self.save_config(config)


# =============================================================================
# Singleton Instance
# =============================================================================


_storage: LocalStorage | None = None


def get_storage() -> LocalStorage:
    """Get the global storage instance."""
    global _storage
    if _storage is None:
        _storage = LocalStorage()
    return _storage
