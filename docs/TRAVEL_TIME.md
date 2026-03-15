# Travel Time Strategy

---

## Why Accuracy Matters

Travel time is load-bearing for the app's core feature. The decision "can I catch this prayer?" is calculated as:

```
arrival_time = current_time + travel_time_to_mosque
```

If travel time is wrong by 5+ minutes, the app gives wrong answers — telling users they can make it when they can't, or vice versa. This destroys trust immediately. Using rough approximations for the initial display and reserving precise routing for when the user needs it is the right trade-off.

---

## Tiered Routing Strategy

### Tier A: Initial List Load — Mapbox Matrix API (batch)

Used for: showing travel time on all mosque cards when the list first loads.

```
ONE API call → travel times to ALL N mosques simultaneously

Request:
  POST https://api.mapbox.com/directions-matrix/v1/mapbox/driving-traffic/
  coordinates: user_lng,user_lat;mosque1_lng,mosque1_lat;mosque2_lng,...
  sources: 0
  destinations: all
  annotations: duration

Response: matrix of durations in seconds
```

**Cost**: $2 / 1,000 elements
- 1 user search × 20 mosques = 20 elements = $0.00004 per search
- 10,000 daily active users × 30% cache miss rate = 60,000 elements/day = $0.12/day → ~**$4/month**

**Caching**: Cache key = (user grid cell 500m, time-of-day bucket 15min)
- Same user refreshing every few minutes → cache hit, no API call
- Different user in the same neighborhood at the same time → cache hit
- Effective cache hit rate: ~70%, reducing real cost further

```python
def get_cache_key(user_lat: float, user_lng: float) -> str:
    # Round to ~500m grid
    grid_lat = round(user_lat * 200) / 200  # 0.005 degree ≈ 500m
    grid_lng = round(user_lng * 200) / 200
    time_bucket = datetime.now().strftime('%H') + str(datetime.now().minute // 15)
    return f"matrix:{grid_lat}:{grid_lng}:{time_bucket}"
```

**Traffic**: Mapbox `driving-traffic` profile uses real-time traffic data. Maghrib at 7 PM during evening rush will show accurate congestion-affected times.

---

### Tier B: Selected Mosque — Mapbox Directions API (precise, live)

Used for: when user taps a mosque card to see full detail. One call, one route.

```
GET https://api.mapbox.com/directions/v5/mapbox/driving-traffic/
    {user_lng},{user_lat};{mosque_lng},{mosque_lat}
    ?access_token=...&overview=false
```

**Cost**: $1 / 1,000 requests → effectively free ($0/month for most usage levels)

**What it adds over the Matrix API**:
- More precise duration (direct A→B route vs. matrix approximation)
- Route summary (for showing on map if desired)
- Live refresh as user moves

**When to refresh**:
- On mosque selection (immediate)
- If user moves >300m from last calculation
- Every 10 minutes while mosque detail is open
- Never while mosque is not selected (no background drain)

---

### Tier C: Offline Approximation (fallback only)

Used for: when Mapbox is unavailable (API down, no network, rate limit hit). Never used as primary.

```python
import math

def haversine_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng/2)**2
    return R * 2 * math.asin(math.sqrt(a))

def estimate_travel_minutes(distance_km: float) -> int:
    """
    Rough urban estimate: straight-line distance × 1.4 (road factor) ÷ 35 km/h average urban speed.
    Adds 3 minutes baseline for traffic lights, parking, etc.
    Only used when Mapbox is unavailable.
    """
    road_km = distance_km * 1.4
    minutes = (road_km / 35) * 60 + 3
    return round(minutes)
```

When this fallback is used, the UI shows a visual indicator: `~12 min (estimated)` instead of `12 min`.

---

## Cost Analysis at Scale

| Daily Active Users | Daily Matrix Elements | Monthly Cost |
|---|---|---|
| 1,000 | 6,000 | $0.40 |
| 10,000 | 60,000 | $4.00 |
| 100,000 | 600,000 | $40.00 |
| 1,000,000 | 6,000,000 | $400.00 |

*Assumes 70% cache hit rate and 20 mosques per search.*

At 1 million DAU, routing costs $400/month — a trivial line item for an app at that scale.

**Comparison to Google Maps Distance Matrix**:
- Same 1M DAU with Google: $0.01/element × 6M elements = **$60,000/month**
- Mapbox: **$400/month**
- Mapbox is 150× cheaper.

---

## Why Not Free Routing

### OSRM (self-hosted)
- No real-time traffic data
- A 10-minute drive at 7 PM rush hour could be 20+ minutes
- For Maghrib (evening rush) this gives dangerously wrong answers
- Self-hosting adds infrastructure cost and ops burden

### OpenRouteService (free tier)
- 2,000 requests/day free — exceeded by any meaningful user count
- No real-time traffic

### Straight-line approximation only
- ±25–40% error in cities
- For a 10-minute drive: could be off by 4 minutes
- "You can make it" when you can't = broken core feature

**Verdict**: Mapbox at $4/month for 10k DAU is the correct choice. Accuracy is not optional for this specific use case.

---

## Implementation Notes

### Mapbox Token Security

The Mapbox token used for the Matrix/Directions API lives in the **backend** (never exposed to frontend). The frontend uses a separate, restricted Mapbox token for map tile display only (no directions access).

```
Backend .env:   MAPBOX_SERVER_TOKEN=sk.eyJ1...  (full access, never leaves server)
Frontend .env:  VITE_MAPBOX_TOKEN=pk.eyJ1...    (tiles only, URL-restricted)
```

### Request Deduplication

Multiple users in the same area at the same time should not trigger duplicate API calls.

```python
async def get_travel_times_cached(
    user_lat: float,
    user_lng: float,
    mosque_coords: list[tuple[float, float]]
) -> dict:
    cache_key = get_cache_key(user_lat, user_lng)

    cached = await redis.get(cache_key)
    if cached:
        return json.loads(cached)

    # Fetch from Mapbox
    result = await mapbox_matrix_api(user_lat, user_lng, mosque_coords)

    # Cache for 15 minutes
    await redis.setex(cache_key, 900, json.dumps(result))
    return result
```

For the initial version without Redis, use an in-process LRU cache with TTL — not as good but functional.
