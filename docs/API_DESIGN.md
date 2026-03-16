# API Design

FastAPI backend. All endpoints return JSON. All timestamps are ISO 8601. Times are always in the mosque's local timezone unless noted.

---

## Base URL

```
Development:  http://localhost:8000
Production:   https://api.catchaprayer.app
```

---

## Endpoints

### `GET /health`

Health check.

```json
// Response 200
{
  "status": "healthy",
  "database": true,
  "scraping_pipeline": true,
  "timestamp": "2024-09-06T14:30:00Z"
}
```

---

### `POST /api/mosques/nearby`

Find mosques near a location and return prayer catching status for each.

**Request**:
```json
{
  "latitude": 35.7796,
  "longitude": -78.6382,
  "radius_km": 10,
  "client_timezone": "America/New_York",
  "client_current_time": "2024-09-06T14:30:00.000Z",
  "travel_mode": false,
  "travel_destination_lat": null,
  "travel_destination_lng": null
}
```

| Field | Required | Description |
|---|---|---|
| `latitude` | Yes | User's current latitude |
| `longitude` | Yes | User's current longitude |
| `radius_km` | No (default 10) | Search radius |
| `client_timezone` | Yes | IANA timezone string from device |
| `client_current_time` | Yes | ISO 8601 from client clock |
| `travel_mode` | No (default false) | Enable combination prayer recommendations |
| `travel_destination_lat/lng` | No | For route-based recommendations |

**Response**:
```json
{
  "mosques": [
    {
      "id": "uuid",
      "name": "Masjid Al-Noor",
      "location": {
        "latitude": 35.7812,
        "longitude": -78.6401,
        "address": "123 Main St, Raleigh, NC 27601"
      },
      "timezone": "America/New_York",
      "distance_meters": 420,
      "travel_time_minutes": 12,
      "travel_time_source": "mapbox_matrix",
      "phone": "+1-919-555-0100",
      "website": "https://masjidalnoor.org",
      "has_womens_section": true,
      "wheelchair_accessible": true,
      "next_catchable": {
        "prayer": "asr",
        "status": "can_catch_with_imam",
        "status_label": "Can catch with Imam",
        "message": "Can catch Asr with Imam — leave by 4:13 PM",
        "urgency": "normal",
        "iqama_time": "16:25",
        "adhan_time": "16:15",
        "arrival_time": "16:22",
        "minutes_until_iqama": 23,
        "leave_by": "16:13",
        "period_ends_at": "18:47"
      },
      "travel_combinations": [],
      "prayers": [
        {
          "prayer": "fajr",
          "adhan_time": "05:31",
          "iqama_time": "05:50",
          "adhan_source": "mosque_website_html",
          "iqama_source": "mosque_website_html",
          "adhan_confidence": "high",
          "iqama_confidence": "high",
          "data_freshness": "3 days ago"
        },
        {
          "prayer": "dhuhr",
          "adhan_time": "12:45",
          "iqama_time": "12:55",
          "adhan_source": "mosque_website_html",
          "iqama_source": "mosque_website_html",
          "adhan_confidence": "high",
          "iqama_confidence": "high",
          "data_freshness": "3 days ago"
        }
        // ... asr, maghrib, isha
      ],
      "sunrise": "06:28",
      "jumuah_sessions": [
        {
          "session_number": 1,
          "khutba_start": "12:30",
          "prayer_start": "13:00",
          "imam_name": "Sheikh Ahmed Al-Farsi",
          "language": "English",
          "special_notes": null,
          "booking_required": false,
          "booking_url": null
        },
        {
          "session_number": 2,
          "khutba_start": "13:30",
          "prayer_start": "14:00",
          "imam_name": null,
          "language": null,
          "special_notes": null,
          "booking_required": false,
          "booking_url": null
        }
      ]
      // Note: jumuah_sessions is only populated on Fridays. The backend
      // queries the jumuah_sessions table only when mosque_today.weekday() == 4.
      // On all other days it always returns [].
    }
  ],
  "user_location": {
    "latitude": 35.7796,
    "longitude": -78.6382
  },
  "request_time": "2024-09-06T14:30:00.000Z"
}
```

**Catching status values**:

| `status` | Description |
|---|---|
| `can_catch_with_imam` | Arrives before or at iqama time |
| `can_catch_with_imam_in_progress` | Arrives during congregation window. Only returned when `current_time >= iqama_time` (congregation has actually started) — not merely when arrival would be after iqama. |
| `can_pray_solo_at_mosque` | Congregation ended, prayer period still active |
| `pray_at_nearby_location` | Cannot reach mosque before period ends, period still active |
| `missed_make_up` | Prayer period has ended |
| `upcoming` | Prayer period has not started yet |

**`next_catchable` (deprecated — kept for backwards compat)**:

Single most urgent prayer. Replaced by `catchable_prayers` for UI use.

