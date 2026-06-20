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

"""Global hotkey manager for TuxVox experimental mode.

Uses :mod:`pynput.keyboard` to listen for a user-defined keyboard
shortcut and fire a callback when all keys in the combination are held
simultaneously.

Designed to degrade gracefully: if ``pynput`` cannot register a listener
(common on Wayland without ``libinput`` permissions) an error message is
returned and the application continues without hotkey support.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from tuxvox.logger import logger

# ---------------------------------------------------------------------------
# Known shortcut conflicts
# ---------------------------------------------------------------------------

_KNOWN_CONFLICTS: set[frozenset[str]] = {
    frozenset({"super", "l"}),  # Lock screen
    frozenset({"ctrl", "c"}),  # Copy
    frozenset({"ctrl", "v"}),  # Paste
    frozenset({"ctrl", "x"}),  # Cut
    frozenset({"ctrl", "z"}),  # Undo
    frozenset({"ctrl", "a"}),  # Select all
    frozenset({"ctrl", "s"}),  # Save
    frozenset({"ctrl", "w"}),  # Close tab
    frozenset({"ctrl", "q"}),  # Quit
    frozenset({"alt", "f4"}),  # Close window
    frozenset({"alt", "tab"}),  # Window switcher
    frozenset({"super", "tab"}),  # Window overview
    frozenset({"super", "s"}),  # Activities (GNOME)
    frozenset({"super", "a"}),  # App grid (GNOME)
    frozenset({"ctrl", "alt", "t"}),  # Terminal
    frozenset({"ctrl", "alt", "delete"}),  # System monitor
}


# ---------------------------------------------------------------------------
# HotkeyManager
# ---------------------------------------------------------------------------


class HotkeyManager:
    """Register and listen for a global keyboard shortcut.

    Example::

        mgr = HotkeyManager()
        err = mgr.register("ctrl+shift+l", my_callback)
        if err:
            print("Hotkey failed:", err)

        # Later:
        mgr.unregister()
    """

    def __init__(self) -> None:
        self._listener: Any = None
        self._hotkey_keys: set[Any] = set()
        self._pressed_keys: set[Any] = set()
        self._callback: Callable[[], None] | None = None
        self._lock = threading.Lock()
        self._registered_hotkey: str | None = None
        self._hotkey_fired: bool = False
        self._evdev: Any = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register(self, hotkey_str: str, callback: Callable[[], None]) -> str | None:
        """Parse *hotkey_str* and start a global listener.

        Args:
            hotkey_str: Human-readable shortcut, e.g. ``'ctrl+shift+l'``.
            callback: Function called (from the listener thread) when
                the shortcut is activated.

        Returns:
            ``None`` on success, or a human-readable error string.
        """
        # Validate for conflicts first
        conflict_msg = self._check_conflicts(hotkey_str)
        if conflict_msg:
            logger.warning(conflict_msg)
            # Warn but don't block — the user chose this deliberately.

        keys = self._parse_hotkey(hotkey_str)
        if keys is None:
            msg = f"Could not parse hotkey string: '{hotkey_str}'"
            logger.error(msg)
            return msg

        # Unregister any existing listener
        self.unregister()

        self._hotkey_keys = keys
        self._callback = callback
        self._registered_hotkey = hotkey_str

        # Preferred backend: read evdev devices directly. This works on
        # GNOME Wayland (where pynput only sees XWayland windows) provided
        # the user can read /dev/input/event* (input group membership).
        evdev_msg = self._try_register_evdev(keys, callback, hotkey_str)
        if evdev_msg is None:
            return None  # evdev backend succeeded

        logger.info(
            "evdev hotkey backend unavailable (%s); falling back to pynput.",
            evdev_msg,
        )

        try:
            from pynput.keyboard import Listener

            self._pressed_keys = set()
            self._listener = Listener(
                on_press=self._on_press,
                on_release=self._on_release,
            )
            self._listener.daemon = True
            self._listener.start()

            logger.info("Global hotkey registered (pynput): %s", hotkey_str)
            return None  # success

        except ImportError:
            msg = "pynput is not installed. Install it with: " "pip install pynput"
            logger.error(msg)
            return msg

        except Exception as exc:
            msg = (
                f"Failed to register global hotkey '{hotkey_str}': {exc}. "
                "This may happen on Wayland if the compositor does not "
                "allow input monitoring."
            )
            logger.error(msg)
            return msg

    def _try_register_evdev(
        self, keys: set[str], callback: Callable[[], None], hotkey_str: str
    ) -> str | None:
        """Attempt to start the evdev backend.

        Returns ``None`` on success, or an error/unavailability message.
        """
        try:
            from tuxvox.experimental.evdev_input import EvdevHotkeyListener
        except Exception as exc:  # pragma: no cover - import guard
            return f"evdev module import failed: {exc}"

        if not EvdevHotkeyListener.is_available():
            return "no readable evdev keyboard devices"

        listener = EvdevHotkeyListener()
        ok, msg = listener.start(keys, callback)
        if not ok:
            return msg

        self._evdev = listener
        logger.info("Global hotkey registered (evdev): %s", hotkey_str)
        return None

    def unregister(self) -> None:
        """Stop the global listener and release resources."""
        with self._lock:
            if self._evdev is not None:
                try:
                    self._evdev.stop()
                except Exception as exc:
                    logger.debug("Error stopping evdev listener: %s", exc)
                self._evdev = None

            if self._listener is not None:
                try:
                    self._listener.stop()
                except Exception as exc:
                    logger.debug("Error stopping hotkey listener: %s", exc)
                self._listener = None
                logger.info("Global hotkey unregistered.")

            self._hotkey_keys = set()
            self._pressed_keys = set()
            self._callback = None
            self._registered_hotkey = None
            self._hotkey_fired = False

    def change_hotkey(self, new_hotkey_str: str) -> str | None:
        """Replace the current hotkey with a new one.

        Args:
            new_hotkey_str: The new shortcut string.

        Returns:
            ``None`` on success, or a human-readable error string.
        """
        callback = self._callback
        if callback is None:
            msg = "No callback registered — cannot change hotkey."
            logger.warning(msg)
            return msg

        self.unregister()
        return self.register(new_hotkey_str, callback)

    @property
    def current_hotkey(self) -> str | None:
        """The currently registered hotkey string, or ``None``."""
        return self._registered_hotkey

    # ------------------------------------------------------------------
    # Listener callbacks (run on pynput thread)
    # ------------------------------------------------------------------

    def _on_press(self, key: Any) -> None:
        """Track pressed keys and fire callback when combo is matched."""
        normalised = self._normalise_key(key)
        cb = None
        with self._lock:
            self._pressed_keys.add(normalised)
            if (
                self._hotkey_keys
                and self._hotkey_keys.issubset(self._pressed_keys)
                and not self._hotkey_fired
            ):
                self._hotkey_fired = True
                cb = self._callback
        # Invoke outside the lock to avoid deadlocks.
        if cb:
            try:
                cb()
            except Exception as exc:
                logger.error("Hotkey callback raised: %s", exc)

    def _on_release(self, key: Any) -> None:
        """Remove released key from the pressed set."""
        normalised = self._normalise_key(key)
        with self._lock:
            self._pressed_keys.discard(normalised)
            if normalised in self._hotkey_keys:
                self._hotkey_fired = False

    # ------------------------------------------------------------------
    # Parsing & normalisation
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_hotkey(hotkey_str: str) -> set[str] | None:
        """Convert a human-readable hotkey string into a set of key names.

        Supports modifiers: ``super``, ``ctrl``, ``alt``, ``shift`` plus
        any single letter, digit, or function key.

        Returns:
            A set of normalised key-name strings, or ``None`` on error.
        """
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        if not parts:
            return None

        keys: set[str] = set()
        for part in parts:
            normalised = _MODIFIER_ALIASES.get(part, part)
            keys.add(normalised)

        if not keys:
            return None

        return keys

    @staticmethod
    def _normalise_key(key: Any) -> str:
        """Map a pynput key object to a canonical string name."""
        try:
            from pynput.keyboard import Key

            # Check well-known modifier keys
            _KEY_MAP: dict[Any, str] = {
                Key.cmd: "super",
                Key.cmd_l: "super",
                Key.cmd_r: "super",
                Key.ctrl: "ctrl",
                Key.ctrl_l: "ctrl",
                Key.ctrl_r: "ctrl",
                Key.alt: "alt",
                Key.alt_l: "alt",
                Key.alt_r: "alt",
                Key.alt_gr: "alt",
                Key.shift: "shift",
                Key.shift_l: "shift",
                Key.shift_r: "shift",
                Key.space: "space",
                Key.enter: "enter",
                Key.tab: "tab",
                Key.esc: "escape",
                Key.backspace: "backspace",
                Key.delete: "delete",
                Key.f1: "f1",
                Key.f2: "f2",
                Key.f3: "f3",
                Key.f4: "f4",
                Key.f5: "f5",
                Key.f6: "f6",
                Key.f7: "f7",
                Key.f8: "f8",
                Key.f9: "f9",
                Key.f10: "f10",
                Key.f11: "f11",
                Key.f12: "f12",
            }

            if key in _KEY_MAP:
                return _KEY_MAP[key]
        except ImportError:
            pass

        # For character keys, use the character itself.
        try:
            ch = key.char
            if ch is not None:
                return ch.lower()
        except AttributeError:
            pass

        # Fallback: string representation.
        return str(key).lower().replace("key.", "")

    @staticmethod
    def _check_conflicts(hotkey_str: str) -> str | None:
        """Return a warning message if *hotkey_str* matches a known OS shortcut."""
        parts = frozenset(
            _MODIFIER_ALIASES.get(p.strip().lower(), p.strip().lower())
            for p in hotkey_str.split("+")
        )
        if parts in _KNOWN_CONFLICTS:
            return (
                f"Warning: '{hotkey_str}' conflicts with a common system "
                f"shortcut. This may cause unexpected behaviour."
            )
        return None


# ---------------------------------------------------------------------------
# Modifier aliases (maps user-facing names to canonical names)
# ---------------------------------------------------------------------------

_MODIFIER_ALIASES: dict[str, str] = {
    "super": "super",
    "win": "super",
    "meta": "super",
    "cmd": "super",
    "command": "super",
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "option": "alt",
    "shift": "shift",
}
