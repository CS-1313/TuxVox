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

"""Floating overlay window for TuxVox experimental mode.

Displays a small, non-intrusive status indicator at the bottom-centre of
the screen.  The overlay never steals focus (critical for inline mode)
and automatically respects the system light/dark colour scheme via
:class:`Adw.StyleManager`.

States
------
``listening``
    Pulsing microphone indicator while recording.
``transcribing``
    Spinner-style message while Whisper processes audio.
``done_panel``
    Confirmation that text is ready in the TuxVox panel (auto-hides).
``done_inline``
    Confirmation that text was typed into the target app (auto-hides).
``error``
    Warning message (auto-hides after 2 s).
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gdk, GLib, Gtk

from tuxvox.logger import logger

# ---------------------------------------------------------------------------
# Overlay-specific CSS
# ---------------------------------------------------------------------------

_OVERLAY_CSS = """
.tuxvox-overlay {
    background-color: alpha(@window_bg_color, 0.92);
    border: 1px solid alpha(@borders, 0.5);
    border-radius: 16px;
    padding: 12px 24px;
    box-shadow: 0 4px 12px alpha(black, 0.25);
}

.tuxvox-overlay-text {
    font-size: 14px;
    font-weight: 600;
}

.tuxvox-overlay-hint {
    font-size: 11px;
    opacity: 0.6;
}

@keyframes sf-pulse-dots {
    0%   { opacity: 0.3; }
    50%  { opacity: 1.0; }
    100% { opacity: 0.3; }
}