**`catchable_prayers` array**:

All prayers with an actionable or imminent status, ordered by prayer time. Returned alongside `next_catchable`. Each entry has the same shape as `next_catchable`.

Inclusion rules:
- Include `can_catch_with_imam`, `can_catch_with_imam_in_progress` always
- Include `can_pray_solo_at_mosque` and `pray_at_nearby_location` always (prayer period still active)
- Include `upcoming` only if adhan is within 2 hours
- Exclude `missed_make_up` (prayer period over — nothing actionable)
- If every prayer has passed, return one `missed_make_up` entry for the most recent prayer

**`sunrise` field**:

`"sunrise"` is the astronomical sunrise time (Shorooq), which marks the end of the Fajr prayer period. It comes from the `prayer_schedules.sunrise` column, calculated by the `praytimes` library. It is displayed in the mosque detail sheet as "Shorooq" between Fajr and Dhuhr.

**Message formats per status** (all include prayer name and actionable timing):

| Status | Message format |
|---|---|
| `upcoming` — can reach before iqama | `"Asr in 10 min — leave by 4:13 PM to catch with Imam"` |
| `upcoming` — can't reach iqama but can pray solo | `"Asr in 10 min — leave by 4:40 PM to pray solo at mosque"` |
| `can_catch_with_imam` | `"Can catch Asr with Imam — leave by 4:13 PM"` |
| `can_catch_with_imam_in_progress` | `"Congregation started 5 min ago — leave now to join"` |
| `can_pray_solo_at_mosque` | `"Congregation ended for Dhuhr — can pray solo until 4:40 PM"` |
| `pray_at_nearby_location` | `"Cannot reach mosque before Asr ends — pray where you are"` |
| `missed_make_up` | `"Dhuhr has ended — make it up"` |

**Urgency values**:

| `urgency` | Meaning |
|---|---|
| `high` | Congregation in progress or <15 min to iqama |
| `normal` | Catchable but not urgent |
| `low` | Solo prayer or future prayer |

---

### `GET /api/mosques/{mosque_id}`

Full mosque detail including complete prayer schedule and Jumuah sessions.

**Query params**:
- `date` (optional): `YYYY-MM-DD`, defaults to today
- `client_timezone` (required)
- `client_current_time` (required)

**Response**: Full mosque object as above, plus full `prayers` array for the date and `jumuah_sessions` for the upcoming Friday.

---

### `GET /api/mosques/{mosque_id}/schedule`

Monthly prayer schedule for a mosque.

**Query params**:
- `year`: integer
- `month`: integer (1-12)

**Response**:
```json
{
  "mosque_id": "uuid",
  "mosque_name": "Masjid Al-Noor",
  "year": 2024,
  "month": 9,
  "schedule": [
    {
      "date": "2024-09-01",
      "fajr_adhan": "05:35", "fajr_iqama": "05:55",
      "dhuhr_adhan": "12:45", "dhuhr_iqama": "12:55",
      "asr_adhan": "16:10", "asr_iqama": "16:20",
      "maghrib_adhan": "19:28", "maghrib_iqama": "19:33",
      "isha_adhan": "20:55", "isha_iqama": "21:10",
      "sunrise": "06:32",
      "sources": {
        "fajr_adhan": "mosque_website_html",
        "fajr_iqama": "mosque_website_html"
        // ...
      }
    }
    // ... one entry per day
  ],
  "data_source": "mosque_website_html",
  "last_scraped": "2024-09-03T02:15:00Z"
}
```

---

### `POST /api/notifications/subscribe`

Register for push notifications.

**Request**:
```json
{
  "push_platform": "webpush",
  "vapid_endpoint": "https://fcm.googleapis.com/...",
  "vapid_p256dh": "base64...",
  "vapid_auth": "base64...",
  "location_lat": 35.78,
  "location_lng": -78.64,
  "timezone": "America/New_York",
  "favorite_mosque_id": "uuid or null",
  "preferences": {
    "fajr":    { "enabled": true, "before_adhan_min": 30, "before_iqama_min": 15 },
    "dhuhr":   { "enabled": true, "before_adhan_min": 15, "before_iqama_min": 10 },
    "asr":     { "enabled": true, "before_adhan_min": 15, "before_iqama_min": 10 },
    "maghrib": { "enabled": true, "before_adhan_min": 15, "before_iqama_min": 5  },
    "isha":    { "enabled": true, "before_adhan_min": 15, "before_iqama_min": 10 },
    "jumuah":  { "enabled": true, "before_khutba_min": 60 },
    "quiet_hours_start": "23:00",
    "quiet_hours_end": "04:30",
    "fajr_override_quiet": true,
    "travel_buffer_min": 5
  }
}
```

**Response 201**:
```json
{ "subscription_id": "uuid", "status": "registered" }
```

---

### `PUT /api/notifications/subscribe/{subscription_id}`

Update notification preferences or location.

