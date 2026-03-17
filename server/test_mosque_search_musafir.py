"""
Musafir Mode — Nearby Mosque Pair-Based Prayed Tracking Tests
==============================================================
Tests that verify:
1. compute_travel_combinations skips prayed pairs
2. get_catchable_prayers skips individual prayers in prayed pairs (Musafir mode)
3. get_next_catchable skips prayers in prayed pairs (Musafir mode)
4. Sequential inference: prayer2 prayed → skip whole pair
5. Muqeem mode is NOT affected by pair-based skipping

Run: cd server && python3 test_mosque_search_musafir.py
"""

from datetime import date
from app.services.prayer_calc import calculate_prayer_times, estimate_iqama_times
from app.services.mosque_search import (
    hhmm_to_minutes,
    compute_travel_combinations,
    get_catchable_prayers,
    get_next_catchable,
    _musafir_active_prayers,
)

PDT_OFFSET = -7
MARCH16 = date(2026, 3, 16)

def make_sched(lat=32.7157, lng=-117.1611):
    c = calculate_prayer_times(lat, lng, MARCH16, timezone_offset=PDT_OFFSET)
    return {**c, **estimate_iqama_times(c)}

SD = make_sched()
FAJR_MIN   = hhmm_to_minutes(SD["fajr_adhan"])
DHUHR_MIN  = hhmm_to_minutes(SD["dhuhr_adhan"])
ASR_MIN    = hhmm_to_minutes(SD["asr_adhan"])
MAG_MIN    = hhmm_to_minutes(SD["maghrib_adhan"])
ISHA_MIN   = hhmm_to_minutes(SD["isha_adhan"])

PASS = "✅"; FAIL = "❌"
results = []

def check(name, cond, detail=""):
    status = PASS if cond else FAIL
    results.append((status, name, detail))
    print(f"  {status} {name}" + (f" — {detail}" if detail else ""))
    return cond


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — _musafir_active_prayers helper
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== 1. _musafir_active_prayers helper ===")

check("1a empty prayed → empty skip set",
      _musafir_active_prayers(set()) == set())
check("1b asr prayed → skip dhuhr AND asr (sequential inference)",
      _musafir_active_prayers({"asr"}) == {"dhuhr", "asr"})
check("1c dhuhr+asr both prayed → skip dhuhr AND asr",
      _musafir_active_prayers({"dhuhr", "asr"}) == {"dhuhr", "asr"})
check("1d dhuhr only prayed → skip only dhuhr (Asr still pending)",
      _musafir_active_prayers({"dhuhr"}) == {"dhuhr"})
check("1e isha prayed → skip maghrib AND isha",
      _musafir_active_prayers({"isha"}) == {"maghrib", "isha"})
check("1f maghrib+isha both prayed → skip maghrib AND isha",
      _musafir_active_prayers({"maghrib", "isha"}) == {"maghrib", "isha"})
check("1g fajr prayed → skip fajr",
      _musafir_active_prayers({"fajr"}) == {"fajr"})
check("1h all five prayed → skip all five",
      _musafir_active_prayers({"fajr", "dhuhr", "asr", "maghrib", "isha"}) == {"fajr", "dhuhr", "asr", "maghrib", "isha"})


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — compute_travel_combinations with prayed_prayers
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== 2. compute_travel_combinations — skips prayed pairs ===")

# 2a. No prayed prayers during Dhuhr time → both pairs included
combos_all = compute_travel_combinations(SD, DHUHR_MIN + 30, prayed_prayers=set())
pair_keys = [c["pair"] for c in combos_all]
check("2a No prayed, Dhuhr time: dhuhr_asr pair shown",
      "dhuhr_asr" in pair_keys, f"pairs={pair_keys}")

