# Islamic Prayer Timing Rules - Ground Truth Documentation

This document is the authoritative reference for all prayer timing logic in the Catch a Prayer application. All implementation must comply with these rules.

---

## The Five Daily Prayers

1. **Fajr** (Dawn Prayer)
2. **Dhuhr** (Noon Prayer) — replaced by Jumuah on Fridays
3. **Asr** (Afternoon Prayer)
4. **Maghrib** (Sunset Prayer)
5. **Isha** (Night Prayer)

---

## Key Timing Concepts

### Adhan Time vs Iqama Time

- **Adhan Time**: The official start of a prayer period (call to prayer)
- **Iqama Time**: When the Imam leads the congregational prayer at the mosque (typically 5–20 minutes after adhan, varies by mosque)
- **Congregation Window**: How long the Imam actively leads the prayer (~10–15 minutes after iqama). A user arriving within this window can still join the ongoing congregation.

### Prayer Periods

Each prayer has a valid time window. Outside this window, the prayer is **missed** (not delayed):

| Prayer  | Period Start   | Period End              |
|---------|----------------|-------------------------|
| Fajr    | Fajr adhan     | **Sunrise (Shorooq)**   |
| Dhuhr   | Dhuhr adhan    | Asr adhan               |
| Asr     | Asr adhan      | Maghrib adhan           |
| Maghrib | Maghrib adhan  | Isha adhan              |
| Isha    | Isha adhan     | **Next day's Fajr adhan** |

**Critical note**: Fajr is the only prayer whose period ends before the next prayer begins (at sunrise). All other prayers run until the next prayer's adhan. Isha in particular runs all the way until the next day's Fajr adhan — there is no arbitrary time cutoff for the Isha prayer period.

### Arrival Time Calculation

```
arrival_time = current_time + travel_time_to_mosque
```

All comparisons are made in the **mosque's local timezone** (see Timezone Handling section).

---

## The Five Catching Statuses

Listed in priority order from most to least preferred.

### Status 1: Can Catch With Imam (From Beginning)

**Condition**: `arrival_time ≤ iqama_time` AND prayer period is currently active

- User arrives at or before the iqama — joins congregation from the start
- This is the most preferred way to pray in Islam
- **Message example**: "Can catch Asr with Imam at Masjid Al-Noor — arrive by 4:15 PM"

### Status 2: Can Catch With Imam (In Progress)

**Condition**: `iqama_time < arrival_time ≤ iqama_time + congregation_window (~15 min)`

- Congregation is still ongoing when user arrives — user can join
- Still fully counts as congregational prayer
- **Message example**: "Asr congregation in progress — 8 minutes left to join, hurry!"

### Status 3: Can Pray Solo at Mosque

**Condition**: `arrival_time > iqama_time + congregation_window` AND `arrival_time < prayer_period_end`

- Congregation has ended but the prayer period is still active
- User prays individually at the mosque — **completely valid in Islam**
- For Fajr: only until sunrise. For all other prayers: until the next prayer's adhan.
- There is no arbitrary time cutoff (e.g., no "30 minutes after iqama" rule) — the full prayer period is always valid.
- **Message example**: "Missed Isha congregation, but can still pray solo at mosque (period active until Fajr at 5:31 AM)"

### Status 4: Pray at Nearby Clean Location

**Condition**: `arrival_time ≥ prayer_period_end` AND `current_time < prayer_period_end`

- User cannot reach the mosque before the prayer period ends
- BUT the prayer period is still active right now — user must pray where they are
- Suitable locations: clean parking lot, office room, park, any clean quiet space
- Prayer is **completely valid** if performed before the period ends
- **Message example**: "Cannot reach mosque before Asr ends — find a clean nearby location (period ends at 6:47 PM, 14 minutes left)"

### Status 5: Missed Prayer — Make Up (Qadha)

**Condition**: `current_time ≥ prayer_period_end`

- The prayer period has already ended and the prayer was not performed
- The prayer must still be made up (qadha) — performed outside its prescribed time
- **Common practice**: Make up the missed prayer immediately after catching the next prayer with the Imam (e.g., catch Asr with Imam, then pray missed Dhuhr solo afterward)
- **Message example**: "Missed Dhuhr — make it up after your next prayer"

---

## Special Cases

### 1. Fajr Prayer Exception

Fajr is the only prayer that becomes missed before the next prayer begins:

```
Fajr Adhan ──────────────── Sunrise ──────────────── Dhuhr Adhan
           [Normal Fajr Period]    [Missed Fajr — Make Up (Status 5)]
```

- **Before sunrise**: Normal Fajr period — Statuses 1–4 apply
- **After sunrise**: Fajr is **missed** — Status 5 (Make Up) applies
- The label "Can Catch Delayed" does **not** apply to post-sunrise Fajr. After sunrise, it is a missed prayer, not a delayed one.

### 2. Asr — Discouraged Near Sunset

Asr is valid from its adhan until Maghrib, but praying it when the sun has turned visibly yellow/orange (roughly the last **15 minutes before Maghrib**) is considered **makruh (disliked)** by the majority of scholars, even though the prayer remains valid.

```
Asr adhan ──────────────[preferred window]──────[makruh zone]── Maghrib adhan
                                                  ↑ ~15 min before Maghrib
```

The app should show a discouragement note whenever the user's status is `can_pray_solo_at_mosque` or `pray_at_nearby_location` for Asr **and** the current time is within 15 minutes of Maghrib adhan. The note should read something like: _"Note: delaying Asr this close to Maghrib is discouraged — pray as soon as possible."_

