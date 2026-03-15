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

### 2. Jumuah (Friday Prayer) Exception

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

### Standard Travel Mode (No Destination Set)

When travel mode is on but the user has no specific destination, show combination options in addition to the normal per-mosque status:

**Example — User in Dhuhr period**:
- Normal: "Can catch Dhuhr with Imam at Masjid Al-Noor"
- Travel addition: "+ Can also combine Dhuhr + Asr here (Early Combination — Jam' Taqdeem)"

**Example — User in Asr period, missed Dhuhr**:
- Normal: "Can catch Asr with Imam"
- Travel addition: "+ Can combine missed Dhuhr + Asr here (Late Combination — Jam' Ta'kheer)"

Combinations are shown **in addition to** the normal status — they never replace it.

### Route-Based Travel Mode (Destination Set)

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

#### Edge Cases in Route Mode

- If a prayer period will end before the user can reach any mosque on the route → show "Pray at nearby clean location before [time]"
- If no mosques are on the route for a given prayer pair → show that combination as unavailable
- If the user has already passed potential mosques → remove those options, update in real time
- Fajr during a road trip: If user is driving through the Fajr period, show nearest mosque or "find a clean rest stop"

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
        period_end = relevant_prayer.period_end  // next prayer's adhan, or sunrise for Fajr
        congregation_end = iqama + 15 minutes

        // Single prayer status
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
            // Append to result alongside status — not instead of it

    RETURN highest_priority_status + combination_options


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

| Time | Condition | Expected Recommendation |
|---|---|---|
| 4:14 AM | Before Fajr adhan | Next prayer: Fajr at 5:30 AM |
| 6:30 AM | After Fajr adhan, before sunrise | Fajr — Status 1, 2, or 3 depending on travel time |
| 7:30 AM | After sunrise | Fajr is **missed** — Status 5: Make up missed Fajr |
| 9:00 PM | Isha iqama was 8:41 PM (19 min ago) | Status 3: Can pray Isha solo at mosque (period active until Fajr) |
| 9:30 PM | Isha iqama was 8:41 PM (49 min ago) | Status 3: Can still pray Isha solo at mosque (period active until Fajr) |
| Friday 12:45 PM | Jumuah khutba started 12:30 PM | Can catch Jumuah (partial sermon + prayer) |
| Friday 1:30 PM | Jumuah prayer ended | Missed Jumuah — can pray Dhuhr solo |
| Travel mode, 1:30 PM | Dhuhr period | "Can catch Dhuhr with Imam" + "Can combine Dhuhr+Asr (Early)" |
| Travel mode, 4:30 PM | Asr period, missed Dhuhr | "Can catch Asr with Imam" + "Can combine Dhuhr+Asr (Late)" |
| Route LA→SF, 11 AM | Dhuhr upcoming | Show multiple mosques along route with combination options |

---

**This document is the ground truth for all prayer timing calculations. Any implementation discrepancy must be resolved in favor of this document.**
