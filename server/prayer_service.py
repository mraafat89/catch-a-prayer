import httpx
import asyncio
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any
from datetime import datetime, time, timedelta
from models import Prayer, PrayerName, NextPrayer, Mosque

class PrayerTimeService:
    def __init__(self):
        self.cache = {}  # Simple in-memory cache
        self.cache_expiry = timedelta(hours=24)
    
    async def get_mosque_prayers(self, mosque: Mosque) -> List[Prayer]:
        """Get today's prayer times for a mosque"""
        if not mosque.website:
            return self._get_default_prayers()
        
        cache_key = f"{mosque.place_id}_{datetime.now().date()}"
        
        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if datetime.now() - cached_time < self.cache_expiry:
                return cached_data
        
        # Try to scrape prayer times
        prayers = await self._scrape_prayer_times(mosque.website)
        if not prayers:
            prayers = self._get_default_prayers()
        
        # Cache results
        self.cache[cache_key] = (prayers, datetime.now())
        
        return prayers
    
    async def _scrape_prayer_times(self, website_url: str) -> List[Prayer]:
        """Attempt to scrape prayer times from mosque website"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(website_url)
                if response.status_code != 200:
                    return []
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Try different scraping strategies
                prayers = (
                    self._extract_from_tables(soup) or
                    self._extract_from_structured_content(soup) or
                    []
                )
                
                return prayers
                
        except Exception as e:
            print(f"Error scraping prayer times from {website_url}: {e}")
            return []
    
    def _extract_from_tables(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract prayer times from HTML tables"""
        prayers = []
        
        # Look for tables with prayer time data
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    prayer_name = self._parse_prayer_name(cells[0].get_text().strip())
                    if prayer_name:
                        # Try to find adhan and iqama times
                        adhan_time = self._parse_time(cells[1].get_text().strip())
                        iqama_time = None
                        if len(cells) > 2:
                            iqama_time = self._parse_time(cells[2].get_text().strip())
                        
                        if adhan_time:
                            prayers.append(Prayer(
                                prayer_name=prayer_name,
                                adhan_time=adhan_time,
                                iqama_time=iqama_time
                            ))
        
        return prayers
    
    def _extract_from_structured_content(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract prayer times from structured divs or other elements"""
        prayers = []
        
        # Look for prayer time patterns in text
        text = soup.get_text()
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        for line in lines:
            prayer_name = None
            adhan_time = None
            
            # Check if line contains prayer name and time
            lower_line = line.lower()
            for prayer in PrayerName:
                if prayer.value in lower_line:
                    prayer_name = prayer
                    # Look for time pattern in the same line
                    import re
                    time_match = re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?', line)
                    if time_match:
                        adhan_time = self._parse_time(time_match.group())
                    break
            
            if prayer_name and adhan_time:
                prayers.append(Prayer(
                    prayer_name=prayer_name,
                    adhan_time=adhan_time
                ))
        
        return prayers
    
    def _parse_prayer_name(self, text: str) -> Optional[PrayerName]:
        """Parse prayer name from text"""
        text_lower = text.lower().strip()
        
        prayer_mappings = {
            'fajr': PrayerName.FAJR,
            'dawn': PrayerName.FAJR,
            'dhuhr': PrayerName.DHUHR,
            'zuhr': PrayerName.DHUHR,
            'noon': PrayerName.DHUHR,
            'asr': PrayerName.ASR,
            'afternoon': PrayerName.ASR,
            'maghrib': PrayerName.MAGHRIB,
            'sunset': PrayerName.MAGHRIB,
            'isha': PrayerName.ISHA,
            'night': PrayerName.ISHA,
            'jumaa': PrayerName.JUMAA,
            'jummah': PrayerName.JUMAA,
            'friday': PrayerName.JUMAA
        }
        
        for key, prayer_name in prayer_mappings.items():
            if key in text_lower:
                return prayer_name
        
        return None
    
    def _parse_time(self, time_str: str) -> Optional[str]:
        """Parse time string and return in HH:MM format"""
        import re
        
        # Remove extra whitespace and normalize
        time_str = re.sub(r'\s+', ' ', time_str.strip())
        
        # Match time patterns
        time_match = re.search(r'(\d{1,2}):(\d{2})\s*(?:(AM|PM|am|pm))?', time_str)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2))
            ampm = time_match.group(3)
            
            # Convert to 24-hour format if needed
            if ampm:
                if ampm.upper() == 'PM' and hour != 12:
                    hour += 12
                elif ampm.upper() == 'AM' and hour == 12:
                    hour = 0
            
            return f"{hour:02d}:{minute:02d}"
        
        return None
    
    def _get_default_prayers(self) -> List[Prayer]:
        """Return default prayer times when scraping fails - updated for September in SF Bay Area"""
        return [
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:50", iqama_time="06:00"),  # Realistic for September
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="12:45", iqama_time="13:00"),
            Prayer(prayer_name=PrayerName.ASR, adhan_time="16:15", iqama_time="16:30"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="19:10", iqama_time="19:20"),  # Realistic for September sunset
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="20:30", iqama_time="20:45")
        ]
    
    def get_next_prayer(self, prayers: List[Prayer], user_travel_minutes: int, client_current_time: Optional[str] = None) -> Optional[NextPrayer]:
        """Determine if user can catch the next prayer"""
        if not prayers:
            return None
        
        # Use client's current time if provided, otherwise fallback to server time
        if client_current_time:
            try:
                # Parse the ISO string - client sends timezone-aware time
                import dateutil.parser
                parsed_dt = dateutil.parser.parse(client_current_time)
                print(f"DEBUG: Parsed client time with timezone: {parsed_dt}")
                
                # Convert to the client's local time (remove timezone for calculations)
                # The parsed time is already in the client's timezone, so we just remove tz info
                current_datetime = parsed_dt.replace(tzinfo=None)
                print(f"DEBUG: Using client time (timezone removed): {current_datetime}")  # Debug log
            except Exception as e:
                print(f"DEBUG: Failed to parse client time {client_current_time}: {e}")  # Debug log
                current_datetime = datetime.now()  # Fallback
        else:
            current_datetime = datetime.now()
            print(f"DEBUG: Using server time: {current_datetime}")  # Debug log
        
        current_time = current_datetime.time()
        
        # Check for current prayer opportunities (including Fajr delayed prayer)
        current_prayer_opportunity = self._find_current_prayer_opportunity(prayers, current_datetime, user_travel_minutes)
        if current_prayer_opportunity:
            return current_prayer_opportunity
            
        # Find the next upcoming prayer
        for prayer in prayers:
            prayer_time = time.fromisoformat(prayer.iqama_time or prayer.adhan_time)
            
            # If prayer is still upcoming today
            if prayer_time > current_time:
                prayer_datetime = datetime.combine(current_datetime.date(), prayer_time)
                time_remaining = (prayer_datetime - current_datetime).total_seconds() / 60
                
                # Can catch if user arrives within congregation time window
                # Congregation typically continues for 10-15 minutes after Iqama
                congregation_window_minutes = 15
                arrival_time_relative = user_travel_minutes - time_remaining
                can_catch = arrival_time_relative <= congregation_window_minutes
                
                arrival_time = current_datetime + timedelta(minutes=user_travel_minutes)
                
                from models import PrayerStatus
                status = PrayerStatus.CAN_CATCH_WITH_IMAM if can_catch else PrayerStatus.CANNOT_CATCH
                message = f"Can catch {prayer.prayer_name.value} with Imam (arrives at {arrival_time.strftime('%I:%M %p')})" if can_catch else f"Cannot catch {prayer.prayer_name.value} - would arrive {user_travel_minutes - int(time_remaining)} minutes after Iqama"
                
                return NextPrayer(
                    prayer=prayer.prayer_name,
                    status=status,
                    can_catch=can_catch,
                    travel_time_minutes=user_travel_minutes,
                    time_remaining_minutes=int(time_remaining),
                    arrival_time=arrival_time,
                    prayer_time=prayer.iqama_time or prayer.adhan_time,
                    message=message
                )
        
        return None
    
    def _find_current_prayer_opportunity(self, prayers: List[Prayer], current_datetime: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """Check if there's a current prayer that can still be caught (especially Fajr until sunrise)"""
        current_time = current_datetime.time()
        print(f"DEBUG: Checking current prayer opportunities at {current_time}")
        
        # Special case: Fajr can be prayed until sunrise (approximately Fajr + 90 minutes)
        fajr_prayer = next((p for p in prayers if p.prayer_name == PrayerName.FAJR), None)
        if fajr_prayer:
            fajr_time = time.fromisoformat(fajr_prayer.iqama_time or fajr_prayer.adhan_time)
            print(f"DEBUG: Fajr time: {fajr_time}, Current time: {current_time}")
            
            # If current time is after Fajr but before estimated sunrise
            if current_time > fajr_time:
                print(f"DEBUG: Current time is after Fajr - checking sunrise window")
                fajr_datetime = datetime.combine(current_datetime.date(), fajr_time)
                estimated_sunrise = fajr_datetime + timedelta(minutes=90)  # Rough estimate
                print(f"DEBUG: Estimated sunrise: {estimated_sunrise}")
                
                # If we're still before sunrise, Fajr can be caught
                # Fix timezone comparison issue
                estimated_sunrise_naive = estimated_sunrise.replace(tzinfo=None) if estimated_sunrise.tzinfo else estimated_sunrise
                current_datetime_naive = current_datetime.replace(tzinfo=None) if current_datetime.tzinfo else current_datetime
                if current_datetime_naive < estimated_sunrise_naive:
                    print(f"DEBUG: Still before sunrise - Fajr can be caught delayed")
                    arrival_time = current_datetime + timedelta(minutes=user_travel_minutes)
                    
                    # Can catch if arrival is before sunrise  
                    arrival_time_naive = arrival_time.replace(tzinfo=None) if arrival_time.tzinfo else arrival_time
                    print(f"DEBUG: arrival_time_naive: {arrival_time_naive}, estimated_sunrise_naive: {estimated_sunrise_naive}")
                    can_catch = arrival_time_naive < estimated_sunrise_naive
                    
                    # Calculate time remaining until sunrise
                    time_remaining = (estimated_sunrise_naive - current_datetime_naive).total_seconds() / 60
                    
                    print(f"DEBUG: Returning Fajr delayed prayer - can_catch: {can_catch}")
                    from models import PrayerStatus
                    return NextPrayer(
                        prayer=fajr_prayer.prayer_name,
                        status=PrayerStatus.CAN_CATCH_DELAYED if can_catch else PrayerStatus.CANNOT_CATCH,
                        can_catch=can_catch,
                        travel_time_minutes=user_travel_minutes,
                        time_remaining_minutes=int(time_remaining),
                        arrival_time=arrival_time,
                        prayer_time=fajr_prayer.iqama_time or fajr_prayer.adhan_time,
                        message=f"Fajr can be prayed delayed until sunrise (arrives at {arrival_time.strftime('%I:%M %p')})" if can_catch else f"Fajr time has passed (sunrise at {estimated_sunrise_naive.strftime('%I:%M %p')})",
                        is_delayed=True
                    )
                else:
                    print(f"DEBUG: Past sunrise - Fajr cannot be caught")
            else:
                print(f"DEBUG: Current time is before Fajr")
        
        print(f"DEBUG: No current prayer opportunities found")
        return None