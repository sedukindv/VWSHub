"""Regression cases reproduced from the supplied hardware diagnostics."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub.devices import _ip_display, patch_config
from hub.failures import failure_details
from hub.media import live_failure_details
from hub.resources import configure


def bounded(value, label, lower, upper):
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(label)
    return value


def test_observed_xm_network_addresses_roundtrip_without_losing_unknown_fields():
    assert _ip_display("0x0A0611AC") == "172.17.6.10"
    assert _ip_display("0x320611AC") == "172.17.6.50"
    original = {"HostIP": "0x320611AC", "GateWay": "0x0A0611AC", "Private": [7, 8]}
    result = patch_config(original, "network", [{"path": ["HostIP"], "value": "172.17.6.10"}])
    assert result == {**original, "HostIP": "0x0A0611AC"}
    assert original["HostIP"] == "0x320611AC"


def test_manual_edit_with_implicit_profile_preserves_remaining_settings():
    current = configure({}, {"profile": "maximum"}, bounded)
    result = configure(current, {"max_live_streams": 9}, bounded)
    assert result == {**current, "profile": "custom", "max_live_streams": 9}
    assert current["profile"] == "maximum"


def test_failure_diagnostics_never_copy_connection_credentials():
    secret = "rtsp://admin:very-private@192.0.2.1/a?password=very-private"
    result = failure_details(output="401 Unauthorized " + secret)
    assert result["error_code"] == "authentication"
    assert "very-private" not in str(result) and "admin" not in str(result)
    assert failure_details(TimeoutError(secret))["error_code"] == "timeout"
    assert failure_details(output="Unrecognized option 'rw_timeout'")["error_code"] == "ffmpeg_option"


def test_missing_ffmpeg_diagnostic_file_does_not_break_error_response():
    assert live_failure_details({"directory": Path("/nonexistent-wvw-test")})["error_code"] == "device_operation"


def test_empty_resource_patch_and_manual_preset_value_do_not_reset_other_limits():
    current = {"profile": "maximum", "max_live_streams": 64, "max_archive_streams": 12,
               "archive_buffer_mb": 64, "archive_idle_seconds": 300, "ffmpeg_threads": 0}
    assert configure(current, {}, bounded) == current
    assert configure(current, {"max_live_streams": 128}, bounded) == {**current, "profile": "custom", "max_live_streams": 128}