The Asr period does not end early — this is purely a note, not a status change.

### 3. Isha Prayer — Midnight Wraparound

Isha is the only prayer whose period **crosses midnight**. This requires careful time arithmetic in implementation.

The Isha window is divided into three sub-cases based on `current_time`:

```
[Isha adhan]──[iqama]──[congregation ends]────────[midnight]────────[Fajr adhan]
     8:30 PM   8:45 PM      9:00 PM                 12:00 AM          5:15 AM
                                                                          ↑
                                                              Isha period ends here
```

| Current time | Situation | Correct behaviour |
|---|---|---|
| **After Isha adhan (e.g. 8:30 PM+)** | Normal evening window | Status 1–4 computed normally |
| **After midnight, before Fajr (e.g. 1:30 AM)** | Still valid but **discouraged** — praying after midnight is considered makruh (disliked) | Status 3: Can pray solo until Fajr, with a note that praying before midnight is preferred |
| **After Fajr, before tonight's Isha (e.g. 9 AM)** | Yesterday's Isha has ended | Status 5: Missed — make it up |

**Implementation note** (`mosque_search.py`): When `current_time < isha_adhan_time` (i.e. we're before tonight's Isha), check `current_time` against `fajr_time`:
- If `current_time < fajr_time` → post-midnight carry-over: bump `current_minutes += 1440` so it compares correctly against the +24h-adjusted `period_end_min`
- If `current_time ≥ fajr_time` → daytime after Fajr: return `missed_make_up` immediately

The displayed `period_ends_at` value is always **today's Fajr time** (e.g. `05:15`), which is:
- Correct when shown before midnight ("can pray solo until 5:15 AM")
- Correct when shown after midnight ("can pray solo until 5:15 AM" — same calendar day)

**Never** use an arbitrary cutoff like `isha_iqama + 6 hours` — Isha is valid all the way to Fajr regardless of how late it is.

### 3. Jumuah (Friday Prayer) Exception

Jumuah replaces Dhuhr on Fridays. It has two components in sequence:
1. **Khutba (Sermon)**: 30–45 minutes
2. **Jumuah Prayer**: 10–15 minutes

| Arrival Time | Status | Message |
|---|---|---|
| Before Khutba starts | Can Catch Jumuah (Full) | "Can attend full Jumuah — sermon + prayer" |
| After Khutba starts, before Khutba ends | Can Catch Jumuah (Partial) | "Can catch Jumuah — partial sermon + prayer (still valid)" |
| After Jumuah prayer ends | Missed Jumuah | "Missed Jumuah — can pray Dhuhr solo (period still active until Asr)" |

**Missing Jumuah is considered highly discouraged in Islamic faith.**

**Multiple Jumuah sessions**: Many mosques offer 2–3 sessions at different times. Each session is evaluated independently — if a user misses the first session, the app should check if they can catch a later one.

#### Jumuah Duration Note
Most mosque websites do not specify the exact khutba duration. When not available, the app should use an estimated duration of 45 minutes total (khutba + prayer) and indicate to the user this is an estimate.

---

## Smart Recommendation Algorithm

### Core Principle

Recommend the **most immediately relevant** prayer opportunity. Never suggest a prayer that is hours away when there is a catchable or active prayer right now.

### Priority Order

For a given mosque, evaluate in this order:

**1. Congregation Currently in Progress** *(highest urgency)*
- `iqama_time ≤ current_time` AND `current_time + travel_time ≤ iqama_time + congregation_window`
- User needs to leave immediately
- → "Isha congregation in progress — 8 minutes left to join, leave now!"

**2. Can Catch Upcoming Congregation**
- `current_time < iqama_time` AND `current_time + travel_time ≤ iqama_time`
- → "Can catch Asr with Imam — leave by 4:00 PM to arrive by 4:15 PM"

**3. Can Pray Solo at Mosque (Period Active)**
- Congregation has ended (or user will arrive after it), but prayer period is still active at arrival
- → "Missed Isha congregation — can still pray solo at mosque (period active until Fajr at 5:31 AM)"
- This applies at 9:00 PM, 10:30 PM, midnight, etc. — any time within the Isha period

**4. Next Upcoming Prayer Today**
- A future prayer that hasn't started yet, and user can catch it
- → "Next prayer: Maghrib at 7:22 PM — you can make it with the Imam (15 min travel)"

**5. Missed Prayer — Make Up**
- A prayer whose period ended today without being performed
- Only recommend this if no current or upcoming prayers are catchable
- → "Can make up missed Fajr (after sunrise)"

**6. Tomorrow's Fajr** *(lowest priority)*
- Only surface when ALL of today's prayers are definitively done or missed
- Do NOT suggest tomorrow's Fajr while today's Isha period is still active
- → "All today's prayers done. Next: Tomorrow's Fajr at 5:31 AM"

### When to Switch to Tomorrow's Fajr

Only recommend tomorrow's Fajr when **both** of these are true:
- The Isha congregation has ended (iqama + congregation window has passed)
- AND the user has explicitly indicated they are done for the day OR the current time is past a reasonable late-night threshold AND the user cannot reach any mosque before Isha ends

The Isha prayer period itself (running until Fajr) does not block tomorrow's Fajr recommendation when the user has no way to act on it — use good judgment based on the full context.

### Error Prevention

