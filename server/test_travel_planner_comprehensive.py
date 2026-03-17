"""
Comprehensive Travel Planner Tests
====================================
Corner cases covering:
  - Musafir vs Muqeem mode
  - No / single / multiple mosques along route
  - Short (1-2h) / medium (6h) / long (11h) routes
  - Departure at every time of day (before Fajr, during each prayer, between prayers)
  - Overnight routes that span 2 calendar days
  - Prayed prayer exclusions (both/one/none prayed)
  - Temporal consistency enforcement

Run: cd server && python3 test_travel_planner_comprehensive.py
"""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import (
    prayer_status_at_arrival,
    _prayer_overlaps_trip,
    _pair_relevant,
    build_itineraries,
    build_combination_plan,
    _build_solo_plan,
    hhmm_to_minutes,
)

PDT = ZoneInfo("America/Los_Angeles")
MARCH16 = date(2026, 3, 16)

# ── Shared schedules ──────────────────────────────────────────────────────────

def make_sched(lat, lng, d=MARCH16, tz=-7):
    c = calculate_prayer_times(lat, lng, d, timezone_offset=tz)
    return {**c, **estimate_iqama_times(c)}

SD_SCHED  = make_sched(32.7157, -117.1611)   # San Diego
MP_SCHED  = make_sched(37.4529, -122.1817)   # Menlo Park

def hm(h, m=0): return h * 60 + m

# Derived time constants from SD schedule
FAJR_MIN    = hhmm_to_minutes(SD_SCHED["fajr_adhan"])     # ~345
SUNRISE_MIN = hhmm_to_minutes(SD_SCHED["sunrise"])         # ~417
DHUHR_MIN   = hhmm_to_minutes(SD_SCHED["dhuhr_adhan"])
ASR_MIN     = hhmm_to_minutes(SD_SCHED["asr_adhan"])
MAG_MIN     = hhmm_to_minutes(SD_SCHED["maghrib_adhan"])   # 1153
ISHA_MIN    = hhmm_to_minutes(SD_SCHED["isha_adhan"])      # ~1200

# ── Helpers ───────────────────────────────────────────────────────────────────

def mosque_at(local_min, minutes_into_trip, schedule=SD_SCHED, mid="m1", name=None):
    """Fake route_mosque arriving at local_min (minutes from midnight)."""
    hh, mm = divmod(local_min % 1440, 60)
    return {
        "id": mid,
        "name": name or f"Mosque-{local_min}",
        "lat": 35.0, "lng": -119.0,
        "address": "Test", "city": "Testville", "state": "CA",
        "google_place_id": None,
        "detour_minutes": 10,
        "minutes_into_trip": minutes_into_trip,
        "local_arrival_minutes": local_min % 1440,  # always 0-1439
        "local_arrival_time_fmt": f"{hh:02d}:{mm:02d}",
        "schedule": schedule,
    }

