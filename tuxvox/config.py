# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""TuxVox configuration persistence module.

Reads and writes application settings as JSON, with thread-safe access
and automatic saving on every mutation.
"""

import json
import os
import threading
from typing import Any

from tuxvox.logger import logger

# ---------------------------------------------------------------------------
# Default settings path — follows the XDG Base Directory Specification
# ---------------------------------------------------------------------------

_CONFIG_DIR: str = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
    "tuxvox",
)
_CONFIG_FILE: str = os.path.join(_CONFIG_DIR, "settings.json")


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    "model": "base",
    "language": "auto",
    "microphone": "default",
    "streaming_speed": 3.0,
    "confidence_threshold": 0.5,
    "punctuation": True,
    "save_history": False,
    "history_path": os.path.expanduser("~/Documents/TuxVox"),
    "diagnostic_logs": False,
    "paragraph_mode": False,
    # v0.2 — Experimental Mode keys
    "experimental_mode": False,
    "output_mode": "panel",
    "global_hotkey": "ctrl+shift+l",
    "inline_wayland_permission_granted": False,
    "background_on_close": True,
    "has_completed_onboarding": False,
}


# ---------------------------------------------------------------------------
# Config class
# ---------------------------------------------------------------------------


class Config:
    """Thread-safe, JSON-backed application configuration.

    Settings are kept in memory as a plain ``dict`` and persisted to
    ``~/.config/tuxvox/settings.json`` (or the ``XDG_CONFIG_HOME``
    equivalent).

    Example::

        cfg = Config()
        cfg.load()
        cfg.set("model", "small")
        print(cfg.get("model"))  # "small"
    """

    def __init__(self) -> None:
        """Create a new Config instance with default values."""
        self._lock = threading.Lock()
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self._path: str = _CONFIG_FILE

    # -- persistence --------------------------------------------------------

    def load(self) -> None:
        """Load settings from the JSON config file.

        Falls back to built-in defaults when the file is missing,
        unreadable, or contains invalid JSON.
        """
        with self._lock:
            if not os.path.isfile(self._path):
                logger.info("Config file not found at %s — using defaults.", self._path)
                self._data = dict(_DEFAULTS)
                return

            try:
                with open(self._path, "r", encoding="utf-8") as fh:
                    loaded: dict[str, Any] = json.load(fh)

                # Merge: start from defaults so missing keys are filled in.
                merged = dict(_DEFAULTS)
                merged.update(loaded)
                self._data = merged
                logger.info("Configuration loaded from %s.", self._path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read config (%s) — using defaults.", exc)
                self._data = dict(_DEFAULTS)

    def save(self) -> None:
        """Persist the current settings to the JSON config file.

        Creates parent directories if they do not exist.
        """
        with self._lock:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                with open(self._path, "w", encoding="utf-8") as fh:
                    json.dump(self._data, fh, indent=2)
                logger.debug("Configuration saved to %s.", self._path)
            except OSError as exc:
                logger.error("Unable to save config: %s", exc)

    # -- accessors ----------------------------------------------------------

    def get(self, key: str) -> Any:
        """Retrieve a single setting value.

        Args:
            key: The setting name (must be a recognised key).

        Returns:
            The current value for *key*, or ``None`` if the key is unknown.
        """
        with self._lock:
            return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        """Update a setting and immediately persist the change.

        Args:
            key: The setting name.
            value: The new value to store.
        """
        with self._lock:
            self._data[key] = value
            logger.debug("Config key '%s' set to %r.", key, value)

        # save() acquires the lock internally, so release first.
        self.save()