**Never do these**:
- Suggest tomorrow's Fajr while today's Isha period is still active and catchable
- Ignore a congregation that is currently in progress
- Apply a 30-minute arbitrary cutoff to the prayer period — the full period is always valid
- Label post-sunrise Fajr as "delayed" — it is missed

**Always do these**:
- Check if a congregation is currently in progress first
- Use the full prayer period (not a shortened window) for solo prayer eligibility
- Show urgency indicators when time is short
- Suggest nearby clean locations when mosque isn't reachable in time

---

## Travel Mode — Prayer Combination Rules

### What Travel Mode Enables

Islam allows travelers to **combine certain prayers** for convenience. Travel Mode unlocks two combination pairs:

| Pair | Early Combination (Jam' Taqdeem) | Late Combination (Jam' Ta'kheer) |
|---|---|---|
| Dhuhr + Asr | Both prayed during Dhuhr period | Both prayed during Asr period |
| Maghrib + Isha | Both prayed during Maghrib period | Both prayed during Isha period |

**Fajr cannot be combined with any prayer.**

Both early and late combinations are equally valid in Islam.

### Musafir Pair-Based Prayed Tracking (Applies to Both Nearby View AND Trip Planning)

**In Musafir mode, prayers are always tracked as pairs (or standalone for Fajr):**

| Unit | Prayers |
|------|---------|
| Fajr | Fajr only |
| Dhuhr+Asr | Dhuhr and Asr together |
| Maghrib+Isha | Maghrib and Isha together |

The app asks the user one of three questions:
- "Have you prayed **Fajr**?" — Fajr unit
- "Have you prayed **Dhuhr + Asr**?" — treated as a pair
- "Have you prayed **Maghrib + Isha**?" — treated as a pair

**Never asks about Dhuhr, Asr, Maghrib, or Isha individually in Musafir mode.**

The "have you prayed?" banner in the app must also reflect pair-level tracking in Musafir mode:
- If **Isha** is currently active → banner asks "Maghrib + Isha — did you already pray both?" and marks BOTH when confirmed
- If **Asr** is currently active → banner asks "Dhuhr + Asr — did you already pray both?" and marks BOTH when confirmed
- **Fajr** is always asked individually (no pair)
- Confirming/undoing always applies to the entire pair

When a pair is marked prayed:
- Both prayers in the pair are passed in `prayed_prayers` (e.g. `["dhuhr", "asr"]`)
- The nearby mosque view **skips** that pair's `travel_combinations` section
- The nearby mosque view **skips** those individual prayers from `catchable_prayers`
- The trip planner **skips** that pair entirely (returns None for the pair)

Sequential inference still applies (Asr prayed alone → Dhuhr is also done → pair skipped), but in normal Musafir mode the UI only ever marks the full pair.

### Standard Travel Mode (No Destination Set — Musafir at Current Location)

The user has already traveled to a location and is staying there for a while. They activate Musafir mode to enable prayer combining. The app shows the normal nearby-mosque list **plus** a combining section on each card.

Each pair section shows the contextually correct option based on the current time (and only for pairs not yet prayed):

**Case A — Currently in first prayer's time (e.g., Dhuhr time, Asr hasn't started)**
> Only Jam' Taqdeem is shown:
> "Pray Dhuhr + Asr together now (during Dhuhr time)"
> → User can advance Asr into the current Dhuhr window

**Case B — First prayer's time has passed (e.g., Asr adhan has happened)**
> Only Jam' Ta'kheer is shown, with a prominent note:
> **"Dhuhr is not missed ✓"**
> "As Musafir, you can still pray Dhuhr + Asr together during Asr time"
> → The user must know the earlier prayer is NOT missed — they have until the end of Asr
>
> **Sub-case B1 — Congregation still ongoing** (within iqama + 15 min): mention the iqama time
> Sub-case B2 — Congregation has ended**: do NOT mention iqama. Instead say:
> "As a Musafir, pray Dhuhr + Asr together now at this mosque (solo, Ta'kheer — Asr period active until Maghrib at HH:MM)"

**Case C — Both options still feasible (e.g., Dhuhr time, Asr adhan is soon)**
> Both shown: Taqdeem as primary ("pray now"), Ta'kheer as alternative ("or wait")

**Critical rule**: A Musafir's window for the first prayer effectively extends until the end of the second prayer's time. Dhuhr is not missed at Asr adhan; it can still be prayed (combined with Asr) until the end of Asr time. Same for Maghrib — not missed at Isha adhan for a Musafir.

### Route-Based Travel Mode (Destination Set)

When the user plans a trip (origin → destination), the app computes **complete trip itineraries** — each itinerary is a full prayer plan covering every prayer that occurs during the journey, presented as a single coherent option.

