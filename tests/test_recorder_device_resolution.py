"""Tests for Recorder device resolution and persistence across device index changes."""

import sys
from unittest.mock import MagicMock, patch

try:
    import sounddevice  # noqa: F401
except (OSError, ImportError):
    sys.modules["sounddevice"] = MagicMock()

from tuxvox.recorder import Recorder


def test_resolve_default_device():
    assert Recorder.resolve_device(None) is None
    assert Recorder.resolve_device("default") is None
    assert Recorder.resolve_device("Default") is None


def test_resolve_int_device():
    assert Recorder.resolve_device(3) == 3


@patch.object(Recorder, "list_devices")
def test_resolve_device_by_name(mock_list_devices):
    mock_list_devices.return_value = [
        {"index": 2, "name": "Internal Mic", "channels": 2},
        {"index": 5, "name": "USB Blue Yeti Microphone", "channels": 1},
    ]

    # Resolves device name to concrete input index 5
    assert Recorder.resolve_device("USB Blue Yeti Microphone") == 5
    assert Recorder.resolve_device("Internal Mic") == 2


@patch.object(Recorder, "list_devices")
def test_resolve_legacy_numeric_string(mock_list_devices):
    mock_list_devices.return_value = [
        {"index": 2, "name": "Internal Mic", "channels": 2},
    ]

    # If no device matches name "5", legacy numeric string "5" falls back to int 5
    assert Recorder.resolve_device("5") == 5


@patch.object(Recorder, "list_devices")
def test_resolve_unknown_string_device(mock_list_devices):
    mock_list_devices.return_value = [
        {"index": 2, "name": "Internal Mic", "channels": 2},
    ]

    # If not a number and not matching list_devices exact name, passes string unchanged to sounddevice
    assert Recorder.resolve_device("Some Unknown USB Device") == "Some Unknown USB Device"