.sf-pulsing {
    animation: sf-pulse-dots 1.4s ease-in-out infinite;
}
"""


class OverlayWindow(Gtk.Window):
    """Compact floating status window — always on top, never focusable.

    Args:
        hotkey_label: Human-readable label for the registered shortcut
            (e.g. ``"Ctrl+Shift+L"``), shown in hint text.
    """

    def __init__(self, hotkey_label: str = "Ctrl+Shift+L") -> None:
        super().__init__()

        self._hotkey_label: str = hotkey_label
        self._auto_hide_id: int | None = None

        # ── Window chrome ────────────────────────────────────────────
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_deletable(False)

        # Non-focusable: the overlay must not steal focus from the
        # user's target application.
        self.set_can_focus(False)
        self.set_focusable(False)

        # ── Load CSS ─────────────────────────────────────────────────
        self._install_css()

        # ── Layout ───────────────────────────────────────────────────
        self._box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=4,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
        )
        self._box.add_css_class("tuxvox-overlay")

        self._label = Gtk.Label()
        self._label.add_css_class("tuxvox-overlay-text")
        self._box.append(self._label)

        self._hint = Gtk.Label()
        self._hint.add_css_class("tuxvox-overlay-hint")
        self._hint.set_visible(False)
        self._box.append(self._hint)

        self.set_child(self._box)

        # ── Initial size ─────────────────────────────────────────────
        self.set_default_size(340, -1)  # natural height

        # ── Position at bottom-centre once mapped ────────────────────
        self.connect("realize", self._on_realize)

        logger.debug("OverlayWindow created.")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_state(self, state: str, **kwargs: str) -> None:
        """Update the overlay content for a given state.

        Args:
            state: One of ``'listening'``, ``'transcribing'``,
                ``'done_panel'``, ``'done_inline'``, ``'error'``.
            **kwargs: Extra context — ``message`` for ``'error'``,
                ``app_name`` for ``'done_inline'``.
        """
        self._cancel_auto_hide()

        if state == "listening":
            self._label.set_text("🎤 TuxVox — Listening…")
            self._label.add_css_class("sf-pulsing")
            self._hint.set_text(f"Press {self._hotkey_label} again to stop")
            self._hint.set_visible(True)

        elif state == "transcribing":
            self._label.set_text("⏳ Transcribing…")
            self._label.remove_css_class("sf-pulsing")
            self._hint.set_visible(False)

        elif state == "done_panel":
            self._label.set_text("✅ Text ready in TuxVox")
            self._label.remove_css_class("sf-pulsing")
            self._hint.set_visible(False)
            self._schedule_auto_hide(1500)

        elif state == "done_inline":
            app_name = kwargs.get("app_name", "application")
            self._label.set_text(f"✅ Typed into {app_name}")
            self._label.remove_css_class("sf-pulsing")
            self._hint.set_visible(False)
            self._schedule_auto_hide(1500)

        elif state == "error":
            message = kwargs.get("message", "Something went wrong")
            self._label.set_text(f"⚠️ {message}")
            self._label.remove_css_class("sf-pulsing")
            self._hint.set_visible(False)
            self._schedule_auto_hide(2000)

        else:
            logger.warning("OverlayWindow: unknown state '%s'", state)

    def show_overlay(self) -> None:
        """Present the overlay window."""
        self.set_visible(True)
        self.present()
        logger.debug("Overlay shown.")

    def hide_overlay(self) -> None:
        """Hide the overlay window."""
        self._cancel_auto_hide()
        self._label.remove_css_class("sf-pulsing")
        self.set_visible(False)
        logger.debug("Overlay hidden.")

    def update_hotkey_label(self, label: str) -> None:
        """Update the shortcut text displayed in the hint.

        Args:
            label: Human-readable shortcut, e.g. ``"Ctrl+Shift+L"``.
        """
        self._hotkey_label = label

    # ------------------------------------------------------------------
    # Positioning
    # ------------------------------------------------------------------

    def _on_realize(self, _widget: Gtk.Widget) -> None:
        """Position the window at bottom-centre once the surface exists."""
        try:
            display = Gdk.Display.get_default()
            if display is None:
                return

            surface = self.get_surface()
            if surface is None:
                return

            monitor = display.get_monitor_at_surface(surface)
            if monitor is None:
                # Fallback: first monitor
                monitors = display.get_monitors()
                if monitors.get_n_items() > 0:
                    monitor = monitors.get_item(0)
            if monitor is None:
                return

            geometry = monitor.get_geometry()
            scale = monitor.get_scale_factor()

            # Overlay width and approximate height
            overlay_w = 340
            overlay_h = 64

            x = geometry.x + (geometry.width // scale - overlay_w) // 2
            y = geometry.y + geometry.height // scale - overlay_h - 40

            # GTK4 layer-shell positioning is compositor-dependent.
            # On X11 we can use the GDK surface directly.
            try:
                toplevel = surface
                if hasattr(toplevel, "set_geometry_hints"):
                    pass  # GTK4 removed set_position; rely on window manager
                # For X11, attempt to set the position via the surface
                if hasattr(surface, "move"):
                    surface.move(x, y)
            except Exception as exc:
                logger.debug("Could not position overlay precisely: %s", exc)

        except Exception as exc:
            logger.debug("Overlay positioning failed: %s", exc)

    # ------------------------------------------------------------------
    # Auto-hide
    # ------------------------------------------------------------------

    def _schedule_auto_hide(self, ms: int) -> None:
        """Schedule the overlay to hide after *ms* milliseconds."""
        self._auto_hide_id = GLib.timeout_add(ms, self._do_auto_hide)

    def _cancel_auto_hide(self) -> None:
        """Cancel any pending auto-hide timer."""
        if self._auto_hide_id is not None:
            GLib.source_remove(self._auto_hide_id)
            self._auto_hide_id = None

    def _do_auto_hide(self) -> bool:
        """GLib timeout callback — hide the overlay."""
        self._auto_hide_id = None
        self.hide_overlay()
        return False  # do not repeat

    # ------------------------------------------------------------------
    # CSS installation
    # ------------------------------------------------------------------

    @staticmethod
    def _install_css() -> None:
        """Load overlay-specific CSS into the default display."""
        try:
            provider = Gtk.CssProvider()
            provider.load_from_string(_OVERLAY_CSS)
            display = Gdk.Display.get_default()
            if display is not None:
                Gtk.StyleContext.add_provider_for_display(
                    display,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
                )
        except Exception as exc:
            logger.warning("Failed to load overlay CSS: %s", exc)
