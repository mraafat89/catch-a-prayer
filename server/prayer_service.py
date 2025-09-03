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
        """Return default prayer times when scraping fails"""
        return [
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:30"),
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="12:30"),
            Prayer(prayer_name=PrayerName.ASR, adhan_time="15:30"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="18:00"),
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="19:30")
        ]
    
    def get_next_prayer(self, prayers: List[Prayer], user_travel_minutes: int) -> Optional[NextPrayer]:
        """Determine if user can catch the next prayer"""
        if not prayers:
            return None
        
        current_time = datetime.now().time()
        current_datetime = datetime.now()
        
        # Find the next upcoming prayer
        for prayer in prayers:
            prayer_time = time.fromisoformat(prayer.iqama_time or prayer.adhan_time)
            
            # If prayer is still upcoming today
            if prayer_time > current_time:
                prayer_datetime = datetime.combine(datetime.now().date(), prayer_time)
                time_remaining = (prayer_datetime - current_datetime).total_seconds() / 60
                
                # Can catch if travel time + buffer < time remaining
                can_catch = time_remaining > (user_travel_minutes + 10)  # 10 min buffer
                
                arrival_time = current_datetime + timedelta(minutes=user_travel_minutes)
                
                return NextPrayer(
                    prayer=prayer.prayer_name,
                    can_catch=can_catch,
                    travel_time_minutes=user_travel_minutes,
                    time_remaining_minutes=int(time_remaining),
                    arrival_time=arrival_time
                )
        
        return None