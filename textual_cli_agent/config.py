from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict
import os

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages persistent configuration using XDG directories."""

    def __init__(self, app_name: str = "textual-cli-agent"):
        self.app_name = app_name
        self._config_dir = self._get_config_dir()
        self._config_file = self._config_dir / "config.json"
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _get_config_dir(self) -> Path:
        """Get XDG-compliant config directory."""
        if os.name == "nt":  # Windows
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        else:  # Unix-like systems
            xdg_config = os.environ.get("XDG_CONFIG_HOME")
            if xdg_config:
                base = Path(xdg_config)
            else:
                base = Path.home() / ".config"

        config_dir = base / self.app_name
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir

    def _load_config(self) -> None:
        """Load configuration from file."""
        try:
            if self._config_file.exists():
                with open(self._config_file, "r", encoding="utf-8") as f:
                    self._config = json.load(f)
                logger.debug(f"Loaded config from {self._config_file}")
            else:
                self._config = {}
                logger.debug("No config file found, using defaults")
        except Exception as e:
            logger.warning(f"Failed to load config from {self._config_file}: {e}")
            self._config = {}

    def _save_config(self) -> None:
        """Save configuration to file."""
        try:
            with open(self._config_file, "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.debug(f"Saved config to {self._config_file}")
        except Exception as e:
            logger.error(f"Failed to save config to {self._config_file}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value and save."""
        self._config[key] = value
        self._save_config()

    def update(self, updates: Dict[str, Any]) -> None:
        """Update multiple configuration values and save."""
        self._config.update(updates)
        self._save_config()

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values."""
        return self._config.copy()

    @property
    def config_file_path(self) -> Path:
        """Get the config file path."""
        return self._config_file
