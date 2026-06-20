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

"""Whisper transcription wrapper for TuxVox.

Implements a clean-slate lifecycle: each call to :meth:`Transcriber.transcribe`
loads the Whisper model, runs inference, and immediately unloads the model so
that memory is released between transcriptions.
"""

from __future__ import annotations

import gc
import re
import time
from dataclasses import dataclass, field
from typing import Callable


from tuxvox.logger import logger

# ------------------------------------------------------------------
# Data classes
# ------------------------------------------------------------------


@dataclass
class WordInfo:
    """Timing and confidence metadata for a single word.

    Attributes:
        word: The transcribed word text.
        start: Start time in seconds within the audio.
        end: End time in seconds within the audio.
        probability: Model confidence in ``[0, 1]``.
    """

    word: str
    start: float
    end: float
    probability: float


@dataclass
class TranscriptionResult:
    """Container for the output of a Whisper transcription run.

    Attributes:
        text: Full transcribed text.
        words: Per-word timing and confidence information.
        duration: Wall-clock time the transcription took, in seconds.
        language: Detected (or specified) language code.
    """

    text: str
    words: list[WordInfo] = field(default_factory=list)
    duration: float = 0.0
    language: str = ""


# ------------------------------------------------------------------
# Transcriber
# ------------------------------------------------------------------


class Transcriber:
    """Thin wrapper around OpenAI Whisper with clean-slate model lifecycle.

    Each call to :meth:`transcribe` loads the requested model, performs
    inference, and then explicitly deletes the model object and triggers
    garbage collection so that RAM is freed before the next run.

    Args:
        cache_dir: Optional directory used as ``download_root`` when
            loading Whisper models.  If ``None`` the Whisper default
            (``~/.cache/whisper``) is used.
    """

    def __init__(self, cache_dir: str | None = None) -> None:
        self._cache_dir: str | None = cache_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def transcribe(
        self,
        audio_path: str,
        model_name: str,
        language: str | None = None,
        word_timestamps: bool = True,
        punctuation: bool = True,
        download_callback: Callable[[int, int], None] | None = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file using the specified Whisper model.

        Args:
            audio_path: Path to the input audio file (WAV, MP3, …).
            model_name: Whisper model size, e.g. ``'tiny'``, ``'base'``,
                ``'small'``, ``'medium'``, ``'large'``.
            language: ISO-639-1 language code (e.g. ``'en'``).  Pass
                ``'auto'`` or ``None`` to let Whisper auto-detect.
            word_timestamps: Whether to request per-word timing data.
            punctuation: If ``False``, punctuation is stripped from the
                transcribed text and individual word strings.
            download_callback: Optional callback receiving (current, total)
                bytes as the model downloads.

        Returns:
            A :class:`TranscriptionResult` populated with text, word
            timings, elapsed duration, and detected language.

        Raises:
            MemoryError: If the system runs out of memory while loading
                the model or during inference.
            RuntimeError: On internal Whisper / PyTorch failures.
            Exception: Any other unexpected error is logged and
                re-raised.
        """
        import whisper  # type: ignore[import-untyped]  # noqa: E402

        original_tqdm = whisper.tqdm
        if download_callback:

            class CustomTqdm(original_tqdm):
                def update(self_tqdm, n=1):
                    super().update(n)
                    if self_tqdm.total:
                        download_callback(self_tqdm.n, self_tqdm.total)

            whisper.tqdm = CustomTqdm

        model = None

        try:
            # ---- Load model ------------------------------------------------
            logger.info("Loading Whisper model: %s...", model_name)
            t_load_start = time.monotonic()

            model = whisper.load_model(  # type: ignore[union-attr]
                model_name,
                device="cpu",
                download_root=self._cache_dir,
            )

            t_load_elapsed = time.monotonic() - t_load_start
            logger.info("Model loaded in %.2fs", t_load_elapsed)

            # ---- Transcribe -------------------------------------------------
            logger.info("Transcription started.")
            t_transcribe_start = time.monotonic()

            effective_language: str | None = (
                None if language is None or language == "auto" else language
            )

            result: dict = model.transcribe(  # type: ignore[assignment]
                audio_path,
                fp16=False,
                language=effective_language,
                word_timestamps=word_timestamps,
            )

            t_transcribe_elapsed = time.monotonic() - t_transcribe_start

            # ---- Extract text -----------------------------------------------
            text: str = result.get("text", "").strip()
            detected_language: str = result.get("language", language or "")

            # ---- Extract per-word info --------------------------------------
            words: list[WordInfo] = []
            for segment in result.get("segments", []):
                for w in segment.get("words", []):
                    words.append(
                        WordInfo(
                            word=w.get("word", "").strip(),
                            start=float(w.get("start", 0.0)),
                            end=float(w.get("end", 0.0)),
                            probability=float(w.get("probability", 0.0)),
                        )
                    )

            # ---- Optionally strip punctuation --------------------------------
            if not punctuation:
                text = re.sub(r"[^\w\s]", "", text)
                for wi in words:
                    wi.word = re.sub(r"[^\w\s]", "", wi.word)

            logger.info(
                'Transcription complete (%.2fs): "%s"',
                t_transcribe_elapsed,
                text[:120] + ("…" if len(text) > 120 else ""),
            )

            return TranscriptionResult(
                text=text,
                words=words,
                duration=t_transcribe_elapsed,
                language=detected_language,
            )

        except MemoryError:
            logger.critical(
                "Out of memory while using model '%s'. " "Try a smaller model or free system RAM.",
                model_name,
            )
            raise MemoryError(
                f"Insufficient memory to run Whisper model '{model_name}'. "
                "Please try a smaller model (e.g. 'tiny' or 'base')."
            ) from None

        except RuntimeError:
            logger.exception("Runtime error during transcription")
            raise

        except Exception:
            logger.exception("Unexpected error during transcription")
            raise

        finally:
            if download_callback:
                whisper.tqdm = original_tqdm
            # Always unload the model and reclaim memory.
            if model is not None:
                del model
            gc.collect()
            logger.info("Model unloaded. gc.collect() called.")