**Key design principle**: instead of showing options per prayer pair (Dhuhr+Asr separately, then Maghrib+Isha separately), the app shows 3–5 complete plans, e.g.:
- *Option 1*: Pray Dhuhr+Asr early en route (Jam' Taqdeem), then Maghrib+Isha late at destination
- *Option 2*: Drive, pray Dhuhr+Asr late (Jam' Ta'kheer), arrive and pray Maghrib+Isha early
- *Option 3*: Pray everything at or near the destination

**Musafir mode** (`trip_mode=travel`): combining (Jam' Taqdeem / Ta'kheer) options are included. Prayers are grouped as pairs (Dhuhr+Asr, Maghrib+Isha). `separate` stops are never shown.
**Muqeem mode** (`trip_mode=driving`): **Normal mode — no combinations, no pairs, no pair labels.** Each prayer is planned as a completely independent section. The response contains one section per prayer (Dhuhr, Asr, Maghrib, Isha, Fajr — whichever overlap the trip window). Each section has individual options only: `solo_stop` (best mosque en route), `pray_before` (mosque near origin), `at_destination` (mosque near destination), `no_option`. No `combine_early`, no `combine_late`, no `separate`, no `combination_label`, no "Dhuhr + Asr" grouping. The nearby-mosque view in Muqeem mode also has no `travel_combinations`.

#### How It Works

1. User sets origin + destination + departure time
2. App identifies mosques along the route (within reasonable detour distance)
3. For each mosque, arrival time is computed from route geometry
4. Prayer status at each mosque is checked at that estimated arrival time
5. Per-pair options (combine_early, combine_late, separate, pray_before, at_destination) are built
6. **Complete itineraries** are generated by combining one strategy per pair — deduplicated and checked for temporal consistency
7. Each itinerary card shows all prayer stops in trip order with tappable mosque links and a "Open in Maps" share button

#### Example Scenario

```
User: Driving Los Angeles → San Francisco (6-hour trip)
Departure: 11:00 AM (Dhuhr period begins ~12:30 PM)
Prayer times today:
  Dhuhr adhan: 12:30 PM | iqama: 12:45 PM
  Asr adhan: 4:00 PM   | iqama: 4:15 PM
  Maghrib adhan: 7:10 PM | iqama: 7:25 PM
  Isha adhan: 8:30 PM  | iqama: 8:45 PM
```

**Recommended options the app surfaces**:

| Option | Mosque | Arrival Time | What You Catch | Type |
|---|---|---|---|---|
| A | Masjid Al-Noor (Bakersfield) | 1:30 PM | Dhuhr + Asr | Early Combination (Jam' Taqdeem) |
| B | Islamic Center of Fresno | 1:30 PM | Dhuhr with Imam | Single prayer |
| B cont. | Masjid Al-Iman (Bay Area) | 4:10 PM | Asr with Imam | Single prayer |
| C | Masjid Al-Iman (Bay Area) | 4:10 PM | Dhuhr + Asr | Late Combination (Jam' Ta'kheer) |
| D | Masjid Warith Deen (Bay Area) | 7:20 PM | Maghrib + Isha | Early Combination |

The app presents all valid options — not just one. The user decides based on their schedule, preferred mosques, and how much they want to stop.

#### Route Option Display Format

Each option should show:
- **Which mosque(s)** to stop at
- **When to arrive** (or leave by)
- **What prayer(s)** to catch
- **Whether it's a combination** and what type
- **How far off the main route** the mosque detour adds

#### Option Types (Route Mode)

| `option_type` | Label | Description |
|---|---|---|
| `pray_before` | Pray Before Leaving | Prayer(s) active at departure — stop at nearest mosque to origin before starting the trip |
| `combine_early` | Jam' Taqdeem | Both prayers combined during the first prayer's time window (e.g. Dhuhr + Asr during Dhuhr) |
| `combine_late` | Jam' Ta'kheer | Both prayers combined during the second prayer's time window (e.g. Dhuhr + Asr during Asr) |
| `separate` | Separate Stops | Two stops: one for each prayer at the best available mosque |
| `at_destination` | Pray Near Destination | Prayer(s) still active upon arrival — stop at nearest mosque to destination |
| `solo_stop` | Stop for [Prayer] | Single prayer stop (used when only one prayer in a pair is needed) |
| `stop_for_fajr` | Stop for Fajr | Fajr-specific stop along the route |
| `no_option` | No Mosque Found | No mosque found for this prayer — pray at a clean rest stop |

**Critical rule: every option that claims a prayer can be performed MUST include a mosque stop** (or fall back to `no_option` if no mosque is found). Options with empty `stops: []` are only allowed for `no_option`. The only time there's no mosque is when the search returned nothing, and in that case the option type must be `no_option` with `feasible: false`.

**Muqeem mode (no combining)**: The plan shows separate stops for each individual prayer. `solo_stop` is the primary option type (one stop per prayer). `pray_before` (mosque near origin) and `at_destination` (mosque near destination) are used as fallbacks when no en-route mosque is available mid-trip. Each stop searches a dedicated ~10 km radius around the anchor point, not just the route corridor.

**Musafir mode (combining allowed)**: The plan focuses on combining options. `separate` stops are **never shown** — only `combine_early`, `combine_late`, `pray_before`, `at_destination`, `solo_stop`, and `no_option` are used. This keeps the plan clean and prevents confusion with two-stop options that are inferior to Jam' combining.

#### Anchor Mosque Search (Origin and Destination)

`pray_before` and `at_destination` require a mosque near a **fixed anchor point** (origin or destination), not just somewhere in the route corridor. These two options use a **dedicated nearby search** around origin/destination with a ~10 km radius, independent of the route corridor mosques.

```
FUNCTION fetch_anchor_mosques(db, lat, lng, local_date, tz_str, anchor_dt, radius_km=10):
    // Query mosques within radius_km of (lat, lng)
    // For each: fetch prayer schedule for the date at anchor_dt
    // Return list of mosque dicts with local_arrival_minutes = anchor_dt converted to mosque tz
```

`find_nearest_mosque` merges anchor mosques + route mosques, sorted by distance to the anchor point. This ensures that even when the route corridor has no mosques, origin/destination mosques are still found.

#### Pseudocode: `build_combination_plan`

```
FUNCTION build_combination_plan(prayer1, prayer2, origin_schedule, route_mosques, departure_dt, arrival_dt, dest_schedule, timezone,
                                 origin_lat, origin_lng, dest_lat, dest_lng,
                                 origin_mosques, dest_mosques):

    dep_min = departure_dt in local minutes
    arr_min = arrival_dt in local minutes

    s1 = prayer_status_at_arrival(prayer1, origin_schedule, dep_min)
    s2 = prayer_status_at_arrival(prayer2, origin_schedule, dep_min)

    options = []

    // ── Pray before leaving ──────────────────────────────────────────────────
    // Search anchor mosques near ORIGIN (dedicated search, not just route corridor).
    IF s1 AND s2:
        // Both prayers active at departure (e.g. during Dhuhr time, Asr about to start)
        best_mosque = find_nearest_mosque(origin_lat, origin_lng, origin_mosques + route_mosques, prayer1, dep_min)
        options.append({ type: pray_before, prayers: [prayer1, prayer2], stops: [best_mosque] if found else [],
                          combination_label: "Jam' Taqdeem or Ta'kheer (both active now)" if allow_combining })

    ELSE IF allow_combining AND s1 AND NOT s2:
        // Musafir: prayer1 active, prayer2 not yet started — prayer1 only before leaving,
        // user will combine en route or at destination
        best_mosque = find_nearest_mosque(origin_lat, origin_lng, origin_mosques + route_mosques, prayer1, dep_min)
        options.append({ type: pray_before, prayers: [prayer1], stops: [best_mosque] if found else [] })

    ELSE IF allow_combining AND NOT s1 AND s2:
        // Musafir: prayer1 standard period has CLOSED but combined window still open (Ta'kheer valid)
        // e.g. it is Isha time and Maghrib+Isha pair not yet prayed → offer BOTH as Jam' Ta'kheer
        // The Musafir's combined window extends until the end of prayer2's period (Fajr for Isha)
        best_mosque = find_nearest_mosque(origin_lat, origin_lng, origin_mosques + route_mosques, prayer2, dep_min)
        options.append({ type: pray_before, prayers: [prayer1, prayer2], stops: [best_mosque] if found else [],
                          combination_label: "Jam' Ta'kheer",
                          label: "Pray Both Before Leaving" })

    ELSE IF NOT allow_combining AND s1:
        // Muqeem: only prayer1 can be prayed now (prayer2 not active yet)
        best_mosque = find_nearest_mosque(origin_lat, origin_lng, origin_mosques + route_mosques, prayer1, dep_min)
        options.append({ type: pray_before, prayers: [prayer1], stops: [best_mosque] if found else [] })
    // Note: Muqeem with s1=None, s2=active is redirected to _build_solo_plan before reaching here

    // ── Combine Early (Jam' Taqdeem) — [Musafir only] ───────────────────────
    FOR mosque IN route_mosques sorted by minutes_into_trip:
        s = prayer_status_at_arrival(prayer1, mosque.schedule, mosque.local_arrival_minutes)
        IF s: options.append({ type: combine_early, stops: [mosque], prayers: [prayer1, prayer2] }); BREAK

    // ── Combine Late (Jam' Ta'kheer) — [Musafir only] ────────────────────────
    // Valid throughout prayer2's entire window, even if prayer1's standard period has closed.
    FOR mosque IN route_mosques sorted by minutes_into_trip:
        s = prayer_status_at_arrival(prayer2, mosque.schedule, mosque.local_arrival_minutes)
        IF s: options.append({ type: combine_late, stops: [mosque], prayers: [prayer1, prayer2] }); BREAK

    // ── Pray near destination ────────────────────────────────────────────────
    // Three cases for Musafir mode (only standard active check for Muqeem):
    s1_dest = prayer_status_at_arrival(prayer1, dest_schedule, arr_min)
    s2_dest = prayer_status_at_arrival(prayer2, dest_schedule, arr_min)

    IF allow_combining AND NOT s1_dest AND s2_dest:
        // Musafir: prayer1 period closed at arrival, prayer2 active → BOTH as Jam' Ta'kheer
        prayers_at_dest = [prayer1, prayer2]
        combination_label = "Jam' Ta'kheer"

    ELSE IF allow_combining AND s1_dest AND NOT s2_dest:
        IF prayer2_adhan_min - arr_min <= 45:
            // Near-arrival Ta'kheer: prayer1 active, prayer2 starting soon (within 45 min)
            prayers_at_dest = [prayer1, prayer2]; combination_label = "Jam' Ta'kheer"
        ELSE:
            prayers_at_dest = [prayer1]; combination_label = None

    ELSE IF s1_dest AND s2_dest:
        prayers_at_dest = [prayer1, prayer2]; combination_label = "Jam' Taqdeem"

    ELSE IF s2_dest:
        prayers_at_dest = [prayer2]; combination_label = None

    IF prayers_at_dest:
        // Search anchor mosques near DESTINATION (dedicated search)
        best_mosque = find_nearest_mosque(dest_lat, dest_lng, dest_mosques + route_mosques, prayers_at_dest[0], arr_min)
        options.append({ type: at_destination, stops: [best_mosque] if found else [],
                          prayers: prayers_at_dest, combination_label: combination_label })

    // ── No mosque fallback ───────────────────────────────────────────────────
    // Always include the deadline so the user knows when they MUST pray by.
    IF options is empty:
        deadline = period_end of prayer2 (e.g. fajr_adhan for Isha, maghrib_adhan for Asr)
        options.append({ type: no_option, feasible: False,
                          note: f"Pray {prayer1}+{prayer2} at a clean rest stop before {deadline}" })

    RETURN { pair, label, emoji, options }
```

#### `find_nearest_mosque` helper

```
FUNCTION find_nearest_mosque(lat, lng, mosque_pool, prayer, time_min):
    // mosque_pool = anchor_mosques + route_mosques (caller concatenates)
    candidates = mosque_pool deduplicated by id, sorted by haversine_distance(lat, lng)
    FOR mosque IN candidates[:15]:
        status = prayer_status_at_arrival(prayer, mosque.schedule, time_min)
        IF status: RETURN mosque
    RETURN None
```

#### Edge Cases in Route Mode

- If a prayer period will end before the user can reach any mosque on the route → show `no_option` with "Pray at a clean rest stop before [deadline]" — **always include the deadline time**
- If no mosques are in the database for the area → `pray_before` and `at_destination` still search the anchor radius; if still nothing, show `no_option` with deadline
- Fajr during a road trip: If user is driving through the Fajr period, show nearest mosque or `no_option` "find a clean rest stop before sunrise"
- **`pray_before` mosque search** uses `origin_mosques` (dedicated 10 km search around origin) merged with `route_mosques` — ensures a mosque near the user's start is found even if the route corridor is empty
- **`at_destination` mosque search** uses `dest_mosques` (dedicated 10 km search around destination) merged with `route_mosques` — same reason
- **Period-closed redirect — Muqeem mode only**: In Muqeem mode (normal mode, no combining), if prayer1's standard window has already closed at departure time AND prayer2 is now active, redirect to a solo plan for prayer2 only. Example: departing during Asr time in Muqeem mode → Dhuhr window is closed → show solo Asr only.
- **Musafir trip planner during Asr/Isha time — STILL offer combining**: In Musafir mode, the user tracks the **pair** as a unit. If the pair has NOT been prayed, the app offers `combine_late` (Jam' Ta'kheer) for en-route stops, AND shows `pray_before`/`at_destination` with **both prayers** (not just prayer2). The period-closed redirect does NOT apply in Musafir mode.
- **Near-arrival Musafir Ta'kheer (prayer1 active at arrival, prayer2 starting within 45 min)**: include prayer2 in `at_destination` as a Jam' Ta'kheer combining stop.
- **Musafir Ta'kheer when prayer1 closed at arrival**: if prayer1's standard period is closed at arrival but prayer2 is active, `at_destination` shows both prayers as Jam' Ta'kheer (same combined-window rule).
- **Mosque candidate limit per option type**: Show max 2–3 mosques per option type (combine_early, combine_late). In Musafir mode (more option types), limit to 2 per type to avoid lengthy confusing option lists.
- **Pair relevance must check BOTH origin AND destination schedules.** On north-south routes (e.g. Menlo Park → San Diego), the destination may have earlier prayer times than the origin. A pair should be included if it is relevant using *either* origin or destination prayer schedule. Example: Maghrib is at 7:33pm in Menlo Park but 7:13pm in San Diego; a 9h13m trip arriving at exactly 7:13pm would miss Maghrib if only origin schedule is checked.
- **Period boundary**: a prayer ends *at* the next prayer's adhan (not one minute after). The `>=` comparison is used: `arrival_minutes >= period_end_min → missed`.
- **Midnight wrap for `prayer_status_at_arrival`**: When `arrival_minutes < adhan_min` and the prayer window spans midnight, check if `arrival_minutes + 1440 <= period_end_min`; if so, treat `arrival_minutes += 1440` before comparing. This correctly handles arriving at 12:30am for an Isha window that opened at 8:30pm.

#### Trip Prayer Section Ordering

Prayer sections in the trip plan are ordered **chronologically relative to departure time**, not by canonical day order. A prayer that is already active at departure (e.g. Isha at 10 PM) must appear BEFORE a prayer that starts later in the trip (e.g. Fajr next morning). The sort key for each section is the adhan time of its first prayer, adjusted for overnight wrap:

- If the prayer started **before** departure AND its period has **not yet ended** at departure: sort by `adhan_m` (earliest adhan = first in the plan)
- If the prayer started **before** departure AND its period **ended** before departure (i.e. next-day occurrence): sort by `adhan_m + 1440`
- If the prayer starts **after** departure: sort by `adhan_m` as-is

**Example**: Departing at 10 PM — Maghrib+Isha (active, adhan=7 PM) appears first, then Fajr (next day, adhan=5 AM+1440) appears second. **Never insert Fajr at position 0 unconditionally.**

#### Prayed Prayer Auto-Refresh

When the user marks a prayer as prayed while a trip plan is already displayed, the frontend **automatically re-fetches the trip plan** with the updated `prayed_prayers` list. This ensures the plan reflects which prayers still need to be covered. The refresh is silent (no loading indicator unless it takes >2 seconds).

---

## Prayed Prayer Exclusion in Trip Planning

When the user marks a prayer as already performed today (`prayedToday` in the store), the trip planner must adjust the plan to exclude those prayers. The rules differ slightly between modes.

### Musafir Mode — Pair-Based Prayed Tracking

**In Musafir mode, the user always combines prayers in pairs.** The "have you prayed?" question is always asked at the pair level:
- "Have you prayed **Dhuhr + Asr**?" (not "have you prayed Dhuhr?" separately)
- "Have you prayed **Maghrib + Isha**?"
- "Have you prayed **Fajr**?" (Fajr has no pair)

**Consequence**: When a Musafir user plans a trip during Asr time and has NOT prayed the Dhuhr+Asr pair yet, the app should still offer combining options (Jam' Ta'kheer — pray both during Asr). There is no "period closed for Dhuhr" redirect in Musafir mode. The combining window stays open for the entire pair until the second prayer's period ends.

**This means the period-closed check (redirect to solo prayer2 when prayer1's standard window is technically closed) applies ONLY in Muqeem mode.**

### Both prayers in a pair already prayed

Omit the entire pair from the plan. No stops needed, no options shown.

### One prayer prayed, one remaining — Muqeem mode (no combining)

The prayed prayer is removed. The remaining prayer is treated as a **standalone single-stop**: plan for it within its own standard time window only.

- Example: User prayed Dhuhr. Show only Asr stops (from Asr adhan onwards). No "Dhuhr+Asr" pair shown.
- The option type is `solo_stop` — a single stop for one prayer, no combining language.

### One prayer prayed, one remaining — Musafir mode (combining allowed)

Since Musafir mode tracks the **pair** as a unit, the typical case is both prayed or neither prayed. However, if the app receives individual prayer states (e.g., from an older client), the same sequential inference applies:

| Case | Rule |
|---|---|
| **Dhuhr already prayed** | Plan Asr as a standalone stop (Asr adhan onward). No Jam' options. |
| **Asr already prayed** | **Infer Dhuhr is also done** (sequential logic — see below). Skip the entire Dhuhr+Asr pair. |
| **Maghrib already prayed** | Plan Isha as standalone. |
| **Isha already prayed** | **Infer Maghrib is also done** (sequential logic — see below). Skip the entire Maghrib+Isha pair. |

**Key principle**: Jam' combining requires both prayers to be pending. If one is done, the pair is broken and the remaining prayer is prayed in its own time only.

### Sequential Prayer Inference

If a user marks a later prayer as prayed, the earlier prayer in the same pair is implicitly also done (you cannot have performed Asr without having addressed Dhuhr first):

| Prayed | Implicit | Reason |
|---|---|---|
| **Asr** prayed | **Dhuhr** is also done | Sequential order — skip entire Dhuhr+Asr pair |
| **Isha** prayed | **Maghrib** is also done | Sequential order — skip entire Maghrib+Isha pair |
| **Dhuhr** prayed | **Fajr** is considered handled | Skip Fajr from planning (it's in the past) |

This inference is applied **before** building the trip plan: expand `prayed_prayers` with any implied prayers, then skip pairs where both prayers are covered.

### Implementation in `build_combination_plan`

Accept `prayed_prayers: set[str]` parameter. Apply sequential inference first:

```
# Sequential inference: second prayer prayed → first is also done → skip entire pair
IF prayer2 IN prayed_prayers:
    RETURN None  # both are handled (prayer1 was implicitly done before prayer2)

IF prayer1 IN prayed_prayers AND prayer2 IN prayed_prayers:
    RETURN None  # skip this pair entirely

IF prayer1 IN prayed_prayers:
    # Only build solo options for prayer2
    RETURN build_solo_plan(prayer2, ...)

# Neither prayed → normal full pair logic
```

The `solo_stop` option type has a single stop for one prayer, no `combination_label`, and the description makes no mention of combining.

---

## Timezone Handling

Timezone handling applies to **all** prayer timing calculations, regardless of whether Travel Mode is on.

### The Three Timezones to Track

1. **User's current timezone**: Where the user is located right now
2. **Mosque's timezone**: Where the target mosque is located
3. **Travel time consideration**: Time passes during travel, potentially crossing timezone boundaries

### Calculation Steps

1. Get user's current time in their timezone: `Intl.DateTimeFormat().resolvedOptions().timeZone`
2. Get mosque's timezone from its coordinates (lat/lng → timezone lookup)
3. Convert user's current time to mosque's timezone
4. Add travel duration to get arrival time in mosque's timezone
5. Compare arrival time to mosque's prayer times (already in mosque's timezone)
6. Display results to user in their own timezone

### Example

```
User: Los Angeles (PST, UTC-8), current time 10:00 AM PST
Mosque: Denver, CO (MST, UTC-7)
Dhuhr iqama at mosque: 1:15 PM MST
Travel time: 2 hours

Calculation:
- User departs: 10:00 AM PST
- User arrives: 12:00 PM PST = 1:00 PM MST (converted)
- Mosque iqama:  1:15 PM MST
- Arrives 15 min before iqama → Status 1: Can Catch With Imam ✅
```

---

## Configuration Parameters

### User-Configurable Settings

| Setting | Default | Description |
|---|---|---|
| Congregation window | 15 minutes | How long after iqama a user can still join |
| Travel buffer | 0 minutes | Extra buffer to account for delays |
| Travel mode | Off | Enable prayer combination rules |
| Search radius | 5 km | Radius for nearby mosque search |

### Mosque-Specific Data Required

- Adhan time for each prayer
- Iqama time for each prayer (mosque-specific, scraped from mosque website)
- Sunrise time (for Fajr period end calculation)
- Jumuah session times, imam details, khutba language (if available)

---

## Status Determination Pseudocode

```
FUNCTION get_catching_status(mosque, current_time, travel_minutes, travel_mode):

    arrival_time = current_time + travel_minutes

    FOR each relevant_prayer IN get_relevant_prayers(current_time):

        iqama = relevant_prayer.iqama_time
        period_end = relevant_prayer.period_end  // see get_period_end() below
        congregation_end = iqama + 15 minutes

        // Adjust times for Isha midnight wraparound (see special case)
        adjusted_current = adjust_for_isha_midnight(prayer, current_time, iqama, period_end)
        IF adjusted_current == MISSED:
            RETURN { status: MISSED_MAKE_UP }  // past Fajr — yesterday's Isha ended

        // Single prayer status (all comparisons use adjusted times)
        IF arrival_time <= iqama:
            status = CAN_CATCH_WITH_IMAM

        ELSE IF arrival_time <= congregation_end:
            status = CAN_CATCH_WITH_IMAM_IN_PROGRESS

        ELSE IF arrival_time < period_end:
            status = CAN_PRAY_SOLO_AT_MOSQUE

        ELSE IF current_time < period_end:
            status = PRAY_AT_NEARBY_CLEAN_LOCATION

        ELSE:
            status = MISSED_MAKE_UP

        // Travel mode additions (never replace the status above)
        IF travel_mode AND relevant_prayer.supports_combination:
            combination_options = get_combination_options(relevant_prayer, arrival_time, current_time)

    RETURN highest_priority_status + combination_options


FUNCTION get_period_end(prayer, schedule):
    Fajr    → schedule.sunrise
    Dhuhr   → schedule.asr_adhan
    Asr     → schedule.maghrib_adhan
    Maghrib → schedule.isha_adhan
    Isha    → schedule.fajr_adhan   // next day's Fajr; midnight wraparound applied separately


FUNCTION adjust_for_isha_midnight(prayer, current_minutes, adhan_min, period_end_min):
    // Only applies to Isha. For other prayers, return current_minutes unchanged.
    IF prayer != "isha" OR current_minutes >= adhan_min:
        RETURN current_minutes  // normal evening case, no adjustment needed

    fajr_min = schedule.fajr_adhan
    IF current_minutes < fajr_min:
        // Post-midnight, before Fajr — still valid Isha window
        RETURN current_minutes + 1440   // bump to "yesterday's" frame of reference
    ELSE:
        // After today's Fajr — yesterday's Isha has ended
        RETURN MISSED


FUNCTION get_relevant_prayers(current_time):
    // Priority order:
    // 1. Any prayer with congregation currently in progress
    // 2. Any prayer whose period is currently active
    // 3. Next upcoming prayer today
    // 4. Any missed prayers from today (make-up)
    // 5. Tomorrow's Fajr (only if all today's prayers are done)
```

---

## Testing Scenarios

### General

| Time | Condition | Expected Recommendation |
|---|---|---|
| 4:14 AM | Before Fajr adhan | Next prayer: Fajr at 5:30 AM |
| 6:30 AM | After Fajr adhan, before sunrise | Fajr — Status 1, 2, or 3 depending on travel time |
| 7:30 AM | After sunrise | Fajr is **missed** — Status 5: Make up missed Fajr |
| 9:00 PM | Isha iqama was 8:45 PM (15 min ago) | Status 3: Can pray Isha solo (period active until Fajr at 5:15 AM) |
| 9:30 PM | Isha iqama was 8:45 PM (45 min ago) | Status 3: Can still pray Isha solo (period active until Fajr at 5:15 AM) |
| 11:08 PM | Isha congregation long ended | Status 3: Can pray Isha solo until Fajr at 5:15 AM |
| Friday 12:45 PM | Jumuah khutba started 12:30 PM | Can catch Jumuah (partial sermon + prayer) |
| Friday 1:30 PM | Jumuah prayer ended | Missed Jumuah — can pray Dhuhr solo |
| Travel mode, 1:30 PM | Dhuhr period | "Can catch Dhuhr with Imam" + "Can combine Dhuhr+Asr (Early)" |
| Travel mode, 4:30 PM | Asr period, missed Dhuhr | "Can catch Asr with Imam" + "Can combine Dhuhr+Asr (Late)" |
| Route LA→SF, 11 AM | Dhuhr upcoming | Show multiple mosques along route with combination options |

### Isha Midnight Wraparound (Fajr 5:15 AM, Isha iqama 8:45 PM)

| Current time | Expected status | Reason |
|---|---|---|
| 8:30 PM | `can_catch_with_imam` | Before iqama |
| 9:10 PM | `can_pray_solo_at_mosque` — until 5:15 AM | Congregation ended, Isha period active |
| 11:08 PM | `can_pray_solo_at_mosque` — until 5:15 AM | Before midnight, still valid |
| 1:30 AM | `can_pray_solo_at_mosque` — until 5:15 AM, **with discouraged note** | After midnight, before Fajr — valid but makruh; note shown in message |
| 5:10 AM | `pray_at_nearby_location` | 5 min before Fajr, can't reach mosque in time |
| 5:20 AM | `missed_make_up` | Past Fajr adhan — Isha period has ended |
| 9:00 AM | `missed_make_up` | Daytime — yesterday's Isha long ended |

---

**This document is the ground truth for all prayer timing calculations. Any implementation discrepancy must be resolved in favor of this document.**
