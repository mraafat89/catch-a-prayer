"""
Prayer Data Validation
========================
Islamic logic rules for validating scraped prayer times.
Every scrape MUST pass through these validators before saving to DB.

If scraped data fails ANY validation → fall back to calculated times.
Never store data you know is wrong.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def hhmm_to_minutes(val: str | None) -> Optional[int]:
    """Convert HH:MM to minutes since midnight."""
    if not val or ":" not in val or val.startswith("+"):
        return None
    try:
        parts = val.split(":")
        h, m = int(parts[0]), int(parts[1])
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h * 60 + m
    except (ValueError, IndexError):
        pass
    return None


def normalize_time_format(val: str) -> Optional[str]:
    """Normalize various time formats to HH:MM (24h)."""
    if not val:
        return None
    val = val.strip()

    # Already HH:MM 24h
    if re.match(r"^\d{2}:\d{2}$", val):
        return val

    # H:MM or HH:MM with AM/PM
    m = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm|AM|PM|a\.m\.|p\.m\.)?$", val)
    if m:
        h, mi, ampm = int(m.group(1)), int(m.group(2)), (m.group(3) or "").lower().replace(".", "")
        if ampm == "pm" and h < 12:
            h += 12
        elif ampm == "am" and h == 12:
            h = 0
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"

    return None


# ---------------------------------------------------------------------------
# Validation ranges from the spec
# ---------------------------------------------------------------------------

# Adhan ranges (minutes since midnight)
ADHAN_RANGES = {
    "fajr_adhan":    (180, 450),   # 03:00 - 07:30
    "sunrise":       (300, 480),   # 05:00 - 08:00
    "dhuhr_adhan":   (660, 810),   # 11:00 - 13:30
    "asr_adhan":     (810, 1110),  # 13:30 - 18:30
    "maghrib_adhan": (960, 1290),  # 16:00 - 21:30
    "isha_adhan":    (1050, 1380), # 17:30 - 23:00
}

# Iqama: min gap, max gap (minutes after adhan), and "must be before" field
IQAMA_LIMITS = {
    "fajr":    (5, 45, "sunrise"),
    "dhuhr":   (5, 45, "asr_adhan"),
    "asr":     (3, 30, "maghrib_adhan"),
    "maghrib": (2, 15, "isha_adhan"),
    "isha":    (5, 45, None),
}

# Minimum gaps between consecutive prayers (minutes)
MIN_GAPS = {
    ("fajr_adhan", "sunrise"):       30,
    ("sunrise", "dhuhr_adhan"):      180,
    ("dhuhr_adhan", "asr_adhan"):    90,
    ("asr_adhan", "maghrib_adhan"):  30,
    ("maghrib_adhan", "isha_adhan"): 30,
}

# Max deviation from calculated times (minutes)
MAX_CALC_DEVIATION = 60


# ---------------------------------------------------------------------------
# Core validation
# ---------------------------------------------------------------------------

class ValidationResult:
    def __init__(self):
        self.valid = True
        self.issues: list[dict] = []  # Each: {field, value, expected, issue, action}
        self.cleaned: dict = {}
        self.fell_back = False

    def log_issue(self, field: str, value: str | None, expected: str, issue: str, action: str):
        self.issues.append({
            "field": field, "value": value, "expected": expected,
            "issue": issue, "action": action,
        })

    def fail(self, field: str, value: str | None, expected: str, issue: str):
        self.valid = False
        self.log_issue(field, value, expected, issue, "fallback_to_calculated")


def validate_prayer_schedule(
    scraped: dict,
    calculated_times: Optional[dict] = None,
    mosque_name: str = "",
) -> ValidationResult:
    """
    Validate scraped prayer times against Islamic logic.

    Args:
        scraped: dict with keys like fajr_adhan, fajr_iqama, dhuhr_adhan, etc.
        calculated_times: optional dict of calculated adhan times for comparison
        mosque_name: for logging

    Returns:
        ValidationResult with .valid, .issues, .cleaned
    """
    result = ValidationResult()
    cleaned = {}

    # --- Step 1: Format validation (must be HH:MM) ---
    for key, val in scraped.items():
        if val is None:
            cleaned[key] = None
            continue
        val = str(val).strip()

        # Offsets like "+15" are valid for iqama
        if val.startswith("+") and "iqama" in key:
            try:
                offset = int(val.replace("+", "").strip())
                if 1 <= offset <= 90:
                    cleaned[key] = val
                else:
                    result.log_issue(key, val, "+1 to +90", f"Unreasonable iqama offset", "nulled")
                    cleaned[key] = None
            except ValueError:
                cleaned[key] = None
            continue

        # Special values
        if val.lower() == "sunset" and "maghrib" in key:
            cleaned[key] = val
            continue

        normalized = normalize_time_format(val)
        if normalized:
            cleaned[key] = normalized
        else:
            result.log_issue(key, val, "HH:MM format", f"Malformed time", "nulled")
            cleaned[key] = None

    # --- Step 2: Range validation ---
    for field, (min_m, max_m) in ADHAN_RANGES.items():
        val = cleaned.get(field)
        mins = hhmm_to_minutes(val)
        if mins is not None and not (min_m <= mins <= max_m):
            result.log_issue(
                field, val,
                f"{min_m // 60}:{min_m % 60:02d}-{max_m // 60}:{max_m % 60:02d}",
                f"Outside valid range", "nulled"
            )
            cleaned[field] = None

    # --- Step 3: Chronological order ---
    order = ["fajr_adhan", "sunrise", "dhuhr_adhan", "asr_adhan", "maghrib_adhan", "isha_adhan"]
    times = [(f, hhmm_to_minutes(cleaned.get(f))) for f in order]
    valid_times = [(f, t) for f, t in times if t is not None]

    for i in range(len(valid_times) - 1):
        f1, t1 = valid_times[i]
        f2, t2 = valid_times[i + 1]
        if t1 >= t2:
            result.fail(
                f"{f1}/{f2}", f"{cleaned.get(f1)}/{cleaned.get(f2)}",
                f"{f1} < {f2}",
                f"Chronological order violated — entire schedule suspect"
            )
            # Fall back to calculated for everything
            if calculated_times:
                result.cleaned = dict(calculated_times)
                result.fell_back = True
            return result

    # Check minimum gaps
    for (f1, f2), min_gap in MIN_GAPS.items():
        t1 = hhmm_to_minutes(cleaned.get(f1))
        t2 = hhmm_to_minutes(cleaned.get(f2))
        if t1 is not None and t2 is not None:
            gap = t2 - t1
            if gap < min_gap:
                result.log_issue(
                    f"{f1}->{f2}", f"{gap}min", f">= {min_gap}min",
                    f"Gap too small", "nulled"
                )
                # Null the later one (likely misassigned)
                cleaned[f2] = None

    # --- Step 4: Iqama validation ---
    for prayer, (min_gap, max_gap, before_field) in IQAMA_LIMITS.items():
        adhan_key = f"{prayer}_adhan"
        iqama_key = f"{prayer}_iqama"
        adhan_val = cleaned.get(adhan_key)
        iqama_val = cleaned.get(iqama_key)

        if not iqama_val or iqama_val.startswith("+"):
            continue

        adhan_m = hhmm_to_minutes(adhan_val)
        iqama_m = hhmm_to_minutes(iqama_val)

        if adhan_m is not None and iqama_m is not None:
            gap = iqama_m - adhan_m
            if gap < min_gap or gap > max_gap:
                result.log_issue(
                    iqama_key, iqama_val, f"adhan +{min_gap} to +{max_gap}min",
                    f"Iqama gap={gap}min", "nulled"
                )
                cleaned[iqama_key] = None

            # Must be before next prayer
            if before_field and cleaned.get(before_field):
                next_m = hhmm_to_minutes(cleaned[before_field])
                if next_m is not None and iqama_m >= next_m:
                    result.log_issue(
                        iqama_key, iqama_val, f"before {before_field}",
                        f"Iqama after next prayer", "nulled"
                    )
                    cleaned[iqama_key] = None

    # --- Step 5: Comparison with calculated ---
    if calculated_times:
        for prayer in ["fajr", "dhuhr", "asr", "maghrib", "isha"]:
            scraped_m = hhmm_to_minutes(cleaned.get(f"{prayer}_adhan"))
            calc_m = hhmm_to_minutes(calculated_times.get(f"{prayer}_adhan"))
            if scraped_m is not None and calc_m is not None:
                diff = abs(scraped_m - calc_m)
                if diff > MAX_CALC_DEVIATION:
                    result.log_issue(
                        f"{prayer}_adhan",
                        cleaned.get(f"{prayer}_adhan"),
                        f"within {MAX_CALC_DEVIATION}min of calculated ({calculated_times.get(f'{prayer}_adhan')})",
                        f"Deviates {diff}min from calculated",
                        "kept_with_warning"
                    )

    # --- Final: need at least 3 valid adhan times ---
    adhan_count = sum(1 for p in ["fajr", "dhuhr", "asr", "maghrib", "isha"]
                      if hhmm_to_minutes(cleaned.get(f"{p}_adhan")) is not None)
    if adhan_count < 3:
        result.fail("schedule", str(adhan_count), ">= 3 prayers", "Too few valid prayer times")
        if calculated_times:
            result.cleaned = dict(calculated_times)
            result.fell_back = True
        return result

    result.cleaned = cleaned
    return result


def validate_jumuah(times: list[str], dhuhr_adhan: str | None = None) -> ValidationResult:
    """Validate Jumuah prayer/khutba times."""
    result = ValidationResult()
    dhuhr_m = hhmm_to_minutes(dhuhr_adhan) if dhuhr_adhan else 750  # ~12:30 default
    valid = []

    for t in times:
        mins = hhmm_to_minutes(t)
        if mins is None:
            continue
        if not (690 <= mins <= 900):  # 11:30 AM - 3:00 PM
            result.log_issue("jumuah", t, "11:30-15:00", "Outside Jumuah range", "nulled")
            continue
        if dhuhr_m and mins < dhuhr_m - 30:  # Allow khutba 30 min before dhuhr
            result.log_issue("jumuah", t, f"after ~{dhuhr_adhan}", "Before Dhuhr", "nulled")
            continue
        valid.append(t)

    # Deduplicate and limit to 3 sessions
    valid = list(dict.fromkeys(valid))[:3]
    result.cleaned = {"jumuah": valid}
    return result


def validate_special_prayer(
    prayer_type: str,
    time_str: str,
    schedule: Optional[dict] = None,
    is_ramadan: bool = False,
) -> ValidationResult:
    """Validate special prayer times (Eid, Taraweeh, Tahajjud)."""
    result = ValidationResult()
    mins = hhmm_to_minutes(time_str)

    if mins is None:
        result.fail(prayer_type, time_str, "HH:MM", "Invalid format")
        return result

    schedule = schedule or {}

    if prayer_type == "taraweeh":
        if not is_ramadan:
            result.log_issue(prayer_type, time_str, "Ramadan only", "Taraweeh outside Ramadan", "kept_with_warning")
        isha_m = hhmm_to_minutes(schedule.get("isha_adhan", "20:30"))
        if isha_m and mins < isha_m:
            result.fail(prayer_type, time_str, f"after Isha ({schedule.get('isha_adhan')})", "Before Isha")

    elif prayer_type in ("eid_fitr", "eid_adha"):
        sunrise_m = hhmm_to_minutes(schedule.get("sunrise", "06:30"))
        dhuhr_m = hhmm_to_minutes(schedule.get("dhuhr_adhan", "12:30"))
        if sunrise_m and mins < sunrise_m:
            result.fail(prayer_type, time_str, f"after sunrise ({schedule.get('sunrise')})", "Before sunrise")
        elif dhuhr_m and mins > dhuhr_m:
            result.fail(prayer_type, time_str, f"before Dhuhr ({schedule.get('dhuhr_adhan')})", "After Dhuhr")

    elif prayer_type in ("tahajjud", "qiyam"):
        fajr_m = hhmm_to_minutes(schedule.get("fajr_adhan", "05:30"))
        if fajr_m and not (0 <= mins <= fajr_m or mins >= 23 * 60):
            result.fail(prayer_type, time_str, "midnight to Fajr", "Not in late night window")

    result.cleaned = {"time": time_str if result.valid else None}
    return result
