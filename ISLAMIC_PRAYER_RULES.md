# Islamic Prayer Timing Rules - Ground Truth Documentation

This document serves as the authoritative reference for understanding Islamic prayer timing rules as implemented in the Catch a Prayer application.

## Overview

There are **5 daily prayers** in Islam, each with specific timing rules that determine when a Muslim can "catch" a prayer at a mosque.

## The Five Daily Prayers

1. **Fajr** (Dawn Prayer)
2. **Dhuhr** (Noon Prayer) 
3. **Asr** (Afternoon Prayer)
4. **Maghrib** (Sunset Prayer)
5. **Isha** (Night Prayer)

## Key Timing Concepts

### Adhan Time vs Iqama Time

- **Adhan Time**: The official start time of a prayer period (call to prayer)
- **Iqama Time**: The time when the Imam leads the congregational prayer at the mosque
- **Gap Between Adhan and Iqama**: Varies by mosque (typically 5-15 minutes)

### Prayer "Catching" Status Definitions

A user can be in one of several states relative to catching a prayer:

#### 1. **Can Catch With Imam** (Optimal)
- User arrives at mosque **before** or **at** Iqama time
- User joins the congregational prayer led by the Imam
- This is the preferred way to pray

#### 2. **Can Catch After Imam Started** (Good)  
- User arrives **after** Iqama time but **within congregation window**
- **Congregation Window**: Configurable parameter (default: 10-15 minutes after Iqama)
- User can still join the ongoing congregational prayer
- Prayer typically lasts 10-15 minutes, so there's a window to join

#### 3. **Can Catch Solo** (Acceptable)
- User arrives **after congregation window** but **within prayer period**
- User prays individually (solo) at the mosque
- Still within the valid time period for that prayer

#### 4. **Can Make Up For Prayer** (Missed Prayers)
- Prayer was missed during its permissible time
- Can and should still be performed to make up for the missed prayer
- Not "valid" timing but necessary to fulfill religious obligation
- **Islamic Practice**: Typically performed after catching the next prayer with Imam (e.g., catch Asr with Imam, then pray missed Dhuhr solo)
- Applies to any missed prayers (e.g., Fajr after sunrise, missed Dhuhr, etc.)

#### 5. **Cannot Catch at This Mosque** (Find Alternative)
- Prayer period will end before user can arrive at this mosque
- **Recommendation**: App advises user to pray elsewhere:
  - Find a clean, quiet parking lot nearby
  - Use an empty, clean room in a building
  - Any suitable clean place for prayer
- **Important**: Prayer should still be performed within its valid time period

## General Prayer Period Rules

**Standard Rule**: Each prayer period starts at its Adhan time and ends at the next prayer's Adhan time.

### Example Timeline:
```
Fajr Adhan (5:30 AM) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Dhuhr Adhan (12:30 PM)
                     [────────────── Fajr Prayer Period ──────────────────]

Dhuhr Adhan (12:30 PM) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Asr Adhan (4:00 PM)  
                        [──────────── Dhuhr Prayer Period ────────────────]
```

## Special Cases and Exceptions

### 1. Fajr Prayer Exception

Fajr has **two distinct periods**:

#### Normal Fajr Period
- **Start**: Fajr Adhan time
- **End**: Sunrise (Shorooq) time
- **Status**: Normal prayer

#### Missed Fajr Period (Make Up For Prayer)
- **Start**: Sunrise (Shorooq) time
- **End**: Dhuhr Adhan time
- **Status**: Missed prayer - can be made up for but NOT within permissible time
- **Note**: Similar to missing any other prayer - should be made up for but is not "valid" timing

```
Fajr Adhan ━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Sunrise ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Dhuhr Adhan
           [── Normal Fajr Period ──]      [───── Missed Fajr (Make-up) ─────]
```

### 2. Jumuah (Friday) Prayer Exception

**Jumuah replaces Dhuhr prayer on Fridays only**

#### Jumuah Prayer Components:
1. **Khutba (Sermon)**: 30-45 minutes (varies by mosque)
2. **Jumuah Prayer**: 10-15 minutes
3. **Total Duration**: ~45 minutes (typical), rarely up to ~60 minutes
4. **Data Source Note**: Most mosque websites don't specify duration - app should indicate this is an estimated duration

#### Jumuah Timing Rules:

**Can Catch Jumuah (Optimal)**:
- Arrive **before** Khutba (sermon) starts
- User attends full sermon + prayer

