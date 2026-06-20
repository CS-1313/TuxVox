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

"""TuxVox logging module.

Provides a configured logger with both console and in-memory output,
plus helpers to retrieve full or privacy-redacted log text.
"""

import logging
import re
from collections import deque

# ---------------------------------------------------------------------------
# Custom handler — stores formatted records in a bounded deque
# ---------------------------------------------------------------------------


class InMemoryHandler(logging.Handler):
    """A logging handler that stores log records in a fixed-size ring buffer.

    Attributes:
        buffer: A deque holding the most recent *maxlen* formatted log strings.
    """

    def __init__(self, maxlen: int = 500) -> None:
        """Initialise the handler with a bounded deque.

        Args:
            maxlen: Maximum number of log records to retain.
        """
        super().__init__()
        self.buffer: deque[str] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        """Format and append a log record to the buffer.

        Args:
            record: The log record emitted by the logging framework.
        """
        try:
            self.buffer.append(self.format(record))
        except Exception:  # noqa: BLE001
            self.handleError(record)


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

logger: logging.Logger = logging.getLogger("tuxvox")
"""Application-wide logger instance."""

_memory_handler: InMemoryHandler | None = None
"""Reference to the in-memory handler (populated by :func:`setup_logging`)."""

_LOG_FORMAT = "[%(asctime)s] %(message)s"
_LOG_DATEFMT = "%H:%M:%S"

# Regex for redacting transcription content.
# Matches lines like:  [HH:MM:SS] Transcription complete: "some text"
# and replaces the quoted payload with [REDACTED].
_REDACT_PATTERN = re.compile(
    r"(Transcription complete.*?:.*?)([\"'])(.+?)(\2)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def setup_logging(level: int = logging.DEBUG) -> None:
    """Configure the *tuxvox* logger with console and in-memory handlers.

    This function is idempotent — calling it more than once will not add
    duplicate handlers.

    Args:
        level: The minimum severity level to capture.
    """
    global _memory_handler  # noqa: PLW0603

    if _memory_handler is not None:
        # Already initialised.
        return

    logger.setLevel(level)

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

    # Console handler (stderr).
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    # In-memory ring-buffer handler.
    _memory_handler = InMemoryHandler(maxlen=500)
    _memory_handler.setFormatter(formatter)
    logger.addHandler(_memory_handler)

    logger.debug("Logging initialised.")


def get_full_log() -> str:
    """Return the complete in-memory log as a single string.

    Returns:
        All stored log records joined by newlines, or an empty string if
        logging has not been set up yet.
    """
    if _memory_handler is None:
        return ""
    return "\n".join(_memory_handler.buffer)


def get_redacted_log() -> str:
    """Return the in-memory log with transcription content redacted.

    Any line that contains ``Transcription complete`` will have the
    quoted text following the colon replaced with ``[REDACTED]``.

    Returns:
        The redacted log text, or an empty string if logging has not
        been set up yet.
    """
    if _memory_handler is None:
        return ""

    redacted_lines: list[str] = []
    for line in _memory_handler.buffer:
        redacted_lines.append(_REDACT_PATTERN.sub(r"\1\2[REDACTED]\4", line))

    return "\n".join(redacted_lines)
