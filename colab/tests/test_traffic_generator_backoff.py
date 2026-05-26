from __future__ import annotations

from traffic_generator import error_backoff_sec


def test_error_backoff_exponential_cap():
    assert error_backoff_sec(1) == 1.0
    assert error_backoff_sec(2) == 2.0
    assert error_backoff_sec(3) == 4.0
    assert error_backoff_sec(4) == 8.0
    assert error_backoff_sec(10) == 8.0