**Can Catch Jumuah Delayed**:
- Arrive **during** Khutba but **before** it ends  
- User catches partial sermon + full prayer
- Still counts as Jumuah prayer

**Cannot Catch Jumuah (Missed)**:
- Arrive **after** Khutba ends
- User can only pray Dhuhr individually
- **Note**: Missing Jumuah is highly discouraged in Islamic faith

#### Multiple Jumuah Sessions:
- Some mosques offer **multiple Jumuah sessions** at different times
- Provides flexibility for working Muslims
- Each session has its own Khutba + Prayer

### 3. Travel Mode - Prayer Combination Rules

**When Travel Mode is Enabled**: Islam allows travelers to combine certain prayers for convenience.

#### Important Notes:
- **Fajr prayer cannot be combined** with any other prayer
- Only applies to the other **4 prayers** (Dhuhr, Asr, Maghrib, Isha)
- Both "early" and "late" combinations are equally acceptable in Islam

#### Combination Rules:

##### Dhuhr + Asr Combination:
- **Early Combination (Jam' Taqdeem)**: Pray both Dhuhr and Asr during Dhuhr period
- **Late Combination (Jam' Ta'kheer)**: Pray both Dhuhr and Asr during Asr period

```
Dhuhr Adhan ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Asr Adhan ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Maghrib Adhan
             [── Can pray Dhuhr + Asr (Early) ──]                                        [── Can pray Dhuhr + Asr (Late) ──]
```

##### Maghrib + Isha Combination:
- **Early Combination (Jam' Taqdeem)**: Pray both Maghrib and Isha during Maghrib period
- **Late Combination (Jam' Ta'kheer)**: Pray both Maghrib and Isha during Isha period

```
Maghrib Adhan ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Isha Adhan ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ Fajr Adhan
               [── Can pray Maghrib + Isha (Early) ──]                                     [── Can pray Maghrib + Isha (Late) ──]
```

#### Travel Mode App Behavior:

When user has travel mode enabled, the app should show additional options:

**Example Scenarios**:

1. **User can arrive during Dhuhr period**:
   - Show: "Can catch Dhuhr + Asr (Early Combination)" 
   - Arabic term: "Jam' Taqdeem"

2. **User can arrive during Asr period but missed Dhuhr**:
   - Show: "Can catch Dhuhr + Asr (Late Combination)"
   - Arabic term: "Jam' Ta'kheer"  

3. **User can arrive during Maghrib period**:
   - Show: "Can catch Maghrib + Isha (Early Combination)"

4. **User can arrive during Isha period but missed Maghrib**:
   - Show: "Can catch Maghrib + Isha (Late Combination)"

## Timezone Handling Rules

### Automatic Multi-Timezone Support

**IMPORTANT**: Timezone calculations are performed automatically for ALL prayer timing calculations, regardless of whether Travel Mode is enabled or not.

**Travel Mode** only affects prayer combination logic (Dhuhr+Asr, Maghrib+Isha). Timezone handling is a core feature that applies to every prayer timing calculation.

The app must always handle **three different timezones**:

1. **User's Current Timezone**: Where the user is located now
2. **Mosque's Timezone**: Where the target mosque is located  
3. **Travel Time Consideration**: Time will pass during travel, potentially crossing timezone boundaries

### Timezone Calculation Logic:

#### Step 1: Establish Reference Times
- **User Current Time**: User's local time in their current timezone
- **Mosque Prayer Times**: All prayer times (Adhan, Iqama) in mosque's local timezone
- **Travel Duration**: Time required to reach mosque (from routing service)

#### Step 2: Calculate Arrival Scenarios
- **User's Departure Time**: Current time in user's timezone
- **Estimated Arrival Time**: Departure time + travel duration
- **Arrival Time in Mosque Timezone**: Convert arrival time to mosque's timezone

#### Example Scenario:
```
User Location: Los Angeles, CA (PST - UTC-8)
User Current Time: 10:00 AM PST

Target Mosque: Denver, CO (MST - UTC-7) 
Mosque Dhuhr Iqama: 1:15 PM MST
Travel Time: 2 hours

Calculation:
- User departs: 10:00 AM PST
- User arrives: 12:00 PM PST = 1:00 PM MST (converted to mosque timezone)
- Mosque Iqama: 1:15 PM MST
- Result: User arrives 15 minutes before Iqama ✅ "Can Catch With Imam"
```

#### Step 3: Account for Timezone Boundaries During Travel

**Complex Case**: Travel crosses timezone boundaries
```
User Location: Las Vegas, NV (PST - UTC-8)
Target Mosque: Phoenix, AZ (MST - UTC-7, no DST)
Travel Time: 5 hours (crossing timezone boundary during travel)

Calculation must account for:
- User's departure timezone
- Timezone change during travel
- Final arrival time in mosque's timezone
```

### Implementation Requirements:

#### Timezone Data Needed:
1. **User's Current Timezone**: From device/client (`Intl.DateTimeFormat().resolvedOptions().timeZone`)
2. **Mosque's Timezone**: From mosque location coordinates (latitude/longitude → timezone lookup)
3. **Travel Route Timezone Changes**: Advanced feature for routes crossing multiple timezones

#### Calculation Priority:
1. **Always calculate prayer catchability in the mosque's local timezone**
2. **Convert user's current time to mosque timezone for comparison**
3. **Factor in travel time and any timezone changes during travel**
4. **Display results to user in their preferred timezone (usually current location)**

## Configuration Parameters

### User-Configurable Settings:
1. **Congregation Window**: How long after Iqama a user can still join (default: 10-15 minutes)
2. **Travel Buffer**: Extra time to account for delays (optional)
3. **Prayer Duration**: How long prayers typically last (default: 10-15 minutes)
4. **Travel Mode**: Enable prayer combination rules for travelers

### Mosque-Specific Data Required:
1. **Adhan times** for each prayer
2. **Iqama times** for each prayer (varies by mosque)
3. **Sunrise (Shorooq) time** for Fajr calculations
4. **Jumuah session times** (if applicable)

## Implementation Logic Flow

### For Any Prayer Check:

1. **Get current time** and **prayer times** for the mosque
2. **Check if Travel Mode is enabled**
3. **Determine which prayer period** we're currently in
4. **Check travel time** to mosque
5. **Calculate arrival time** at mosque
6. **Determine catching status** based on arrival time vs prayer timing windows
7. **If Travel Mode enabled**: Check combination opportunities

### Status Determination Logic:

```
IF travel_mode_enabled AND prayer_supports_combination:
    // Check combination opportunities first
    IF can_do_early_combination:
        status = "Can Catch [Prayer1] + [Prayer2] (Early Combination)"
    ELSE IF can_do_late_combination:
        status = "Can Catch [Prayer1] + [Prayer2] (Late Combination)"
    
// Standard single prayer logic
IF arrival_time <= iqama_time:
    status = "Can Catch With Imam"
    
ELSE IF arrival_time <= (iqama_time + congregation_window):
    status = "Can Catch After Imam Started"
    
ELSE IF arrival_time <= prayer_period_end:
    status = "Can Catch Solo"
    
ELSE IF prayer has delayed_period AND arrival_time <= delayed_period_end:
    status = "Can Catch Delayed"
    
ELSE:
    status = "Cannot Catch at This Mosque - Pray Nearby"
```

## Testing Examples

### Test Case: User at 4:14 AM
- **Expected Result**: Next catchable prayer should be **Fajr** (not Dhuhr)
- **Reason**: 4:14 AM is before Fajr Adhan time, so Fajr is the next upcoming prayer

### Test Case: User at 6:30 AM (after Fajr, before sunrise)  
- **Expected Result**: **Fajr** can still be caught (normal period)
- **Status**: "Can Catch Solo" or "Can Catch With Imam" depending on Iqama time

### Test Case: User at 7:30 AM (after sunrise, before Dhuhr)
- **Expected Result**: **Fajr** can be caught delayed
- **Status**: "Can Catch Delayed"

### Test Case: Friday 12:00 PM 
- **Expected Result**: **Jumuah** (not Dhuhr)
- **Status**: Depends on Khutba start time and user's arrival time

### Test Case: Travel Mode - User at 1:30 PM (Dhuhr period)
- **Expected Result**: "Can catch Dhuhr + Asr (Early Combination)" if enabled
- **Standard Mode**: Just "Can catch Dhuhr"

### Test Case: Travel Mode - User at 4:30 PM (Asr period, missed Dhuhr)
- **Expected Result**: "Can catch Dhuhr + Asr (Late Combination)" if enabled  
- **Standard Mode**: Just "Can catch Asr"

---

**This document serves as the ground truth for all prayer timing calculations in the application. Any implementation should reference and comply with these rules.**