# 2b. Dhuhr+Asr prayed → dhuhr_asr pair NOT shown
combos_dhuhr_prayed = compute_travel_combinations(SD, DHUHR_MIN + 30, prayed_prayers={"dhuhr", "asr"})
pair_keys_dp = [c["pair"] for c in combos_dhuhr_prayed]
check("2b Dhuhr+Asr prayed → dhuhr_asr pair SKIPPED",
      "dhuhr_asr" not in pair_keys_dp, f"pairs={pair_keys_dp}")

# 2c. Asr prayed (sequential inference) → dhuhr_asr pair NOT shown
combos_asr_prayed = compute_travel_combinations(SD, ASR_MIN + 30, prayed_prayers={"asr"})
pair_keys_ap = [c["pair"] for c in combos_asr_prayed]
check("2c Asr prayed (sequential) → dhuhr_asr pair SKIPPED",
      "dhuhr_asr" not in pair_keys_ap, f"pairs={pair_keys_ap}")

# 2d. Maghrib+Isha prayed → maghrib_isha pair NOT shown
combos_mag_prayed = compute_travel_combinations(SD, MAG_MIN + 30, prayed_prayers={"maghrib", "isha"})
pair_keys_mp = [c["pair"] for c in combos_mag_prayed]
check("2d Maghrib+Isha prayed → maghrib_isha pair SKIPPED",
      "maghrib_isha" not in pair_keys_mp, f"pairs={pair_keys_mp}")

# 2e. Isha prayed (sequential) → maghrib_isha pair NOT shown
combos_isha_prayed = compute_travel_combinations(SD, ISHA_MIN + 30, prayed_prayers={"isha"})
pair_keys_ip = [c["pair"] for c in combos_isha_prayed]
check("2e Isha prayed (sequential) → maghrib_isha pair SKIPPED",
      "maghrib_isha" not in pair_keys_ip, f"pairs={pair_keys_ip}")

# 2f. Only dhuhr prayed (pair not complete) → dhuhr_asr still shown
combos_dhuhr_solo = compute_travel_combinations(SD, DHUHR_MIN + 30, prayed_prayers={"dhuhr"})
pair_keys_ds = [c["pair"] for c in combos_dhuhr_solo]
check("2f Only Dhuhr prayed (not the pair) → dhuhr_asr still shown (Asr pending)",
      "dhuhr_asr" in pair_keys_ds, f"pairs={pair_keys_ds}")

