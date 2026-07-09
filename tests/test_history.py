"""Unit tests for TuxVox transcription history saving.

Tests cover:
- Mode tagging ([Panel Mode] vs [Inline Mode])
- Full timestamp including date (YYYY-MM-DD HH:MM:SS)
- Daily file creation in designated folder
"""

import os
import sys
import tempfile
from datetime import datetime
from unittest.mock import MagicMock

try:
    import gi  # noqa: F401
except (ImportError, ModuleNotFoundError):
    mock_gi = MagicMock()
    sys.modules["gi"] = mock_gi

    class _DummyWindow:
        def __init__(self, **kwargs):
            pass

    import types

    mock_adw = MagicMock()
    mock_adw.ApplicationWindow = _DummyWindow
    mock_repo = types.ModuleType("gi.repository")
    mock_repo.Adw = mock_adw
    mock_repo.Gtk = MagicMock()
    mock_repo.Gdk = MagicMock()
    mock_repo.GLib = MagicMock()
    sys.modules["gi.repository"] = mock_repo

try:
    import sounddevice  # noqa: F401
except (OSError, ImportError):
    sys.modules["sounddevice"] = MagicMock()

from tuxvox.app_window import AppWindow
from tuxvox.config import Config


class TestTranscriptionHistorySaving:
    """Test history file saving, formatting, and mode identifiers."""

    def _make_app_window(self, tmpdir: str) -> AppWindow:
        # Avoid GTK UI initialization for headless unit testing
        window = AppWindow.__new__(AppWindow)
        window._config = Config()
        window._config._path = os.path.join(tmpdir, "settings.json")
        window._config.load()
        window._config.set("save_history", True)
        window._config.set("history_path", tmpdir)
        window._text_buffer = MagicMock()
        window._text_view = MagicMock()
        window._set_status_ready = MagicMock()
        return window

    def test_save_history_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            window = self._make_app_window(tmpdir)
            window._config.set("save_history", False)
            window.save_transcription_history("Hello world", mode="Panel Mode")

            # Verify no history files were created
            files = [f for f in os.listdir(tmpdir) if f.startswith("tuxvox_")]
            assert len(files) == 0

    def test_save_history_panel_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            window = self._make_app_window(tmpdir)
            window.save_transcription_history("Hello panel world", mode="Panel Mode")

            now = datetime.now()
            expected_filename = now.strftime("tuxvox_%Y-%m-%d.txt")
            filepath = os.path.join(tmpdir, expected_filename)
            assert os.path.isfile(filepath)

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            date_str = now.strftime("%Y-%m-%d")
            assert f"[{date_str}" in content
            assert "][Panel Mode]" in content
            assert "Hello panel world" in content

    def test_save_history_inline_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            window = self._make_app_window(tmpdir)
            window.save_transcription_history("Hello inline world", mode="Inline Mode")

            now = datetime.now()
            expected_filename = now.strftime("tuxvox_%Y-%m-%d.txt")
            filepath = os.path.join(tmpdir, expected_filename)
            assert os.path.isfile(filepath)

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            date_str = now.strftime("%Y-%m-%d")
            assert f"[{date_str}" in content
            assert "][Inline Mode]" in content
            assert "Hello inline world" in content

    def test_append_transcription_text_saves_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            window = self._make_app_window(tmpdir)
            window._text_buffer.get_char_count.return_value = 0

            window.append_transcription_text("Appended text test", mode="Panel Mode")

            now = datetime.now()
            expected_filename = now.strftime("tuxvox_%Y-%m-%d.txt")
            filepath = os.path.join(tmpdir, expected_filename)
            assert os.path.isfile(filepath)

            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()

            assert "][Panel Mode]" in content
            assert "Appended text test" in content
