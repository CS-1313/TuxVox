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

"""Unit tests for TuxVox core modules.

Tests cover configuration persistence, logger redaction, system info
recommendation logic, punctuation stripping, and data class construction.
These tests are designed to run without requiring a microphone, GPU, or
Whisper model download.
"""

import os
import re
import tempfile
from unittest import mock

import pytest

# ──────────────────────────────────────────────────────────────────────────────
# Logger tests
# ──────────────────────────────────────────────────────────────────────────────


class TestLogger:
    """Tests for tuxvox.logger module."""

    def test_setup_logging_is_idempotent(self):
        from tuxvox.logger import logger, setup_logging

        setup_logging()
        handler_count = len(logger.handlers)
        setup_logging()  # Second call should be no-op
        assert len(logger.handlers) == handler_count

    def test_get_full_log_returns_logged_messages(self):
        from tuxvox.logger import get_full_log, logger, setup_logging

        setup_logging()
        logger.info("Test message alpha")
        log_text = get_full_log()
        assert "Test message alpha" in log_text

    def test_get_redacted_log_redacts_transcription(self):
        from tuxvox.logger import get_redacted_log, logger, setup_logging

        setup_logging()
        logger.info('Transcription complete (2.1s): "Hello world, this is secret."')
        redacted = get_redacted_log()
        assert "[REDACTED]" in redacted
        assert "Hello world, this is secret." not in redacted

    def test_get_redacted_log_keeps_non_transcription_lines(self):
        from tuxvox.logger import get_redacted_log, logger, setup_logging

        setup_logging()
        logger.info("Model loaded in 1.5s")
        redacted = get_redacted_log()
        assert "Model loaded in 1.5s" in redacted


# ──────────────────────────────────────────────────────────────────────────────
# Config tests
# ──────────────────────────────────────────────────────────────────────────────


class TestConfig:
    """Tests for tuxvox.config module."""

    def test_defaults(self):
        from tuxvox.config import Config

        cfg = Config()
        cfg._path = "/tmp/nonexistent_tuxvox_test.json"
        cfg.load()
        assert cfg.get("model") == "base"
        assert cfg.get("punctuation") is True
        assert cfg.get("language") == "auto"

    def test_set_and_get(self):
        from tuxvox.config import Config

        cfg = Config()
        cfg.load()

        # Use a temp path so we don't clobber real config
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg._path = os.path.join(tmpdir, "settings.json")
            cfg.set("model", "small")
            assert cfg.get("model") == "small"

    def test_save_and_reload(self):
        from tuxvox.config import Config

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")

            # Save
            cfg1 = Config()
            cfg1._path = path
            cfg1.load()
            cfg1.set("model", "medium")
            cfg1.set("language", "fr")

            # Reload
            cfg2 = Config()
            cfg2._path = path
            cfg2.load()
            assert cfg2.get("model") == "medium"
            assert cfg2.get("language") == "fr"
            # Defaults should still be present for unset keys
            assert cfg2.get("punctuation") is True

    def test_corrupt_config_falls_back_to_defaults(self):
        from tuxvox.config import Config

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "settings.json")
            with open(path, "w") as f:
                f.write("NOT VALID JSON {{{{")

            cfg = Config()
            cfg._path = path
            cfg.load()
            assert cfg.get("model") == "base"


# ──────────────────────────────────────────────────────────────────────────────
# System info / recommendation tests
# ──────────────────────────────────────────────────────────────────────────────


class TestSystemInfo:
    """Tests for tuxvox.system_info module."""

    def test_model_info_has_all_expected_keys(self):
        from tuxvox.system_info import MODEL_INFO

        required_keys = {
            "name",
            "display_name",
            "internal_name",
            "speed_label",
            "accuracy_stars",
            "ram_usage",
            "description",
        }
        for model_key, info in MODEL_INFO.items():
            assert required_keys.issubset(info.keys()), f"Missing keys in {model_key}"

    def test_recommend_tiny_for_low_ram(self):
        from tuxvox.system_info import recommend_model

        model, explanation = recommend_model(ram_gb=3.0, cpu_cores=4)
        assert model == "tiny"

    def test_recommend_base_for_4gb_4cores(self):
        from tuxvox.system_info import recommend_model

        model, explanation = recommend_model(ram_gb=5.0, cpu_cores=4)
        assert model == "base"

    def test_recommend_base_for_8gb(self):
        from tuxvox.system_info import recommend_model

        model, explanation = recommend_model(ram_gb=8.0, cpu_cores=6)
        assert model == "base"

    def test_recommend_base_for_16gb_6cores(self):
        from tuxvox.system_info import recommend_model

        model, explanation = recommend_model(ram_gb=16.0, cpu_cores=6)
        assert model == "base"

    def test_recommend_small_for_32gb_8cores(self):
        from tuxvox.system_info import recommend_model

        model, explanation = recommend_model(ram_gb=32.0, cpu_cores=8)
        assert model == "small"

    def test_get_model_description(self):
        from tuxvox.system_info import get_model_description

        desc = get_model_description("base")
        assert isinstance(desc, str)
        assert len(desc) > 10

    def test_get_model_description_unknown(self):
        from tuxvox.system_info import get_model_description

        desc = get_model_description("nonexistent_model")
        assert "no description" in desc.lower() or "nonexistent" in desc.lower()

    @mock.patch("tuxvox.system_info.psutil")
    def test_get_system_info(self, mock_psutil):
        from tuxvox.system_info import get_system_info

        mock_psutil.virtual_memory.return_value.total = 16 * (1024**3)
        mock_psutil.cpu_count.return_value = 8

        info = get_system_info()
        assert info["ram_gb"] == pytest.approx(16.0, abs=0.2)
        assert info["cpu_cores"] == 8


# ──────────────────────────────────────────────────────────────────────────────
# Transcriber data class and punctuation tests
# ──────────────────────────────────────────────────────────────────────────────


class TestTranscriberDataClasses:
    """Tests for TranscriptionResult and WordInfo dataclasses."""

    def test_word_info_creation(self):
        from tuxvox.transcriber import WordInfo

        w = WordInfo(word="hello", start=0.0, end=0.5, probability=0.95)
        assert w.word == "hello"
        assert w.probability == 0.95

    def test_transcription_result_creation(self):
        from tuxvox.transcriber import TranscriptionResult, WordInfo

        result = TranscriptionResult(
            text="Hello world",
            words=[
                WordInfo("Hello", 0.0, 0.5, 0.9),
                WordInfo("world", 0.5, 1.0, 0.85),
            ],
            duration=1.5,
            language="en",
        )
        assert result.text == "Hello world"
        assert len(result.words) == 2
        assert result.language == "en"

    def test_transcription_result_defaults(self):
        from tuxvox.transcriber import TranscriptionResult

        result = TranscriptionResult(text="test")
        assert result.words == []
        assert result.duration == 0.0
        assert result.language == ""


class TestPunctuationStripping:
    """Tests for the punctuation stripping regex used by the transcriber."""

    def test_strip_punctuation(self):
        text = "Hello, world! How are you? I'm fine."
        stripped = re.sub(r"[^\w\s]", "", text)
        assert stripped == "Hello world How are you Im fine"

    def test_strip_preserves_words(self):
        text = "Dr. Smith said: 'It works!'"
        stripped = re.sub(r"[^\w\s]", "", text)
        assert "Dr" in stripped
        assert "Smith" in stripped
        assert "works" in stripped

    def test_no_punctuation_passthrough(self):
        text = "No punctuation here"
        stripped = re.sub(r"[^\w\s]", "", text)
        assert stripped == text
