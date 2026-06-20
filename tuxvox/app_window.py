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

"""Main application window for TuxVox.

Contains the transcript editor, record button, copy/clear buttons,
status bar, and orchestrates the recording → transcription → display pipeline.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk

from tuxvox.config import Config
from tuxvox.logger import logger
from tuxvox.recorder import Recorder
from tuxvox.transcriber import Transcriber, TranscriptionResult

if TYPE_CHECKING:
    pass


class AppWindow(Adw.ApplicationWindow):
    """Main window for TuxVox — transcript editor + recording controls."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

        self._config = Config()
        self._config.load()
        self._recorder = Recorder()
        self._transcriber = Transcriber()

        # State tracking
        self._is_recording = False
        self._is_transcribing = False
        self._stream_words: list[dict] = []
        self._stream_index = 0
        self._stream_timeout_id: int | None = None

        self.set_default_size(700, 600)
        self.set_title("TuxVox")

        self._build_ui()
        self._set_status_ready()

        # Handle onboarding
        if not self._config.get("has_completed_onboarding"):
            from tuxvox.onboarding import show_onboarding_dialog

            def on_download():
                self._config.set("has_completed_onboarding", True)
                self._config.set("model", "base")

            def on_choose_model():
                self._config.set("has_completed_onboarding", True)
                self._on_settings_clicked(None)

            GLib.idle_add(show_onboarding_dialog, self, on_download, on_choose_model)

        # Handle experimental mode
        self._experimental_manager = None
        if self._config.get("experimental_mode"):
            self.toggle_experimental_mode(True)

    def toggle_experimental_mode(self, active: bool) -> None:
        """Enable or disable experimental features."""
        if active:
            if not self._experimental_manager:
                from tuxvox.experimental import ExperimentalManager

                self._experimental_manager = ExperimentalManager(
                    config=self._config, app_window=self, app=self.get_application()
                )
            self._experimental_manager.enable()
        else:
            if self._experimental_manager:
                self._experimental_manager.disable()

    # ── UI Construction ──────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the complete window UI."""
        # Root layout
        toolbar_view = Adw.ToolbarView()

        # Header bar
        header = Adw.HeaderBar()
        header.set_title_widget(self._build_title_widget())

        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.set_tooltip_text("Settings")
        settings_btn.connect("clicked", self._on_settings_clicked)
        header.pack_end(settings_btn)

        toolbar_view.add_top_bar(header)

        # Main content area
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_start(24)
        content_box.set_margin_end(24)
        content_box.set_margin_top(16)
        content_box.set_margin_bottom(16)

        # ── Text editor ──
        self._text_buffer = Gtk.TextBuffer()
        self._create_text_tags()

        self._text_view = Gtk.TextView(buffer=self._text_buffer)
        self._text_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self._text_view.set_top_margin(12)
        self._text_view.set_bottom_margin(12)
        self._text_view.set_left_margin(12)
        self._text_view.set_right_margin(12)
        self._text_view.add_css_class("transcript-editor")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_child(self._text_view)
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)
        scrolled.set_min_content_height(200)
        scrolled.add_css_class("card")

        content_box.append(scrolled)

        # ── Record button ──
        self._record_btn = Gtk.Button()
        self._record_btn.set_halign(Gtk.Align.CENTER)
        self._record_btn.set_size_request(280, 48)
        self._record_btn.add_css_class("pill")
        self._record_btn.add_css_class("suggested-action")
        self._record_btn.connect("clicked", self._on_record_clicked)
        self._update_record_button_label(recording=False)

        content_box.append(self._record_btn)

        # ── Action buttons row ──
        action_box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
        )

        self._copy_btn = Gtk.Button()
        copy_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        copy_content.append(Gtk.Image.new_from_icon_name("edit-copy-symbolic"))
        self._copy_label = Gtk.Label(label="Copy All to Clipboard")
        copy_content.append(self._copy_label)
        self._copy_btn.set_child(copy_content)
        self._copy_btn.connect("clicked", self._on_copy_clicked)
        action_box.append(self._copy_btn)

        self._clear_btn = Gtk.Button()
        clear_content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        clear_content.append(Gtk.Image.new_from_icon_name("edit-clear-all-symbolic"))
        clear_content.append(Gtk.Label(label="Clear All"))
        self._clear_btn.set_child(clear_content)
        self._clear_btn.connect("clicked", self._on_clear_clicked)
        action_box.append(self._clear_btn)

        content_box.append(action_box)

        # ── Status bar ──
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)

        # Privacy indicator — always visible
        self._privacy_label = Gtk.Label(label="🔒 Fully offline & private")
        self._privacy_label.set_halign(Gtk.Align.START)
        self._privacy_label.add_css_class("status-bar")
        self._privacy_label.add_css_class("dim-label")
        self._privacy_label.set_opacity(0.6)
        status_box.append(self._privacy_label)

        # Download progress bar
        self._download_progress = Gtk.ProgressBar()
        self._download_progress.set_valign(Gtk.Align.CENTER)
        self._download_progress.set_size_request(150, -1)
        self._download_progress.set_show_text(True)
        self._download_progress.set_visible(False)
        status_box.append(self._download_progress)

        separator = Gtk.Label(label="|")
        separator.add_css_class("dim-label")
        separator.set_opacity(0.4)
        status_box.append(separator)

        # Session status — dynamic
        self._status_label = Gtk.Label()
        self._status_label.set_halign(Gtk.Align.START)
        self._status_label.set_hexpand(True)
        self._status_label.add_css_class("status-bar")
        self._status_label.add_css_class("dim-label")
        status_box.append(self._status_label)

        content_box.append(status_box)

        toolbar_view.set_content(content_box)
        self.set_content(toolbar_view)

    def _build_title_widget(self) -> Gtk.Widget:
        """Build the header bar title with a microphone icon."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        icon = Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic")
        box.append(icon)
        label = Gtk.Label(label="TuxVox")
        label.add_css_class("title")
        box.append(label)
        return box

    def _create_text_tags(self) -> None:
        """Create text tags for styling (confidence, streaming)."""
        tag_table = self._text_buffer.get_tag_table()

        # Low-confidence words — dimmed
        low_conf_tag = Gtk.TextTag(name="low-confidence")
        low_conf_tag.set_property(
            "foreground-rgba", Gdk.RGBA(red=0.6, green=0.6, blue=0.6, alpha=0.6)
        )
        tag_table.add(low_conf_tag)

        # Currently streaming word — slightly transparent
        streaming_tag = Gtk.TextTag(name="streaming")
        streaming_tag.set_property(
            "foreground-rgba", Gdk.RGBA(red=0.7, green=0.7, blue=0.7, alpha=0.7)
        )
        tag_table.add(streaming_tag)

    # ── Status bar helpers ────────────────────────────────────────────

    def _set_status_ready(self) -> None:
        """Set status to 'Ready — clean session'."""
        self._status_label.set_text("● Ready — clean session")
        self._remove_status_classes()
        self._status_label.add_css_class("status-ready")

    def _set_status_recording(self) -> None:
        """Set status to 'Recording... speak now'."""
        self._status_label.set_text("● Recording… speak now")
        self._remove_status_classes()
        self._status_label.add_css_class("status-recording")
        self._status_label.add_css_class("recording-pulse")

    def _set_status_transcribing(self) -> None:
        """Set status to 'Transcribing... please wait'."""
        self._status_label.set_text("⏳ Transcribing… please wait")
        self._remove_status_classes()
        self._status_label.add_css_class("status-transcribing")

    def _set_status_loading(self) -> None:
        """Set status to 'Loading engine...'."""
        self._status_label.set_text("⏳ Loading engine…")
        self._remove_status_classes()
        self._status_label.add_css_class("status-transcribing")

    def _update_download_progress(self, current: int, total: int) -> None:
        """Update the model download progress bar."""
        if total > 0:
            fraction = current / total
            self._download_progress.set_fraction(fraction)
            self._download_progress.set_text(f"Downloading model... {int(fraction * 100)}%")

            if not self._download_progress.get_visible():
                self._download_progress.set_visible(True)
                self._status_label.set_visible(False)

        if current >= total:
            self._download_progress.set_visible(False)
            self._status_label.set_visible(True)
            self._set_status_loading()

    def _set_status_error(self, message: str) -> None:
        """Set status to an error message."""
        self._status_label.set_text(f"⚠ {message}")
        self._remove_status_classes()
        self._status_label.add_css_class("status-recording")

    def _remove_status_classes(self) -> None:
        """Remove all status CSS classes."""
        for cls in ("status-ready", "status-recording", "status-transcribing", "recording-pulse"):
            self._status_label.remove_css_class(cls)

    # ── Record button ─────────────────────────────────────────────────

    def _update_record_button_label(self, recording: bool) -> None:
        """Update the record button text and style."""
        if recording:
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.append(Gtk.Image.new_from_icon_name("media-playback-stop-symbolic"))
            content.append(Gtk.Label(label="Stop & Transcribe"))
            self._record_btn.set_child(content)
            self._record_btn.remove_css_class("suggested-action")
            self._record_btn.add_css_class("destructive-action")
        else:
            content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            content.append(Gtk.Image.new_from_icon_name("audio-input-microphone-symbolic"))
            content.append(Gtk.Label(label="Start Recording"))
            self._record_btn.set_child(content)
            self._record_btn.remove_css_class("destructive-action")
            self._record_btn.add_css_class("suggested-action")

    def _on_record_clicked(self, _button: Gtk.Button) -> None:
        """Handle record button click — toggle recording state."""
        if self._is_transcribing:
            return  # Ignore clicks while transcribing

        if self._is_recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self) -> None:
        """Start audio recording."""
        try:
            mic = self._config.get("microphone")
            device = None if mic == "default" else mic

            # Try to convert device to int index if it's a number string
            if device is not None:
                try:
                    device = int(device)
                except (ValueError, TypeError):
                    pass

            self._recorder.start(device=device)
            self._is_recording = True
            self._update_record_button_label(recording=True)
            self._set_status_recording()
            logger.info(f"Recording started. Device: {mic or 'default'}")

        except Exception as e:
            logger.error(f"Failed to start recording: {e}")
            self._show_error_dialog(
                "Recording Failed",
                (
                    "No microphone found. Please connect a microphone and restart TuxVox."
                    if "no" in str(e).lower() or "device" in str(e).lower()
                    else f"Could not start recording: {e}"
                ),
            )

    def _stop_recording(self) -> None:
        """Stop recording and begin transcription pipeline."""
        self._is_recording = False
        self._update_record_button_label(recording=False)

        try:
            duration = self._recorder.duration
            audio_path = self._recorder.stop()
            logger.info(
                f"Recording stopped. Duration: {duration:.1f}s. " f"Audio file: {audio_path}"
            )

            # Disable button during transcription
            self._is_transcribing = True
            self._record_btn.set_sensitive(False)
            self._set_status_loading()

            # Run transcription in background thread
            thread = threading.Thread(
                target=self._transcribe_background,
                args=(audio_path,),
                daemon=True,
            )
            thread.start()

        except Exception as e:
            logger.error(f"Failed to stop recording: {e}")
            self._recorder.cleanup()
            self._set_status_error("Recording failed")
            self._show_error_dialog(
                "Recording Error",
                "Something went wrong while saving the recording. Please try again.",
            )

    # ── Transcription pipeline ────────────────────────────────────────

    def _transcribe_background(self, audio_path: str) -> None:
        """Run transcription in a background thread (no GTK calls here)."""
        try:
            model_key = self._config.get("model")
            language = self._config.get("language")
            punctuation = self._config.get("punctuation")
            show_confidence = self._config.get("show_confidence")

            # Resolve config key → actual Whisper model name
            from tuxvox.system_info import MODEL_INFO

            info = MODEL_INFO.get(model_key, {})
            model_name = info.get("internal_name", model_key)

            GLib.idle_add(self._set_status_transcribing)

            def on_progress(current: int, total: int):
                GLib.idle_add(self._update_download_progress, current, total)

            result = self._transcriber.transcribe(
                audio_path=audio_path,
                model_name=model_name,
                language=language if language != "auto" else None,
                word_timestamps=show_confidence,
                punctuation=punctuation,
                download_callback=on_progress,
            )

            # Schedule UI update on main thread
            GLib.idle_add(self._on_transcription_complete, result)

        except MemoryError:
            logger.error(
                f"MemoryError: Not enough RAM to load model '{self._config.get('model')}'. "
                "Recommend switching to 'small'."
            )
            GLib.idle_add(
                self._on_transcription_error,
                "Not enough memory to load this model. "
                "Please choose a smaller model in Settings.",
            )

        except Exception as e:
            logger.error(f"Transcription error: {e}")
            GLib.idle_add(
                self._on_transcription_error,
                "Something went wrong during transcription. "
                "The app has reset itself — please try again.",
            )

        finally:
            # Always clean up — this is the core stability mechanism
            self._recorder.cleanup()
            logger.info("Cleanup complete. Ready for next session.")

    def _on_transcription_complete(self, result: TranscriptionResult) -> None:
        """Handle completed transcription on the main thread."""
        if not result.text.strip():
            self._is_transcribing = False
            self._record_btn.set_sensitive(True)
            self._set_status_error("No speech detected")
            self._show_error_dialog(
                "No Speech Detected",
                "No speech detected. Please speak closer to your microphone and try again.",
            )
            return

        # Prepare words for streaming
        show_confidence = self._config.get("show_confidence")

        if result.words and show_confidence:
            self._stream_words = [
                {"text": w.word, "probability": w.probability} for w in result.words
            ]
        else:
            # Split text into words for streaming
            words = result.text.split()
            self._stream_words = [{"text": w, "probability": 1.0} for w in words]

        # Add separator if there's existing text
        end_iter = self._text_buffer.get_end_iter()
        if self._text_buffer.get_char_count() > 0:
            if not self._config.get("paragraph_mode"):
                self._text_buffer.insert(end_iter, "\n\n")

        # Start typewriter streaming
        self._stream_index = 0
        speed = self._config.get("streaming_speed")
        self._stream_timeout_id = GLib.timeout_add(speed, self._stream_next_word)

        self._set_status_transcribing()
        return False  # GLib.idle_add: don't repeat

    def _stream_next_word(self) -> bool:
        """Insert the next word in the typewriter effect. Returns True to continue."""
        if self._stream_index >= len(self._stream_words):
            if self._config.get("paragraph_mode"):
                end_iter = self._text_buffer.get_end_iter()
                self._text_buffer.insert(end_iter, " ")

            # Streaming complete
            self._stream_timeout_id = None
            self._is_transcribing = False
            self._record_btn.set_sensitive(True)
            self._set_status_ready()

            # Save to history if enabled
            self._save_to_history()

            return False  # Stop the timeout

        word_info = self._stream_words[self._stream_index]
        word_text = word_info["text"]

        # Add space before word (except first word in this transcription)
        if self._stream_index > 0:
            word_text = " " + word_text

        end_iter = self._text_buffer.get_end_iter()

        # Insert with optional confidence tag
        show_confidence = self._config.get("show_confidence")
        if show_confidence and word_info["probability"] < 0.7:
            self._text_buffer.insert_with_tags_by_name(end_iter, word_text, "low-confidence")
        else:
            self._text_buffer.insert(end_iter, word_text)

        # Auto-scroll to bottom
        end_iter = self._text_buffer.get_end_iter()
        self._text_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 1.0)

        self._stream_index += 1
        return True  # Continue streaming

    def _on_transcription_error(self, message: str) -> None:
        """Handle transcription error on the main thread."""
        self._is_transcribing = False
        self._record_btn.set_sensitive(True)
        self._set_status_error("Transcription failed — ready to retry")
        self._show_error_dialog("Transcription Error", message)
        return False

    # ── Copy / Clear ──────────────────────────────────────────────────

    def _on_copy_clicked(self, _button: Gtk.Button) -> None:
        """Copy all text to system clipboard."""
        start = self._text_buffer.get_start_iter()
        end = self._text_buffer.get_end_iter()
        text = self._text_buffer.get_text(start, end, True)

        if not text.strip():
            return

        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)

        logger.info("Text copied to clipboard.")

        # Visual feedback: show "Copied!" for 1.5 seconds
        self._copy_label.set_text("✅ Copied!")
        self._copy_btn.add_css_class("copy-success")

        GLib.timeout_add(1500, self._reset_copy_button)

    def _reset_copy_button(self) -> bool:
        """Reset the copy button to its default state."""
        self._copy_label.set_text("Copy All to Clipboard")
        self._copy_btn.remove_css_class("copy-success")
        return False  # Don't repeat

    def _on_clear_clicked(self, _button: Gtk.Button) -> None:
        """Show confirmation dialog, then clear all text."""
        dialog = Adw.AlertDialog.new(
            "Clear All Text?",
            "Are you sure you want to clear all transcribed text? This cannot be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("clear", "Clear All")
        dialog.set_response_appearance("clear", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_clear_response)
        dialog.present(self)

    def _on_clear_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        """Handle clear confirmation dialog response."""
        if response == "clear":
            self._text_buffer.set_text("")
            logger.info("Text editor cleared by user.")

    # ── Settings ──────────────────────────────────────────────────────

    def _on_settings_clicked(self, _button: Gtk.Button) -> None:
        """Open the settings window."""
        from tuxvox.settings_window import SettingsWindow

        prefs = SettingsWindow(parent=self, config=self._config)
        prefs.present()

    # ── History saving ────────────────────────────────────────────────

    def _save_to_history(self) -> None:
        """Save transcription to file if history saving is enabled."""
        if not self._config.get("save_history"):
            return

        import os
        from datetime import datetime

        history_path = self._config.get("history_path")
        if not history_path:
            return

        try:
            os.makedirs(history_path, exist_ok=True)
            filename = datetime.now().strftime("tuxvox_%Y-%m-%d.txt")
            filepath = os.path.join(history_path, filename)

            start = self._text_buffer.get_start_iter()
            end = self._text_buffer.get_end_iter()
            text = self._text_buffer.get_text(start, end, True)

            with open(filepath, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%H:%M:%S")
                f.write(f"\n[{timestamp}]\n{text}\n")

            logger.info(f"Transcription saved to {filepath}")

        except Exception as e:
            logger.error(f"Failed to save transcription history: {e}")

    # ── Public API for experimental mode ────────────────────────────

    def append_transcription_text(self, text: str) -> None:
        """Append transcribed text to the editor (used by ExperimentalManager).

        This is the public entry point for the experimental hotkey pipeline
        to add text to the editor without going through the full internal
        streaming pipeline.
        """
        if not text.strip():
            return

        end_iter = self._text_buffer.get_end_iter()
        if self._text_buffer.get_char_count() > 0:
            self._text_buffer.insert(end_iter, "\n\n")
            end_iter = self._text_buffer.get_end_iter()

        self._text_buffer.insert(end_iter, text.strip())

        # Auto-scroll to bottom
        end_iter = self._text_buffer.get_end_iter()
        self._text_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 1.0)

        self._set_status_ready()
        logger.info("Text appended via experimental hotkey pipeline.")

    def flash_taskbar(self) -> None:
        """Flash the taskbar entry to notify user of new text (panel mode)."""
        try:
            self.set_urgency_hint(True)
            GLib.timeout_add(3000, self._clear_urgency)
        except AttributeError:
            pass  # GTK4 does not support urgency hints

    def _clear_urgency(self) -> bool:
        """Clear the urgency hint after timeout."""
        try:
            self.set_urgency_hint(False)
        except AttributeError:
            pass  # GTK4 does not support urgency hints
        return False

    # ── Close request handling ─────────────────────────────────────────

    def do_close_request(self) -> bool:
        """Handle window close request — may keep running in background."""
        if self._config.get("experimental_mode") and self._config.get("background_on_close"):
            self._show_close_dialog()
            return True  # Prevent default close
        return False  # Allow normal close

    def _show_close_dialog(self) -> None:
        """Show dialog asking whether to keep running in background."""
        dialog = Adw.AlertDialog.new(
            "Keep Running in Background?",
            "TuxVox will keep running in the background so your hotkey "
            "keeps working. You can quit it fully from the system tray, or "
            "turn off Experimental Mode in Settings.",
        )
        dialog.add_response("keep", "Keep Running")
        dialog.add_response("quit", "Quit Fully")
        dialog.set_response_appearance("quit", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("keep")
        dialog.set_close_response("keep")
        dialog.connect("response", self._on_close_dialog_response)
        dialog.present(self)

    def _on_close_dialog_response(self, _dialog: Adw.AlertDialog, response: str) -> None:
        """Handle close dialog response."""
        if response == "quit":
            app = self.get_application()
            if app:
                app.quit()
        else:
            # Keep running — just hide the window
            self.set_visible(False)

    # ── Error dialog helper ───────────────────────────────────────────

    def _show_error_dialog(self, title: str, message: str) -> None:
        """Show a simple error dialog."""
        dialog = Adw.AlertDialog.new(title, message)
        dialog.add_response("ok", "OK")
        dialog.set_default_response("ok")
        dialog.set_close_response("ok")
        dialog.present(self)