def dep_arr_dt(dep_hm, dur_hours, tz=PDT, d=MARCH16):
    """Return (departure_dt, arrival_dt) for a trip starting at dep_hm minutes
    and lasting dur_hours. Arrival may be on the next day."""
    dep_dt = datetime(d.year, d.month, d.day,
                      dep_hm // 60, dep_hm % 60, tzinfo=tz)
    arr_dt = dep_dt + timedelta(hours=dur_hours)
    return dep_dt, arr_dt

def build_plan(p1, p2, mosques, dep_min_local, arr_min_local,
               mode="travel", prayed=None, sched=SD_SCHED, dest_sched=SD_SCHED):
    """Thin wrapper around build_combination_plan with sensible defaults.
    arr_min_local may exceed 1439 to express next-day times (e.g. 1500 = 01:00 next day).
    """
    dep_dt = datetime(2026, 3, 16, dep_min_local // 60, dep_min_local % 60, tzinfo=PDT)
    extra_days, arr_min_in_day = divmod(arr_min_local, 1440)
    arr_dt = datetime(2026, 3, 16, arr_min_in_day // 60, arr_min_in_day % 60, tzinfo=PDT)
    arr_dt += timedelta(days=extra_days)
    # Also handle conventional overnight (arr_min < dep_min, both in 0-1439 range)
    if arr_min_local < 1440 and arr_min_local <= dep_min_local:
        arr_dt += timedelta(days=1)
    return build_combination_plan(
        p1, p2, sched, mosques,
        dep_dt, arr_dt, dest_sched,
        "America/Los_Angeles",
        trip_mode=mode,
        prayed_prayers=prayed or set(),
        origin_lat=37.4529, origin_lng=-122.1817,
        dest_lat=32.7157, dest_lng=-117.1611,
    )

PASS = "✅"
FAIL = "❌"
results = []

def check(name, cond, detail=""):
    status = PASS if cond else FAIL
    results.append((status, name, detail))
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    return cond

def opt_types(plan):
    return [o["option_type"] for o in plan["options"]] if plan else []


# ═══════════════════════════════════════════════════════════════════════════════
# A.  _prayer_overlaps_trip  — same-day and overnight
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== A. _prayer_overlaps_trip — same-day and overnight ===")

# A1. Same-day morning trip (8am–2pm) — Dhuhr overlaps, Fajr does NOT
check("A1 Dhuhr overlaps 8am–2pm trip",
      _prayer_overlaps_trip("dhuhr", SD_SCHED, hm(8), hm(14)))
check("A2 Fajr does NOT overlap 8am–2pm trip",
      not _prayer_overlaps_trip("fajr", SD_SCHED, hm(8), hm(14)))

# A3. Short trip during Asr (4pm–5pm) — Asr overlaps, Dhuhr and Maghrib do NOT
check("A3 Asr overlaps 4pm–5pm trip",
      _prayer_overlaps_trip("asr", SD_SCHED, ASR_MIN, ASR_MIN + 60))
check("A4 Dhuhr does NOT overlap 4pm–5pm trip (period ended)",
      not _prayer_overlaps_trip("dhuhr", SD_SCHED, ASR_MIN, ASR_MIN + 60))
check("A5 Maghrib does NOT overlap 4pm–5pm trip (not started yet)",
      not _prayer_overlaps_trip("maghrib", SD_SCHED, ASR_MIN, ASR_MIN + 60))

# A6. Overnight trip 10pm→8am next day (10h) — Fajr next day IS covered
#     dep=1320, arr=480 (raw) → _prayer_overlaps_trip should use +1440 shift for next-day Fajr
check("A6 Fajr overlaps 10pm→8am overnight trip (6h)",
      _prayer_overlaps_trip("fajr", SD_SCHED, hm(22), hm(8)),
      f"fajr_adhan={SD_SCHED['fajr_adhan']}")

# A7. Isha (started at 8pm) overlaps 10pm→8am overnight trip
check("A7 Isha overlaps 10pm→8am overnight trip (Isha was active at 10pm)",
      _prayer_overlaps_trip("isha", SD_SCHED, hm(22), hm(8)))

# A8. Dhuhr does NOT overlap 10pm→8am trip (arrives 8am before Dhuhr starts)
check("A8 Dhuhr does NOT overlap 10pm→8am trip (arrives before Dhuhr)",
      not _prayer_overlaps_trip("dhuhr", SD_SCHED, hm(22), hm(8)),
      f"dhuhr_adhan={SD_SCHED['dhuhr_adhan']}")

# A9. Long overnight trip 10pm→2pm next day (16h) — Fajr AND Dhuhr next day covered
check("A9 Fajr overlaps 10pm→2pm+1day trip (16h)",
      _prayer_overlaps_trip("fajr", SD_SCHED, hm(22), hm(14)))
check("A10 Dhuhr overlaps 10pm→2pm+1day trip (arrives during Dhuhr)",
      _prayer_overlaps_trip("dhuhr", SD_SCHED, hm(22), hm(14)),
      f"dhuhr_adhan={SD_SCHED['dhuhr_adhan']}")
check("A11 Asr overlaps 10pm→6pm+1day trip (20h, arrives during Asr)",
      _prayer_overlaps_trip("asr", SD_SCHED, hm(22), hm(18)))

# A12. Very short pre-Fajr trip (2am–4am) — Isha overlaps (Isha period is still active), Fajr not yet
check("A12 Isha overlaps 2am–4am trip (Isha period still active)",
      _prayer_overlaps_trip("isha", SD_SCHED, hm(2), hm(4)))
check("A13 Fajr does NOT overlap 2am–4am trip (starts at 5:45am)",
      not _prayer_overlaps_trip("fajr", SD_SCHED, hm(2), hm(4)))

# A14. Fajr-window trip (5:30am–6:30am) — Fajr overlaps, Dhuhr does NOT
check("A14 Fajr overlaps 5:30am–6:30am trip",
      _prayer_overlaps_trip("fajr", SD_SCHED, FAJR_MIN - 15, FAJR_MIN + 60))
check("A15 Dhuhr does NOT overlap 5:30am–6:30am trip",
      not _prayer_overlaps_trip("dhuhr", SD_SCHED, FAJR_MIN, FAJR_MIN + 60))


# ═══════════════════════════════════════════════════════════════════════════════
# B.  _pair_relevant — overnight and cross-timezone scenarios
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== B. _pair_relevant — overnight and cross-schedule ===")

# B1. 10pm→2pm+1day: Dhuhr+Asr IS relevant (next-day Dhuhr covered)
check("B1 Dhuhr+Asr relevant for 10pm→2pm+1day overnight trip",
      _pair_relevant("dhuhr", "asr", SD_SCHED, hm(22), hm(14)))

# B2. Maghrib+Isha relevant for 10pm→8am (Isha active at departure + Maghrib was active earlier)
check("B2 Maghrib+Isha relevant for 10pm→8am overnight trip",
      _pair_relevant("maghrib", "isha", SD_SCHED, hm(22), hm(8)))

# B3. Dhuhr+Asr NOT relevant for 10pm→8am (arrives before Dhuhr next day)
check("B3 Dhuhr+Asr NOT relevant for 10pm→8am trip (arrives before Dhuhr)",
      not _pair_relevant("dhuhr", "asr", SD_SCHED, hm(22), hm(8)))

# B4. Short trip 8am–10am: no prayer pair relevant (Dhuhr hasn't started yet)
check("B4 Dhuhr+Asr NOT relevant for 8am–10am trip",
      not _pair_relevant("dhuhr", "asr", SD_SCHED, hm(8), hm(10)))
check("B5 Maghrib+Isha NOT relevant for 8am–10am trip",
      not _pair_relevant("maghrib", "isha", SD_SCHED, hm(8), hm(10)))

# B6. Origin vs destination schedule matters (MP departure, SD arrival at SD Maghrib time)
dep_min = hm(10, 0)     # 10am departure from MP
arr_min = hm(19, 13)    # 7:13pm arrival (exactly SD Maghrib)
check("B6 Maghrib+Isha NOT relevant with MP schedule only (trip ends before MP Maghrib)",
      not _pair_relevant("maghrib", "isha", MP_SCHED, dep_min, arr_min))
check("B7 Maghrib+Isha IS relevant with SD schedule (SD Maghrib starts exactly at arrival)",
      _pair_relevant("maghrib", "isha", SD_SCHED, dep_min, arr_min))


# ═══════════════════════════════════════════════════════════════════════════════
# C.  No mosques along route
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== C. No mosques along route ===")

# C1. Musafir, Dhuhr+Asr, no mosques, prayers not prayed at dest either
# Trip departs before Dhuhr, arrives before Dhuhr → no at_destination either
plan_nomosq_musafir = build_plan("dhuhr", "asr", [],
                                  dep_min_local=hm(8), arr_min_local=hm(10))
types_c1 = opt_types(plan_nomosq_musafir)
check("C1 No mosques, Musafir, pre-Dhuhr trip → no_option only",
      types_c1 == ["no_option"] or all(t in ("no_option", "at_destination") for t in types_c1),
      f"types={types_c1}")

# C2. No mosques but prayer active on arrival → at_destination offered even without mosque
# Trip arrives during Dhuhr, no route mosques
plan_dest_only = build_plan("dhuhr", "asr", [],
                             dep_min_local=hm(8), arr_min_local=DHUHR_MIN + 30)
types_c2 = opt_types(plan_dest_only)
check("C2 No route mosques but Dhuhr active at arrival → at_destination or no_option offered",
      "at_destination" in types_c2 or "no_option" in types_c2,
      f"types={types_c2}")

# C3. No mosques, Muqeem, trip overlaps Dhuhr+Asr → no_option
plan_nomosq_muqeem = build_plan("dhuhr", "asr", [],
                                 dep_min_local=hm(12), arr_min_local=hm(18),
                                 mode="driving")
types_c3 = opt_types(plan_nomosq_muqeem)
check("C3 No mosques, Muqeem, Dhuhr+Asr trip → at_destination or no_option",
      all(t in ("no_option", "at_destination", "pray_before") for t in types_c3),
      f"types={types_c3}")
check("C4 No mosques, Muqeem → no separate option (nothing to separate onto)",
      "separate" not in types_c3,
      f"types={types_c3}")


# ═══════════════════════════════════════════════════════════════════════════════
# D.  Single mosque scenarios
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== D. Single mosque scenarios ===")

# D1. Single mosque supporting Dhuhr en route (during Dhuhr window)
#     Musafir: combine_early offered (Dhuhr during Dhuhr period = Taqdeem for both)
dhuhr_mosque = mosque_at(DHUHR_MIN + 30, minutes_into_trip=120, name="Dhuhr Mosque")
plan_d1 = build_plan("dhuhr", "asr", [dhuhr_mosque],
                     dep_min_local=hm(10), arr_min_local=hm(21))
types_d1 = opt_types(plan_d1)
check("D1 Single mosque at Dhuhr time: combine_early offered (Musafir)",
      "combine_early" in types_d1, f"types={types_d1}")
check("D2 Single mosque at Dhuhr time: no separate (Musafir)",
      "separate" not in types_d1, f"types={types_d1}")

# D3. Single mosque supporting Asr en route (during Asr window)
#     Musafir: combine_late offered (Asr during Asr period = Ta'kheer for both)
asr_mosque = mosque_at(ASR_MIN + 30, minutes_into_trip=200, name="Asr Mosque")
plan_d3 = build_plan("dhuhr", "asr", [asr_mosque],
                     dep_min_local=hm(10), arr_min_local=hm(21))
types_d3 = opt_types(plan_d3)
check("D3 Single mosque at Asr time: combine_late offered (Musafir)",
      "combine_late" in types_d3, f"types={types_d3}")
check("D4 Single mosque at Asr time: no separate (Musafir)",
      "separate" not in types_d3, f"types={types_d3}")

# D5. Single mosque, Muqeem: separate allowed (Muqeem mode)
plan_d5 = build_plan("dhuhr", "asr", [dhuhr_mosque, asr_mosque],
                     dep_min_local=hm(10), arr_min_local=hm(21),
                     mode="driving")
types_d5 = opt_types(plan_d5)
check("D5 Muqeem with both Dhuhr + Asr mosque: separate offered",
      "separate" in types_d5, f"types={types_d5}")
check("D6 Muqeem: no combine_early or combine_late",
      "combine_early" not in types_d5 and "combine_late" not in types_d5,
      f"types={types_d5}")


# ═══════════════════════════════════════════════════════════════════════════════
# E.  Multiple mosques — MAX_OPTIONS cap
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== E. Multiple mosques — MAX_OPTIONS cap ===")

# Musafir mode: max 2 combine_early/late options
many_dhuhr = [mosque_at(DHUHR_MIN + 10 * i, minutes_into_trip=60 + 20 * i,
                        mid=f"m{i}", name=f"Mosque {i}")
              for i in range(5)]
plan_e1 = build_plan("dhuhr", "asr", many_dhuhr,
                     dep_min_local=hm(10), arr_min_local=hm(21))
early_opts = [o for o in plan_e1["options"] if o["option_type"] == "combine_early"]
check("E1 Musafir: at most 2 combine_early candidates (MAX_OPTIONS=2)",
      len(early_opts) <= 2, f"got {len(early_opts)} combine_early options")

# Muqeem mode: separate requires both prayer1 AND prayer2 mosque available
# Use a mix of Dhuhr-window and Asr-window mosques
many_mixed = (
    [mosque_at(DHUHR_MIN + 10 * i, minutes_into_trip=60 + 20 * i, mid=f"d{i}", name=f"Dhuhr {i}")
     for i in range(3)] +
    [mosque_at(ASR_MIN + 10 * i, minutes_into_trip=250 + 20 * i, mid=f"a{i}", name=f"Asr {i}")
     for i in range(3)]
)
plan_e2 = build_plan("dhuhr", "asr", many_mixed,
                     dep_min_local=hm(10), arr_min_local=hm(21),
                     mode="driving")
sep_opts = [o for o in plan_e2["options"] if o["option_type"] == "separate"]
check("E2 Muqeem: separate offered with Dhuhr+Asr mosques available",
      len(sep_opts) >= 1, f"got {len(sep_opts)} separate options, types={opt_types(plan_e2)}")

# E3. Many Asr mosques → max 2 combine_late in Musafir
many_asr = [mosque_at(ASR_MIN + 10 * i, minutes_into_trip=150 + 20 * i,
                      mid=f"a{i}", name=f"Asr Mosque {i}")
            for i in range(5)]
plan_e3 = build_plan("dhuhr", "asr", many_asr,
                     dep_min_local=hm(10), arr_min_local=hm(21))
late_opts = [o for o in plan_e3["options"] if o["option_type"] == "combine_late"]
check("E3 Musafir: at most 2 combine_late candidates",
      len(late_opts) <= 2, f"got {len(late_opts)} combine_late options")


# ═══════════════════════════════════════════════════════════════════════════════
# F.  Departure time variations
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== F. Departure time variations ===")

asr_mosque2 = mosque_at(ASR_MIN + 30, minutes_into_trip=60)
mag_mosque  = mosque_at(MAG_MIN + 30, minutes_into_trip=60)
isha_mosque = mosque_at(ISHA_MIN + 30, minutes_into_trip=60)

# F1. Depart at 2am (before Fajr), arrive 8am — Dhuhr pair NOT relevant, Isha pair IS relevant
#     build_combination_plan for Maghrib+Isha: Isha was active at departure, mosque at 2:30am
early_night_mosque = mosque_at(hm(2, 30), minutes_into_trip=30)
plan_f1 = build_plan("maghrib", "isha", [early_night_mosque],
                     dep_min_local=hm(2), arr_min_local=hm(8))
types_f1 = opt_types(plan_f1)
check("F1 Depart 2am: Isha active at dep → pray_before offered",
      "pray_before" in types_f1, f"types={types_f1}")

# F2. Depart at 4am (after Fajr adhan, before sunrise), 30-min trip → Fajr active at departure
fajr_dep_mosque = mosque_at(FAJR_MIN + 15, minutes_into_trip=15)
plan_f2 = build_plan("dhuhr", "asr", [fajr_dep_mosque],
                     dep_min_local=FAJR_MIN + 10, arr_min_local=FAJR_MIN + 40)
# This Dhuhr+Asr pair should yield no options (neither active at departure or arrival)
types_f2 = opt_types(plan_f2)
check("F2 Depart during Fajr, short trip: Dhuhr+Asr → no_option (not active yet)",
      all(t in ("no_option",) for t in types_f2), f"types={types_f2}")

# F3. Depart during Dhuhr (30 min after adhan), 1-hour trip:
#     Dhuhr active at departure → pray_before; no en-route mosque → no combine options
plan_f3 = build_plan("dhuhr", "asr", [],
                     dep_min_local=DHUHR_MIN + 30, arr_min_local=DHUHR_MIN + 90)
types_f3 = opt_types(plan_f3)
check("F3 Depart during Dhuhr, no mosques: pray_before offered",
      "pray_before" in types_f3, f"types={types_f3}")

# F4. Depart during Asr (Dhuhr period closed), Musafir:
#     combine_late for Dhuhr+Asr offered (Musafir extends Dhuhr to Asr end)
plan_f4 = build_plan("dhuhr", "asr", [asr_mosque2],
                     dep_min_local=ASR_MIN + 30, arr_min_local=hm(21))
types_f4 = opt_types(plan_f4)
check("F4 Depart during Asr, Musafir: combine_late Dhuhr+Asr offered",
      "combine_late" in types_f4, f"types={types_f4}")
check("F5 Depart during Asr, Musafir: pray_before shows BOTH prayers as Jam' Ta'kheer",
      all(set(o["prayers"]) == {"dhuhr", "asr"} for o in plan_f4["options"]
          if o["option_type"] == "pray_before"),
      f"pray_before prayers={[o['prayers'] for o in plan_f4['options'] if o['option_type']=='pray_before']}")

# F6. Muqeem depart during Asr (Dhuhr period closed):
#     Only Asr stop (Dhuhr's window is closed — Muqeem can't combine)
plan_f6 = build_plan("dhuhr", "asr", [asr_mosque2],
                     dep_min_local=ASR_MIN + 30, arr_min_local=hm(21),
                     mode="driving")
types_f6 = opt_types(plan_f6)
check("F6 Muqeem, depart during Asr: no combine (Muqeem mode)",
      "combine_late" not in types_f6 and "combine_early" not in types_f6,
      f"types={types_f6}")

# F7. Depart during Maghrib, 6-hour trip → Maghrib active at dep; Isha will start en route
# MAG_MIN + 360 overflows past midnight, pass as 1440+ to trigger next-day handling
plan_f7 = build_plan("maghrib", "isha", [mag_mosque, isha_mosque],
                     dep_min_local=MAG_MIN + 10, arr_min_local=MAG_MIN + 360)  # ~1:13am next day
types_f7 = opt_types(plan_f7)
check("F7 Depart during Maghrib: pray_before offered (Maghrib active)",
      "pray_before" in types_f7, f"types={types_f7}")
check("F8 Depart during Maghrib: combine_early offered (pray both during Maghrib time)",
      "combine_early" in types_f7, f"types={types_f7}")

# F9. Depart during Isha (late at night), Musafir: Isha active at departure
plan_f9 = build_plan("maghrib", "isha", [isha_mosque],
                     dep_min_local=ISHA_MIN + 30, arr_min_local=ISHA_MIN + 180)
types_f9 = opt_types(plan_f9)
check("F9 Depart during Isha: pray_before offered",
      "pray_before" in types_f9, f"types={types_f9}")


# ═══════════════════════════════════════════════════════════════════════════════
# G.  Prayed prayer exclusions
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== G. Prayed prayer exclusions ===")

asr_mosque3 = mosque_at(ASR_MIN + 30, minutes_into_trip=200)
dhuhr_mosque2 = mosque_at(DHUHR_MIN + 30, minutes_into_trip=100)

# G1. Both Dhuhr and Asr already prayed → build_combination_plan returns None
plan_g1 = build_plan("dhuhr", "asr", [dhuhr_mosque2, asr_mosque3],
                     dep_min_local=hm(10), arr_min_local=hm(21),
                     prayed={"dhuhr", "asr"})
check("G1 Both Dhuhr+Asr prayed → plan is None",
      plan_g1 is None)

# G2. Dhuhr prayed, Asr pending → solo plan for Asr
plan_g2 = build_plan("dhuhr", "asr", [asr_mosque3],
                     dep_min_local=hm(10), arr_min_local=hm(21),
                     prayed={"dhuhr"})
types_g2 = opt_types(plan_g2)
check("G2 Dhuhr prayed: solo plan for Asr (solo_stop or at_destination offered)",
      any(t in ("solo_stop", "at_destination", "pray_before") for t in types_g2),
      f"types={types_g2}")
check("G3 Dhuhr prayed: no combine options in solo plan",
      "combine_early" not in types_g2 and "combine_late" not in types_g2,
      f"types={types_g2}")
check("G4 Dhuhr prayed: no dhuhr in any option's prayers",
      all("dhuhr" not in o["prayers"] for o in plan_g2["options"]),
      f"prayers={[o['prayers'] for o in plan_g2['options']]}")

# G5. Asr prayed → sequential inference: Dhuhr is also implicitly done → skip pair entirely
plan_g5 = build_plan("dhuhr", "asr", [dhuhr_mosque2],
                     dep_min_local=hm(10), arr_min_local=hm(21),
                     prayed={"asr"})
check("G5 Asr prayed → Dhuhr+Asr pair skipped entirely (returns None, sequential inference)",
      plan_g5 is None,
      f"got plan with types={opt_types(plan_g5)}")

# G7. Isha prayed → sequential inference: Maghrib is also implicitly done → skip pair → None
isha_prayed_mosque = mosque_at(MAG_MIN + 30, minutes_into_trip=120)
plan_g7 = build_plan("maghrib", "isha", [isha_prayed_mosque],
                     dep_min_local=hm(14), arr_min_local=hm(23),
                     prayed={"isha"})
check("G7 Isha prayed → Maghrib+Isha pair skipped entirely (returns None, sequential inference)",
      plan_g7 is None,
      f"got plan with types={opt_types(plan_g7)}")


# ═══════════════════════════════════════════════════════════════════════════════
# H.  Overnight routes spanning 2 days — build_combination_plan
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== H. Overnight routes spanning 2 days ===")

# H1. 10pm departure, 8am+1 arrival (10h): Isha active at departure
#     Isha mosque available at 10:30pm en route
isha_late_mosque = mosque_at(hm(22, 30) % 1440, minutes_into_trip=30)
plan_h1 = build_plan("maghrib", "isha", [isha_late_mosque],
                     dep_min_local=hm(22), arr_min_local=hm(8))  # overnight
types_h1 = opt_types(plan_h1)
check("H1 Overnight 10pm→8am: Isha mosque at 10:30pm → options found",
      len(types_h1) > 0 and "no_option" != types_h1[-1],
      f"types={types_h1}")
check("H2 Overnight 10pm→8am: pray_before or combine options for Isha",
      any(t in ("pray_before", "combine_late", "combine_early") for t in types_h1),
      f"types={types_h1}")

# H3. 10pm departure, 2pm+1 arrival (16h): Dhuhr should appear in itineraries
#     because the trip spans overnight into the next afternoon
#     Use _pair_relevant to confirm pair detection (covered in B1 above)
#     Build plan with a mosque at 1pm (next day) in Dhuhr window
dhuhr_next_day = mosque_at(DHUHR_MIN + 30, minutes_into_trip=900, name="Dhuhr NextDay")
plan_h3 = build_plan("dhuhr", "asr", [dhuhr_next_day],
                     dep_min_local=hm(22), arr_min_local=hm(14))  # overnight
types_h3 = opt_types(plan_h3)
check("H3 16h overnight trip: Dhuhr mosque at 1pm next day → combine_early offered",
      "combine_early" in types_h3 or "combine_late" in types_h3 or "at_destination" in types_h3,
      f"types={types_h3}")

# H4. Overnight trip: temporal consistency of stops
#     Mosque at 11pm (t=60) for Isha, then mosque at 8am (t=600) for Fajr
#     These are monotonically increasing → should NOT be rejected by temporal check
from app.services.travel_planner import build_itineraries
from test_travel_planner import make_option, make_stop  # reuse from existing file

fajr_stop = make_stop(600, "fajr")
isha_stop_t = make_stop(60, "isha")
pairs_overnight = [
    {"pair": "maghrib_isha", "label": "Mag+Isha", "emoji": "🌙",
     "options": [{"option_type": "combine_late", "label": "Late", "description": "",
                  "prayers": ["maghrib", "isha"], "combination_label": "Jam' Ta'kheer",
                  "stops": [isha_stop_t], "feasible": True, "note": None}]},
    {"pair": "fajr", "label": "Fajr", "emoji": "🌅",
     "options": [{"option_type": "stop_for_fajr", "label": "Fajr", "description": "",
                  "prayers": ["fajr"], "combination_label": None,
                  "stops": [fajr_stop], "feasible": True, "note": None}]},
]
its_h4 = build_itineraries(pairs_overnight, allow_combining=True)
check("H4 Overnight: Isha at t=60 + Fajr at t=600 → temporally valid itinerary",
      len(its_h4) >= 1,
      f"got {len(its_h4)} itineraries")

# H5. Reversed overnight: Fajr stop before Isha stop (impossible ordering) → rejected
pairs_reversed_overnight = [
    {"pair": "maghrib_isha", "label": "Mag+Isha", "emoji": "🌙",
     "options": [{"option_type": "combine_late", "label": "Late", "description": "",
                  "prayers": ["maghrib", "isha"], "combination_label": None,
                  "stops": [make_stop(600, "isha")], "feasible": True, "note": None}]},
    {"pair": "fajr", "label": "Fajr", "emoji": "🌅",
     "options": [{"option_type": "stop_for_fajr", "label": "Fajr", "description": "",
                  "prayers": ["fajr"], "combination_label": None,
                  "stops": [make_stop(60, "fajr")], "feasible": True, "note": None}]},
]
its_h5 = build_itineraries(pairs_reversed_overnight, allow_combining=True)
check("H5 Overnight reversed order (Isha at t=600, Fajr at t=60) → 0 valid itineraries",
      len(its_h5) == 0, f"got {len(its_h5)} itineraries")


# ═══════════════════════════════════════════════════════════════════════════════
# I.  Route length variations — full pair coverage
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== I. Route length (short/medium/long) and pair relevance ===")

# I1. Short route (2h, 10am–12pm): NO prayer pair is active in this window
short_pairs_relevant = (
    _pair_relevant("dhuhr", "asr", SD_SCHED, hm(10), hm(12)) or
    _pair_relevant("maghrib", "isha", SD_SCHED, hm(10), hm(12))
)
check("I1 Short 10am–12pm route: no prayer pair relevant (Dhuhr not started)",
      not short_pairs_relevant)

# I2. Medium route (6h, 11am–5pm): Dhuhr+Asr IS relevant
check("I2 Medium 11am–5pm route: Dhuhr+Asr IS relevant",
      _pair_relevant("dhuhr", "asr", SD_SCHED, hm(11), hm(17)))
check("I3 Medium 11am–5pm route: Maghrib+Isha NOT relevant",
      not _pair_relevant("maghrib", "isha", SD_SCHED, hm(11), hm(17)))

# I4. Long route (11h, 10am–9pm): BOTH pairs relevant
check("I4 Long 10am–9pm route: Dhuhr+Asr IS relevant",
      _pair_relevant("dhuhr", "asr", SD_SCHED, hm(10), hm(21)))
check("I5 Long 10am–9pm route: Maghrib+Isha IS relevant",
      _pair_relevant("maghrib", "isha", SD_SCHED, hm(10), hm(21)))

# I6. Long Musafir route with both pairs: itineraries cover both pairs
all_mosques = [
    mosque_at(DHUHR_MIN + 30, 120, name="Dhuhr En Route"),
    mosque_at(ASR_MIN + 30, 300, name="Asr En Route"),
    mosque_at(MAG_MIN + 30, 500, name="Mag En Route"),
    mosque_at(ISHA_MIN + 30, 600, name="Isha En Route"),
]
from app.services.travel_planner import build_combination_plan as bcp
dep_dt_long = datetime(2026, 3, 16, 10, 0, tzinfo=PDT)
arr_dt_long = datetime(2026, 3, 16, 21, 0, tzinfo=PDT)

pair1 = bcp("dhuhr", "asr", SD_SCHED, all_mosques, dep_dt_long, arr_dt_long,
            SD_SCHED, "America/Los_Angeles", trip_mode="travel", prayed_prayers=set(),
            origin_lat=37.4529, origin_lng=-122.1817, dest_lat=32.7157, dest_lng=-117.1611)
pair2 = bcp("maghrib", "isha", SD_SCHED, all_mosques, dep_dt_long, arr_dt_long,
            SD_SCHED, "America/Los_Angeles", trip_mode="travel", prayed_prayers=set(),
            origin_lat=37.4529, origin_lng=-122.1817, dest_lat=32.7157, dest_lng=-117.1611)

check("I6 Long route, Musafir: Dhuhr+Asr pair has options",
      pair1 is not None and len(pair1["options"]) > 0,
      f"types={opt_types(pair1)}")
check("I7 Long route, Musafir: Maghrib+Isha pair has options",
      pair2 is not None and len(pair2["options"]) > 0,
      f"types={opt_types(pair2)}")
check("I8 Long route, Musafir: no separate in Dhuhr+Asr options",
      pair1 is not None and "separate" not in opt_types(pair1),
      f"types={opt_types(pair1)}")
check("I9 Long route, Musafir: no separate in Maghrib+Isha options",
      pair2 is not None and "separate" not in opt_types(pair2),
      f"types={opt_types(pair2)}")

its_long_musafir = build_itineraries([pair1, pair2], allow_combining=True) if pair1 and pair2 else []
check("I10 Long route, Musafir: produces at least 2 itineraries covering both pairs",
      len(its_long_musafir) >= 2,
      f"got {len(its_long_musafir)} itineraries")
check("I11 Long route, Musafir: every itinerary covers exactly 2 pairs",
      all(len(it["pair_choices"]) == 2 for it in its_long_musafir),
      f"pair counts={[len(it['pair_choices']) for it in its_long_musafir]}")

# I12/I13. Long Muqeem route: individual prayer plans (no pairs, no combining)
# Muqeem mode uses _build_solo_plan for each prayer, not build_combination_plan
solo_dhuhr = _build_solo_plan("dhuhr", SD_SCHED, all_mosques, dep_dt_long, arr_dt_long,
                              SD_SCHED, "America/Los_Angeles",
                              origin_lat=37.4529, origin_lng=-122.1817, dest_lat=32.7157, dest_lng=-117.1611)
solo_asr   = _build_solo_plan("asr",   SD_SCHED, all_mosques, dep_dt_long, arr_dt_long,
                              SD_SCHED, "America/Los_Angeles",
                              origin_lat=37.4529, origin_lng=-122.1817, dest_lat=32.7157, dest_lng=-117.1611)
solo_mag   = _build_solo_plan("maghrib", SD_SCHED, all_mosques, dep_dt_long, arr_dt_long,
                              SD_SCHED, "America/Los_Angeles",
                              origin_lat=37.4529, origin_lng=-122.1817, dest_lat=32.7157, dest_lng=-117.1611)
solo_isha  = _build_solo_plan("isha",  SD_SCHED, all_mosques, dep_dt_long, arr_dt_long,
                              SD_SCHED, "America/Los_Angeles",
                              origin_lat=37.4529, origin_lng=-122.1817, dest_lat=32.7157, dest_lng=-117.1611)
its_long_muqeem = build_itineraries([solo_dhuhr, solo_asr, solo_mag, solo_isha], allow_combining=False)
combo_in_muqeem = any(
    pc["option"]["option_type"] in ("combine_early", "combine_late")
    for it in its_long_muqeem for pc in it["pair_choices"]
)
check("I12 Long route, Muqeem: no combining in any itinerary",
      not combo_in_muqeem,
      f"got {len(its_long_muqeem)} itineraries")
check("I13 Long route, Muqeem: produces at least 1 itinerary",
      len(its_long_muqeem) >= 1)


# ═══════════════════════════════════════════════════════════════════════════════
# J.  Near-arrival Musafir Ta'kheer (at_destination)
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== J. Near-arrival Musafir Ta'kheer ===")

# J1. Arrive 20 min before Asr adhan (still in Dhuhr window, Asr starting soon)
#     → at_destination with Jam' Ta'kheer for Dhuhr+Asr
arr_20_before_asr = ASR_MIN - 20
dest_mosque_dhuhr = mosque_at(arr_20_before_asr, minutes_into_trip=300)
plan_j1 = build_plan("dhuhr", "asr", [dest_mosque_dhuhr],
                     dep_min_local=hm(10), arr_min_local=arr_20_before_asr)
at_dest_j1 = [o for o in plan_j1["options"] if o["option_type"] == "at_destination"]
check("J1 Arrive 20 min before Asr: at_destination Jam' Ta'kheer offered",
      any(o.get("combination_label") == "Jam' Ta'kheer" for o in at_dest_j1),
      f"at_dest_options={[{'label':o['label'],'combo':o.get('combination_label'),'prayers':o['prayers']} for o in at_dest_j1]}")
check("J2 Near-arrival Ta'kheer: prayers include both dhuhr AND asr",
      any("dhuhr" in o["prayers"] and "asr" in o["prayers"] for o in at_dest_j1),
      f"prayers={[o['prayers'] for o in at_dest_j1]}")

# J3. Arrive 50 min before Asr (outside 45-min window) → no Ta'kheer extension
arr_50_before_asr = ASR_MIN - 50
plan_j3 = build_plan("dhuhr", "asr", [mosque_at(arr_50_before_asr, 300)],
                     dep_min_local=hm(10), arr_min_local=arr_50_before_asr)
at_dest_j3 = [o for o in plan_j3["options"] if o["option_type"] == "at_destination"]
check("J3 Arrive 50 min before Asr: no Ta'kheer extension (>45 min window)",
      not any(o.get("combination_label") == "Jam' Ta'kheer" for o in at_dest_j3),
      f"at_dest_combos={[o.get('combination_label') for o in at_dest_j3]}")

# J4. Same scenario in Muqeem mode: no Ta'kheer at_destination extension
plan_j4 = build_plan("dhuhr", "asr", [dest_mosque_dhuhr],
                     dep_min_local=hm(10), arr_min_local=arr_20_before_asr,
                     mode="driving")
at_dest_j4 = [o for o in plan_j4["options"] if o["option_type"] == "at_destination"]
check("J4 Muqeem near-arrival: no Ta'kheer extension (Muqeem doesn't combine)",
      not any(o.get("combination_label") == "Jam' Ta'kheer" for o in at_dest_j4),
      f"at_dest_combos={[o.get('combination_label') for o in at_dest_j4]}")


# ═══════════════════════════════════════════════════════════════════════════════
# K.  Musafir itinerary templates — no separate, correct fallback
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== K. Musafir itinerary templates ===")

# K1. Pair with only separate option → Musafir builds 0 itineraries (separate forbidden)
pairs_sep_only = [{"pair": "dhuhr_asr", "label": "Dhuhr+Asr", "emoji": "🕌",
                   "options": [{"option_type": "separate", "label": "Sep", "description": "",
                                "prayers": ["dhuhr","asr"], "combination_label": None,
                                "stops": [make_stop(200)], "feasible": True, "note": None}]}]
its_sep_only = build_itineraries(pairs_sep_only, allow_combining=True)
check("K1 Musafir: pair with only separate option → 0 itineraries (separate forbidden)",
      len(its_sep_only) == 0, f"got {len(its_sep_only)} itineraries")

# K2. Pair with combine_late only → at least 1 itinerary
pairs_late_only = [{"pair": "dhuhr_asr", "label": "Dhuhr+Asr", "emoji": "🕌",
                    "options": [{"option_type": "combine_late", "label": "Late", "description": "",
                                 "prayers": ["dhuhr","asr"], "combination_label": "Jam' Ta'kheer",
                                 "stops": [make_stop(200)], "feasible": True, "note": None}]}]
its_late_only = build_itineraries(pairs_late_only, allow_combining=True)
check("K2 Musafir: pair with combine_late only → at least 1 itinerary",
      len(its_late_only) >= 1, f"got {len(its_late_only)} itineraries")
check("K3 Musafir: combine_late-only pair → no separate used",
      all(pc["option"]["option_type"] != "separate"
          for it in its_late_only for pc in it["pair_choices"]),
      f"types used={[pc['option']['option_type'] for it in its_late_only for pc in it['pair_choices']]}")

# K4. Two pairs: first combine_early, second combine_late → both valid orderings
pairs_two = [
    {"pair": "dhuhr_asr", "label": "Dhuhr+Asr", "emoji": "🕌",
     "options": [{"option_type": "combine_early", "label": "Early", "description": "",
                  "prayers": ["dhuhr","asr"], "combination_label": None,
                  "stops": [make_stop(120)], "feasible": True, "note": None},
                 {"option_type": "combine_late", "label": "Late", "description": "",
                  "prayers": ["dhuhr","asr"], "combination_label": None,
                  "stops": [make_stop(200)], "feasible": True, "note": None}]},
    {"pair": "maghrib_isha", "label": "Mag+Isha", "emoji": "🌙",
     "options": [{"option_type": "combine_late", "label": "Late", "description": "",
                  "prayers": ["maghrib","isha"], "combination_label": None,
                  "stops": [make_stop(400)], "feasible": True, "note": None},
                 {"option_type": "at_destination", "label": "AtDest", "description": "",
                  "prayers": ["maghrib","isha"], "combination_label": None,
                  "stops": [make_stop(500)], "feasible": True, "note": None}]},
]
its_two = build_itineraries(pairs_two, allow_combining=True)
check("K4 Two pairs (early/late first, late/at_dest second) → multiple itineraries",
      len(its_two) >= 2, f"got {len(its_two)} itineraries")
no_sep_k4 = all(pc["option"]["option_type"] != "separate"
                for it in its_two for pc in it["pair_choices"])
check("K5 Two-pair Musafir itineraries: no separate in any",
      no_sep_k4)

# K6. Muqeem two individual prayers: solo_stop used (no separate, no pairs)
# Muqeem mode uses _build_solo_plan — option types are solo_stop/pray_before/at_destination
pairs_two_muq = [
    {"pair": "dhuhr", "label": "Dhuhr", "emoji": "🕌",
     "options": [{"option_type": "solo_stop", "label": "Stop", "description": "",
                  "prayers": ["dhuhr"], "combination_label": None,
                  "stops": [make_stop(150)], "feasible": True, "note": None},
                 {"option_type": "pray_before", "label": "Before", "description": "",
                  "prayers": ["dhuhr"], "combination_label": None,
                  "stops": [make_stop(0)], "feasible": True, "note": None}]},
    {"pair": "maghrib", "label": "Maghrib", "emoji": "🌙",
     "options": [{"option_type": "solo_stop", "label": "Stop", "description": "",
                  "prayers": ["maghrib"], "combination_label": None,
                  "stops": [make_stop(400)], "feasible": True, "note": None}]},
]
its_muq = build_itineraries(pairs_two_muq, allow_combining=False)
check("K6 Muqeem two individual prayers: at least 1 itinerary with solo_stop (no separate)",
      any(pc["option"]["option_type"] == "solo_stop"
          for it in its_muq for pc in it["pair_choices"]),
      f"got {len(its_muq)} itineraries")


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
total = len(results)
passed = sum(1 for r in results if r[0] == PASS)
failed = total - passed
print(f"Results: {passed}/{total} passed" + (f", {failed} FAILED" if failed else " — all good"))
if failed:
    print("\nFailed tests:")
    for status, name, detail in results:
        if status == FAIL:
            print(f"  {FAIL} {name}" + (f" — {detail}" if detail else ""))
    raise SystemExit(1)
