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

"""Wayland RemoteDesktop portal integration for TuxVox.

Wraps the ``org.freedesktop.portal.RemoteDesktop`` D-Bus interface so that
TuxVox can simulate keypresses on Wayland compositors where ``xdotool``
is unavailable.

All errors are caught and surfaced as return values — this module will
never raise into calling code.
"""

from __future__ import annotations

from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from tuxvox.logger import logger

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DESKTOP_BUS_NAME = "org.freedesktop.portal.Desktop"
_DESKTOP_OBJECT_PATH = "/org/freedesktop/portal/desktop"
_REMOTE_DESKTOP_IFACE = "org.freedesktop.portal.RemoteDesktop"

# Portal device type flags
_DEVICE_KEYBOARD = 1  # Portal keyboard device flag


class WaylandPortal:
    """Wrapper around the XDG RemoteDesktop portal for simulated input.

    Usage::

        portal = WaylandPortal(config)
        if portal.is_available():
            ok = portal.request_permission(parent_window)
            if ok:
                portal.create_session()
                portal.simulate_text("hello world")
    """

    def __init__(self, config: Any) -> None:
        """Initialise the portal wrapper.

        Args:
            config: A :class:`tuxvox.config.Config` instance used to
                persist the ``inline_wayland_permission_granted`` flag.
        """
        self._config = config
        self._proxy: Gio.DBusProxy | None = None
        self._session_path: str | None = None

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Check whether the RemoteDesktop portal is reachable on D-Bus.

        Returns:
            ``True`` if the portal proxy can be created, ``False`` otherwise.
        """
        try:
            proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                _DESKTOP_BUS_NAME,
                _DESKTOP_OBJECT_PATH,
                _REMOTE_DESKTOP_IFACE,
                None,
            )
            if proxy is None:
                logger.debug("RemoteDesktop portal proxy is None.")
                return False
            self._proxy = proxy
            logger.info("RemoteDesktop portal is available.")
            return True
        except GLib.Error as exc:
            logger.debug("RemoteDesktop portal not available: %s", exc.message)
            return False
        except Exception as exc:
            logger.debug("RemoteDesktop portal check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Permission flow
    # ------------------------------------------------------------------

    def request_permission(self, parent_window: Gtk.Window) -> bool:
        """Request user permission for remote-input access.

        Shows a TuxVox-branded explanation dialog *before* the system
        portal dialog so the user understands why the permission is needed.

        Args:
            parent_window: The parent GTK window for dialog attachment.

        Returns:
            ``True`` if the user granted permission, ``False`` otherwise.
        """
        # If already granted in a previous session, skip the dialog.
        if self._config.get("inline_wayland_permission_granted"):
            logger.info("Wayland permission already granted (cached).")
            return True

        # -- TuxVox pre-warning dialog (spec §7.2) --
        granted = self._show_pre_warning_dialog(parent_window)
        if not granted:
            logger.info("User declined the Wayland permission pre-warning.")
            return False

        # -- Trigger the actual system portal dialog --
        try:
            ok = self._request_portal_permission()
            if ok:
                self._config.set("inline_wayland_permission_granted", True)
                logger.info("Wayland RemoteDesktop permission granted.")
                return True
            else:
                logger.warning("System portal denied RemoteDesktop permission.")
                self._show_permission_denied_dialog(parent_window)
                return False
        except Exception as exc:
            logger.error("Error requesting portal permission: %s", exc)
            self._show_permission_denied_dialog(parent_window)
            return False

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self) -> tuple[bool, str]:
        """Create a RemoteDesktop session via the portal.

        Returns:
            A ``(success, message)`` tuple.
        """
        if self._proxy is None:
            msg = "Portal proxy not initialised — call is_available() first."
            logger.error(msg)
            return False, msg

        try:
            options = GLib.Variant(
                "a{sv}",
                {
                    "handle_token": GLib.Variant("s", "tuxvox_rd"),
                    "session_handle_token": GLib.Variant("s", "tuxvox_session"),
                },
            )

            result = self._proxy.call_sync(
                "CreateSession",
                GLib.Variant.new_tuple(options),
                Gio.DBusCallFlags.NONE,
                5000,  # 5-second timeout
                None,
            )

            if result is not None:
                request_path = result.unpack()[0]
                logger.info("RemoteDesktop session request: %s", request_path)
                # In a full implementation the request path would be
                # monitored for the Response signal.  For now we store
                # a placeholder session path.
                self._session_path = request_path
                return True, "Session created."

            return False, "CreateSession returned None."

        except GLib.Error as exc:
            msg = f"D-Bus error creating session: {exc.message}"
            logger.error(msg)
            return False, msg
        except Exception as exc:
            msg = f"Unexpected error creating session: {exc}"
            logger.error(msg)
            return False, msg

    # ------------------------------------------------------------------
    # Input simulation
    # ------------------------------------------------------------------

    def simulate_keypress(self, keycode: int, pressed: bool = True) -> tuple[bool, str]:
        """Simulate a single keypress or release via the portal.

        Args:
            keycode: Linux evdev keycode to simulate.
            pressed: ``True`` for key-down, ``False`` for key-up.

        Returns:
            A ``(success, message)`` tuple.
        """
        if self._proxy is None or self._session_path is None:
            msg = "No active portal session — cannot simulate keypress."
            logger.error(msg)
            return False, msg

        try:
            state = 1 if pressed else 0
            options = GLib.Variant("a{sv}", {})

            self._proxy.call_sync(
                "NotifyKeyboardKeycode",
                GLib.Variant.new_tuple(
                    GLib.Variant("o", self._session_path),
                    options,
                    GLib.Variant("i", keycode),
                    GLib.Variant("u", state),
                ),
                Gio.DBusCallFlags.NONE,
                1000,
                None,
            )
            return True, "OK"

        except GLib.Error as exc:
            msg = f"D-Bus error simulating keypress: {exc.message}"
            logger.error(msg)
            return False, msg
        except Exception as exc:
            msg = f"Unexpected error simulating keypress: {exc}"
            logger.error(msg)
            return False, msg

    def simulate_text(self, text: str) -> tuple[bool, str]:
        """Type *text* character-by-character via simulated keypresses.

        Uses a simple ASCII-to-evdev mapping.  Characters outside the
        supported range are skipped with a warning.

        Args:
            text: The string to type.

        Returns:
            A ``(success, message)`` tuple.
        """
        if not text:
            return True, "Nothing to type."

        # Minimal ASCII → evdev keycode map (lowercase letters + digits).
        _CHAR_TO_KEYCODE: dict[str, int] = {}
        # a-z  →  keycodes 30-48, 16-25 (matches standard QWERTY evdev)
        _QWERTY_ROWS = "qwertyuiop"  # 16-25
        _HOME_ROW = "asdfghjkl"  # 30-38
        _BOTTOM_ROW = "zxcvbnm"  # 44-50
        for i, ch in enumerate(_QWERTY_ROWS):
            _CHAR_TO_KEYCODE[ch] = 16 + i
        for i, ch in enumerate(_HOME_ROW):
            _CHAR_TO_KEYCODE[ch] = 30 + i
        for i, ch in enumerate(_BOTTOM_ROW):
            _CHAR_TO_KEYCODE[ch] = 44 + i
        # digits 0-9  →  keycodes 11, 2-10
        _CHAR_TO_KEYCODE["0"] = 11
        for i in range(1, 10):
            _CHAR_TO_KEYCODE[str(i)] = i + 1
        _CHAR_TO_KEYCODE[" "] = 57  # space
        _CHAR_TO_KEYCODE["\n"] = 28  # enter
        _CHAR_TO_KEYCODE["."] = 52
        _CHAR_TO_KEYCODE[","] = 51

        _SHIFT_KEYCODE = 42  # left shift

        errors: list[str] = []
        for ch in text:
            needs_shift = ch.isupper() or ch in "!@#$%^&*()_+"
            lower = ch.lower()

            kc = _CHAR_TO_KEYCODE.get(lower)
            if kc is None:
                logger.debug("No evdev mapping for character %r — skipping.", ch)
                errors.append(ch)
                continue

            if needs_shift:
                self.simulate_keypress(_SHIFT_KEYCODE, pressed=True)

            self.simulate_keypress(kc, pressed=True)
            self.simulate_keypress(kc, pressed=False)

            if needs_shift:
                self.simulate_keypress(_SHIFT_KEYCODE, pressed=False)

        if errors:
            msg = f"Typed with {len(errors)} unmapped character(s)."
            logger.warning(msg)
            return True, msg

        return True, "OK"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _show_pre_warning_dialog(self, parent: Gtk.Window) -> bool:
        """Show the TuxVox permission explanation dialog.

        Returns ``True`` if the user clicks *Allow*, ``False`` on *Cancel*.
        """
        result: list[bool] = [False]
        loop = GLib.MainLoop.new(None, False)

        dialog = Adw.AlertDialog.new(
            "Keyboard Simulation Permission",
            (
                "TuxVox's Inline Mode needs permission to simulate "
                "keyboard input so it can type transcribed text directly "
                "into your active application.\n\n"
                "Your desktop environment will show a system dialog asking "
                "you to grant this access. TuxVox only uses this "
                "capability to type transcription results — nothing else "
                "is captured or recorded.\n\n"
                "You can revoke this permission at any time in Settings."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("allow", "Allow")
        dialog.set_response_appearance("allow", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("allow")
        dialog.set_close_response("cancel")

        def _on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            result[0] = response == "allow"
            loop.quit()

        dialog.connect("response", _on_response)
        dialog.present(parent)

        loop.run()
        return result[0]

    def _show_permission_denied_dialog(self, parent: Gtk.Window) -> None:
        """Inform the user that Wayland permission was denied."""
        dialog = Adw.AlertDialog.new(
            "Permission Denied",
            (
                "TuxVox was not granted keyboard simulation access. "
                "Inline Mode cannot function without this permission.\n\n"
                "Transcribed text will be placed in the TuxVox panel "
                "instead.  You can retry from Settings → Experimental → "
                "Output Mode."
            ),
        )
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present(parent)

    def _request_portal_permission(self) -> bool:
        """Trigger the system RemoteDesktop permission dialog.

        Returns ``True`` on success.  This is a best-effort implementation
        that may need runtime testing with specific Wayland compositors.
        """
        if self._proxy is None:
            return False

        try:
            # Select devices (keyboard only)
            options = GLib.Variant(
                "a{sv}",
                {
                    "handle_token": GLib.Variant("s", "tuxvox_select"),
                    "types": GLib.Variant("u", _DEVICE_KEYBOARD),
                },
            )

            # First create a session, then select devices
            session_ok, msg = self.create_session()
            if not session_ok:
                logger.error("Cannot request permission — session failed: %s", msg)
                return False

            if self._session_path is None:
                return False

            self._proxy.call_sync(
                "SelectDevices",
                GLib.Variant.new_tuple(
                    GLib.Variant("o", self._session_path),
                    options,
                ),
                Gio.DBusCallFlags.NONE,
                10000,
                None,
            )

            # Start the session (triggers the compositor dialog)
            start_options = GLib.Variant(
                "a{sv}",
                {
                    "handle_token": GLib.Variant("s", "tuxvox_start"),
                },
            )

            self._proxy.call_sync(
                "Start",
                GLib.Variant.new_tuple(
                    GLib.Variant("o", self._session_path),
                    GLib.Variant("s", ""),
                    start_options,
                ),
                Gio.DBusCallFlags.NONE,
                30000,  # 30 s — user interaction needed
                None,
            )

            return True

        except GLib.Error as exc:
            logger.error("Portal permission request failed: %s", exc.message)
            return False
        except Exception as exc:
            logger.error("Unexpected error in permission request: %s", exc)
            return False
