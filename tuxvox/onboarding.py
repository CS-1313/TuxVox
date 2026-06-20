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

"""First-launch onboarding dialog for TuxVox.

Presents a privacy-first welcome message and offers the user a choice
between downloading the default model immediately or selecting a
different model first.  This module is intended to replace the older
model-download dialog flow.
"""

from __future__ import annotations

from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from tuxvox.logger import logger  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WELCOME_HEADING: str = "Welcome to TuxVox"

_WELCOME_BODY: str = (
    "\U0001f512 TuxVox processes everything on your computer using a "
    "local AI model. Your voice recordings are never sent to the internet. "
    "Your voice audio is never stored after transcription is complete, and "
    "is never shared with anyone \u2014 including the developers.\n\n"
    "The only internet connection TuxVox will ever make is the one-time "
    "model download below. After that, the app works entirely offline \u2014 "
    "forever.\n\n"
    "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500"
    "\u2500\u2500\u2500\u2500\u2500\n\n"
    "TuxVox needs to download the speech recognition model "
    "(approx. 300 MB for the default \u201cBase\u201d model). "
    "This only happens once."
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def show_onboarding_dialog(
    parent_window: Gtk.Window,
    on_download: Callable[[], None],
    on_choose_model: Callable[[], None],
) -> None:
    """Present the first-launch onboarding dialog.

    The dialog explains TuxVox's privacy model and offers two
    actions:

    * **Download & Get Started** — downloads the default "Base" model
      and proceeds immediately.
    * **Choose a Different Model** — opens the model-selection flow so
      the user can pick an alternative before downloading.

    Args:
        parent_window: The GTK window to attach the dialog to.
        on_download: Callback invoked when the user chooses to download
            the default model.
        on_choose_model: Callback invoked when the user wants to pick a
            different model first.
    """
    logger.info("Presenting onboarding dialog.")

    dialog = Adw.AlertDialog.new(_WELCOME_HEADING, _WELCOME_BODY)

    # -- responses --------------------------------------------------------
    dialog.add_response("choose", "Choose a Different Model")
    dialog.add_response("download", "Download & Get Started")

    dialog.set_response_appearance("download", Adw.ResponseAppearance.SUGGESTED)
    dialog.set_default_response("download")
    dialog.set_close_response("choose")

    # -- response handler -------------------------------------------------
    def _on_response(_dialog: Adw.AlertDialog, response: str) -> None:
        """Dispatch to the appropriate callback based on the user's choice."""
        if response == "download":
            logger.info("User chose: Download & Get Started.")
            on_download()
        elif response == "choose":
            logger.info("User chose: Choose a Different Model.")
            on_choose_model()
        else:
            # Fallback — treat unknown / close as "choose"
            logger.debug("Onboarding dialog closed with response: %s", response)
            on_choose_model()

    dialog.connect("response", _on_response)
    dialog.present(parent_window)
