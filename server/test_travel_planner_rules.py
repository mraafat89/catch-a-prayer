"""
Rule-Focused Travel Planner Tests
===================================
Tests derived directly from the rules in ISLAMIC_PRAYER_RULES.md.
Covers:
  - Muqeem mode: every scenario, no combining ever
  - Musafir trip planner: pair-based prayed tracking, combine_late offered during 2nd prayer's window
  - Sequential prayer inference: Asr prayed → Dhuhr implicitly done; Isha → Maghrib
  - Edge cases around departure time and prayed-prayer state

Run: cd server && python3 test_travel_planner_rules.py
"""

from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.travel_planner import (
    hhmm_to_minutes,
    build_combination_plan,
    build_itineraries,
    _pair_relevant,
    _build_solo_plan,
)

PDT = ZoneInfo("America/Los_Angeles")
MARCH16 = date(2026, 3, 16)

# ── Schedules ─────────────────────────────────────────────────────────────────

def make_sched(lat, lng, d=MARCH16, tz=-7):
    c = calculate_prayer_times(lat, lng, d, timezone_offset=tz)
    return {**c, **estimate_iqama_times(c)}

SD = make_sched(32.7157, -117.1611)   # San Diego

FAJR_MIN   = hhmm_to_minutes(SD["fajr_adhan"])
DHUHR_MIN  = hhmm_to_minutes(SD["dhuhr_adhan"])
ASR_MIN    = hhmm_to_minutes(SD["asr_adhan"])
MAG_MIN    = hhmm_to_minutes(SD["maghrib_adhan"])
ISHA_MIN   = hhmm_to_minutes(SD["isha_adhan"])

def hm(h, m=0): return h * 60 + m

# ── Helpers ────────────────────────────────────────────────────────────────────

def mosque_at(local_min, minutes_into_trip, schedule=SD, mid="m1", name=None):
    hh, mm = divmod(local_min % 1440, 60)
    return {
        "id": mid, "name": name or f"Mosque@{local_min}",
        "lat": 35.0, "lng": -119.0,
        "address": "Test", "city": "TC", "state": "CA",
        "google_place_id": None,
        "detour_minutes": 10,
        "minutes_into_trip": minutes_into_trip,
        "local_arrival_minutes": local_min % 1440,
        "local_arrival_time_fmt": f"{hh:02d}:{mm:02d}",
        "schedule": schedule,
    }

