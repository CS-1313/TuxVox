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

"""Low-level evdev/uinput backend for TuxVox experimental mode.

This module provides two compositor-independent capabilities that work on
GNOME Wayland (where ``pynput`` and ``xdotool`` fail):

* :class:`EvdevHotkeyListener` reads ``/dev/input/event*`` directly to detect
  a global keyboard shortcut, regardless of which window is focused.
* :class:`UinputTyper` injects keystrokes through ``/dev/uinput`` at the
  kernel level, typing into whatever window currently has focus.

Both degrade gracefully: if the required device nodes are not accessible an
``is_available()`` check returns ``False`` and the caller can fall back to the
legacy ``pynput``/``xdotool`` paths.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Callable

from tuxvox.logger import logger

try:
    import evdev
    from evdev import InputDevice, UInput, ecodes

    _EVDEV_IMPORT_OK = True
except Exception as _exc:  # pragma: no cover - import guard
    evdev = None  # type: ignore
    InputDevice = None  # type: ignore
    UInput = None  # type: ignore
    ecodes = None  # type: ignore
    _EVDEV_IMPORT_OK = False
    logger.debug("evdev import failed: %s", _exc)


# ---------------------------------------------------------------------------
# Hotkey name -> set of evdev ecodes
# ---------------------------------------------------------------------------


def _build_name_to_ecodes() -> dict[str, set[int]]:
    """Map canonical hotkey-name strings to the set of evdev key codes."""
    if not _EVDEV_IMPORT_OK:
        return {}

    e = ecodes
    mapping: dict[str, set[int]] = {
        "super": {e.KEY_LEFTMETA, e.KEY_RIGHTMETA},
        "ctrl": {e.KEY_LEFTCTRL, e.KEY_RIGHTCTRL},
        "alt": {e.KEY_LEFTALT, e.KEY_RIGHTALT},
        "shift": {e.KEY_LEFTSHIFT, e.KEY_RIGHTSHIFT},
        "space": {e.KEY_SPACE},
        "enter": {e.KEY_ENTER},
        "tab": {e.KEY_TAB},
        "escape": {e.KEY_ESC},
        "backspace": {e.KEY_BACKSPACE},
        "delete": {e.KEY_DELETE},
    }

    for ch in "abcdefghijklmnopqrstuvwxyz":
        mapping[ch] = {getattr(e, f"KEY_{ch.upper()}")}
    for d in "0123456789":
        mapping[d] = {getattr(e, f"KEY_{d}")}
    for n in range(1, 13):
        mapping[f"f{n}"] = {getattr(e, f"KEY_F{n}")}

    return mapping


# ---------------------------------------------------------------------------
# Character -> (ecode, needs_shift) for US layout, used by UinputTyper
# ---------------------------------------------------------------------------


def _build_char_map() -> dict[str, tuple[int, bool]]:
    if not _EVDEV_IMPORT_OK:
        return {}

    e = ecodes
    m: dict[str, tuple[int, bool]] = {}

    for ch in "abcdefghijklmnopqrstuvwxyz":
        m[ch] = (getattr(e, f"KEY_{ch.upper()}"), False)
        m[ch.upper()] = (getattr(e, f"KEY_{ch.upper()}"), True)

    for d in "0123456789":
        m[d] = (getattr(e, f"KEY_{d}"), False)

    shifted_digits = {
        ")": e.KEY_0,
        "!": e.KEY_1,
        "@": e.KEY_2,
        "#": e.KEY_3,
        "$": e.KEY_4,
        "%": e.KEY_5,
        "^": e.KEY_6,
        "&": e.KEY_7,
        "*": e.KEY_8,
        "(": e.KEY_9,
    }
    for ch, code in shifted_digits.items():
        m[ch] = (code, True)

    m[" "] = (e.KEY_SPACE, False)
    m["\t"] = (e.KEY_TAB, False)
    m["\n"] = (e.KEY_ENTER, False)

    punct = {
        "-": (e.KEY_MINUS, False),
        "_": (e.KEY_MINUS, True),
        "=": (e.KEY_EQUAL, False),
        "+": (e.KEY_EQUAL, True),
        "[": (e.KEY_LEFTBRACE, False),
        "{": (e.KEY_LEFTBRACE, True),
        "]": (e.KEY_RIGHTBRACE, False),
        "}": (e.KEY_RIGHTBRACE, True),
        "\\": (e.KEY_BACKSLASH, False),
        "|": (e.KEY_BACKSLASH, True),
        ";": (e.KEY_SEMICOLON, False),
        ":": (e.KEY_SEMICOLON, True),
        "'": (e.KEY_APOSTROPHE, False),
        '"': (e.KEY_APOSTROPHE, True),
        "`": (e.KEY_GRAVE, False),
        "~": (e.KEY_GRAVE, True),
        ",": (e.KEY_COMMA, False),
        "<": (e.KEY_COMMA, True),
        ".": (e.KEY_DOT, False),
        ">": (e.KEY_DOT, True),
        "/": (e.KEY_SLASH, False),
        "?": (e.KEY_SLASH, True),
    }
    m.update(punct)
    return m


# ---------------------------------------------------------------------------
# EvdevHotkeyListener
# ---------------------------------------------------------------------------


class EvdevHotkeyListener:
    """Detect a global hotkey by reading evdev keyboard devices directly.

    Works on any compositor (X11 or Wayland) provided the user has read
    access to ``/dev/input/event*`` (typically by membership of the
    ``input`` group).
    """

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._devices: list["InputDevice"] = []
        self._hotkey_ecodes: list[set[int]] = []
        self._callback: Callable[[], None] | None = None
        self._fired = False

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` if evdev keyboard devices can be read."""
        if not _EVDEV_IMPORT_OK:
            return False
        try:
            for path in evdev.list_devices():
                try:
                    dev = InputDevice(path)
                except Exception:
                    continue
                caps = dev.capabilities()
                try:
                    if ecodes.EV_KEY in caps and ecodes.KEY_A in caps.get(ecodes.EV_KEY, []):
                        dev.close()
                        return True
                except Exception:
                    pass
                dev.close()
        except Exception as exc:
            logger.debug("evdev availability check failed: %s", exc)
        return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, hotkey_names: set[str], callback: Callable[[], None]) -> tuple[bool, str]:
        """Begin listening for the hotkey described by *hotkey_names*.

        Args:
            hotkey_names: Canonical key-name strings (e.g. ``{"ctrl", "shift", "l"}``).
            callback: Invoked from the listener thread when all keys are held.

        Returns:
            A ``(success, message)`` tuple.
        """
        if not _EVDEV_IMPORT_OK:
            return False, "evdev is not available."

        name_map = _build_name_to_ecodes()
        ecode_sets: list[set[int]] = []
        for name in hotkey_names:
            codes = name_map.get(name)
            if not codes:
                return False, f"evdev: unsupported hotkey key '{name}'."
            ecode_sets.append(codes)

        if not ecode_sets:
            return False, "evdev: empty hotkey."

        devices: list["InputDevice"] = []
        try:
            for path in evdev.list_devices():
                try:
                    dev = InputDevice(path)
                except Exception:
                    continue
                caps = dev.capabilities()
                if ecodes.EV_KEY in caps and ecodes.KEY_A in caps.get(ecodes.EV_KEY, []):
                    devices.append(dev)
                else:
                    dev.close()
        except Exception as exc:
            return False, f"evdev: failed to enumerate devices: {exc}"

        if not devices:
            return False, "evdev: no readable keyboard devices found."

        self._devices = devices
        self._hotkey_ecodes = ecode_sets
        self._callback = callback
        self._fired = False
        self._stop_event.clear()

        self._thread = threading.Thread(target=self._run_loop, name="evdev-hotkey", daemon=True)
        self._thread.start()
        logger.info("evdev hotkey listener started on %d device(s).", len(devices))
        return True, "OK"

    def stop(self) -> None:
        """Stop the listener and release all device handles."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        for dev in self._devices:
            try:
                dev.close()
            except Exception:
                pass
        self._devices = []
        self._callback = None
        self._fired = False
        logger.info("evdev hotkey listener stopped.")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _all_hotkey_ecodes(self) -> set[int]:
        flat: set[int] = set()
        for codes in self._hotkey_ecodes:
            flat |= codes
        return flat

    def _is_combo_pressed(self, pressed: set[int]) -> bool:
        return all(bool(codes & pressed) for codes in self._hotkey_ecodes)

    def _run_loop(self) -> None:
        import selectors

        selector = selectors.DefaultSelector()
        for dev in self._devices:
            try:
                selector.register(dev, selectors.EVENT_READ)
            except Exception as exc:
                logger.debug("evdev: cannot register device %s: %s", dev.path, exc)

        pressed: set[int] = set()
        hotkey_all = self._all_hotkey_ecodes()

        try:
            while not self._stop_event.is_set():
                events = selector.select(timeout=0.5)
                if not events:
                    continue
                for key, _mask in events:
                    dev = key.fileobj
                    try:
                        for event in dev.read():
                            if event.type != ecodes.EV_KEY:
                                continue
                            if event.value == 1:  # key down
                                pressed.add(event.code)
                                if not self._fired and self._is_combo_pressed(pressed):
                                    self._fired = True
                                    self._fire()
                            elif event.value == 0:  # key up
                                pressed.discard(event.code)
                                if event.code in hotkey_all:
                                    self._fired = False
                            # value == 2 (autorepeat) ignored
                    except OSError:
                        continue
                    except Exception as exc:
                        logger.debug("evdev read error: %s", exc)
        finally:
            try:
                selector.close()
            except Exception:
                pass

    def _fire(self) -> None:
        cb = self._callback
        if cb is None:
            return
        try:
            cb()
        except Exception as exc:
            logger.error("evdev hotkey callback raised: %s", exc)


# ---------------------------------------------------------------------------
# UinputTyper
# ---------------------------------------------------------------------------


class UinputTyper:
    """Type text by injecting key events through ``/dev/uinput``.

    Kernel-level injection bypasses the display server entirely, so it works
    identically on X11 and Wayland and types into whichever window currently
    holds the keyboard focus.
    """

    def __init__(self) -> None:
        self._char_map = _build_char_map()

    @staticmethod
    def is_available() -> bool:
        """Return ``True`` if ``/dev/uinput`` is writable."""
        if not _EVDEV_IMPORT_OK:
            return False
        return os.access("/dev/uinput", os.W_OK)

    def type_text(self, text: str) -> tuple[bool, str]:
        """Type *text* into the currently focused window.

        Returns:
            A ``(success, message)`` tuple.
        """
        if not text:
            return True, "Nothing to type."
        if not _EVDEV_IMPORT_OK:
            return False, "evdev is not available."
        if not os.access("/dev/uinput", os.W_OK):
            return False, (
                "/dev/uinput is not writable. Run ~/TuxVox/scripts/setup-uinput.sh "
                "once with sudo to enable inline typing."
            )

        ui = None
        try:
            ui = UInput()
            skipped = 0
            time.sleep(0.05)
            for ch in text:
                entry = self._char_map.get(ch)
                if entry is None:
                    skipped += 1
                    continue
                code, needs_shift = entry
                self._tap(ui, code, needs_shift)
                time.sleep(0.003)

            msg = "OK" if skipped == 0 else f"OK ({skipped} chars skipped)"
            logger.info(
                "uinput typed %d characters (%d skipped).",
                len(text) - skipped,
                skipped,
            )
            return True, msg

        except Exception as exc:
            msg = f"uinput typing failed: {exc}"
            logger.error(msg)
            return False, msg
        finally:
            if ui is not None:
                try:
                    ui.close()
                except Exception:
                    pass

    def _tap(self, ui: "UInput", code: int, needs_shift: bool) -> None:
        e = ecodes
        if needs_shift:
            ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 1)
            ui.syn()
        ui.write(e.EV_KEY, code, 1)
        ui.syn()
        ui.write(e.EV_KEY, code, 0)
        ui.syn()
        if needs_shift:
            ui.write(e.EV_KEY, e.KEY_LEFTSHIFT, 0)
            ui.syn()
