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

"""Inline typing module for TuxVox experimental mode.

Saves the currently focused window *before* the TuxVox overlay
appears, then restores focus and types the transcribed text into that
window.  Two backends are supported:

* **X11** — uses ``xdotool`` via :mod:`subprocess`.
* **Wayland** — delegates to :class:`~tuxvox.experimental.wayland_portal.WaylandPortal`.

On any failure the caller receives an error message and can fall back to
panel mode.  This module will never crash.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any

from tuxvox.logger import logger

# ---------------------------------------------------------------------------
# Display-server detection
# ---------------------------------------------------------------------------


def _detect_session_type() -> str:
    """Return ``'x11'``, ``'wayland'``, or ``'unknown'``."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session in ("x11", "wayland"):
        return session
    # Fallback heuristic
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"
    return "unknown"


# ---------------------------------------------------------------------------
# InlineTyper
# ---------------------------------------------------------------------------


class InlineTyper:
    """Save the focused window, then type transcribed text into it.

    Args:
        wayland_portal: An optional
            :class:`~tuxvox.experimental.wayland_portal.WaylandPortal`
            instance.  Required for Wayland support.
    """

    def __init__(self, wayland_portal: Any | None = None) -> None:
        self._session_type: str = _detect_session_type()
        self._wayland_portal = wayland_portal
        self._saved_window_id: str | None = None
        self._saved_window_name: str | None = None

        # Preferred backend: kernel-level injection via /dev/uinput. This
        # bypasses the display server entirely and works on both X11 and
        # Wayland, typing into whichever window currently holds focus.
        self._uinput: Any = None
        try:
            from tuxvox.experimental.evdev_input import UinputTyper

            typer = UinputTyper()
            if typer.is_available():
                self._uinput = typer
                logger.info("InlineTyper: using uinput backend.")
        except Exception as exc:  # pragma: no cover - import guard
            logger.debug("uinput backend unavailable: %s", exc)

        logger.debug("InlineTyper initialised. Session type: %s", self._session_type)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save_focused_window(self) -> tuple[bool, str]:
        """Capture the identity of the currently focused window.

        Must be called *before* the TuxVox overlay is shown so that
        the correct target window is recorded.

        Returns:
            A ``(success, message)`` tuple.
        """
        # The uinput backend injects into the currently focused window, so
        # there is no window ID to capture. The non-focusable overlay keeps
        # focus on the target app.
        if self._uinput is not None:
            self._saved_window_id = "__uinput__"
            self._saved_window_name = "Active Window"
            return True, "OK"

        if self._session_type == "x11":
            return self._save_focused_x11()
        elif self._session_type == "wayland":
            return self._save_focused_wayland()
        else:
            msg = f"Unsupported session type: {self._session_type}"
            logger.warning(msg)
            return False, msg

    def type_text(self, text: str) -> tuple[bool, str]:
        """Restore focus and type *text* into the previously saved window.

        Args:
            text: The transcription text to type.

        Returns:
            A ``(success, message)`` tuple.
        """
        if not text:
            return True, "Nothing to type."

        if self._uinput is not None:
            return self._uinput.type_text(text)

        if self._session_type == "x11":
            return self._type_text_x11(text)
        elif self._session_type == "wayland":
            return self._type_text_wayland(text)
        else:
            msg = f"Unsupported session type: {self._session_type}"
            logger.warning(msg)
            return False, msg

    def get_focused_app_name(self) -> str:
        """Return the human-readable name of the saved focused window.

        Returns:
            The window title/name, or ``"Unknown App"`` if unavailable.
        """
        return self._saved_window_name or "Unknown App"

    def inline_backend_status(self) -> tuple[bool, str]:
        """Report whether a working inline-typing backend is available.

        Returns:
            A ``(available, message)`` tuple. When unavailable the message
            explains how to enable inline typing.
        """
        if self._uinput is not None:
            return True, "uinput backend ready."

        if self._session_type == "x11":
            if shutil.which("xdotool"):
                return True, "xdotool backend ready."
            return False, (
                "Inline typing on X11 requires xdotool. Install it with: "
                "sudo apt install xdotool"
            )

        # Wayland without uinput access.
        return False, (
            "Inline typing needs access to /dev/uinput. Run ~/TuxVox/scripts/setup-uinput.sh "
            "once with sudo, then reboot your computer. Until then, transcriptions "
            "will appear in the TuxVox panel instead of being typed."
        )

    # ------------------------------------------------------------------
    # X11 backend
    # ------------------------------------------------------------------

    def _save_focused_x11(self) -> tuple[bool, str]:
        """Save the active window ID via ``xdotool``."""
        if not shutil.which("xdotool"):
            msg = "xdotool is not installed — inline mode requires xdotool on X11."
            logger.error(msg)
            return False, msg

        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                msg = f"xdotool getactivewindow failed: {result.stderr.strip()}"
                logger.error(msg)
                return False, msg

            self._saved_window_id = result.stdout.strip()
            logger.info("Saved focused X11 window: %s", self._saved_window_id)

            # Try to get the window name
            self._saved_window_name = self._get_x11_window_name(self._saved_window_id)

            return True, "OK"

        except subprocess.TimeoutExpired:
            msg = "xdotool timed out while getting active window."
            logger.error(msg)
            return False, msg
        except Exception as exc:
            msg = f"Failed to save focused window: {exc}"
            logger.error(msg)
            return False, msg

    def _type_text_x11(self, text: str) -> tuple[bool, str]:
        """Restore focus to saved window and type *text* via ``xdotool``."""
        if not shutil.which("xdotool"):
            msg = "xdotool is not installed."
            logger.error(msg)
            return False, msg

        if not self._saved_window_id:
            msg = "No saved window ID — call save_focused_window() first."
            logger.error(msg)
            return False, msg

        try:
            # Restore focus
            activate_result = subprocess.run(
                ["xdotool", "windowactivate", "--sync", self._saved_window_id],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if activate_result.returncode != 0:
                msg = (
                    f"Failed to activate window {self._saved_window_id}: "
                    f"{activate_result.stderr.strip()}"
                )
                logger.error(msg)
                return False, msg

            logger.info("Restored focus to window %s.", self._saved_window_id)

            # Type the text
            type_result = subprocess.run(
                [
                    "xdotool",
                    "type",
                    "--clearmodifiers",
                    "--delay",
                    "10",
                    "--",
                    text,
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if type_result.returncode != 0:
                msg = f"xdotool type failed: {type_result.stderr.strip()}"
                logger.error(msg)
                return False, msg

            logger.info("Typed %d characters into window %s.", len(text), self._saved_window_id)
            return True, "OK"

        except subprocess.TimeoutExpired:
            msg = "xdotool timed out while typing text."
            logger.error(msg)
            return False, msg
        except Exception as exc:
            msg = f"Failed to type text via xdotool: {exc}"
            logger.error(msg)
            return False, msg

    def _get_x11_window_name(self, window_id: str) -> str:
        """Retrieve the window title for a given X11 window ID."""
        try:
            result = subprocess.run(
                ["xdotool", "getwindowname", window_id],
                capture_output=True,
                text=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout.strip():
                name = result.stdout.strip()
                logger.debug("X11 window name: %s", name)
                return name
        except Exception as exc:
            logger.debug("Could not get X11 window name: %s", exc)

        return "Unknown App"

    # ------------------------------------------------------------------
    # Wayland backend
    # ------------------------------------------------------------------

    def _save_focused_wayland(self) -> tuple[bool, str]:
        """Save the focused window via the Wayland RemoteDesktop portal.

        On Wayland the compositor controls window focus.  The portal does
        not directly expose "get focused window", so we note that inline
        mode is being used and rely on the portal session for typing.
        """
        if self._wayland_portal is None:
            msg = "Wayland portal not available — inline mode unsupported."
            logger.error(msg)
            return False, msg

        # Wayland does not expose window IDs to applications.  We store
        # a sentinel value and rely on compositor focus restoration after
        # the non-focusable overlay is hidden.
        self._saved_window_id = "__wayland__"
        self._saved_window_name = "Previous Application"
        logger.info("Wayland: marked previous focus for restoration.")
        return True, "OK"

    def _type_text_wayland(self, text: str) -> tuple[bool, str]:
        """Type *text* via the Wayland RemoteDesktop portal."""
        if self._wayland_portal is None:
            msg = "Wayland portal not available."
            logger.error(msg)
            return False, msg

        try:
            ok, msg = self._wayland_portal.simulate_text(text)
            if ok:
                logger.info("Typed %d characters via Wayland portal.", len(text))
            else:
                logger.error("Wayland portal typing failed: %s", msg)
            return ok, msg
        except Exception as exc:
            msg = f"Wayland portal typing error: {exc}"
            logger.error(msg)
            return False, msg
