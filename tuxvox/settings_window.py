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

"""Settings / Preferences window for TuxVox.

Uses Adw.PreferencesWindow with two pages:
  1. General — model selection, input, display, history
  2. Help & Diagnostics — log copying, bug report link
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk
import numpy as np
import sounddevice as sd

from tuxvox.config import Config
from tuxvox.logger import get_full_log, get_redacted_log, logger
from tuxvox.recorder import Recorder
from tuxvox.system_info import (
    MODEL_INFO,
    get_system_info,
    recommend_model,
)

# Language list for the dropdown
LANGUAGES = [
    ("auto", "Auto-Detect"),
    ("en", "English"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("zh", "Chinese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("ru", "Russian"),
    ("ar", "Arabic"),
    ("hi", "Hindi"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("sv", "Swedish"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("vi", "Vietnamese"),
    ("th", "Thai"),
    ("id", "Indonesian"),
    ("cs", "Czech"),
    ("ro", "Romanian"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("el", "Greek"),
    ("he", "Hebrew"),
    ("hu", "Hungarian"),
    ("no", "Norwegian"),
    ("sk", "Slovak"),
    ("ca", "Catalan"),
    ("hr", "Croatian"),
    ("bg", "Bulgarian"),
    ("ms", "Malay"),
    ("ta", "Tamil"),
    ("ur", "Urdu"),
]


class SettingsWindow(Adw.PreferencesWindow):
    """Preferences window for TuxVox settings."""

    def __init__(self, parent: Adw.ApplicationWindow, config: Config | None = None) -> None:
        super().__init__(
            transient_for=parent,
            title="Settings",
            modal=True,
        )
        self.set_default_size(500, 700)
        self.set_search_enabled(False)

        self._config = config or Config()
        self._config.load()

        self._test_stream: sd.InputStream | None = None
        self._test_audio_level: float = 0.0
        self._test_timer_id: int = 0

        self._build_general_page()
        self._build_diagnostics_page()

        self.connect("close-request", self._on_close_request)

    # ── Page 1: General ───────────────────────────────────────────────

    def _build_general_page(self) -> None:
        """Build the General preferences page."""
        page = Adw.PreferencesPage(
            title="General",
            icon_name="preferences-system-symbolic",
        )
        self.add(page)

        # ── Privacy banner (always visible) ──
        privacy_group = Adw.PreferencesGroup()
        privacy_banner = Adw.ActionRow(
            title="\U0001f512  Your privacy: TuxVox runs entirely on your computer.",
            subtitle="No cloud, no data collection, no account.",
        )
        privacy_banner.set_sensitive(False)  # informational only
        privacy_group.add(privacy_banner)
        page.add(privacy_group)

        # ── Model selection group ──
        model_group = Adw.PreferencesGroup(
            title="Transcription Model",
            description="Choose which Whisper model to use for speech recognition.",
        )
        page.add(model_group)

        # Model ComboRow
        model_names = [info["display_name"] for info in MODEL_INFO.values()]
        model_list = Gtk.StringList.new(model_names)

        self._model_combo = Adw.ComboRow(
            title="Model",
            subtitle="Larger models are more accurate but slower on CPU.",
        )
        self._model_combo.set_model(model_list)

        # Set current selection
        current_model = self._config.get("model")
        model_keys = list(MODEL_INFO.keys())
        if current_model in model_keys:
            self._model_combo.set_selected(model_keys.index(current_model))

        self._model_combo.connect("notify::selected", self._on_model_changed)
        model_group.add(self._model_combo)

        # Model description label
        self._model_desc_label = Gtk.Label(
            wrap=True,
            xalign=0.0,
            margin_start=12,
            margin_end=12,
            margin_bottom=8,
        )
        self._model_desc_label.add_css_class("dim-label")
        self._model_desc_label.add_css_class("caption")
        self._update_model_description()
        model_group.add(self._model_desc_label)

        # Recommend button
        recommend_row = Adw.ActionRow(
            title="Auto-Detect Best Model",
            subtitle="Analyses your hardware and recommends the best model.",
        )
        recommend_btn = Gtk.Button(
            label="Recommend",
            valign=Gtk.Align.CENTER,
        )
        recommend_btn.add_css_class("suggested-action")
        recommend_btn.connect("clicked", self._on_recommend_clicked)
        recommend_row.add_suffix(recommend_btn)
        recommend_row.set_activatable_widget(recommend_btn)
        model_group.add(recommend_row)

        # ── Input group ──
        input_group = Adw.PreferencesGroup(
            title="Input",
            description="Configure your microphone and spoken language.",
        )
        page.add(input_group)

        # Microphone selector
        devices = Recorder.list_devices()
        device_names = ["Default System Microphone"] + [d["name"] for d in devices]
        mic_list = Gtk.StringList.new(device_names)

        self._mic_combo = Adw.ComboRow(
            title="Input Microphone",
            subtitle=(
                "Choose which microphone TuxVox listens to. "
                "If you're not sure, leave this on 'Default System Microphone'."
            ),
        )
        self._mic_combo.set_model(mic_list)

        # Set current selection
        current_mic = self._config.get("microphone")
        if current_mic == "default":
            self._mic_combo.set_selected(0)
        else:
            for i, d in enumerate(devices):
                if str(d.get("index")) == str(current_mic) or d["name"] == current_mic:
                    self._mic_combo.set_selected(i + 1)
                    break

        self._mic_combo.connect("notify::selected", self._on_mic_changed)
        self._devices = devices
        input_group.add(self._mic_combo)

        # Auto-configure microphone button
        auto_config_row = Adw.ActionRow(
            title="Auto-Configure Microphone",
            subtitle="Tests all microphones and selects the best one while you speak.",
        )
        auto_config_btn = Gtk.Button(
            label="Auto-Configure",
            valign=Gtk.Align.CENTER,
        )
        auto_config_btn.add_css_class("suggested-action")
        auto_config_btn.connect("clicked", self._on_autoconfig_mic_clicked)
        auto_config_row.add_suffix(auto_config_btn)
        auto_config_row.set_activatable_widget(auto_config_btn)
        input_group.add(auto_config_row)

        # Microphone test bar
        self._mic_level_bar = Gtk.LevelBar()
        self._mic_level_bar.set_min_value(0.0)
        self._mic_level_bar.set_max_value(1.0)
        self._mic_level_bar.set_valign(Gtk.Align.CENTER)
        self._mic_level_bar.set_size_request(-1, 8)
        self._mic_level_bar.set_hexpand(True)

        test_row = Adw.ActionRow(
            title="Test Microphone",
            subtitle="Speak to check if the app receives audio.",
        )

        level_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        level_box.set_valign(Gtk.Align.CENTER)
        level_box.set_size_request(200, -1)
        level_box.append(self._mic_level_bar)

        test_row.add_suffix(level_box)
        input_group.add(test_row)

        self._start_mic_test()

        # Language selector
        lang_names = [name for _, name in LANGUAGES]
        lang_list = Gtk.StringList.new(lang_names)

        self._lang_combo = Adw.ComboRow(
            title="Spoken Language",
            subtitle=(
                "Tell the app what language you'll be speaking. "
                "'Auto-Detect' works well most of the time, but selecting "
                "your language manually can improve accuracy."
            ),
        )
        self._lang_combo.set_model(lang_list)

        # Set current selection
        current_lang = self._config.get("language")
        for i, (code, _) in enumerate(LANGUAGES):
            if code == current_lang:
                self._lang_combo.set_selected(i)
                break

        self._lang_combo.connect("notify::selected", self._on_language_changed)
        input_group.add(self._lang_combo)

        # ── Display group ──
        display_group = Adw.PreferencesGroup(
            title="Display",
            description="Customise how transcribed text appears.",
        )
        page.add(display_group)

        # Text streaming speed slider
        speed_row = Adw.ActionRow(
            title="Text Appearance Speed",
            subtitle=(
                "Controls how quickly words appear on screen after transcription "
                "finishes. This is a visual effect only — it does not affect how "
                "fast your speech is processed."
            ),
        )

        speed_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        speed_box.set_valign(Gtk.Align.CENTER)
        speed_box.set_size_request(200, -1)

        instant_label = Gtk.Label(label="Instant")
        instant_label.add_css_class("dim-label")
        instant_label.add_css_class("caption")
        speed_box.append(instant_label)

        self._speed_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 80, 5)
        self._speed_scale.set_hexpand(True)
        self._speed_scale.set_draw_value(False)
        self._speed_scale.set_value(self._config.get("streaming_speed"))
        self._speed_scale.connect("value-changed", self._on_speed_changed)
        speed_box.append(self._speed_scale)

        slow_label = Gtk.Label(label="Slow")
        slow_label.add_css_class("dim-label")
        slow_label.add_css_class("caption")
        speed_box.append(slow_label)

        speed_row.add_suffix(speed_box)
        display_group.add(speed_row)

        # Show confidence toggle
        self._confidence_switch = Adw.SwitchRow(
            title="Show Word Confidence",
            subtitle=(
                "When turned on, words the app is less certain about are shown "
                "in a lighter colour. Useful if you want to spot-check accuracy, "
                "but can look busy for everyday use."
            ),
        )
        self._confidence_switch.set_active(self._config.get("show_confidence"))
        self._confidence_switch.connect("notify::active", self._on_confidence_changed)
        display_group.add(self._confidence_switch)

        # Punctuation toggle
        self._punctuation_switch = Adw.SwitchRow(
            title="Include Punctuation",
            subtitle=(
                "When turned on, TuxVox automatically adds commas, periods, "
                "question marks, and other punctuation to your transcribed text. "
                "Turn this off if you prefer raw text without punctuation."
            ),
        )
        self._punctuation_switch.set_active(self._config.get("punctuation"))
        self._punctuation_switch.connect("notify::active", self._on_punctuation_changed)
        display_group.add(self._punctuation_switch)

        # Paragraph Mode toggle
        self._paragraph_mode_switch = Adw.SwitchRow(
            title="Paragraph Mode",
            subtitle=(
                "When turned on, newly transcribed material will be added after what was "
                "previously generated on the same line, rather than starting on a new line."
            ),
        )
        self._paragraph_mode_switch.set_active(self._config.get("paragraph_mode") or False)
        self._paragraph_mode_switch.connect("notify::active", self._on_paragraph_mode_changed)
        display_group.add(self._paragraph_mode_switch)

        # ── History group ──
        history_group = Adw.PreferencesGroup(
            title="History",
            description="Optionally save your transcriptions to text files.",
        )
        page.add(history_group)

        # Save history toggle
        self._history_switch = Adw.SwitchRow(
            title="Save Transcriptions to File",
            subtitle=(
                "When turned on, TuxVox saves everything you transcribe to "
                "a text file on your computer. Each day gets its own file. "
                "Useful if you want a record of your dictation."
            ),
        )
        self._history_switch.set_active(self._config.get("save_history"))
        self._history_switch.connect("notify::active", self._on_history_toggled)
        history_group.add(self._history_switch)

        # History path row (shown only when save_history is on)
        self._history_path_row = Adw.ActionRow(
            title="Save Location",
            subtitle=self._config.get("history_path") or "Not set",
        )
        browse_btn = Gtk.Button(
            label="Browse…",
            valign=Gtk.Align.CENTER,
        )
        browse_btn.connect("clicked", self._on_browse_history_path)
        self._history_path_row.add_suffix(browse_btn)
        self._history_path_row.set_visible(self._config.get("save_history"))
        history_group.add(self._history_path_row)

        # ── Experimental Mode section ──
        self._build_experimental_section(page)

    # ── Page 2: Help & Diagnostics ────────────────────────────────────

    def _build_diagnostics_page(self) -> None:
        """Build the Help & Diagnostics preferences page."""
        page = Adw.PreferencesPage(
            title="Help & Diagnostics",
            icon_name="dialog-information-symbolic",
        )
        self.add(page)

        # ── Diagnostic Logs group ──
        log_group = Adw.PreferencesGroup(
            title="Diagnostic Logs",
            description=(
                "If something isn't working correctly, you can copy the app's "
                "diagnostic log and paste it into a bug report on GitHub. "
                "Use 'Redacted' if you'd prefer not to share what you said — "
                "your speech is replaced with [REDACTED] but all technical "
                "information is kept."
            ),
        )
        page.add(log_group)

        # Copy Full Log
        full_log_row = Adw.ActionRow(
            title="📋  Copy Full Log",
            subtitle="Copies the complete diagnostic log including transcribed text.",
        )
        self._full_log_btn = Gtk.Button(
            label="Copy",
            valign=Gtk.Align.CENTER,
        )
        self._full_log_btn.connect("clicked", self._on_copy_full_log)
        full_log_row.add_suffix(self._full_log_btn)
        full_log_row.set_activatable_widget(self._full_log_btn)
        log_group.add(full_log_row)

        # Copy Redacted Log
        redacted_log_row = Adw.ActionRow(
            title="🔒  Copy Redacted Log",
            subtitle="Copies the log with all transcribed speech replaced by [REDACTED].",
        )
        self._redacted_log_btn = Gtk.Button(
            label="Copy",
            valign=Gtk.Align.CENTER,
        )
        self._redacted_log_btn.connect("clicked", self._on_copy_redacted_log)
        redacted_log_row.add_suffix(self._redacted_log_btn)
        redacted_log_row.set_activatable_widget(self._redacted_log_btn)
        log_group.add(redacted_log_row)

        # ── Report a Bug group ──
        bug_group = Adw.PreferencesGroup(title="Report a Bug")
        page.add(bug_group)

        bug_row = Adw.ActionRow(
            title="🐛  Report a Bug on GitHub",
            subtitle="Opens the GitHub new issue page in your browser.",
        )
        link_btn = Gtk.Button(
            icon_name="external-link-symbolic",
            valign=Gtk.Align.CENTER,
        )
        link_btn.connect("clicked", self._on_report_bug)
        bug_row.add_suffix(link_btn)
        bug_row.set_activatable_widget(link_btn)
        bug_group.add(bug_row)

    # ── Signal handlers ───────────────────────────────────────────────

    def _on_model_changed(self, combo: Adw.ComboRow, _pspec) -> None:
        """Handle model selection change."""
        idx = combo.get_selected()
        model_keys = list(MODEL_INFO.keys())
        if 0 <= idx < len(model_keys):
            model_key = model_keys[idx]
            self._config.set("model", model_key)
            self._update_model_description()
            logger.info(f"Model changed to: {model_key}")

            # Show warning for large models
            if model_key in ("large", "large-v3"):
                self._show_large_model_warning(model_key)

    def _update_model_description(self) -> None:
        """Update the model description label based on current selection."""
        model_key = self._config.get("model")
        info = MODEL_INFO.get(model_key, {})
        desc = info.get("description", "")
        ram = info.get("ram_usage", "")
        speed = info.get("speed_label", "")
        self._model_desc_label.set_text(f"{desc}\n\n💾 RAM: {ram}  ·  ⚡ Speed: {speed}")

    def _show_large_model_warning(self, model_key: str) -> None:
        """Show a warning dialog when a large model is selected."""
        dialog = Adw.AlertDialog.new(
            "Large Model Selected",
            "This model requires a lot of memory and is much slower on CPU. "
            "It is best suited for computers with 16 GB of RAM or more. "
            "Are you sure you want to use this model?",
        )
        dialog.add_response("cancel", "Switch Back")
        dialog.add_response("confirm", "Use Anyway")
        dialog.set_response_appearance("confirm", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self._on_large_model_warning_response)
        dialog.present(self)

    def _on_large_model_warning_response(self, _dialog, response: str) -> None:
        """Handle large model warning response."""
        if response == "cancel":
            # Revert to 'small'
            model_keys = list(MODEL_INFO.keys())
            small_idx = model_keys.index("small") if "small" in model_keys else 2
            self._model_combo.set_selected(small_idx)
            self._config.set("model", "small")

    def _on_recommend_clicked(self, _button: Gtk.Button) -> None:
        """Run system detection and recommend a model."""
        info = get_system_info()
        model_name, explanation = recommend_model(info["ram_gb"], info["cpu_cores"])

        dialog = Adw.AlertDialog.new(
            "Model Recommendation",
            f"Your computer has {info['ram_gb']:.0f} GB of RAM and "
            f"{info['cpu_cores']} CPU cores/threads.\n\n{explanation}",
        )
        dialog.add_response("dismiss", "OK")
        dialog.add_response("apply", "Apply Recommendation")
        dialog.set_response_appearance("apply", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("apply")
        dialog.set_close_response("dismiss")
        dialog.connect("response", self._on_recommend_response, model_name)
        dialog.present(self)

    def _on_recommend_response(self, _dialog, response: str, model_name: str) -> None:
        """Apply recommended model if user confirms."""
        if response == "apply":
            model_keys = list(MODEL_INFO.keys())
            if model_name in model_keys:
                self._model_combo.set_selected(model_keys.index(model_name))
                self._config.set("model", model_name)
                self._update_model_description()
                logger.info(f"Applied recommended model: {model_name}")

    def _on_mic_changed(self, combo: Adw.ComboRow, _pspec) -> None:
        """Handle microphone selection change."""
        idx = combo.get_selected()
        if idx == 0:
            self._config.set("microphone", "default")
        elif 0 < idx <= len(self._devices):
            device = self._devices[idx - 1]
            self._config.set("microphone", str(device["index"]))

        self._start_mic_test()

    def _on_language_changed(self, combo: Adw.ComboRow, _pspec) -> None:
        """Handle language selection change."""
        idx = combo.get_selected()
        if 0 <= idx < len(LANGUAGES):
            code, _ = LANGUAGES[idx]
            self._config.set("language", code)
            logger.info(f"Language changed to: {code}")

    def _on_speed_changed(self, scale: Gtk.Scale) -> None:
        """Handle streaming speed slider change."""
        self._config.set("streaming_speed", int(scale.get_value()))

    def _on_confidence_changed(self, switch: Adw.SwitchRow, _pspec) -> None:
        """Handle confidence toggle change."""
        self._config.set("show_confidence", switch.get_active())

    def _on_punctuation_changed(self, switch: Adw.SwitchRow, _pspec) -> None:
        """Handle punctuation toggle change."""
        self._config.set("punctuation", switch.get_active())

    def _on_paragraph_mode_changed(self, switch: Adw.SwitchRow, _pspec) -> None:
        """Handle paragraph mode toggle change."""
        self._config.set("paragraph_mode", switch.get_active())

    def _on_history_toggled(self, switch: Adw.SwitchRow, _pspec) -> None:
        """Handle history save toggle change."""
        active = switch.get_active()
        self._config.set("save_history", active)
        self._history_path_row.set_visible(active)

    def _on_browse_history_path(self, _button: Gtk.Button) -> None:
        """Open a folder chooser for history save location."""
        dialog = Gtk.FileDialog()
        dialog.set_title("Choose Save Location")
        dialog.select_folder(self, None, self._on_folder_selected)

    def _on_folder_selected(self, dialog: Gtk.FileDialog, result) -> None:
        """Handle folder selection result."""
        try:
            folder = dialog.select_folder_finish(result)
            if folder:
                path = folder.get_path()
                self._config.set("history_path", path)
                self._history_path_row.set_subtitle(path)
                logger.info(f"History path set to: {path}")
        except GLib.Error:
            pass  # User cancelled

    # ── Microphone Testing ────────────────────────────────────────────

    def _on_autoconfig_mic_clicked(self, _button: Gtk.Button) -> None:
        """Launch mic auto-configure."""
        dialog = Gtk.Window(title="Auto-Configure Microphone")
        dialog.set_modal(True)
        dialog.set_transient_for(self)
        dialog.set_default_size(400, 200)
        dialog.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        label = Gtk.Label(
            label="Speak as close as possible to the desired microphone and repeatedly say “Testing, Testing, Testing, Testing” until the test is finished."
        )
        label.set_justify(Gtk.Justification.CENTER)

        progress = Gtk.ProgressBar()
        progress.set_fraction(0.0)

        box.append(label)
        box.append(progress)

        cancel_btn = Gtk.Button(label="Cancel")
        box.append(cancel_btn)

        dialog.set_child(box)

        self._autoconfig_dialog = dialog
        self._autoconfig_progress = progress
        self._autoconfig_cancelled = False
        self._autoconfig_best_mic = None
        self._autoconfig_best_level = 0.0
        self._autoconfig_current_idx = 0

        # Build device list: index 0 is default mic, rest are specific mics
        self._autoconfig_device_list = [
            {"name": "Default System Microphone", "index": None}
        ] + self._devices

        # Stop the default mic test stream so it doesn't conflict
        self._stop_mic_test()

        cancel_btn.connect("clicked", self._on_autoconfig_cancel)
        dialog.connect("close-request", self._on_autoconfig_cancel)
        dialog.present()

        # Start the sequence
        GLib.timeout_add(100, self._autoconfig_step)

    def _on_autoconfig_cancel(self, *args) -> bool:
        """Handle auto-config cancellation."""
        self._autoconfig_cancelled = True
        if hasattr(self, "_autoconfig_stream") and self._autoconfig_stream:
            try:
                self._autoconfig_stream.stop()
                self._autoconfig_stream.close()
            except Exception:
                pass
            self._autoconfig_stream = None
        if hasattr(self, "_autoconfig_dialog") and self._autoconfig_dialog:
            self._autoconfig_dialog.close()
            self._autoconfig_dialog = None
        self._start_mic_test()
        return False

    def _autoconfig_step(self) -> bool:
        """Process one step (one microphone) of the auto-config process."""
        if self._autoconfig_cancelled:
            return False

        # Evaluate previous stream if open
        if hasattr(self, "_autoconfig_stream") and self._autoconfig_stream:
            try:
                self._autoconfig_stream.stop()
                self._autoconfig_stream.close()
            except Exception:
                pass
            self._autoconfig_stream = None

            if self._autoconfig_current_level > self._autoconfig_best_level:
                self._autoconfig_best_level = self._autoconfig_current_level
                self._autoconfig_best_mic = self._autoconfig_current_idx - 1

        if self._autoconfig_current_idx >= len(self._autoconfig_device_list):
            self._finish_autoconfig()
            return False

        device = self._autoconfig_device_list[self._autoconfig_current_idx]
        self._autoconfig_current_level = 0.0

        def _test_cb(
            indata: np.ndarray, frames: int, time_info: object, status: sd.CallbackFlags
        ) -> None:
            if not indata.size:
                return
            rms = float(np.sqrt(np.mean(indata**2)))
            level = min(1.0, rms * 5.0)
            if level > self._autoconfig_current_level:
                self._autoconfig_current_level = level

        try:
            device_arg = device.get("index") if device.get("index") is not None else None
            self._autoconfig_stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=device_arg,
                callback=_test_cb,
            )
            self._autoconfig_stream.start()
        except Exception as exc:
            logger.error("Auto-config failed for device %s: %s", device.get("name"), exc)

        self._autoconfig_current_idx += 1
        fraction = self._autoconfig_current_idx / len(self._autoconfig_device_list)
        self._autoconfig_progress.set_fraction(fraction)

        # Move to next step after 600ms to allow user to speak
        GLib.timeout_add(600, self._autoconfig_step)
        return False

    def _finish_autoconfig(self) -> None:
        """Finalize auto-config and apply the best mic."""
        if hasattr(self, "_autoconfig_dialog") and self._autoconfig_dialog:
            self._autoconfig_dialog.close()
            self._autoconfig_dialog = None

        if self._autoconfig_best_mic is not None and self._autoconfig_best_level > 0.01:
            self._mic_combo.set_selected(self._autoconfig_best_mic)
            logger.info(
                "Auto-configured mic to index %d with level %f",
                self._autoconfig_best_mic,
                self._autoconfig_best_level,
            )
            toast = Adw.Toast.new("Microphone auto-configured successfully.")
            toast.set_timeout(3)
            self.add_toast(toast)
        else:
            toast = Adw.Toast.new("Could not detect audio on any microphone.")
            toast.set_timeout(3)
            self.add_toast(toast)

        self._start_mic_test()

    def _start_mic_test(self) -> None:
        """Start or restart the background stream to test microphone input."""
        self._stop_mic_test()

        current_mic = self._config.get("microphone")
        device_arg = None
        if current_mic and current_mic != "default":
            try:
                device_arg = int(current_mic)
            except ValueError:
                device_arg = current_mic

        try:
            self._test_stream = sd.InputStream(
                samplerate=16000,
                channels=1,
                dtype="float32",
                device=device_arg,
                callback=self._mic_test_callback,
            )
            self._test_stream.start()
            self._test_timer_id = GLib.timeout_add(50, self._update_mic_level_ui)
        except Exception as exc:
            logger.error("Failed to start mic test stream: %s", exc)
            self._mic_level_bar.set_value(0.0)

    def _mic_test_callback(
        self, indata: np.ndarray, frames: int, time_info: object, status: sd.CallbackFlags
    ) -> None:
        """Audio callback to compute RMS volume of the chunk."""
        if not indata.size:
            return

        rms = float(np.sqrt(np.mean(indata**2)))
        level = min(1.0, rms * 5.0)
        self._test_audio_level = level

    def _update_mic_level_ui(self) -> bool:
        """Update the LevelBar from the main thread."""
        current = self._mic_level_bar.get_value()
        target = self._test_audio_level

        if target > current:
            new_val = target
        else:
            new_val = max(0.0, current - 0.05)

        self._mic_level_bar.set_value(new_val)
        return True

    def _stop_mic_test(self) -> None:
        """Stop the mic test stream and timer."""
        if self._test_timer_id:
            GLib.source_remove(self._test_timer_id)
            self._test_timer_id = 0

        if self._test_stream:
            try:
                self._test_stream.stop()
                self._test_stream.close()
            except Exception as exc:
                logger.error("Error closing mic test stream: %s", exc)
            self._test_stream = None

        self._test_audio_level = 0.0
        if hasattr(self, "_mic_level_bar"):
            self._mic_level_bar.set_value(0.0)

    def _on_close_request(self, *args) -> bool:
        """Cleanup when the settings window is closed."""
        self._stop_mic_test()
        return False

    # ── Log copying ───────────────────────────────────────────────────

    def _on_copy_full_log(self, _button: Gtk.Button) -> None:
        """Copy the full diagnostic log to clipboard."""
        log_text = get_full_log()
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(log_text)

        self._full_log_btn.set_label("✅ Copied!")
        GLib.timeout_add(1500, lambda: self._full_log_btn.set_label("Copy") or False)
        logger.info("Full diagnostic log copied to clipboard.")

    def _on_copy_redacted_log(self, _button: Gtk.Button) -> None:
        """Copy the redacted diagnostic log to clipboard."""
        log_text = get_redacted_log()
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(log_text)

        self._redacted_log_btn.set_label("✅ Copied!")
        GLib.timeout_add(1500, lambda: self._redacted_log_btn.set_label("Copy") or False)
        logger.info("Redacted diagnostic log copied to clipboard.")

    def _on_report_bug(self, _button: Gtk.Button) -> None:
        """Open the GitHub issues page in the default browser."""
        Gtk.show_uri(
            self,
            "https://github.com/CS-1313/TuxVox/issues/new?template=bug_report.md",
            Gdk.CURRENT_TIME,
        )

    # ── Experimental Mode Section ─────────────────────────────────────

    def _build_experimental_section(self, page: Adw.PreferencesPage) -> None:
        """Build the Experimental Mode settings section."""
        exp_group = Adw.PreferencesGroup(
            title="\u2697\ufe0f  Experimental Features",
            description=(
                "These features are in testing and may not work perfectly on "
                "all systems. They can be turned off at any time to instantly "
                "return to standard mode \u2014 nothing is permanently changed."
            ),
        )
        page.add(exp_group)

        # Privacy note for experimental mode
        exp_privacy_row = Adw.ActionRow(
            title="\U0001f512 Fully offline even in Experimental Mode",
            subtitle=(
                "Your voice is never sent anywhere, even when typing into "
                "other apps. Inline typing works entirely through your "
                "computer's own input system."
            ),
        )
        exp_privacy_row.set_sensitive(False)
        exp_group.add(exp_privacy_row)

        # Main toggle
        self._exp_toggle = Adw.SwitchRow(
            title="Enable Experimental Mode",
            subtitle="Unlocks Global Hotkey and Inline Typing features.",
        )
        self._exp_toggle.set_active(self._config.get("experimental_mode") or False)
        self._exp_toggle.connect("notify::active", self._on_experimental_toggled)
        exp_group.add(self._exp_toggle)

        # Revealer for sub-settings (animated expand/collapse)
        self._exp_revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
            transition_duration=300,
            reveal_child=self._config.get("experimental_mode") or False,
        )

        exp_sub_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        # ── Output Mode sub-group ──
        output_group = Adw.PreferencesGroup(title="Output Mode")

        # Panel mode radio
        self._panel_check = Gtk.CheckButton()
        panel_row = Adw.ActionRow(
            title="Panel Mode",
            subtitle=(
                "Text appears in TuxVox as usual. "
                "You copy and paste it yourself. The most stable option."
            ),
        )
        panel_row.add_prefix(self._panel_check)
        panel_row.set_activatable_widget(self._panel_check)
        output_group.add(panel_row)

        # Inline mode radio
        self._inline_check = Gtk.CheckButton(group=self._panel_check)
        inline_row = Adw.ActionRow(
            title="Inline Mode  \u2697\ufe0f",
            subtitle=(
                "Text is typed directly into whatever app you are using "
                "when you press the hotkey. Requires a one-time system "
                "permission on modern Linux desktops."
            ),
        )
        inline_row.add_prefix(self._inline_check)
        inline_row.set_activatable_widget(self._inline_check)
        output_group.add(inline_row)

        # Set current selection
        current_mode = self._config.get("output_mode") or "panel"
        if current_mode == "inline":
            self._inline_check.set_active(True)
        else:
            self._panel_check.set_active(True)

        self._panel_check.connect("toggled", self._on_output_mode_changed)

        exp_sub_box.append(output_group)

        # ── Global Hotkey sub-group ──
        hotkey_group = Adw.PreferencesGroup(
            title="Global Hotkey",
            description=(
                "Press this key combination from any app to start recording "
                "without switching to TuxVox. Press it again to stop, or "
                "speak and it will stop after a short silence."
            ),
        )

        current_hotkey = self._config.get("global_hotkey") or "ctrl+shift+l"
        self._hotkey_row = Adw.ActionRow(
            title="Record Shortcut",
            subtitle=current_hotkey.replace("+", " + ").title(),
        )
        change_btn = Gtk.Button(
            label="Change",
            valign=Gtk.Align.CENTER,
        )
        change_btn.connect("clicked", self._on_change_hotkey_clicked)
        self._hotkey_row.add_suffix(change_btn)
        self._hotkey_row.set_activatable_widget(change_btn)
        hotkey_group.add(self._hotkey_row)

        exp_sub_box.append(hotkey_group)

        self._exp_revealer.set_child(exp_sub_box)
        # Wrap revealer in a group so it fits in the PreferencesPage
        revealer_group = Adw.PreferencesGroup()
        revealer_group.add(self._exp_revealer)
        page.add(revealer_group)

    def _on_experimental_toggled(self, switch: Adw.SwitchRow, _pspec) -> None:
        """Handle Experimental Mode toggle."""
        active = switch.get_active()
        self._config.set("experimental_mode", active)
        self._exp_revealer.set_reveal_child(active)

        if not active:
            # Show toast notification
            toast = Adw.Toast.new(
                "Experimental features disabled. TuxVox has returned to standard mode."
            )
            toast.set_timeout(3)
            self.add_toast(toast)

        logger.info("Experimental mode %s.", "enabled" if active else "disabled")

        parent = self.get_transient_for()
        if parent and hasattr(parent, "toggle_experimental_mode"):
            parent.toggle_experimental_mode(active)

    def _on_output_mode_changed(self, _check: Gtk.CheckButton) -> None:
        """Handle output mode radio button change."""
        if self._panel_check.get_active():
            self._config.set("output_mode", "panel")
            logger.info("Output mode changed to: panel")
        else:
            self._config.set("output_mode", "inline")
            logger.info("Output mode changed to: inline")

            import os

            if not os.access("/dev/uinput", os.W_OK):
                dialog = Adw.AlertDialog.new(
                    "Setup Required for Inline Mode",
                    "Inline mode requires write access to /dev/uinput. "
                    "To enable this, run the setup script included with TuxVox. "
                    "After running the script, reboot your computer.",
                )

                command_label = Gtk.Label(
                    label="sudo bash ~/TuxVox/scripts/setup-uinput.sh",
                    selectable=True,
                    wrap=True,
                    xalign=0.0,
                )
                command_label.add_css_class("card")
                command_label.add_css_class("dim-label")
                command_label.set_margin_top(12)

                dialog.set_extra_child(command_label)
                dialog.add_response("ok", "OK")
                dialog.set_default_response("ok")
                dialog.set_close_response("ok")
                dialog.present(self)

    def _on_change_hotkey_clicked(self, _button: Gtk.Button) -> None:
        """Open the hotkey capture dialog."""
        dialog = Gtk.Window(title="Set Recording Shortcut")
        dialog.set_modal(True)
        dialog.set_transient_for(self)
        dialog.set_default_size(400, 150)
        dialog.set_resizable(False)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_top(24)
        box.set_margin_bottom(24)
        box.set_margin_start(24)
        box.set_margin_end(24)

        label = Gtk.Label(
            label="Press the key combination you want to use for recording.\n(Listening for input...)"
        )
        label.set_justify(Gtk.Justification.CENTER)

        # We need a place to show conflict warnings
        warning_label = Gtk.Label(label="")
        warning_label.set_justify(Gtk.Justification.CENTER)
        warning_label.add_css_class("error")

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: dialog.close())

        box.append(label)
        box.append(warning_label)
        box.append(cancel_btn)
        dialog.set_child(box)

        # We use a key event controller to capture the shortcut
        self._capture_dialog = dialog
        self._warning_label = warning_label
        self._captured_keys: set[str] = set()

        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self._on_hotkey_capture_press)

        # Attach directly to the dialog window so it intercepts the keys
        dialog.add_controller(key_controller)

        # Cleanup when closed
        def on_close(*_args):
            self._capture_dialog = None
            self._warning_label = None

        dialog.connect("close-request", on_close)
        dialog.present()

    def _on_hotkey_capture_press(
        self,
        _controller: Gtk.EventControllerKey,
        keyval: int,
        _keycode: int,
        state: Gdk.ModifierType,
    ) -> bool:
        """Capture key press during hotkey configuration."""
        key_name = Gdk.keyval_name(keyval)
        if key_name is None:
            return False

        parts: list[str] = []
        if state & Gdk.ModifierType.SUPER_MASK:
            parts.append("super")
        if state & Gdk.ModifierType.CONTROL_MASK:
            parts.append("ctrl")
        if state & Gdk.ModifierType.ALT_MASK:
            parts.append("alt")
        if state & Gdk.ModifierType.SHIFT_MASK:
            parts.append("shift")

        # Ignore bare modifier keys
        if key_name.lower() in (
            "super_l",
            "super_r",
            "control_l",
            "control_r",
            "alt_l",
            "alt_r",
            "shift_l",
            "shift_r",
            "meta_l",
            "meta_r",
            "iso_level3_shift",
        ):
            return False

        if not parts:
            # Must include at least one modifier
            return False

        parts.append(key_name.lower())
        hotkey_str = "+".join(parts)

        # Check for known conflicts
        known_conflicts = {
            "super+l",
            "ctrl+c",
            "ctrl+v",
            "ctrl+x",
            "ctrl+z",
            "alt+f4",
            "super+tab",
            "ctrl+alt+delete",
        }
        if hotkey_str in known_conflicts:
            if hasattr(self, "_warning_label") and self._warning_label:
                self._warning_label.set_label(
                    f"\u26a0\ufe0f '{hotkey_str}' is commonly used by the system. "
                    "We recommend choosing a different one."
                )
            return True

        self._config.set("global_hotkey", hotkey_str)
        self._hotkey_row.set_subtitle(hotkey_str.replace("+", " + ").title())
        logger.info("Global hotkey changed to: %s", hotkey_str)

        parent = self.get_transient_for()
        if parent and hasattr(parent, "_experimental_manager") and parent._experimental_manager:
            parent._experimental_manager.hotkey_mgr.change_hotkey(hotkey_str)

        # Close the capture dialog
        if hasattr(self, "_capture_dialog") and self._capture_dialog:
            self._capture_dialog.close()
            self._capture_dialog = None

        # Remove the key controller
        if hasattr(self, "_hotkey_controller"):
            self.remove_controller(self._hotkey_controller)
            self._hotkey_controller = None

        return True

    def _on_hotkey_capture_response(self, _dialog: Adw.AlertDialog, _response: str) -> None:
        """Handle hotkey capture dialog close."""
        self._capture_dialog = None
        if hasattr(self, "_hotkey_controller") and self._hotkey_controller:
            self.remove_controller(self._hotkey_controller)
            self._hotkey_controller = None
