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

"""TuxVox application entry point.

Initialises the Adw.Application, registers app-level actions, and
presents the main window on activation.
"""

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio  # noqa: E402

from tuxvox.logger import logger, setup_logging  # noqa: E402
from tuxvox.system_info import get_system_info  # noqa: E402
from tuxvox import __version__  # noqa: E402


class TuxVoxApp(Adw.Application):
    """Main application class for TuxVox."""

    def __init__(self) -> None:
        super().__init__(
            application_id="org.tuxvox.TuxVox",
            flags=Gio.ApplicationFlags.FLAGS_NONE,
        )

    def do_startup(self) -> None:
        """Called once when the application first starts."""
        Adw.Application.do_startup(self)
        self._create_actions()
        self._load_css()

    def do_activate(self) -> None:
        """Called when the application is activated (launched or re-focused)."""
        # Avoid creating duplicate windows
        win = self.props.active_window
        if not win:
            # Deferred import to avoid circular dependency
            from tuxvox.app_window import AppWindow

            win = AppWindow(application=self)

            # Log startup info
            logger.info(f"App launched. TuxVox v{__version__}")
            info = get_system_info()
            logger.info(
                f"RAM: {info['ram_gb']:.1f} GB total. "
                f"CPU cores: {info['cpu_cores']} (logical)."
            )

        win.present()

    def _create_actions(self) -> None:
        """Register application-level actions for menus and shortcuts."""
        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>q"])

        # Preferences action
        prefs_action = Gio.SimpleAction.new("preferences", None)
        prefs_action.connect("activate", self._on_preferences)
        self.add_action(prefs_action)
        self.set_accels_for_action("app.preferences", ["<Ctrl>comma"])

    def _on_preferences(self, _action: Gio.SimpleAction, _param: None) -> None:
        """Open the settings/preferences window."""
        from tuxvox.settings_window import SettingsWindow

        win = self.props.active_window
        if win:
            prefs = SettingsWindow(parent=win)
            prefs.present()

    def _load_css(self) -> None:
        """Load custom CSS for the application."""
        from gi.repository import Gdk, Gtk

        css_provider = Gtk.CssProvider()
        css_provider.load_from_string(APP_CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


APP_CSS = """
/* Text editor area */
.transcript-editor {
    font-size: 15px;
    padding: 12px;
}

/* Pulsing recording indicator */
@keyframes pulse-recording {
    0% { opacity: 1.0; }
    50% { opacity: 0.4; }
    100% { opacity: 1.0; }
}

.recording-pulse {
    animation: pulse-recording 1.2s ease-in-out infinite;
}

/* Status bar */
.status-bar {
    padding: 6px 12px;
    font-size: 13px;
}

.status-recording {
    color: @error_color;
    font-weight: bold;
}

.status-transcribing {
    color: @warning_color;
    font-weight: bold;
}

.status-ready {
    color: @success_color;
}

/* Copy confirmation green flash */
.copy-success {
    background-color: alpha(@success_color, 0.15);
    color: @success_color;
}

/* Fade-in effect for new words */
@keyframes word-fade-in {
    from { opacity: 0.3; }
    to { opacity: 1.0; }
}

/* Low-confidence word styling */
.low-confidence {
    opacity: 0.5;
}

/* Record button recording state */
.recording-button {
    background-color: @error_bg_color;
}
"""


def main() -> int:
    """Entry point for TuxVox."""
    setup_logging()
    app = TuxVoxApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
