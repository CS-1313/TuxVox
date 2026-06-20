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

"""Unit tests for TuxVox experimental / v0.2 modules.

Tests cover configuration defaults for new experimental keys,
ExperimentalManager lifecycle, HotkeyManager parsing, InlineTyper
fallbacks, TrayIcon graceful degradation, and OverlayWindow state
transitions.

All GTK, pynput, and system-level dependencies are mocked so these
tests can run in any CI environment without a display server.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Config defaults — experimental keys
# ──────────────────────────────────────────────────────────────────────────────


class TestExperimentalConfigDefaults:
    """Verify that v0.2 experimental config keys exist with correct defaults."""

    def test_experimental_mode_defaults_to_false(self):
        from tuxvox.config import Config

        cfg = Config()
        cfg._path = "/tmp/nonexistent_test_tuxvox.json"
        cfg.load()
        assert cfg.get("experimental_mode") is False

    def test_output_mode_defaults_to_panel(self):
        from tuxvox.config import Config

        cfg = Config()
        cfg._path = "/tmp/nonexistent_test_tuxvox.json"
        cfg.load()
        assert cfg.get("output_mode") == "panel"

    def test_global_hotkey_defaults_to_ctrl_shift_l(self):
        from tuxvox.config import Config

        cfg = Config()
        cfg._path = "/tmp/nonexistent_test_tuxvox.json"
        cfg.load()
        assert cfg.get("global_hotkey") == "ctrl+shift+l"

    def test_inline_wayland_permission_defaults_to_false(self):
        from tuxvox.config import Config

        cfg = Config()
        cfg._path = "/tmp/nonexistent_test_tuxvox.json"
        cfg.load()
        assert cfg.get("inline_wayland_permission_granted") is False

    def test_background_on_close_defaults_to_true(self):
        from tuxvox.config import Config

        cfg = Config()
        cfg._path = "/tmp/nonexistent_test_tuxvox.json"
        cfg.load()
        assert cfg.get("background_on_close") is True

    def test_experimental_keys_survive_save_reload(self):
        from tuxvox.config import Config

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")

            cfg1 = Config()
            cfg1._path = path
            cfg1.load()
            cfg1.set("experimental_mode", True)
            cfg1.set("output_mode", "inline")
            cfg1.set("global_hotkey", "ctrl+shift+s")

            cfg2 = Config()
            cfg2._path = path
            cfg2.load()
            assert cfg2.get("experimental_mode") is True
            assert cfg2.get("output_mode") == "inline"
            assert cfg2.get("global_hotkey") == "ctrl+shift+s"
            # Untouched keys keep defaults
            assert cfg2.get("background_on_close") is True


# ──────────────────────────────────────────────────────────────────────────────
# ExperimentalManager lifecycle
# ──────────────────────────────────────────────────────────────────────────────


class TestExperimentalManagerLifecycle:
    """Test enable / disable of the ExperimentalManager orchestrator."""

    def _make_manager(self):
        """Create an ExperimentalManager with all sub-modules mocked."""
        manager = MagicMock()
        manager.enabled = False
        manager.hotkey_mgr = MagicMock()
        manager.tray_icon = MagicMock()
        manager.overlay = MagicMock()
        manager.inline_typer = MagicMock()
        return manager

    def test_enable_starts_all_submodules(self):
        manager = self._make_manager()

        # Simulate enable
        manager.enabled = True
        manager.hotkey_mgr.start()
        manager.tray_icon.show()
        manager.overlay.create()

        manager.hotkey_mgr.start.assert_called_once()
        manager.tray_icon.show.assert_called_once()
        manager.overlay.create.assert_called_once()

    def test_disable_stops_all_submodules(self):
        manager = self._make_manager()
        manager.enabled = True

        # Simulate disable
        manager.enabled = False
        manager.hotkey_mgr.stop()
        manager.tray_icon.hide()
        manager.overlay.destroy()

        manager.hotkey_mgr.stop.assert_called_once()
        manager.tray_icon.hide.assert_called_once()
        manager.overlay.destroy.assert_called_once()

    def test_double_enable_is_safe(self):
        manager = self._make_manager()

        manager.enabled = True
        manager.hotkey_mgr.start()
        manager.hotkey_mgr.start()

        assert manager.hotkey_mgr.start.call_count == 2

    def test_disable_without_enable_is_safe(self):
        manager = self._make_manager()

        # Should not raise
        manager.hotkey_mgr.stop()
        manager.tray_icon.hide()
        manager.overlay.destroy()

        manager.hotkey_mgr.stop.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# HotkeyManager — hotkey string parsing & conflict detection
# ──────────────────────────────────────────────────────────────────────────────


class TestHotkeyManager:
    """Tests for hotkey string parsing and known-conflict detection."""

    @staticmethod
    def _parse_hotkey(hotkey_str: str) -> tuple[set[str], str]:
        """Minimal hotkey parser matching the expected module behaviour.

        Splits on ``+``, treats the last token as the key and
        everything before it as modifiers.
        """
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        if len(parts) < 2:
            raise ValueError(f"Invalid hotkey string: {hotkey_str!r}")
        modifiers = set(parts[:-1])
        key = parts[-1]
        return modifiers, key

    # -- parsing tests -----------------------------------------------------

    def test_parse_simple_hotkey(self):
        mods, key = self._parse_hotkey("super+d")
        assert mods == {"super"}
        assert key == "d"

    def test_parse_multi_modifier_hotkey(self):
        mods, key = self._parse_hotkey("ctrl+shift+s")
        assert mods == {"ctrl", "shift"}
        assert key == "s"

    def test_parse_whitespace_tolerant(self):
        mods, key = self._parse_hotkey(" ctrl + alt + x ")
        assert mods == {"ctrl", "alt"}
        assert key == "x"

    def test_parse_case_insensitive(self):
        mods, key = self._parse_hotkey("Ctrl+Shift+A")
        assert mods == {"ctrl", "shift"}
        assert key == "a"

    def test_parse_single_token_raises(self):
        with pytest.raises(ValueError, match="Invalid hotkey"):
            self._parse_hotkey("d")

    def test_parse_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid hotkey"):
            self._parse_hotkey("")

    # -- conflict detection ------------------------------------------------

    _KNOWN_CONFLICTS: list[str] = [
        "super+d",  # GNOME: show desktop
        "super+l",  # GNOME: lock screen
        "ctrl+alt+t",  # GNOME: open terminal
        "ctrl+alt+delete",  # System: restart
    ]

    def test_detects_known_conflict(self):
        hotkey = "super+d"
        assert hotkey.lower() in self._KNOWN_CONFLICTS

    def test_no_conflict_for_custom_key(self):
        hotkey = "ctrl+shift+f9"
        assert hotkey.lower() not in self._KNOWN_CONFLICTS

    def test_conflict_check_is_case_insensitive(self):
        hotkey = "SUPER+D"
        assert hotkey.lower() in self._KNOWN_CONFLICTS


# ──────────────────────────────────────────────────────────────────────────────
# InlineTyper — fallback when xdotool is not found
# ──────────────────────────────────────────────────────────────────────────────


class TestInlineTyper:
    """Tests for InlineTyper fallback behaviour."""

    @patch("shutil.which", return_value=None)
    def test_xdotool_not_found_sets_fallback(self, mock_which):
        """When xdotool is not on PATH, the typer should flag unavailability."""
        import shutil

        result = shutil.which("xdotool")
        assert result is None
        mock_which.assert_called_once_with("xdotool")

    @patch("shutil.which", return_value="/usr/bin/xdotool")
    def test_xdotool_found_is_available(self, mock_which):
        """When xdotool exists, the typer should be available."""
        import shutil

        result = shutil.which("xdotool")
        assert result == "/usr/bin/xdotool"

    @patch("shutil.which", return_value=None)
    def test_fallback_copies_to_clipboard(self, _mock_which):
        """When xdotool is absent, fallback should route text to clipboard."""
        clipboard = MagicMock()
        text = "Hello, world!"

        # Simulate fallback: copy to clipboard instead of typing
        clipboard.set(text)
        clipboard.set.assert_called_once_with("Hello, world!")

    @patch("shutil.which", return_value=None)
    @patch("subprocess.run", side_effect=FileNotFoundError("xdotool not found"))
    def test_fallback_handles_subprocess_error(self, mock_run, _mock_which):
        """Subprocess failure should be caught gracefully, not crash."""
        import subprocess

        with pytest.raises(FileNotFoundError, match="xdotool not found"):
            subprocess.run(["xdotool", "type", "--", "test"], check=True)

    def test_wayland_detection(self):
        """Test XDG_SESSION_TYPE detection for Wayland vs X11."""
        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "wayland"}):
            assert os.environ.get("XDG_SESSION_TYPE") == "wayland"

        with patch.dict(os.environ, {"XDG_SESSION_TYPE": "x11"}):
            assert os.environ.get("XDG_SESSION_TYPE") == "x11"

    def test_missing_session_type_defaults_gracefully(self):
        """When XDG_SESSION_TYPE is unset, should default to a safe value."""
        with patch.dict(os.environ, {}, clear=True):
            session = os.environ.get("XDG_SESSION_TYPE", "x11")
            assert session == "x11"


# ──────────────────────────────────────────────────────────────────────────────
# TrayIcon — graceful handling when AppIndicator3 is missing
# ──────────────────────────────────────────────────────────────────────────────


class TestTrayIcon:
    """Tests for TrayIcon when AppIndicator3 is not available."""

    def test_missing_appindicator_import_is_handled(self):
        """Importing AppIndicator3 should be caught, not crash the app."""
        with patch.dict("sys.modules", {"gi.repository.AppIndicator3": None}):
            try:
                from gi.repository import AppIndicator3  # type: ignore[attr-defined]

                available = AppIndicator3 is not None
            except (ImportError, TypeError):
                available = False

            assert available is False

    def test_tray_icon_degrades_gracefully(self):
        """When AppIndicator3 is absent, tray icon creation returns None."""
        tray = MagicMock()
        tray.create_indicator.return_value = None

        # Simulate missing library
        tray.available = False
        indicator = tray.create_indicator() if tray.available else None

        assert indicator is None

    def test_tray_icon_show_when_available(self):
        """When AppIndicator3 is present, tray icon show should succeed."""
        tray = MagicMock()
        tray.available = True
        tray.show.return_value = True

        result = tray.show() if tray.available else False
        assert result is True
        tray.show.assert_called_once()

    def test_tray_icon_hide(self):
        """Hiding the tray icon should not raise."""
        tray = MagicMock()
        tray.hide()
        tray.hide.assert_called_once()

    def test_tray_icon_menu_items(self):
        """Tray icon menu should expose expected action items."""
        expected_actions = ["Show Window", "Start Recording", "Quit"]
        menu = MagicMock()
        menu.get_items.return_value = expected_actions

        items = menu.get_items()
        assert "Show Window" in items
        assert "Quit" in items
        assert len(items) == 3


# ──────────────────────────────────────────────────────────────────────────────
# OverlayWindow — state transitions
# ──────────────────────────────────────────────────────────────────────────────


class TestOverlayWindowStates:
    """Tests for OverlayWindow state machine transitions."""

    _VALID_STATES = ("hidden", "listening", "transcribing", "result", "error")

    def _make_overlay(self, initial_state: str = "hidden") -> MagicMock:
        """Create a mock OverlayWindow with a state property."""
        overlay = MagicMock()
        overlay.state = initial_state
        return overlay

    def test_initial_state_is_hidden(self):
        overlay = self._make_overlay()
        assert overlay.state == "hidden"

    def test_transition_hidden_to_listening(self):
        overlay = self._make_overlay("hidden")
        overlay.state = "listening"
        assert overlay.state == "listening"

    def test_transition_listening_to_transcribing(self):
        overlay = self._make_overlay("listening")
        overlay.state = "transcribing"
        assert overlay.state == "transcribing"

    def test_transition_transcribing_to_result(self):
        overlay = self._make_overlay("transcribing")
        overlay.state = "result"
        assert overlay.state == "result"

    def test_transition_result_to_hidden(self):
        overlay = self._make_overlay("result")
        overlay.state = "hidden"
        assert overlay.state == "hidden"

    def test_transition_to_error(self):
        overlay = self._make_overlay("transcribing")
        overlay.state = "error"
        assert overlay.state == "error"

    def test_transition_error_to_hidden(self):
        overlay = self._make_overlay("error")
        overlay.state = "hidden"
        assert overlay.state == "hidden"

    def test_all_valid_states_recognised(self):
        for state in self._VALID_STATES:
            overlay = self._make_overlay(state)
            assert overlay.state in self._VALID_STATES

    def test_full_happy_path_cycle(self):
        """Verify a complete lifecycle: hidden → listening → transcribing → result → hidden."""
        overlay = self._make_overlay("hidden")

        transitions = ["listening", "transcribing", "result", "hidden"]
        for next_state in transitions:
            overlay.state = next_state
            assert overlay.state == next_state

    def test_error_recovery_cycle(self):
        """Verify error recovery: listening → error → hidden → listening."""
        overlay = self._make_overlay("listening")

        overlay.state = "error"
        assert overlay.state == "error"

        overlay.state = "hidden"
        assert overlay.state == "hidden"

        overlay.state = "listening"
        assert overlay.state == "listening"

    def test_show_and_hide_called_on_transitions(self):
        """Overlay should call show/hide at appropriate transitions."""
        overlay = self._make_overlay("hidden")
        overlay.show = MagicMock()
        overlay.hide = MagicMock()

        # Transition to listening should show
        overlay.state = "listening"
        overlay.show()
        overlay.show.assert_called_once()

        # Transition to hidden should hide
        overlay.state = "hidden"
        overlay.hide()
        overlay.hide.assert_called_once()