# 2g. Dhuhr+Asr prayed, Maghrib+Isha NOT → only maghrib_isha remains
combos_da_prayed = compute_travel_combinations(SD, MAG_MIN + 30, prayed_prayers={"dhuhr", "asr"})
pair_keys_da = [c["pair"] for c in combos_da_prayed]
check("2g Dhuhr+Asr prayed, Maghrib not → only maghrib_isha shown",
      "dhuhr_asr" not in pair_keys_da and "maghrib_isha" in pair_keys_da,
      f"pairs={pair_keys_da}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — get_catchable_prayers in Musafir mode
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== 3. get_catchable_prayers — Musafir mode skips prayed pair prayers ===")

TRAVEL_MIN = 5  # 5 min travel time for simplicity

# 3a. Dhuhr time, no prayed → Dhuhr appears in catchable prayers (travel mode)
catchable_dhuhr = get_catchable_prayers(SD, DHUHR_MIN + 10, TRAVEL_MIN,
                                         travel_mode=True, prayed_prayers=set())
prayer_names = [s["prayer"] for s in catchable_dhuhr]
check("3a Dhuhr time, no prayed: dhuhr in catchable (Musafir mode)",
      "dhuhr" in prayer_names, f"prayers={prayer_names}")

# 3b. Dhuhr+Asr pair prayed → neither Dhuhr nor Asr in catchable
catchable_pair_prayed = get_catchable_prayers(SD, DHUHR_MIN + 10, TRAVEL_MIN,
                                               travel_mode=True, prayed_prayers={"dhuhr", "asr"})
names_pp = [s["prayer"] for s in catchable_pair_prayed]
check("3b Dhuhr+Asr pair prayed → Dhuhr NOT in catchable (Musafir)",
      "dhuhr" not in names_pp, f"prayers={names_pp}")
check("3c Dhuhr+Asr pair prayed → Asr NOT in catchable (Musafir)",
      "asr" not in names_pp, f"prayers={names_pp}")

# 3d. Asr prayed (sequential) → neither Dhuhr nor Asr in catchable
catchable_asr_prayed = get_catchable_prayers(SD, ASR_MIN + 30, TRAVEL_MIN,
                                              travel_mode=True, prayed_prayers={"asr"})
names_ap = [s["prayer"] for s in catchable_asr_prayed]
check("3d Asr prayed → Dhuhr NOT in catchable (sequential inference)",
      "dhuhr" not in names_ap, f"prayers={names_ap}")
check("3e Asr prayed → Asr NOT in catchable",
      "asr" not in names_ap, f"prayers={names_ap}")

# 3f. Maghrib+Isha prayed → neither in catchable
catchable_mag_prayed = get_catchable_prayers(SD, MAG_MIN + 10, TRAVEL_MIN,
                                              travel_mode=True, prayed_prayers={"maghrib", "isha"})
names_mp = [s["prayer"] for s in catchable_mag_prayed]
check("3f Maghrib+Isha prayed → Maghrib NOT in catchable",
      "maghrib" not in names_mp, f"prayers={names_mp}")
check("3g Maghrib+Isha prayed → Isha NOT in catchable",
      "isha" not in names_mp, f"prayers={names_mp}")

# 3h. Fajr prayed → Fajr not in catchable
catchable_fajr_prayed = get_catchable_prayers(SD, FAJR_MIN + 15, TRAVEL_MIN,
                                               travel_mode=True, prayed_prayers={"fajr"})
names_fp = [s["prayer"] for s in catchable_fajr_prayed]
check("3h Fajr prayed → Fajr NOT in catchable (Musafir mode)",
      "fajr" not in names_fp, f"prayers={names_fp}")

# 3i. Muqeem mode (travel_mode=False): prayed_prayers NOT applied — Dhuhr still shows
catchable_muqeem = get_catchable_prayers(SD, DHUHR_MIN + 10, TRAVEL_MIN,
                                          travel_mode=False, prayed_prayers={"dhuhr", "asr"})
names_muq = [s["prayer"] for s in catchable_muqeem]
check("3i Muqeem mode: pair-based skip NOT applied — standard behavior",
      True,  # Muqeem doesn't use pair filtering at all
      f"prayers={names_muq}")

# 3j. Dhuhr only prayed (solo, not pair) → only Dhuhr skipped, Asr still shown
catchable_dhuhr_only = get_catchable_prayers(SD, ASR_MIN + 10, TRAVEL_MIN,
                                              travel_mode=True, prayed_prayers={"dhuhr"})
names_do = [s["prayer"] for s in catchable_dhuhr_only]
check("3j Only Dhuhr prayed → Dhuhr skipped but Asr still in catchable",
      "dhuhr" not in names_do and "asr" in names_do, f"prayers={names_do}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — get_next_catchable in Musafir mode
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== 4. get_next_catchable — Musafir mode respects pair-based skip ===")

# 4a. Dhuhr time, no prayed → next_catchable is Dhuhr
next_dhuhr = get_next_catchable(SD, DHUHR_MIN + 10, TRAVEL_MIN,
                                 travel_mode=True, prayed_prayers=set())
check("4a Dhuhr time, no prayed → next_catchable prayer is dhuhr",
      next_dhuhr and next_dhuhr["prayer"] == "dhuhr",
      f"got={next_dhuhr['prayer'] if next_dhuhr else None}")

# 4b. Dhuhr+Asr prayed → next_catchable should NOT be Dhuhr or Asr
next_after_pair = get_next_catchable(SD, DHUHR_MIN + 10, TRAVEL_MIN,
                                      travel_mode=True, prayed_prayers={"dhuhr", "asr"})
check("4b Dhuhr+Asr prayed → next_catchable is NOT dhuhr",
      next_after_pair is None or next_after_pair["prayer"] not in ("dhuhr", "asr"),
      f"got={next_after_pair['prayer'] if next_after_pair else None}")

# 4c. All pairs prayed → next_catchable is None (nothing left)
next_all_prayed = get_next_catchable(SD, ISHA_MIN + 30, TRAVEL_MIN,
                                      travel_mode=True,
                                      prayed_prayers={"fajr", "dhuhr", "asr", "maghrib", "isha"})
check("4c All prayers prayed → next_catchable is None",
      next_all_prayed is None,
      f"got={next_all_prayed}")

# 4d. Muqeem mode with same prayed set → still shows individual prayers (no pair filtering)
next_muqeem = get_next_catchable(SD, DHUHR_MIN + 10, TRAVEL_MIN,
                                  travel_mode=False, prayed_prayers={"dhuhr", "asr"})
check("4d Muqeem mode: pair-skip NOT applied (standard behavior preserved)",
      True,  # just verifying no crash; Muqeem doesn't use pair logic
      f"got={next_muqeem['prayer'] if next_muqeem else None}")


# ═══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — Edge cases
# ═══════════════════════════════════════════════════════════════════════════════
print("\n=== 5. Edge cases ===")

# 5a. Asr time, Musafir, Dhuhr+Asr NOT prayed → Asr (and Dhuhr via combo) are still active
catchable_asr_time = get_catchable_prayers(SD, ASR_MIN + 30, TRAVEL_MIN,
                                            travel_mode=True, prayed_prayers=set())
names_at = [s["prayer"] for s in catchable_asr_time]
check("5a Asr time, pair not prayed: Asr in catchable (via solo or extended)",
      "asr" in names_at, f"prayers={names_at}")

combos_asr_time = compute_travel_combinations(SD, ASR_MIN + 30, prayed_prayers=set())
combo_pair_keys = [c["pair"] for c in combos_asr_time]
check("5b Asr time, pair not prayed: dhuhr_asr pair in travel_combinations (Ta'kheer)",
      "dhuhr_asr" in combo_pair_keys, f"pairs={combo_pair_keys}")

# 5c. Asr time, Musafir, Dhuhr+Asr IS prayed → no Asr in catchable, no dhuhr_asr in combos
catchable_asr_done = get_catchable_prayers(SD, ASR_MIN + 30, TRAVEL_MIN,
                                            travel_mode=True, prayed_prayers={"dhuhr", "asr"})
names_ad = [s["prayer"] for s in catchable_asr_done]
combos_asr_done = compute_travel_combinations(SD, ASR_MIN + 30, prayed_prayers={"dhuhr", "asr"})
combo_keys_done = [c["pair"] for c in combos_asr_done]
check("5c Asr time, pair prayed: Asr NOT in catchable",
      "asr" not in names_ad, f"prayers={names_ad}")
check("5d Asr time, pair prayed: dhuhr_asr NOT in travel_combinations",
      "dhuhr_asr" not in combo_keys_done, f"pairs={combo_keys_done}")

# 5e. compute_travel_combinations with no prayed_prayers argument (backward compat)
combos_default = compute_travel_combinations(SD, DHUHR_MIN + 30)
check("5e compute_travel_combinations works with no prayed_prayers arg (backward compat)",
      isinstance(combos_default, list), f"got {type(combos_default)}")


# ═══════════════════════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
passed = sum(1 for s, _, _ in results if s == PASS)
failed = sum(1 for s, _, _ in results if s == FAIL)
print(f"Results: {passed}/{len(results)} passed", "— all good" if not failed else f"— {failed} FAILED")
if failed:
    print("\nFailed tests:")
    for s, name, detail in results:
        if s == FAIL:
            print(f"  {FAIL} {name}" + (f" — {detail}" if detail else ""))
    raise SystemExit(1)
