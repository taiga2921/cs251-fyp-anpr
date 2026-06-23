"""Unit tests for plate normalization and validation."""

from __future__ import annotations

import pytest

from anpr import normalize_plate_text, validate_plate_text


class TestPlateNormalization:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("abc 1234", "ABC1234"),
            ("WXY-5678", "WXY5678"),
            ("pmk.8811", "PMK8811"),
            ("  jke_9900  ", "JKE9900"),
            ("a/b\\c1", "ABC1"),
        ],
    )
    def test_normalize_plate_text_strips_separators(self, raw, expected):
        assert normalize_plate_text(raw) == expected

    def test_validate_plate_text_accepts_malaysian_pattern(self):
        ok, reason = validate_plate_text("ABC1234")
        assert ok is True
        assert reason is None

    @pytest.mark.parametrize(
        ("plate", "reason_substring"),
        [
            ("", "empty"),
            ("AB1", "too short"),
            ("ABCDEFGHIJK", "too long"),
            ("1234", "no letters"),
            ("ABCD", "no digits"),
            ("ABCD12345", "does not match"),
        ],
    )
    def test_validate_plate_text_rejects_invalid(self, plate, reason_substring):
        ok, reason = validate_plate_text(plate)
        assert ok is False
        assert reason_substring in (reason or "")
