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

"""Audio chime feedback for TuxVox experimental mode.

Plays short, non-blocking event sounds so the user gets clear cues for
dictation start/stop without needing to look at (or focus) a window.  This
is important for inline mode where any focus-stealing overlay would prevent
text from being typed into the target application.

Sounds are played via ``canberra-gtk-play`` (freedesktop event sounds) with
a fallback to various command-line audio players.  All
playback is fire-and-forget; failures are logged at debug level and never
raised.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Final

from tuxvox.logger import logger

# Logical chime -> freedesktop event id (canberra) and file basename.
_CHIME_EVENTS: Final[dict[str, str]] = {
    "start": "device-added",
    "stop": "device-removed",
    "done": "complete",
    "error": "dialog-error",
}

_SOUND_DIRS: Final[tuple[str, ...]] = ("/usr/share/sounds/freedesktop/stereo",)


def _find_sound_file(event_id: str) -> str | None:
    import os

    for base in _SOUND_DIRS:
        for ext in (".oga", ".wav"):
            path = os.path.join(base, f"{event_id}{ext}")
            if os.path.exists(path):
                return path
    return None


def play(chime: str) -> None:
    """Play a named chime without blocking the caller.

    Args:
        chime: One of ``'start'``, ``'stop'``, ``'done'``, ``'error'``.
    """
    event_id = _CHIME_EVENTS.get(chime)
    if event_id is None:
        logger.debug("Unknown chime '%s'", chime)
        return

    canberra = shutil.which("canberra-gtk-play")
    if canberra:
        if _spawn([canberra, "-i", event_id]):
            return

    sound_file = _find_sound_file(event_id)
    if sound_file:
        players = [
            ["paplay"],
            ["pw-play"],
            ["play", "-q"],
            ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet"],
            ["mpv", "--no-video", "--really-quiet"],
        ]

        # aplay can only safely play .wav files; .oga causes static screeching
        if sound_file.endswith(".wav"):
            players.append(["aplay", "-q"])

        for cmd_args in players:
            exe = shutil.which(cmd_args[0])
            if exe and _spawn([exe] + cmd_args[1:] + [sound_file]):
                return

    logger.debug("No audio backend available to play chime '%s'.", chime)


def _spawn(cmd: list[str]) -> bool:
    """Launch *cmd* detached; return ``True`` if it started."""
    try:
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        logger.debug("Failed to spawn chime command %s: %s", cmd, exc)
        return False
