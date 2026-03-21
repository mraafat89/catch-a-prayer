# Client TODO — Features to Implement

These are backend-ready features that need client implementation.
The API already returns the data — the client just needs to display it.

---

## P0 — Must Have for Launch

### 1. Call Mosque Button
**API field**: `mosque.phone` (string, already returned)
**Where**: MosqueDetailSheet, next to the navigate and website icons
**Behavior**: Tap → open native phone dialer with the number
**Design**: Phone icon in a rounded circle (same style as globe/navigate icons)
**Show only when**: `mosque.phone` is not null
```tsx
// Example
<a href={`tel:${mosque.phone}`} className="w-9 h-9 ...">
  <PhoneIcon />
</a>
```

### 2. Data Source Label on Mosque Card
**API field**: `prayer.adhan_source` / `prayer.iqama_source` (already returned per prayer)
**Where**: MosqueDetailSheet, below prayer times table
**Design**: Small text badge
- "Scraped from mosque website" (source = html_parse, claude_jina, iframe_widget)
- "From Mawaqit" (source = mawaqit_api)
- "Estimated times — help us get real times" (source = calculated)
**Why**: Users need to know if times are real or estimated. Builds trust.

### 3. Denomination Display
**API field**: `mosque.denomination` (string: "sunni", "shia", or null)
**Where**: MosqueDetailSheet, in the info section
**Show only when**: not null

---

## P1 — Should Have for v1.0.0

### 4. Eid Prayer Card
**API field**: `mosque.special_prayers[]` where `prayer_type = "eid_fitr"` or `"eid_adha"`
**When to show**: When special_prayers has upcoming Eid entries
**Where**: MosqueDetailSheet, as a highlighted card above the prayer times table
**Design**: Prominent card with Eid theme
```
🎉 Eid ul-Fitr Prayer
Session 1: Takbeer 7:00 AM, Prayer 7:30 AM
Session 2: Takbeer 9:00 AM, Prayer 9:30 AM
Location: Outdoor parking lot
```
**Fields**: prayer_time, takbeer_time, session_number, location_notes, special_notes

### 5. Taraweeh Card
**API field**: `mosque.special_prayers[]` where `prayer_type = "taraweeh"`
**When to show**: During Ramadan (when API returns taraweeh entries)
**Where**: MosqueDetailSheet, below Isha prayer row
**Design**: Subtle card
```
🌙 Taraweeh: 9:30 PM nightly
Imam: Sheikh Ahmad
```
**Fields**: prayer_time, imam_name

### 6. Jumuah Display Improvement
**API field**: `mosque.jumuah_sessions[]` (already displayed)
**Improvement**: Show khutbah language and imam name when available
```
🕋 Jumuah Session 1
  Khutbah: 1:00 PM (English) — Imam Pasha
  Salah: 1:30 PM

🕋 Jumuah Session 2
  Khutbah: 2:00 PM (Arabic)
  Salah: 2:30 PM
```

### 7. "Help Improve Data" Prompt
**When**: Mosque has `adhan_source = "calculated"` (estimated times)
**Where**: MosqueDetailSheet, below prayer table
**Design**: Subtle callout
```
ℹ️ These times are estimated. Visit the mosque or check their website
to help us get accurate iqama times.
[Submit Real Times]
```
**Action**: Opens community submission form (when built)

---

## P2 — Nice to Have for v1.1.0

### 8. Mosque Facilities Section
**API fields**: `has_womens_section`, `wheelchair_accessible`, `denomination`
**Where**: MosqueDetailSheet, collapsible section
**Design**: Icon tags/chips
```
♿ Wheelchair Accessible  👩 Women's Section  🅿 Parking
```

### 9. Community Submission Form
**Endpoint**: POST `/api/community/submit` (not built yet)
**Where**: MosqueDetailSheet → "Submit Real Times" button
**Form fields**:
- Fajr/Dhuhr/Asr/Maghrib/Isha iqama times (HH:MM pickers)
- Jumuah times
- Has women's section? (toggle)
- Notes (text)

### 10. Report Wrong Data
**Endpoint**: POST `/api/community/report` (not built yet)
**Where**: MosqueDetailSheet → small "Report Issue" link
**Quick report**: "Times are wrong" / "Mosque is closed" / "Wrong location"

---

## API Response Reference

```json
{
  "id": "uuid",
  "name": "Mosque Name",
  "phone": "(555) 123-4567",
  "website": "https://...",
  "denomination": "sunni",
  "has_womens_section": true,
  "wheelchair_accessible": true,
  "prayers": [
    {"prayer": "fajr", "adhan_time": "05:30", "iqama_time": "06:00", "adhan_source": "html_parse"}
  ],
  "jumuah_sessions": [
    {"session_number": 1, "khutba_start": "13:00", "prayer_start": "13:30", "language": "English", "imam_name": "Imam Ahmad"}
  ],
  "special_prayers": [
    {"prayer_type": "eid_fitr", "prayer_time": "07:30", "takbeer_time": "07:00", "session_number": 1, "special_notes": "Outdoor in parking lot"},
    {"prayer_type": "taraweeh", "prayer_time": "21:30", "imam_name": "Sheikh Omar"}
  ]
}
```