**Request**: Same shape as POST, all fields optional.

---

### `DELETE /api/notifications/subscribe/{subscription_id}`

Unsubscribe from all notifications.

---

### `POST /api/spots/nearby`

Find community prayer spots near a location. Returns active spots first, pending spots (with disclaimer) second.

**Request**:
```json
{
  "latitude": 37.368,
  "longitude": -122.036,
  "radius_km": 10
}
```

**Response**:
```json
{
  "spots": [
    {
      "id": "uuid",
      "name": "Sunnyvale Public Library — Quiet Room",
      "spot_type": "library",
      "location": {
        "latitude": 37.371,
        "longitude": -122.040,
        "address": "665 W Olive Ave, Sunnyvale, CA 94086"
      },
      "distance_meters": 380,
      "has_wudu_facilities": true,
      "gender_access": "all",
      "is_indoor": true,
      "operating_hours": "Mon-Sat 10am-9pm, Sun 12pm-5pm",
      "notes": "Quiet study room on second floor, usually empty",
      "status": "active",
      "verification_count": 7,
      "rejection_count": 0,
      "verification_label": "Verified by 7 users",
      "last_verified_at": "2024-09-01T18:30:00Z"
    },
    {
      "id": "uuid",
      "name": "Yahoo Campus Building D — Prayer Room",
      "spot_type": "campus",
      "status": "pending",
      "verification_count": 1,
      "verification_label": "Reported by 1 user — not yet verified",
      ...
    }
  ]
}
```

---

### `POST /api/spots`

Submit a new prayer spot.

**Request**:
```json
{
  "name": "Safeway Sunnyvale — Corner Deli",
  "spot_type": "other",
  "latitude": 37.365,
  "longitude": -122.033,
  "address": "819 E El Camino Real, Sunnyvale, CA 94087",
  "has_wudu_facilities": false,
  "gender_access": "all",
  "is_indoor": true,
  "operating_hours": "6am-midnight",
  "notes": "Quiet corner near deli section, manager is accommodating",
  "session_id": "anon-device-hash"
}
```

**Response 201**:
```json
{
  "spot_id": "uuid",
  "status": "pending",
  "message": "Thank you! Your spot has been submitted. It will appear once verified by the community."
}
```

---

### `POST /api/spots/{spot_id}/verify`

Submit a verification or rejection for a prayer spot.

**Request**:
```json
{
  "session_id": "anon-device-hash",
  "is_positive": true,
  "attributes": {
    "has_prayer_space": true,
    "has_wudu": false,
    "gender_access": "all",
    "is_indoor": true
  }
}
```

**Response 200**:
```json
{
  "spot_id": "uuid",
  "verification_count": 4,
  "rejection_count": 0,
  "status": "active",
  "verification_label": "Verified by 4 users"
}
```

Returns `409 Conflict` if this `session_id` has already verified this spot.

---

### `GET /api/settings`

Get default user settings.

**Response**:
```json
{
  "default_radius_km": 10,
  "congregation_window_minutes": 15,
  "travel_buffer_minutes": 5,
  "show_adhan_times": true,
  "show_iqama_times": true,
  "show_data_source": true,
  "calculation_method": "ISNA"
}
```

---

## Error Response Format

All errors follow this structure:

```json
{
  "error": "mosque_not_found",
  "message": "No mosque found with ID: abc123",
  "status_code": 404
}
```

Common error codes:

| Code | HTTP Status | Meaning |
|---|---|---|
| `invalid_location` | 400 | Coordinates outside US/Canada bounds |
| `mosque_not_found` | 404 | No mosque with given ID |
| `no_mosques_found` | 404 | No mosques within search radius |
| `routing_unavailable` | 503 | Mapbox API unavailable, fallback used |
| `prayer_data_unavailable` | 503 | No prayer data for this mosque/date |

---

## Rate Limiting

```
/api/mosques/nearby:    30 requests/minute per IP
All other endpoints:    60 requests/minute per IP
```

Headers returned:
```
X-RateLimit-Limit: 30
X-RateLimit-Remaining: 28
X-RateLimit-Reset: 1725634800
```

---

## Data Source Transparency

Every time field in every response includes a `_source` and `_confidence` field. The frontend must display this to the user. Never silently show estimated or calculated data without disclosure.

Source label strings for UI display:

```python
SOURCE_LABELS = {
    "mosque_website_html":  "From mosque website",
    "mosque_website_js":    "From mosque website",
    "mosque_website_image": "From mosque schedule (image)",
    "mosque_website_pdf":   "From mosque schedule (PDF)",
    "islamicfinder":        "From IslamicFinder",
    "aladhan_mosque_db":    "From Aladhan database",
    "user_submitted":       "Community-submitted",
    "calculated":           "Calculated (astronomical) — verify with mosque",
    "estimated":            "Estimated — congregation time not confirmed",
}
```
