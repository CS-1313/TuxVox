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

"""TuxVox system information and model recommendation module.

Detects hardware capabilities and suggests the most appropriate Whisper
model for the current machine.
"""

from __future__ import annotations

import psutil

from tuxvox.logger import logger

# ---------------------------------------------------------------------------
# Model metadata
# ---------------------------------------------------------------------------

MODEL_INFO: dict[str, dict[str, str]] = {
    "tiny": {
        "name": "Tiny",
        "display_name": "Tiny — ⚡ Fastest",
        "internal_name": "tiny",
        "speed_label": "Fastest",
        "accuracy_stars": "★★☆☆☆",
        "ram_usage": "~150 MB",
        "description": (
            "The fastest option — great if you want instant results and "
            "don't mind occasional small errors. Recommended for older "
            "or lower-powered computers."
        ),
    },
    "base": {
        "name": "Base",
        "display_name": "Base — 🚀 Fast",
        "internal_name": "base",
        "speed_label": "Fast",
        "accuracy_stars": "★★★☆☆",
        "ram_usage": "~300 MB",
        "description": (
            "A good balance of speed and accuracy for everyday dictation. "
            "Works well on modest hardware and handles clear speech reliably."
        ),
    },
    "small": {
        "name": "Small",
        "display_name": "Small — 🔄 Balanced",
        "internal_name": "small",
        "speed_label": "Balanced",
        "accuracy_stars": "★★★★☆",
        "ram_usage": "~500 MB",
        "description": (
            "Better accuracy with a moderate speed trade-off. "
            "Recommended for most users who want reliable transcriptions."
        ),
    },
    "medium": {
        "name": "Medium",
        "display_name": "Medium — 🐢 Slower",
        "internal_name": "medium",
        "speed_label": "Slower",
        "accuracy_stars": "★★★★★",
        "ram_usage": "~1.5 GB",
        "description": (
            "A highly accurate option, but takes longer to process. "
            "Best for computers with 8 GB of RAM or more."
        ),
    },
    "large": {
        "name": "Large",
        "display_name": "Large — 🐌 Slow",
        "internal_name": "large-v2",
        "speed_label": "Slow",
        "accuracy_stars": "★★★★★+",
        "ram_usage": "~3 GB",
        "description": (
            "Best overall accuracy. Requires a powerful computer with at "
            "least 16 GB of RAM. Transcription will take significantly "
            "longer than smaller models on CPU."
        ),
    },
    "large-v3": {
        "name": "Large V3",
        "display_name": "Large V3 — 🐌 Slow",
        "internal_name": "large-v3",
        "speed_label": "Slow",
        "accuracy_stars": "★★★★★+",
        "ram_usage": "~3 GB",
        "description": (
            "The most accurate model available — ideal for professional "
            "transcription or difficult audio. Requires a powerful computer "
            "with at least 16 GB of RAM. Transcription will take significantly "
            "longer than smaller models on CPU."
        ),
    },
}


# ---------------------------------------------------------------------------
# System detection
# ---------------------------------------------------------------------------


def get_system_info() -> dict[str, float | int]:
    """Detect basic hardware characteristics.

    Returns:
        A dict with keys ``ram_gb`` (float) and ``cpu_cores`` (int).
    """
    ram_gb = round(psutil.virtual_memory().total / (1024**3), 1)
    cpu_cores = psutil.cpu_count(logical=True) or 1

    logger.debug("System info: %.1f GB RAM, %d CPU cores.", ram_gb, cpu_cores)
    return {"ram_gb": ram_gb, "cpu_cores": cpu_cores}


# ---------------------------------------------------------------------------
# Model recommendation
# ---------------------------------------------------------------------------


def recommend_model(ram_gb: float, cpu_cores: int) -> tuple[str, str]:
    """Suggest a Whisper model based on available hardware.

    The recommendation prioritizes transcription speed and system responsiveness,
    capping the selection at the 'small' model.

    Args:
        ram_gb: Total physical RAM in gigabytes.
        cpu_cores: Number of logical CPU cores.

    Returns:
        A ``(model_name, explanation)`` tuple where *model_name* matches
        a key in :data:`MODEL_INFO`.
    """
    if ram_gb < 4 or cpu_cores < 4:
        model = "tiny"
        reason = (
            f"With {ram_gb:.1f} GB of RAM and {cpu_cores} cores, the Tiny model is the safest "
            "choice to avoid memory pressure and maintain responsiveness."
        )
    elif ram_gb < 16 or cpu_cores < 8:
        model = "base"
        reason = (
            f"{ram_gb:.1f} GB RAM and {cpu_cores} cores can comfortably "
            "run the Base model for fast and reliable transcriptions."
        )
    else:
        model = "small"
        reason = (
            f"High-end specifications ({ram_gb:.1f} GB RAM, {cpu_cores} cores) "
            "are well-suited for the Small model, balancing accuracy and fast performance."
        )

    logger.info("Recommended model: %s (%s).", model, reason)
    return model, reason


# ---------------------------------------------------------------------------
# Model descriptions
# ---------------------------------------------------------------------------


def get_model_description(model_name: str) -> str:
    """Return a human-readable description for a Whisper model.

    Args:
        model_name: A model key (e.g. ``'base'``, ``'large-v3'``).

    Returns:
        The plain-English description from :data:`MODEL_INFO`, or a
        fallback string if the model name is unrecognised.
    """
    info = MODEL_INFO.get(model_name)
    if info is None:
        logger.warning("Unknown model name: %r", model_name)
        return f"No description available for model '{model_name}'."
    return info["description"]
