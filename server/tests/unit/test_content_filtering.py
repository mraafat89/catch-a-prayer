"""
Unit tests for content filtering and input validation.
Source: server/app/api/spots.py, server/app/api/suggestions.py
Rules: PRODUCT_REQUIREMENTS.md NFR-5.2
"""
import pytest
from fastapi import HTTPException

from app.api.spots import _check_content, _LAT_MIN, _LAT_MAX, _LNG_MIN, _LNG_MAX
from app.api.suggestions import (
    _validate_iqama_time,
    _validate_boolean_field,
    _accept_threshold,
    _expiry_days,
)
from app.schemas import SUGGESTION_IQAMA_FIELDS, SUGGESTION_FACILITY_FIELDS


# ─── Content Filtering (spots) ────────────────────────────────────────────────

class TestCheckContent:
    def test_none_passes(self):
        _check_content(None, "test")  # should not raise

    def test_empty_passes(self):
        _check_content("", "test")  # should not raise

    def test_normal_text_passes(self):
        _check_content("Islamic Center of Durham", "Name")

    def test_url_blocked(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_content("Visit http://spam.com", "Name")
        assert exc_info.value.status_code == 422

    def test_www_url_blocked(self):
        with pytest.raises(HTTPException):
            _check_content("Check www.spam.com", "Name")

    def test_allcaps_spam_blocked(self):
        with pytest.raises(HTTPException) as exc_info:
            _check_content("VISIT THE BEST MOSQUE NOW TODAY", "Name")
        assert exc_info.value.status_code == 422

    def test_some_caps_ok(self):
        # Fewer than 3 all-caps words should pass
        _check_content("Visit the BEST mosque", "Name")

    def test_arabic_text_passes(self):
        _check_content("مسجد النور", "Name")


# ─── Geographic Bounds ────────────────────────────────────────────────────────

class TestGeographicBounds:
    def test_nyc_within_bounds(self):
        assert _LAT_MIN <= 40.71 <= _LAT_MAX
        assert _LNG_MIN <= -74.00 <= _LNG_MAX

    def test_toronto_within_bounds(self):
        assert _LAT_MIN <= 43.65 <= _LAT_MAX
        assert _LNG_MIN <= -79.38 <= _LNG_MAX

    def test_london_outside_bounds(self):
        assert not (_LAT_MIN <= 51.50 <= _LAT_MAX and _LNG_MIN <= -0.12 <= _LNG_MAX)

    def test_africa_outside_bounds(self):
        assert not (_LAT_MIN <= 10.0 <= _LAT_MAX and _LNG_MIN <= 50.0 <= _LNG_MAX)


# ─── Suggestion Validators ────────────────────────────────────────────────────

class TestValidateIqamaTime:
    def test_valid_time(self):
        _validate_iqama_time("13:30")  # should not raise

    def test_midnight(self):
        _validate_iqama_time("00:00")

    def test_invalid_format(self):
        with pytest.raises(HTTPException):
            _validate_iqama_time("1330")

    def test_letters(self):
        with pytest.raises(HTTPException):
            _validate_iqama_time("abc")

    def test_out_of_range_hour(self):
        with pytest.raises(HTTPException):
            _validate_iqama_time("25:00")

    def test_out_of_range_minute(self):
        with pytest.raises(HTTPException):
            _validate_iqama_time("12:60")


class TestValidateBooleanField:
    def test_true(self):
        _validate_boolean_field("true")

    def test_false(self):
        _validate_boolean_field("false")

    def test_True_caps(self):
        _validate_boolean_field("True")

    def test_invalid(self):
        with pytest.raises(HTTPException):
            _validate_boolean_field("yes")

    def test_number(self):
        with pytest.raises(HTTPException):
            _validate_boolean_field("1")


# ─── Threshold & Expiry ──────────────────────────────────────────────────────

class TestAcceptThreshold:
    def test_iqama_field_threshold_is_2(self):
        for field in SUGGESTION_IQAMA_FIELDS:
            assert _accept_threshold(field) == 2

    def test_facility_field_threshold_is_3(self):
        for field in SUGGESTION_FACILITY_FIELDS:
            assert _accept_threshold(field) == 3


class TestExpiryDays:
    def test_iqama_expires_7_days(self):
        for field in SUGGESTION_IQAMA_FIELDS:
            assert _expiry_days(field) == 7

    def test_facility_expires_90_days(self):
        for field in SUGGESTION_FACILITY_FIELDS:
            assert _expiry_days(field) == 90
