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

### Standard Travel Mode (No Destination Set — Musafir at Current Location)

The user has already traveled to a location and is staying there for a while. They activate Musafir mode to enable prayer combining. The app shows the normal nearby-mosque list **plus** a combining section on each card.

Each pair section shows the contextually correct option based on the current time:

**Case A — Currently in first prayer's time (e.g., Dhuhr time, Asr hasn't started)**
> Only Jam' Taqdeem is shown:
> "Pray Dhuhr + Asr together now (during Dhuhr time)"
> → User can advance Asr into the current Dhuhr window

**Case B — First prayer's time has passed (e.g., Asr adhan has happened)**
> Only Jam' Ta'kheer is shown, with a prominent note:
> **"Dhuhr is not missed ✓"**
> "As Musafir, you can still pray Dhuhr + Asr together during Asr time"
> → The user must know the earlier prayer is NOT missed — they have until the end of Asr

**Case C — Both options still feasible (e.g., Dhuhr time, Asr adhan is soon)**
> Both shown: Taqdeem as primary ("pray now"), Ta'kheer as alternative ("or wait")

**Critical rule**: A Musafir's window for the first prayer effectively extends until the end of the second prayer's time. Dhuhr is not missed at Asr adhan; it can still be prayed (combined with Asr) until the end of Asr time. Same for Maghrib — not missed at Isha adhan for a Musafir.

### Route-Based Travel Mode (Destination Set)

When the user has a travel destination (entered in the `DestinationInput` bar that appears when travel mode is ON), the app enters **Route Mode**. In Route Mode:
- The normal mosque list is **replaced** by a **Travel Prayer Plan**.
- The plan is grouped into prayer pair sections (Fajr if applicable, Dhuhr+Asr, Maghrib+Isha).
- Each section shows all valid catching options so the user can choose the one that fits their schedule.

When the user has a travel destination, the app knows their **route** and can calculate arrival times at mosques along the way. This enables intelligent route-aware prayer planning.

The app should calculate multiple valid options and present them to the user so they can choose.

#### How It Works

1. User sets origin + destination
2. App identifies mosques along the route (within reasonable detour distance)
3. For each mosque, calculate estimated arrival time based on route progress
4. Determine which prayers will be active at each arrival time
5. Generate all valid catching options (single prayers and combinations)
6. Present the options grouped by prayer pair or individual prayer

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
| `pray_before` | Pray Before Leaving | One or both prayers are active at departure time — no road stop needed |
| `combine_early` | Jam' Taqdeem | Both prayers combined during the first prayer's time window (e.g. Dhuhr + Asr during Dhuhr) |
| `combine_late` | Jam' Ta'kheer | Both prayers combined during the second prayer's time window (e.g. Dhuhr + Asr during Asr) |
| `separate` | Separate Stops | Two stops: one for each prayer at the best available mosque |
| `at_destination` | Pray Near Destination | Prayer(s) still active upon arrival — find a mosque near the destination |
| `stop_for_fajr` | Stop for Fajr | Fajr-specific stop along the route |
| `no_option` | No Mosque Found | No mosque option feasible — pray at a clean rest stop |

#### Pseudocode: `build_combination_plan`

```
FUNCTION build_combination_plan(prayer1, prayer2, origin_schedule, route_mosques, departure_dt, arrival_dt, dest_schedule, timezone):

    dep_min = departure_dt in local minutes
    arr_min = arrival_dt in local minutes

    options = []

    // Pray before leaving
    s1 = prayer_status_at_arrival(prayer1, origin_schedule, dep_min)
    s2 = prayer_status_at_arrival(prayer2, origin_schedule, dep_min)
    IF s1 AND s2:
        options.append({ type: pray_before, prayers: [prayer1, prayer2], stops: [] })
    ELSE IF s1 only:
        options.append({ type: pray_before, prayers: [prayer1], stops: [] })

    // Combine Early (Jam' Taqdeem) — best mosque catchable during prayer1's window
    FOR mosque IN route_mosques sorted by minutes_into_trip:
        s = prayer_status_at_arrival(prayer1, mosque.schedule, mosque.local_arrival_minutes)
        IF s: options.append({ type: combine_early, stops: [mosque], prayers: [prayer1, prayer2] }); BREAK

    // Combine Late (Jam' Ta'kheer) — best mosque catchable during prayer2's window
    FOR mosque IN route_mosques sorted by minutes_into_trip:
        s = prayer_status_at_arrival(prayer2, mosque.schedule, mosque.local_arrival_minutes)
        IF s: options.append({ type: combine_late, stops: [mosque], prayers: [prayer1, prayer2] }); BREAK

    // Separate stops — find best mosque for each prayer independently
    best_p1, best_p2 = find_best_mosques_for(prayer1, prayer2, route_mosques)
    IF best_p1 AND best_p2:
        options.append({ type: separate, stops: [best_p1, best_p2] if different mosques else [best_p1] })

    // Pray near destination
    s1_dest = prayer_status_at_arrival(prayer1, dest_schedule, arr_min)
    s2_dest = prayer_status_at_arrival(prayer2, dest_schedule, arr_min)
    IF s1_dest OR s2_dest:
        options.append({ type: at_destination, prayers: [p for p in [prayer1, prayer2] if active at dest] })

    IF options is empty:
        options.append({ type: no_option, feasible: False })

    RETURN { pair, label, emoji, options }
```

#### Edge Cases in Route Mode

- If a prayer period will end before the user can reach any mosque on the route → show "Pray at nearby clean location before [time]"
- If no mosques are on the route for a given prayer pair → show that combination as unavailable
- If the user has already passed potential mosques → remove those options, update in real time
- Fajr during a road trip: If user is driving through the Fajr period, show nearest mosque or "find a clean rest stop"
- "Pray before leaving" (`pray_before`) is always checked first — it requires no detour

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
