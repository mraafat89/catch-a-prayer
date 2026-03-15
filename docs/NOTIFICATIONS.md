# Push Notifications Design

---

## Overview

Push notifications tell the user:
1. A prayer is coming up soon
2. They can catch a congregation right now if they leave immediately
3. A prayer period is about to end

All notifications are optional and fully configurable per prayer.

---

## Platform Strategy

### Phase 1: Progressive Web App (PWA) with Web Push

- Works on Android (Chrome) natively — no app store needed
- Works on iOS 16.4+ when app is added to home screen
- Uses Web Push API + Service Workers + VAPID keys
- Backend sends via Firebase Cloud Messaging (FCM) free tier
- Deploy fast, no app store review

### Phase 2: Capacitor Wrapper (Native App)

- Same React codebase wrapped with Capacitor
- Native iOS (APNs) + Android (FCM) push support
- Most reliable notification delivery
- Required for iOS notification reliability at scale
- Publish to App Store + Google Play

**The React/TypeScript code is identical for both phases.** Only the push registration and receive layer changes with Capacitor.

---

## Notification Types

### Type 1: Pre-Adhan Reminder

Fires X minutes before adhan (user configurable: 15/30/45/60 min).

```
Title:  "Asr in 30 minutes"
Body:   "Masjid Al-Noor is 12 min away — you can make it with the Imam."
Action: Open app to mosque detail
```

### Type 2: Pre-Iqama Reminder

Fires X minutes before iqama (user configurable: 5/10/15/20 min).

```
Title:  "Asr congregation in 10 minutes"
Body:   "Islamic Center of Raleigh — Iqama at 4:25 PM. Leave now (12 min away)."
Action: Open app → navigate prompt
```

### Type 3: Leave-Now Alert *(the core feature)*

Fires at exactly the right moment when user must leave immediately to catch the Imam. Calculated as:

```
send_at = iqama_time - travel_time - user_buffer_minutes - 2 min pre-alert
```

```
Title:  "⚡ Leave now for Maghrib"
Body:   "Congregation at Al-Farooq starts in 14 min. You're 12 min away. Leave now."
Action: Open app → navigate prompt
```

This notification is only sent if the user has a registered location (home, work, or current known position).

### Type 4: Congregation In Progress

Fires when congregation has started but is still catchable (within the 15-min congregation window).

```
Title:  "🕌 Isha in progress — join now"
Body:   "Al-Farooq Masjid — Imam started 4 min ago. 8 min away — you can still join."
Action: Open app → navigate prompt
```

### Type 5: Prayer Period Ending

Optional. For users who want a final reminder that the prayer period is about to close.

```
Title:  "⚠️ Asr ends in 20 minutes"
Body:   "Cannot reach a mosque in time? Find a clean nearby location to pray."
Action: Open app
```

### Type 6: Jumuah Reminder

Fires on Fridays based on user's preferred mosque's Jumuah schedule.

```
Title:  "Jumuah in 1 hour"
Body:   "Masjid Al-Noor — Khutba at 1:00 PM
         Sheikh Ahmed · 'The Importance of Brotherhood' · English"
Action: Open app to mosque Jumuah detail
```

---

## Notification Calculation Logic

Notification times are calculated server-side nightly and stored as scheduled send times.

```python
def schedule_notifications_for_user(subscription: PushSubscription, date: date):
    """
    Calculate and schedule all notifications for a user for the given date.
    Called nightly for the next day.
    """
    prefs = subscription.preferences
    tz = ZoneInfo(subscription.timezone)
    lat = subscription.location_lat
    lng = subscription.location_lng

    # Get prayer times for user's location
    prayer_times = calculate_prayer_times(lat, lng, date)

    # Get nearest relevant mosque(s)
    nearest_mosques = get_nearest_mosques(lat, lng, limit=3)

    for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']:
        prayer_prefs = prefs[prayer]
        if not prayer_prefs['enabled']:
            continue

        adhan_time = prayer_times[f'{prayer}_adhan']
        mosque = nearest_mosques[0]  # or favorite mosque if set
        iqama_time = mosque.prayer_schedule[f'{prayer}_iqama'] or adhan_time + estimated_offset

        # Travel time to nearest mosque (from cached Mapbox estimate or approximation)
        travel_minutes = get_cached_travel_time(lat, lng, mosque.lat, mosque.lng)

        # Type 1: Pre-adhan
        if prayer_prefs.get('before_adhan_min'):
            send_at = adhan_time - timedelta(minutes=prayer_prefs['before_adhan_min'])
            if not in_quiet_hours(send_at, prefs, prayer):
                schedule_push(subscription, send_at, build_pre_adhan_notification(prayer, mosque))

        # Type 2: Pre-iqama
        if prayer_prefs.get('before_iqama_min'):
            send_at = iqama_time - timedelta(minutes=prayer_prefs['before_iqama_min'])
            if not in_quiet_hours(send_at, prefs, prayer):
                schedule_push(subscription, send_at, build_pre_iqama_notification(prayer, mosque, travel_minutes))

        # Type 3: Leave-now (only if we have travel time data)
        if travel_minutes and prayer_prefs.get('before_iqama_min'):
            buffer = prefs.get('travel_buffer_min', 5)
            send_at = iqama_time - timedelta(minutes=travel_minutes + buffer + 2)
            if send_at > now() and not in_quiet_hours(send_at, prefs, prayer):
                schedule_push(subscription, send_at, build_leave_now_notification(prayer, mosque, travel_minutes))


def in_quiet_hours(send_at: datetime, prefs: dict, prayer: str) -> bool:
    """Check if send_at falls within quiet hours, with Fajr override."""
    quiet_start = prefs.get('quiet_hours_start', '23:00')
    quiet_end = prefs.get('quiet_hours_end', '04:30')
    fajr_override = prefs.get('fajr_override_quiet', True)

    if prayer == 'fajr' and fajr_override:
        return False  # Always allow Fajr notifications

    return time_is_between(send_at.time(), quiet_start, quiet_end)
```

