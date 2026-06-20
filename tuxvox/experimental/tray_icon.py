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

"""System tray icon for TuxVox experimental mode.

Uses ``AppIndicator3`` from the GObject-Introspection bindings to place
a persistent icon in the system tray.  If ``AppIndicator3`` is not
installed, every public method silently becomes a no-op so the rest of
the application is unaffected.
"""

from __future__ import annotations

from typing import Any, Callable

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk

from tuxvox.logger import logger

# ---------------------------------------------------------------------------
# Try to import AppIndicator3 — it is an optional dependency.
# ---------------------------------------------------------------------------

_HAS_INDICATOR = False
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator3

    _HAS_INDICATOR = True
    logger.debug("AyatanaAppIndicator3 loaded successfully.")
except (ValueError, ImportError):
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3  # type: ignore[no-redef]

        _HAS_INDICATOR = True
        logger.debug("AppIndicator3 loaded successfully.")
    except (ValueError, ImportError):
        logger.warning(
            "Neither AyatanaAppIndicator3 nor AppIndicator3 is available. "
            "System tray icon will be disabled."
        )

# ---------------------------------------------------------------------------
# TrayIcon class
# ---------------------------------------------------------------------------

_INDICATOR_ID = "tuxvox-indicator"
_ICON_NAME = "audio-input-microphone-symbolic"


class TrayIcon:
    """System tray indicator with a right-click context menu.

    If the AppIndicator3 library is not present, all methods are safe to
    call but do nothing.

    Args:
        on_open: Callback invoked when the user clicks *Open TuxVox*.
        on_disable: Callback invoked when the user clicks *Disable
            Experimental Mode*.
        on_quit: Callback invoked when the user clicks *Quit*.
    """

    def __init__(
        self,
        on_open: Callable[[], None],
        on_disable: Callable[[], None],
        on_quit: Callable[[], None],
    ) -> None:
        self._on_open = on_open
        self._on_disable = on_disable
        self._on_quit = on_quit
        self._indicator: Any = None
        self._menu: Gtk.Menu | None = None  # GTK3-style menu for AppIndicator

        if _HAS_INDICATOR:
            self._build_indicator()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show(self) -> None:
        """Make the tray icon visible."""
        if self._indicator is None:
            return
        try:
            self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            logger.info("Tray icon shown.")
        except Exception as exc:
            logger.warning("Could not show tray icon: %s", exc)

    def hide(self) -> None:
        """Hide the tray icon."""
        if self._indicator is None:
            return
        try:
            self._indicator.set_status(AppIndicator3.IndicatorStatus.PASSIVE)
            logger.info("Tray icon hidden.")
        except Exception as exc:
            logger.warning("Could not hide tray icon: %s", exc)

    def destroy(self) -> None:
        """Remove the tray icon and release resources."""
        self.hide()
        self._indicator = None
        self._menu = None
        logger.debug("Tray icon destroyed.")

    # ------------------------------------------------------------------
    # Internal construction
    # ------------------------------------------------------------------

    def _build_indicator(self) -> None:
        """Create the AppIndicator3 indicator and its context menu.

        AppIndicator3 still uses GTK 3-style ``Gtk.Menu`` widgets.  We
        import them at the GI level only when the library is available.
        """
        try:
            # AppIndicator3 requires GTK3-style menus.
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk as Gtk3  # type: ignore[no-redef]
        except (ValueError, ImportError):
            # If GTK3 introspection isn't available alongside GTK4,
            # build a minimal indicator without a menu.
            try:
                self._indicator = AppIndicator3.Indicator.new(
                    _INDICATOR_ID,
                    _ICON_NAME,
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
                )
                self._indicator.set_status(AppIndicator3.IndicatorStatus.PASSIVE)
                logger.info("Tray icon created (without menu — GTK3 unavailable).")
            except Exception as exc:
                logger.warning("Failed to create tray indicator: %s", exc)
                self._indicator = None
            return

        try:
            self._indicator = AppIndicator3.Indicator.new(
                _INDICATOR_ID,
                _ICON_NAME,
                AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
            )
            self._indicator.set_status(AppIndicator3.IndicatorStatus.PASSIVE)

            # -- Context menu (GTK3-style) --
            menu = Gtk3.Menu()

            # Status label (not clickable)
            status_item = Gtk3.MenuItem(label="● TuxVox is running")
            status_item.set_sensitive(False)
            menu.append(status_item)

            menu.append(Gtk3.SeparatorMenuItem())

            # Open TuxVox
            open_item = Gtk3.MenuItem(label="Open TuxVox")
            open_item.connect("activate", lambda *_: self._on_open())
            menu.append(open_item)

            # Disable Experimental Mode
            disable_item = Gtk3.MenuItem(label="Disable Experimental Mode")
            disable_item.connect("activate", lambda *_: self._on_disable())
            menu.append(disable_item)

            menu.append(Gtk3.SeparatorMenuItem())

            # Quit
            quit_item = Gtk3.MenuItem(label="Quit")
            quit_item.connect("activate", lambda *_: self._on_quit())
            menu.append(quit_item)

            menu.show_all()
            self._indicator.set_menu(menu)

            logger.info("Tray icon created with context menu.")

        except Exception as exc:
            logger.warning("Failed to build tray indicator: %s", exc)
            self._indicator = None
