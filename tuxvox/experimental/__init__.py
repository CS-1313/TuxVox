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

"""Experimental Mode orchestration for TuxVox.

Contains the ExperimentalManager which ties together global hotkeys,
overlay UI, and inline typing.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib

from tuxvox.experimental.hotkey_manager import HotkeyManager
from tuxvox.experimental.inline_typer import InlineTyper
from tuxvox.experimental.overlay_window import OverlayWindow
from tuxvox.experimental.tray_icon import TrayIcon
from tuxvox.experimental import chime
from tuxvox.logger import logger

if TYPE_CHECKING:
    from tuxvox.app_window import AppWindow
    from tuxvox.config import Config


class ExperimentalManager:
    """Orchestrates experimental features (global hotkey, inline typing)."""

    def __init__(self, config: Config, app_window: AppWindow, app: Adw.Application) -> None:
        """Initialise the ExperimentalManager."""
        self._config = config
        self._app_window = app_window
        self._app = app

        self.hotkey_mgr = HotkeyManager()
        from tuxvox.experimental.wayland_portal import WaylandPortal

        self.wayland_portal = WaylandPortal(self._config)
        self.inline_typer = InlineTyper(self.wayland_portal)

        self.overlay: OverlayWindow | None = None
        self.tray_icon: TrayIcon | None = None

        self.enabled = False

    def enable(self) -> None:
        """Enable experimental features, registering hotkeys and showing tray icon."""
        if self.enabled:
            return

        logger.info("Enabling experimental mode.")
        self.enabled = True

        # Initialize UI components
        if not self.overlay:
            self.overlay = OverlayWindow()

        if not self.tray_icon:
            self.tray_icon = TrayIcon(
                on_open=self._on_tray_open,
                on_disable=self._on_tray_disable,
                on_quit=self._on_tray_quit,
            )

        self.tray_icon.show()

        # Register hotkey
        hotkey = self._config.get("global_hotkey")
        if hotkey:
            err = self.hotkey_mgr.register(hotkey, self._on_hotkey_triggered)
            if err:
                logger.error(f"Failed to register hotkey: {err}")

        # Warn early if inline output is configured but no typing backend is
        # available, so the user knows to run the setup script.
        if self._config.get("output_mode") == "inline":
            ok, msg = self.inline_typer.inline_backend_status()
            if not ok:
                logger.warning("Inline typing unavailable: %s", msg)

    def disable(self) -> None:
        """Disable experimental features, unregistering hotkeys and hiding tray icon."""
        if not self.enabled:
            return

        logger.info("Disabling experimental mode.")
        self.enabled = False

        self.hotkey_mgr.unregister()

        if self.tray_icon:
            self.tray_icon.hide()

        if self.overlay:
            self.overlay.hide_overlay()

    def cleanup(self) -> None:
        """Clean up all resources during application shutdown."""
        self.disable()
        if self.overlay:
            self.overlay.destroy()
            self.overlay = None
        self.tray_icon = None

    # -- Tray callbacks --------------------------------------------------------

    def _on_tray_open(self) -> None:
        GLib.idle_add(self._app_window.present)

    def _on_tray_disable(self) -> None:
        GLib.idle_add(self._app_window.present)
        GLib.idle_add(self._config.set, "experimental_mode", False)
        # We don't disable ourselves here; the settings window UI handles the toggle
        # and we assume main.py or app_window listens to config changes, or we just call disable
        GLib.idle_add(self.disable)

    def _on_tray_quit(self) -> None:
        GLib.idle_add(self._app.quit)

    # -- Hotkey trigger flow --------------------------------------------------

    def _on_hotkey_triggered(self) -> None:
        """Called by HotkeyManager from a background thread."""
        GLib.idle_add(self._handle_hotkey_main_thread)

    def _handle_hotkey_main_thread(self) -> bool:
        """Process hotkey trigger on the GTK main thread."""
        if not self.enabled or not self.overlay:
            return False

        if self._app_window._is_transcribing:
            logger.warning("Hotkey ignored: transcription currently in progress.")
            return False

        if self._app_window._is_recording:
            # Stop recording
            self._app_window._is_recording = False
            chime.play("stop")
            inline = self._config.get("output_mode") == "inline"
            self.overlay.set_state("transcribing")
            if not inline:
                self.overlay.show_overlay()

            try:
                audio_path = self._app_window._recorder.stop()
                thread = threading.Thread(
                    target=self._transcribe_background,
                    args=(audio_path,),
                    daemon=True,
                )
                thread.start()
            except Exception as e:
                logger.error(f"Failed to stop recording via hotkey: {e}")
                self._app_window._recorder.cleanup()
                chime.play("error")
                self.overlay.set_state("error", message=str(e))
                self.overlay.show_overlay()
                GLib.timeout_add(2000, self.overlay.hide_overlay)
        else:
            # Start recording
            inline = self._config.get("output_mode") == "inline"
            if inline:
                success, err_msg = self.inline_typer.save_focused_window()
                if not success:
                    logger.warning(f"Failed to save focused window: {err_msg}")

            try:
                mic = self._config.get("microphone")
                self._app_window._recorder.start(device=mic)
                self._app_window._is_recording = True

                chime.play("start")
                self.overlay.set_state("listening")
                # In inline mode the overlay must NOT be shown: presenting a
                # window steals focus from the target app on Wayland, which
                # would send the typed text nowhere. Audio chimes provide
                # feedback instead.
                if not inline:
                    self.overlay.show_overlay()

            except Exception as e:
                logger.error(f"Failed to start recording via hotkey: {e}")
                chime.play("error")
                self.overlay.set_state("error", message=str(e))
                self.overlay.show_overlay()
                GLib.timeout_add(2000, self.overlay.hide_overlay)

        return False

    def _transcribe_background(self, audio_path: str) -> None:
        """Run Whisper transcription in the background."""
        try:
            model_key = self._config.get("model")
            language = self._config.get("language")
            punctuation = self._config.get("punctuation")

            from tuxvox.system_info import MODEL_INFO

            info = MODEL_INFO.get(model_key, {})
            model_name = info.get("internal_name", model_key)

            result = self._app_window._transcriber.transcribe(
                audio_path=audio_path,
                model_name=model_name,
                language=language if language != "auto" else None,
                word_timestamps=False,
                punctuation=punctuation,
            )

            GLib.idle_add(self._on_transcription_complete, result.text)

        except Exception as e:
            logger.error(f"Background transcription failed: {e}")
            GLib.idle_add(self._on_transcription_error, str(e))

        finally:
            self._app_window._recorder.cleanup()

    def _on_transcription_complete(self, text: str) -> bool:
        """Handle completed transcription on the main thread."""
        self._app_window._is_transcribing = False

        if not self.overlay:
            return False

        if not text.strip():
            chime.play("error")
            self.overlay.set_state("error", message="No speech detected")
            self.overlay.show_overlay()
            GLib.timeout_add(2000, self.overlay.hide_overlay)
            return False

        output_mode = self._config.get("output_mode")

        if output_mode == "inline":
            text_to_type = text + " "
            success, err_msg = self.inline_typer.type_text(text_to_type)
            if not success:
                logger.warning(f"Inline typing failed, falling back to panel: {err_msg}")
                chime.play("error")
                self._app_window.append_transcription_text(text, mode="Panel Mode")
                self._app_window.flash_taskbar()
                self.overlay.set_state("done_panel")
                self.overlay.show_overlay()
                GLib.timeout_add(1500, self.overlay.hide_overlay)
            else:
                # Success: text was typed into the focused app. Do NOT show
                # the overlay (it would steal focus). A chime confirms it.
                chime.play("done")
                self._app_window.save_transcription_history(text, mode="Inline Mode")
            return False
        else:
            chime.play("done")
            self._app_window.append_transcription_text(text, mode="Panel Mode")
            self._app_window.flash_taskbar()
            self.overlay.set_state("done_panel")
            self.overlay.show_overlay()
            GLib.timeout_add(1500, self.overlay.hide_overlay)
            return False

    def _on_transcription_error(self, message: str) -> bool:
        """Handle transcription error on the main thread."""
        self._app_window._is_transcribing = False
        chime.play("error")
        if self.overlay:
            self.overlay.set_state("error", message=message)
            self.overlay.show_overlay()
            GLib.timeout_add(3000, self.overlay.hide_overlay)
        return False
