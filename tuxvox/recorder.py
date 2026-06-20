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

"""Audio recording module for TuxVox.

Provides the ``Recorder`` class which captures microphone audio via
``sounddevice`` and writes the result to a temporary WAV file using
``soundfile``.
"""

from __future__ import annotations

import gc
import os
import tempfile

import numpy as np
import sounddevice as sd
import soundfile as sf

from tuxvox.logger import logger


class Recorder:
    """Captures audio from a microphone and persists it as a WAV file.

    Typical usage::

        rec = Recorder()
        rec.start(sample_rate=16000)
        # ... user speaks ...
        wav_path = rec.stop()
        # wav_path now points to a temporary .wav file
        rec.cleanup()

    Attributes:
        _stream: The active ``sounddevice.InputStream``, or ``None``.
        _buffer: List of numpy audio chunks accumulated during recording.
        _sample_rate: Sample rate used for the current/last recording.
        _temp_path: Path to the last written temporary WAV file.
    """

    # ------------------------------------------------------------------
    # Class / static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def list_devices() -> list[dict]:
        """Return a list of available audio *input* devices.

        Each dictionary contains:
            - ``index``   – device index understood by sounddevice.
            - ``name``    – human-readable device name.
            - ``channels`` – maximum number of input channels.

        Returns:
            A list of dicts, one per input-capable device.
        """
        devices: list[dict] = []
        try:
            all_devs = sd.query_devices()
        except Exception:
            logger.exception("Failed to query audio devices")
            return devices

        for idx, dev in enumerate(all_devs):
            max_in: int = dev.get("max_input_channels", 0)  # type: ignore[union-attr]
            if max_in > 0:
                devices.append(
                    {
                        "index": idx,
                        "name": dev["name"],  # type: ignore[index]
                        "channels": max_in,
                    }
                )

        logger.debug("Found %d input device(s)", len(devices))
        return devices

    # ------------------------------------------------------------------
    # Instance lifecycle
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        """Initialise the recorder with empty state."""
        self._stream: sd.InputStream | None = None
        self._buffer: list[np.ndarray] = []
        self._sample_rate: int = 16_000
        self._temp_path: str | None = None

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def start(
        self,
        device: int | str | None = None,
        sample_rate: int = 16_000,
    ) -> None:
        """Begin capturing audio from the given device.

        Args:
            device: Device index (int), device name (str), or ``None`` /
                ``'default'`` to use the system default input device.
            sample_rate: Sampling rate in Hz.  Defaults to 16 000 Hz
                which is the rate expected by Whisper.

        Raises:
            RuntimeError: If a recording is already in progress.
            OSError: If the audio stream cannot be opened (e.g. no
                microphone connected).
        """
        if self._stream is not None:
            raise RuntimeError("Recording is already in progress — call stop() first.")

        # Normalise the device argument.
        if isinstance(device, str) and device.lower() == "default":
            device = None

        self._sample_rate = sample_rate
        self._buffer = []

        def _audio_callback(
            indata: np.ndarray,
            frames: int,  # noqa: ARG001
            time_info: object,  # noqa: ARG001
            status: sd.CallbackFlags,
        ) -> None:
            """Sounddevice callback – appends each chunk to the buffer."""
            if status:
                logger.warning("Audio callback status: %s", status)
            self._buffer.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
                device=device,
                callback=_audio_callback,
            )
            self._stream.start()
            logger.info(
                "Recording started (device=%s, rate=%d Hz)",
                device if device is not None else "default",
                sample_rate,
            )
        except Exception as exc:
            self._stream = None
            self._buffer = []
            logger.error("Failed to open audio stream: %s", exc)
            raise OSError(f"Could not open audio input device: {exc}") from exc

    def stop(self) -> str:
        """Stop recording and write captured audio to a temporary WAV file.

        Returns:
            Absolute path to the temporary ``.wav`` file.

        Raises:
            RuntimeError: If no recording is currently in progress.
            RuntimeError: If the recording buffer is empty (no audio
                captured).
        """
        if self._stream is None:
            raise RuntimeError("No recording in progress — call start() first.")

        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            logger.exception("Error while stopping audio stream")
        finally:
            self._stream = None

        if not self._buffer:
            raise RuntimeError("Recording buffer is empty — no audio was captured.")

        # Concatenate all chunks into a single array (shape: (N, 1)).
        audio_data: np.ndarray = np.concatenate(self._buffer, axis=0)
        duration_s = len(audio_data) / self._sample_rate
        logger.info(
            "Recording stopped — %.2f s of audio captured (%d samples)",
            duration_s,
            len(audio_data),
        )

        # Write to a temporary WAV file.
        self._temp_path = tempfile.mktemp(suffix=".wav", prefix="sf_audio_")
        try:
            sf.write(self._temp_path, audio_data, self._sample_rate)
            logger.info("Audio written to %s", self._temp_path)
        except Exception as exc:
            logger.error("Failed to write WAV file: %s", exc)
            raise

        return self._temp_path

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Delete the temporary WAV file and release memory.

        Safe to call multiple times; will not raise if the file has
        already been removed.
        """
        if self._temp_path and os.path.isfile(self._temp_path):
            try:
                os.remove(self._temp_path)
                logger.info("Deleted temp file: %s", self._temp_path)
            except OSError:
                logger.exception("Could not delete temp file: %s", self._temp_path)
        else:
            logger.debug("No temp file to delete (path=%s)", self._temp_path)

        self._temp_path = None
        self._buffer = []
        logger.debug("Buffer cleared")

        gc.collect()
        logger.debug("gc.collect() called")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        """Return ``True`` if the recorder is actively capturing audio."""
        return self._stream is not None

    @property
    def duration(self) -> float:
        """Return the current recording duration in seconds.

        Calculated from the accumulated buffer size and sample rate.
        Returns ``0.0`` when no audio has been captured.
        """
        if not self._buffer:
            return 0.0
        total_samples = sum(chunk.shape[0] for chunk in self._buffer)
        return total_samples / self._sample_rate