---

## Backend Architecture

### Notification Scheduler Service

Runs as a background process within FastAPI using APScheduler.

```
Nightly 11 PM: schedule_all_notifications_for_tomorrow()
  → For each active push_subscription:
    → Calculate prayer times for their location + timezone
    → Find nearest mosques + cached travel times
    → Compute send_at timestamps for each notification type
    → Store in notification_queue table

At each scheduled time: send_queued_notifications()
  → Query notification_queue WHERE send_at <= NOW() AND status = 'pending'
  → Send via FCM
  → Mark as sent or failed
  → For failed: retry up to 3 times with 5-min backoff
```

### `notification_queue` table (operational)

```sql
CREATE TABLE notification_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id UUID NOT NULL REFERENCES push_subscriptions(id),
    send_at         TIMESTAMPTZ NOT NULL,
    notification_type TEXT NOT NULL,   -- pre_adhan / pre_iqama / leave_now / in_progress / jumuah
    prayer          TEXT NOT NULL,
    mosque_id       UUID REFERENCES mosques(id),
    payload         JSONB NOT NULL,    -- full notification payload
    status          TEXT DEFAULT 'pending',  -- pending / sent / failed / cancelled
    attempts        INTEGER DEFAULT 0,
    sent_at         TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX nq_send_at_status_idx ON notification_queue (send_at, status)
    WHERE status = 'pending';
```

---

## Frontend: Push Registration

```typescript
// services/notifications.ts

export async function registerForPushNotifications(
  preferences: NotificationPreferences,
  location: { lat: number; lng: number },
  timezone: string
): Promise<boolean> {

  // Check support
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    return false;
  }

  // Request permission
  const permission = await Notification.requestPermission();
  if (permission !== 'granted') return false;

  // Get service worker registration
  const registration = await navigator.serviceWorker.ready;

  // Subscribe to push
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(import.meta.env.VITE_VAPID_PUBLIC_KEY),
  });

  // Register with backend
  await apiService.registerPushSubscription({
    push_token: JSON.stringify(subscription),
    push_platform: 'webpush',
    vapid_endpoint: subscription.endpoint,
    vapid_p256dh: btoa(String.fromCharCode(...new Uint8Array(subscription.getKey('p256dh')!))),
    vapid_auth: btoa(String.fromCharCode(...new Uint8Array(subscription.getKey('auth')!))),
    location_lat: Math.round(location.lat * 100) / 100,  // grid cell privacy
    location_lng: Math.round(location.lng * 100) / 100,
    timezone,
    preferences,
  });

  return true;
}
```

---

## Service Worker: Receive Push

```javascript
// public/sw.js

self.addEventListener('push', (event) => {
  const data = event.data.json();

  const options = {
    body: data.body,
    icon: '/icon-192.png',
    badge: '/badge-72.png',
    tag: `prayer-${data.prayer}`,     // replaces previous notification for same prayer
    renotify: data.urgency === 'high',
    data: { mosque_id: data.mosque_id, url: data.action_url },
    actions: data.urgency === 'high'
      ? [{ action: 'navigate', title: '🧭 Navigate' }]
      : [],
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  if (event.action === 'navigate' && event.notification.data.mosque_id) {
    // Open app focused on that mosque
    event.waitUntil(
      clients.openWindow(`/?mosque=${event.notification.data.mosque_id}`)
    );
  } else {
    event.waitUntil(clients.openWindow('/'));
  }
});
```

---

## Privacy

- User location stored at grid-cell granularity only (rounded to 0.01°, ~1km precision)
- No user account required — push token is the only identifier
- Push subscriptions expire naturally (browser/OS manages token lifecycle)
- User can revoke at any time from app settings or browser settings
- No location stored beyond what is needed for prayer time calculation