def plan(p1, p2, mosques, dep_min, arr_min, mode="travel",
         prayed=None, sched=SD, dest_sched=SD):
    """Build a combination plan. dep_min/arr_min are minutes-from-midnight; arr may exceed 1439."""
    extra_days, arr_in_day = divmod(arr_min, 1440)
    dep_dt = datetime(2026, 3, 16, dep_min // 60, dep_min % 60, tzinfo=PDT)
    arr_dt = datetime(2026, 3, 16, arr_in_day // 60, arr_in_day % 60, tzinfo=PDT)
    arr_dt += timedelta(days=extra_days)
    if arr_min < 1440 and arr_min <= dep_min:
        arr_dt += timedelta(days=1)
    return build_combination_plan(
        p1, p2, sched, mosques, dep_dt, arr_dt, dest_sched,
        "America/Los_Angeles",
        trip_mode=mode, prayed_prayers=prayed or set(),
        origin_lat=37.4529, origin_lng=-122.1817,
        dest_lat=32.7157, dest_lng=-117.1611,
    )

def opt_types(p):
    return [o["option_type"] for o in p["options"]] if p else []

def all_prayers(p):
    """Flat list of all prayers mentioned across all options."""
    return [pr for o in p["options"] for pr in o["prayers"]] if p else []


PASS = "✅"; FAIL = "❌"
results = []

def check(name, cond, detail=""):
    status = PASS if cond else FAIL
    results.append((status, name, detail))
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    return cond


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — Muqeem mode: no combining, each prayer planned individually
# In Muqeem mode, build_travel_plan calls _build_solo_plan for EACH prayer
# independently (not build_combination_plan for pairs). No "Dhuhr + Asr" grouping.
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== 1. Muqeem mode — individual prayer plans, no combining ===")

dhuhr_m = mosque_at(DHUHR_MIN + 30, 120)
asr_m   = mosque_at(ASR_MIN + 30,   280)
mag_m   = mosque_at(MAG_MIN + 30,   450)
isha_m  = mosque_at(ISHA_MIN + 30,  550)

# Helper to call _build_solo_plan directly
def solo(prayer, mosques, dep_min, arr_min, sched=SD, dest_sched=SD):
    extra_days, arr_in_day = divmod(arr_min, 1440)
    dep_dt = datetime(2026, 3, 16, dep_min // 60, dep_min % 60, tzinfo=PDT)
    arr_dt = datetime(2026, 3, 16, arr_in_day // 60, arr_in_day % 60, tzinfo=PDT)
    arr_dt += timedelta(days=extra_days)
    if arr_min < 1440 and arr_min <= dep_min:
        arr_dt += timedelta(days=1)
    return _build_solo_plan(
        prayer, sched, mosques, dep_dt, arr_dt, dest_sched,
        "America/Los_Angeles",
        origin_lat=37.4529, origin_lng=-122.1817,
        dest_lat=32.7157, dest_lng=-117.1611,
    )

# 1a. _build_solo_plan for Dhuhr during Dhuhr time → individual plan
p_dhuhr = solo("dhuhr", [dhuhr_m], DHUHR_MIN + 10, MAG_MIN + 60)
ts_dh = opt_types(p_dhuhr)
check("1a Muqeem _build_solo_plan Dhuhr: no combine_early/late",
      "combine_early" not in ts_dh and "combine_late" not in ts_dh, f"types={ts_dh}")
check("1b Muqeem _build_solo_plan Dhuhr: no separate",
      "separate" not in ts_dh, f"types={ts_dh}")
check("1c Muqeem _build_solo_plan Dhuhr: pair key is 'dhuhr' (not 'dhuhr_asr')",
      p_dhuhr["pair"] == "dhuhr", f"pair={p_dhuhr['pair']}")
check("1d Muqeem _build_solo_plan Dhuhr: prayers only contain dhuhr",
      all(o["prayers"] == ["dhuhr"] for o in p_dhuhr["options"]), f"prayers={[o['prayers'] for o in p_dhuhr['options']]}")
check("1e Muqeem _build_solo_plan Dhuhr: combination_label is None",
      all(o.get("combination_label") is None for o in p_dhuhr["options"]))

# 1f. _build_solo_plan for Asr during Asr time → individual plan
p_asr = solo("asr", [asr_m], ASR_MIN + 10, MAG_MIN + 60)
ts_as = opt_types(p_asr)
check("1f Muqeem _build_solo_plan Asr: no combine",
      "combine_early" not in ts_as and "combine_late" not in ts_as, f"types={ts_as}")
check("1g Muqeem _build_solo_plan Asr: pair key is 'asr' (not 'dhuhr_asr')",
      p_asr["pair"] == "asr", f"pair={p_asr['pair']}")
check("1h Muqeem _build_solo_plan Asr: prayers only contain asr",
      all(o["prayers"] == ["asr"] for o in p_asr["options"]), f"prayers={[o['prayers'] for o in p_asr['options']]}")

# 1i. Muqeem build_itineraries: individual prayer plans produce itineraries with no combining
from test_travel_planner import make_stop

def muqeem_solo_prayer(prayer_name, opt_type, t):
    return {
        "pair": prayer_name, "label": prayer_name.title(), "emoji": "🕌",
        "options": [{"option_type": opt_type, "label": opt_type, "description": "",
                     "prayers": [prayer_name], "combination_label": None,
                     "stops": [make_stop(t)], "feasible": True, "note": None}]
    }

its_muq = build_itineraries(
    [muqeem_solo_prayer("dhuhr",   "solo_stop",   200),
     muqeem_solo_prayer("asr",     "solo_stop",   280),
     muqeem_solo_prayer("maghrib", "solo_stop",   450),
     muqeem_solo_prayer("isha",    "solo_stop",   550)],
    allow_combining=False
)
check("1i Muqeem build_itineraries with 4 individual prayers: produces at least 1 itinerary",
      len(its_muq) >= 1, f"got {len(its_muq)}")
no_combine_i = all(
    pc["option"]["option_type"] not in ("combine_early", "combine_late")
    for it in its_muq for pc in it["pair_choices"]
)
check("1j Muqeem itineraries: zero combining options in any itinerary", no_combine_i)
pair_keys_i = [pc["pair"] for it in its_muq for pc in it["pair_choices"]]
check("1k Muqeem itineraries: individual prayer keys (not pair keys like dhuhr_asr)",
      "dhuhr_asr" not in pair_keys_i and "maghrib_isha" not in pair_keys_i,
      f"pairs_used={set(pair_keys_i)}")

# 1l. Muqeem at_destination only → itinerary produced
its_at_dest = build_itineraries(
    [muqeem_solo_prayer("dhuhr", "at_destination", 400)],
    allow_combining=False
)
check("1l Muqeem at_destination only: produces itinerary", len(its_at_dest) >= 1,
      f"got {len(its_at_dest)}")

# 1m. Muqeem pray_before only → itinerary produced
its_pb = build_itineraries(
    [muqeem_solo_prayer("dhuhr", "pray_before", 0)],
    allow_combining=False
)
check("1m Muqeem pray_before only: produces itinerary", len(its_pb) >= 1, f"got {len(its_pb)}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — Musafir trip planner: pair-based prayed tracking, combine during 2nd prayer time
# Rule: In Musafir mode, the pair (Dhuhr+Asr or Maghrib+Isha) is tracked as a unit.
# Departing during Asr time with the pair NOT prayed → combine_late (Jam' Ta'kheer) is still offered.
# The period-closed redirect applies ONLY in Muqeem mode.
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== 2. Musafir trip planner — pair-based combining, combine during Asr time ===")

# 2a. Depart exactly at Asr adhan — Musafir, pair not prayed → combine_late OFFERED
p_asr_dep = plan("dhuhr", "asr", [asr_m], ASR_MIN, MAG_MIN + 120, mode="travel")
ts_ad = opt_types(p_asr_dep)
check("2a Musafir depart at Asr adhan: combine_late IS offered (pair tracking, Jam' Ta'kheer)",
      "combine_late" in ts_ad, f"types={ts_ad}")
check("2b Musafir depart at Asr adhan: no combine_early (Dhuhr window closed at mosque too)",
      "combine_early" not in ts_ad, f"types={ts_ad}")
check("2c Musafir depart at Asr adhan: plan covers Dhuhr+Asr pair (not solo Asr)",
      any("dhuhr" in o["prayers"] for o in p_asr_dep["options"]) if p_asr_dep else False,
      f"prayers={[o['prayers'] for o in p_asr_dep['options']] if p_asr_dep else []}")

# 2d. Depart 30 minutes INTO Asr — same: combine_late still offered
p_asr_30 = plan("dhuhr", "asr", [asr_m], ASR_MIN + 30, MAG_MIN + 120, mode="travel")
ts_a30 = opt_types(p_asr_30)
check("2d Musafir depart 30min into Asr: combine_late IS offered (pair not prayed)",
      "combine_late" in ts_a30, f"types={ts_a30}")
check("2e Musafir depart 30min into Asr: plan is non-empty",
      len(ts_a30) > 0, f"types={ts_a30}")

# 2f. Compare: depart during Dhuhr — combine_late IS also valid (Asr in the future, Taqdeem too)
p_dhuhr_dep = plan("dhuhr", "asr", [asr_m], DHUHR_MIN + 30, MAG_MIN + 120, mode="travel")
ts_dd = opt_types(p_dhuhr_dep)
check("2f Musafir depart during Dhuhr: combine_late IS offered (Asr in the future)",
      "combine_late" in ts_dd, f"types={ts_dd}")

# 2g. Depart during Asr, Muqeem — REDIRECTED to solo Asr (period-closed check active in Muqeem)
p_asr_muq = plan("dhuhr", "asr", [asr_m], ASR_MIN + 30, MAG_MIN + 120, mode="driving")
ts_am = opt_types(p_asr_muq)
check("2g Muqeem depart at Asr: no combine_late (period-closed → solo Asr redirect)",
      "combine_late" not in ts_am, f"types={ts_am}")
check("2g2 Muqeem depart at Asr: no Dhuhr in options (redirected to solo Asr plan)",
      all("dhuhr" not in o["prayers"] for o in p_asr_muq["options"]) if p_asr_muq else True,
      f"prayers={[o['prayers'] for o in p_asr_muq['options']] if p_asr_muq else []}")

# 2h. Musafir depart at Asr adhan: plan includes combine_late with both prayers
if p_asr_dep:
    combo_options = [o for o in p_asr_dep["options"] if o["option_type"] == "combine_late"]
    check("2h Musafir Asr time: combine_late option includes both Dhuhr+Asr",
          any(set(o["prayers"]) == {"dhuhr", "asr"} for o in combo_options),
          f"combo_options={[{'type': o['option_type'], 'prayers': o['prayers']} for o in combo_options]}")

# 2i. Musafir Asr time, only a Dhuhr-time mosque available:
#     combine_late not offered (no Asr-active mosque), combine_early also not offered
#     (even though Dhuhr is technically active at that mosque's arrival slot — since the
#      mosque passes during Dhuhr time, it can offer combine_early for a Musafir)
p_asr_dhuhr_mosque = plan("dhuhr", "asr", [asr_m], ASR_MIN + 30, MAG_MIN + 120, mode="travel")
ts_aem = opt_types(p_asr_dhuhr_mosque)
check("2i Musafir Asr time with asr_m: no combine_early (Dhuhr window closed at asr_m arrival)",
      "combine_early" not in ts_aem, f"types={ts_aem}")

# 2j. Depart during Isha (Maghrib window closed) → Musafir Mag+Isha:
#     combine_late IS offered (pair tracking, Jam' Ta'kheer during Isha period)
p_isha_dep = plan("maghrib", "isha", [isha_m], ISHA_MIN + 30, ISHA_MIN + 180, mode="travel")
ts_id = opt_types(p_isha_dep)
check("2j Musafir depart during Isha: combine_late IS offered (Maghrib+Isha pair tracking)",
      "combine_late" in ts_id, f"types={ts_id}")
check("2k Musafir depart during Isha: plan covers Maghrib+Isha pair",
      any("maghrib" in o["prayers"] for o in p_isha_dep["options"]) if p_isha_dep else False,
      f"options={[o['prayers'] for o in p_isha_dep['options']] if p_isha_dep else []}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — Sequential prayer inference
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== 3. Sequential prayer inference ===")

# 3a. Asr prayed → Dhuhr is implicitly done → skip entire Dhuhr+Asr pair → None
p_asr_prayed = plan("dhuhr", "asr", [dhuhr_m, asr_m],
                    DHUHR_MIN + 10, MAG_MIN + 60, prayed={"asr"})
check("3a Asr prayed → Dhuhr+Asr pair skipped (returns None)",
      p_asr_prayed is None,
      f"got plan with options={opt_types(p_asr_prayed)}")

# 3b. Isha prayed → Maghrib is implicitly done → skip entire Maghrib+Isha pair → None
p_isha_prayed = plan("maghrib", "isha", [mag_m, isha_m],
                     MAG_MIN + 10, ISHA_MIN + 120, prayed={"isha"})
check("3b Isha prayed → Maghrib+Isha pair skipped (returns None)",
      p_isha_prayed is None,
      f"got plan with options={opt_types(p_isha_prayed)}")

# 3c. Dhuhr prayed (explicitly) + Asr not prayed → solo plan for Asr
p_dhuhr_prayed = plan("dhuhr", "asr", [asr_m],
                      DHUHR_MIN + 10, MAG_MIN + 60, prayed={"dhuhr"})
ts_dp = opt_types(p_dhuhr_prayed)
check("3c Dhuhr prayed, Asr pending → solo Asr plan (not None)",
      p_dhuhr_prayed is not None, f"types={ts_dp}")
check("3d Dhuhr prayed, Asr pending → no Dhuhr in any option",
      all("dhuhr" not in o["prayers"] for o in p_dhuhr_prayed["options"]) if p_dhuhr_prayed else True,
      f"prayers={[o['prayers'] for o in p_dhuhr_prayed['options']] if p_dhuhr_prayed else []}")
check("3e Dhuhr prayed, Asr pending → no combine options",
      "combine_early" not in ts_dp and "combine_late" not in ts_dp, f"types={ts_dp}")

# 3f. Maghrib prayed (explicitly) + Isha not prayed → solo plan for Isha
p_mag_prayed = plan("maghrib", "isha", [isha_m],
                    MAG_MIN + 10, ISHA_MIN + 120, prayed={"maghrib"})
ts_mp = opt_types(p_mag_prayed)
check("3f Maghrib prayed, Isha pending → solo Isha plan",
      p_mag_prayed is not None, f"types={ts_mp}")
check("3g Maghrib prayed, Isha pending → no Maghrib in any option",
      all("maghrib" not in o["prayers"] for o in p_mag_prayed["options"]) if p_mag_prayed else True,
      f"prayers={[o['prayers'] for o in p_mag_prayed['options']] if p_mag_prayed else []}")

# 3h. Both in a pair explicitly prayed → None
p_both_prayed = plan("dhuhr", "asr", [asr_m],
                     DHUHR_MIN + 10, MAG_MIN + 60, prayed={"dhuhr", "asr"})
check("3h Both Dhuhr+Asr explicitly prayed → None", p_both_prayed is None)

# 3i. Asr prayed in Muqeem mode → same inference (Dhuhr+Asr pair skipped)
p_asr_muq2 = plan("dhuhr", "asr", [dhuhr_m, asr_m],
                  DHUHR_MIN + 10, MAG_MIN + 60, mode="driving", prayed={"asr"})
check("3i Muqeem + Asr prayed → Dhuhr+Asr pair skipped (returns None)",
      p_asr_muq2 is None,
      f"got plan with options={opt_types(p_asr_muq2)}")

# 3j. Isha prayed in Muqeem mode → Maghrib+Isha skipped
p_isha_muq = plan("maghrib", "isha", [mag_m, isha_m],
                  MAG_MIN + 10, ISHA_MIN + 120, mode="driving", prayed={"isha"})
check("3j Muqeem + Isha prayed → Maghrib+Isha pair skipped (returns None)",
      p_isha_muq is None,
      f"got plan with options={opt_types(p_isha_muq)}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — Musafir: combine_late valid during both prayer1 AND prayer2 windows
# Rule: Musafir tracks the pair as a unit. combine_late (Jam' Ta'kheer) is valid
# whether departing during Dhuhr time or Asr time — pair not prayed → offer combining.
# The period-closed redirect is Muqeem-only.
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== 4. Musafir combine_late: valid throughout pair window (Dhuhr or Asr time) ===")

# 4a. Depart 5 min before Asr adhan (last few min of Dhuhr window) → combine_late valid
dep_just_before_asr = ASR_MIN - 5
p_just_before = plan("dhuhr", "asr", [asr_m], dep_just_before_asr, MAG_MIN + 60, mode="travel")
ts_jb = opt_types(p_just_before)
check("4a Depart 5min before Asr: combine_late IS offered (Dhuhr time, Asr upcoming)",
      "combine_late" in ts_jb, f"types={ts_jb}")

# 4b. Depart exactly at Asr adhan → combine_late STILL offered in Musafir mode
dep_exact_asr = ASR_MIN
p_exact = plan("dhuhr", "asr", [asr_m], dep_exact_asr, MAG_MIN + 60, mode="travel")
ts_ex = opt_types(p_exact)
check("4b Musafir depart exactly at Asr adhan: combine_late STILL offered (pair tracking)",
      "combine_late" in ts_ex, f"types={ts_ex}")

# 4c. Depart 1 min into Asr → combine_late STILL offered in Musafir mode
p_1min = plan("dhuhr", "asr", [asr_m], ASR_MIN + 1, MAG_MIN + 60, mode="travel")
ts_1m = opt_types(p_1min)
check("4c Musafir depart 1min into Asr: combine_late STILL offered (pair tracking)",
      "combine_late" in ts_1m, f"types={ts_1m}")

# 4b-muqeem. Same departure, Muqeem → combine_late NOT offered (period-closed redirect)
p_exact_muq = plan("dhuhr", "asr", [asr_m], dep_exact_asr, MAG_MIN + 60, mode="driving")
ts_em = opt_types(p_exact_muq)
check("4b-muqeem Muqeem depart at Asr adhan: combine_late NOT offered",
      "combine_late" not in ts_em, f"types={ts_em}")

# 4d. Maghrib: depart 5 min before Isha adhan → combine_late for Mag+Isha IS offered
dep_just_before_isha = ISHA_MIN - 5
p_mag_before_isha = plan("maghrib", "isha", [isha_m], dep_just_before_isha,
                          ISHA_MIN + 120, mode="travel")
ts_mbi = opt_types(p_mag_before_isha)
check("4d Depart 5min before Isha: combine_late Mag+Isha IS offered",
      "combine_late" in ts_mbi, f"types={ts_mbi}")

# 4e. Maghrib: depart during Isha → combine_late STILL offered in Musafir mode
p_isha_adhan = plan("maghrib", "isha", [isha_m], ISHA_MIN, ISHA_MIN + 120, mode="travel")
ts_ia = opt_types(p_isha_adhan)
check("4e Musafir depart at Isha adhan: combine_late Mag+Isha STILL offered (pair tracking)",
      "combine_late" in ts_ia, f"types={ts_ia}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Muqeem: itinerary building with individual prayer plans
# In Muqeem mode, each entry in prayer_pairs is a solo prayer (not a pair).
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== 5. Muqeem itinerary building — individual prayer plans ===")

def muqeem_prayer_plan(prayer_name, types_and_times):
    """Build a fake individual prayer plan dict for muqeem testing."""
    options = []
    for ot, t in types_and_times:
        options.append({
            "option_type": ot, "label": ot, "description": "",
            "prayers": [prayer_name], "combination_label": None,
            "stops": [make_stop(t)] if t is not None else [],
            "feasible": t is not None, "note": None,
        })
    return {"pair": prayer_name, "label": prayer_name.title(), "emoji": "🕌", "options": options}

# 5a. Two individual prayers → distinct itinerary strategies
dhuhr_plan = muqeem_prayer_plan("dhuhr", [("solo_stop", 200), ("pray_before", 0)])
its_5a = build_itineraries([dhuhr_plan], allow_combining=False)
check("5a Muqeem Dhuhr solo_stop+pray_before → 2 itineraries",
      len(its_5a) == 2,
      f"got {len(its_5a)}, types={[pc['option']['option_type'] for it in its_5a for pc in it['pair_choices']]}")

# 5b. Four individual prayers → at least 1 itinerary
plans_4 = [
    muqeem_prayer_plan("dhuhr",   [("solo_stop", 200)]),
    muqeem_prayer_plan("asr",     [("solo_stop", 280)]),
    muqeem_prayer_plan("maghrib", [("solo_stop", 450)]),
    muqeem_prayer_plan("isha",    [("solo_stop", 550)]),
]
its_5b = build_itineraries(plans_4, allow_combining=False)
check("5b Muqeem 4 individual prayers → at least 1 itinerary", len(its_5b) >= 1, f"got {len(its_5b)}")
no_combine_5b = all(
    pc["option"]["option_type"] not in ("combine_early", "combine_late")
    for it in its_5b for pc in it["pair_choices"]
)
check("5c Muqeem 4 individual prayers: no combining in any itinerary", no_combine_5b)
pair_keys_5b = [pc["pair"] for it in its_5b for pc in it["pair_choices"]]
check("5d Muqeem 4 prayers: no pair keys in itinerary (dhuhr, not dhuhr_asr)",
      "dhuhr_asr" not in pair_keys_5b and "dhuhr" in pair_keys_5b,
      f"pairs={set(pair_keys_5b)}")

# 5e. Individual prayer with only at_destination → itinerary produced
its_at_dest = build_itineraries([muqeem_prayer_plan("dhuhr", [("at_destination", 400)])], allow_combining=False)
check("5e Muqeem at_destination only → itinerary produced", len(its_at_dest) >= 1, f"got {len(its_at_dest)}")

# 5f. Individual prayer with only no_option → itinerary produced (feasible=False)
its_no = build_itineraries([muqeem_prayer_plan("dhuhr", [("no_option", None)])], allow_combining=False)
check("5f Muqeem no_option only → itinerary produced (feasible=False but shown)",
      len(its_no) >= 1, f"got {len(its_no)}")

# 5g. Two prayers in order (Dhuhr t=200, Asr t=280) → temporally valid
plans_order = [
    muqeem_prayer_plan("dhuhr", [("solo_stop", 200)]),
    muqeem_prayer_plan("asr",   [("solo_stop", 280)]),
]
its_5g = build_itineraries(plans_order, allow_combining=False)
check("5g Muqeem Dhuhr(t=200) then Asr(t=280) → valid itinerary", len(its_5g) >= 1, f"got {len(its_5g)}")

# 5h. Two prayers with chronologically ordered stops (Asr t=100, Dhuhr t=200)
# build_itineraries validates stop chronological order only — [100,200] is sorted → 1 itinerary
# (canonical Islamic prayer order is enforced by build_travel_plan, not build_itineraries)
plans_rev = [
    muqeem_prayer_plan("asr",   [("solo_stop", 100)]),
    muqeem_prayer_plan("dhuhr", [("solo_stop", 200)]),
]
its_5h = build_itineraries(plans_rev, allow_combining=False)
check("5h Asr(t=100) then Dhuhr(t=200): stops in order → itinerary accepted",
      len(its_5h) == 1, f"got {len(its_5h)}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — Cross-cutting: mode consistency and no bleed-through
# ═══════════════════════════════════════════════════════════════════════════════

print("\n=== 6. No mode bleed-through ===")

# 6a. Musafir depart in Dhuhr time → combine_early offered
p_musfr_dhuhr = plan("dhuhr", "asr", [dhuhr_m, asr_m], DHUHR_MIN + 30, MAG_MIN + 60,
                     mode="travel")
ts_6a = opt_types(p_musfr_dhuhr)
check("6a Musafir in Dhuhr time: combine_early offered", "combine_early" in ts_6a, f"types={ts_6a}")
check("6b Musafir in Dhuhr time: combine_late offered", "combine_late" in ts_6a, f"types={ts_6a}")
check("6c Musafir in Dhuhr time: no separate", "separate" not in ts_6a, f"types={ts_6a}")

# 6d. Same scenario in Muqeem → individual prayer plan (via _build_solo_plan), no combine
p_muqeem_dhuhr = solo("dhuhr", [dhuhr_m, asr_m], DHUHR_MIN + 30, MAG_MIN + 60)
ts_6d = opt_types(p_muqeem_dhuhr)
check("6d Muqeem individual Dhuhr plan: no combine_early", "combine_early" not in ts_6d, f"types={ts_6d}")
check("6e Muqeem individual Dhuhr plan: no combine_late",  "combine_late"  not in ts_6d, f"types={ts_6d}")
check("6f Muqeem individual Dhuhr plan: no separate",      "separate"      not in ts_6d, f"types={ts_6d}")
check("6f2 Muqeem individual Dhuhr plan: pair='dhuhr' not 'dhuhr_asr'",
      p_muqeem_dhuhr["pair"] == "dhuhr", f"pair={p_muqeem_dhuhr['pair']}")

# 6g. Musafir at Asr time + Asr prayed → pair skipped (sequential inference)
p_6g = plan("dhuhr", "asr", [asr_m], ASR_MIN + 30, MAG_MIN + 60,
            mode="travel", prayed={"asr"})
check("6g Musafir at Asr time + Asr prayed → None (Dhuhr inferred done)", p_6g is None)

# 6h. Musafir at Asr time + Dhuhr prayed (explicitly) → Asr solo plan
p_6h = plan("dhuhr", "asr", [asr_m], ASR_MIN + 30, MAG_MIN + 60,
            mode="travel", prayed={"dhuhr"})
ts_6h = opt_types(p_6h)
check("6h Musafir at Asr time + Dhuhr explicitly prayed → Asr solo plan",
      p_6h is not None and all("dhuhr" not in o["prayers"] for o in p_6h["options"]),
      f"types={ts_6h}, prayers={[o['prayers'] for o in p_6h['options']] if p_6h else []}")


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════

print("\n" + "=" * 60)
total  = len(results)
passed = sum(1 for r in results if r[0] == PASS)
failed = total - passed
print(f"Results: {passed}/{total} passed" + (f", {failed} FAILED" if failed else " — all good"))
if failed:
    print("\nFailed tests:")
    for status, name, detail in results:
        if status == FAIL:
            print(f"  {FAIL} {name}" + (f" — {detail}" if detail else ""))
    raise SystemExit(1)
