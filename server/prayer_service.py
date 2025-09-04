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
    
    def get_next_prayer(self, prayers: List[Prayer], user_travel_minutes: int, client_current_time: Optional[str] = None, mosque_coordinates: Optional[tuple] = None, client_timezone: Optional[str] = None) -> Optional[NextPrayer]:
        """
        Determine the next prayer a user can catch with proper multi-timezone support.
        
        TIMEZONE CALCULATION LOGIC:
        1. User current time in their timezone
        2. Mosque prayer times in mosque's timezone  
        3. Calculate arrival time by adding travel duration to user's current time
        4. Convert arrival time to mosque's timezone for comparison
        5. All prayer catchability calculated in mosque's timezone
        
        Args:
            prayers: List of today's prayer times (in mosque's local timezone)
            user_travel_minutes: Travel time to mosque in minutes
            client_current_time: ISO string of user's current time with timezone
            mosque_coordinates: (latitude, longitude) for timezone lookup
            client_timezone: User's current timezone (fallback)
            
        Returns:
            NextPrayer with detailed status considering timezone differences
        """
        if not prayers:
            return None
        
        # Parse user's current time (keep timezone info)
        user_current_dt = self._parse_user_current_time(client_current_time, client_timezone)
        if not user_current_dt:
            return None
        
        # Get mosque timezone
        mosque_timezone = self._get_mosque_timezone(mosque_coordinates, client_timezone)
        if not mosque_timezone:
            print("WARNING: Could not determine mosque timezone, using user timezone")
            mosque_timezone = user_current_dt.tzinfo
        
        print(f"DEBUG: Raw client_current_time: {client_current_time}")
        print(f"DEBUG: Raw client_timezone: {client_timezone}")
        print(f"DEBUG: User time: {user_current_dt} ({user_current_dt.tzinfo})")
        print(f"DEBUG: Mosque timezone: {mosque_timezone}")
        print(f"DEBUG: Travel time: {user_travel_minutes} minutes")
        
        # Calculate arrival time in mosque's timezone
        arrival_time_user_tz = user_current_dt + timedelta(minutes=user_travel_minutes)
        arrival_time_mosque_tz = arrival_time_user_tz.astimezone(mosque_timezone)
        
        print(f"DEBUG: User departure: {user_current_dt}")
        print(f"DEBUG: Arrival in user TZ: {arrival_time_user_tz}")  
        print(f"DEBUG: Arrival in mosque TZ: {arrival_time_mosque_tz}")
        
        # Convert current user time to mosque timezone for prayer period checks
        user_current_mosque_tz = user_current_dt.astimezone(mosque_timezone)
        
        # Sort prayers by time to ensure proper order
        sorted_prayers = sorted(prayers, key=lambda p: time.fromisoformat(p.iqama_time or p.adhan_time))
        
        # Find the best prayer opportunity
        return self._find_best_prayer_opportunity(
            sorted_prayers, 
            user_current_mosque_tz, 
            arrival_time_mosque_tz, 
            user_travel_minutes
        )
    
    def _parse_user_current_time(self, client_current_time: Optional[str], client_timezone: Optional[str]) -> Optional[datetime]:
        """Parse user's current time preserving timezone information"""
        if client_current_time:
            try:
                import dateutil.parser
                parsed_dt = dateutil.parser.parse(client_current_time)
                if parsed_dt.tzinfo:
                    print(f"DEBUG: Parsed client time with timezone: {parsed_dt}")
                    return parsed_dt
                else:
                    print(f"DEBUG: Client time has no timezone info, adding client timezone")
                    if client_timezone:
                        import pytz
                        tz = pytz.timezone(client_timezone)
                        return tz.localize(parsed_dt)
            except Exception as e:
                print(f"DEBUG: Failed to parse client time {client_current_time}: {e}")
        
        # Fallback to server time with UTC
        import pytz
        server_time = datetime.now(pytz.UTC)
        print(f"DEBUG: Using server time (UTC): {server_time}")
        return server_time
    
    def _get_mosque_timezone(self, mosque_coordinates: Optional[tuple], fallback_timezone: Optional[str]) -> Optional[any]:
        """Get mosque's timezone from coordinates or fallback"""
        if mosque_coordinates:
            try:
                from timezonefinder import TimezoneFinder
                import pytz
                
                lat, lng = mosque_coordinates
                tf = TimezoneFinder()
                timezone_name = tf.timezone_at(lat=lat, lng=lng)
                
                if timezone_name:
                    mosque_tz = pytz.timezone(timezone_name)
                    print(f"DEBUG: Found mosque timezone from coordinates: {timezone_name}")
                    return mosque_tz
            except ImportError:
                print("DEBUG: timezonefinder not available - using fallback timezone")
            except Exception as e:
                print(f"DEBUG: Failed to get timezone from coordinates: {e}")
        
        # For testing: hardcode timezone mappings for known locations
        if mosque_coordinates:
            lat, lng = mosque_coordinates
            # San Francisco Bay Area
            if 37.0 <= lat <= 38.0 and -123.0 <= lng <= -121.0:
                try:
                    import pytz
                    return pytz.timezone('America/Los_Angeles')
                except ImportError:
                    pass
            # Denver area  
            elif 39.0 <= lat <= 40.0 and -106.0 <= lng <= -104.0:
                try:
                    import pytz
                    return pytz.timezone('America/Denver')
                except ImportError:
                    pass
        
        # Fallback to user's timezone (assume same timezone)
        if fallback_timezone:
            try:
                import pytz
                fallback_tz = pytz.timezone(fallback_timezone)
                print(f"DEBUG: Using fallback timezone: {fallback_timezone}")
                return fallback_tz
            except Exception as e:
                print(f"DEBUG: Failed to use fallback timezone: {e}")
        
        return None
    
    def _find_best_prayer_opportunity(self, prayers: List[Prayer], user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """
        Find the best prayer opportunity following Islamic timing rules.
        All calculations done in mosque's timezone.
        """
        from models import PrayerStatus
        
        current_time = user_current_mosque_tz.time()
        arrival_time = arrival_time_mosque_tz.time()
        current_date = user_current_mosque_tz.date()
        
        print(f"DEBUG: Finding prayer for current time: {current_time}, arrival time: {arrival_time}")
        
        # 1. Check if we can catch any prayer that's currently happening
        current_prayer = self._find_current_prayer_in_progress(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        if current_prayer:
            return current_prayer
        
        # 2. Find next upcoming prayer (including next day if needed)
        upcoming_prayer = self._find_next_upcoming_prayer(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        if upcoming_prayer:
            return upcoming_prayer
        
        # 3. Check for make-up prayer opportunities (missed prayers)
        makeup_prayer = self._find_makeup_prayer_opportunity(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        return makeup_prayer
    
    def _find_current_prayer_in_progress(self, prayers: List[Prayer], user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """Check for prayers currently in progress that can still be joined"""
        from models import PrayerStatus
        
        current_time = user_current_mosque_tz.time()
        
        for prayer in prayers:
            iqama_time = time.fromisoformat(prayer.iqama_time or prayer.adhan_time)
            
            # Check if prayer is currently in progress (started but within congregation window)
            congregation_window_minutes = 15  # Configurable
            iqama_end_time = (datetime.combine(user_current_mosque_tz.date(), iqama_time) + timedelta(minutes=congregation_window_minutes)).time()
            
            if iqama_time <= current_time <= iqama_end_time:
                print(f"DEBUG: {prayer.prayer_name.value} is currently in progress")
                
                # Check if user can arrive within congregation window
                arrival_time = arrival_time_mosque_tz.time()
                if arrival_time <= iqama_end_time:
                    can_catch = True
                    status = PrayerStatus.CAN_CATCH_AFTER_IMAM if arrival_time > iqama_time else PrayerStatus.CAN_CATCH_WITH_IMAM
                    message = f"Can join {prayer.prayer_name.value} in progress (arrives at {arrival_time_mosque_tz.strftime('%I:%M %p')})"
                else:
                    can_catch = False
                    status = PrayerStatus.CANNOT_CATCH
                    message = f"Cannot catch {prayer.prayer_name.value} - congregation will end before arrival"
                
                # Ensure both datetimes have same timezone info for calculation
                iqama_end_datetime_tz = datetime.combine(user_current_mosque_tz.date(), iqama_end_time)
                if user_current_mosque_tz.tzinfo:
                    iqama_end_datetime_tz = iqama_end_datetime_tz.replace(tzinfo=user_current_mosque_tz.tzinfo)
                minutes_remaining = int((iqama_end_datetime_tz - user_current_mosque_tz).total_seconds() / 60)
                
                return NextPrayer(
                    prayer=prayer.prayer_name,
                    status=status,
                    can_catch=can_catch,
                    travel_time_minutes=user_travel_minutes,
                    time_remaining_minutes=minutes_remaining,
                    arrival_time=arrival_time_mosque_tz,
                    prayer_time=prayer.iqama_time or prayer.adhan_time,
                    message=message
                )
        
        return None
    
    def _find_next_upcoming_prayer(self, prayers: List[Prayer], user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """Find the next upcoming prayer (today or tomorrow)"""
        from models import PrayerStatus
        
        current_time = user_current_mosque_tz.time()
        
        # Check remaining prayers today
        for prayer in prayers:
            iqama_time = time.fromisoformat(prayer.iqama_time or prayer.adhan_time)
            
            if iqama_time > current_time:
                print(f"DEBUG: Found next prayer today: {prayer.prayer_name.value} at {iqama_time}")
                return self._evaluate_prayer_catchability(prayer, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        
        # No prayers left today - return tomorrow's Fajr
        fajr_prayer = next((p for p in prayers if p.prayer_name == PrayerName.FAJR), None)
        if fajr_prayer:
            print("DEBUG: No prayers left today, returning tomorrow's Fajr")
            # Calculate for tomorrow
            tomorrow = user_current_mosque_tz.date() + timedelta(days=1)
            tomorrow_fajr_dt = datetime.combine(tomorrow, time.fromisoformat(fajr_prayer.iqama_time or fajr_prayer.adhan_time))
            
            # Calculate travel time to tomorrow's prayer
            # Ensure both datetimes have same timezone info
            tomorrow_fajr_dt_tz = tomorrow_fajr_dt.replace(tzinfo=user_current_mosque_tz.tzinfo) if user_current_mosque_tz.tzinfo and not tomorrow_fajr_dt.tzinfo else tomorrow_fajr_dt
            time_until_fajr = (tomorrow_fajr_dt_tz - user_current_mosque_tz).total_seconds() / 60
            
            # For tomorrow's prayers, assume user will travel closer to prayer time
            can_catch = True  # Tomorrow's prayers are generally catchable
            status = PrayerStatus.CAN_CATCH_WITH_IMAM
            message = f"Next prayer: Tomorrow's Fajr at {fajr_prayer.iqama_time}"
            
            return NextPrayer(
                prayer=fajr_prayer.prayer_name,
                status=status,
                can_catch=can_catch,
                travel_time_minutes=user_travel_minutes,
                time_remaining_minutes=int(time_until_fajr - user_travel_minutes),
                arrival_time=arrival_time_mosque_tz,  # This would be today's arrival time, but not relevant for tomorrow
                prayer_time=fajr_prayer.iqama_time or fajr_prayer.adhan_time,
                message=message
            )
        
        return None
    
    def _evaluate_prayer_catchability(self, prayer: Prayer, user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> NextPrayer:
        """Evaluate if a specific prayer can be caught and with what status"""
        from models import PrayerStatus
        
        iqama_time = time.fromisoformat(prayer.iqama_time or prayer.adhan_time)
        adhan_time = time.fromisoformat(prayer.adhan_time) if prayer.adhan_time else iqama_time
        
        # Make datetime calculations timezone-aware to avoid mixing naive and aware
        iqama_datetime = datetime.combine(user_current_mosque_tz.date(), iqama_time)
        if user_current_mosque_tz.tzinfo:
            iqama_datetime = iqama_datetime.replace(tzinfo=user_current_mosque_tz.tzinfo)
        
        arrival_time = arrival_time_mosque_tz.time()
        
        congregation_window_minutes = 15
        congregation_end_datetime = iqama_datetime + timedelta(minutes=congregation_window_minutes)
        congregation_end_time = congregation_end_datetime.time()
        
        # Calculate time remaining until prayer (both must have same timezone info)
        time_remaining = (iqama_datetime - user_current_mosque_tz).total_seconds() / 60
        
        # Determine status based on arrival time
        if arrival_time <= iqama_time:
            status = PrayerStatus.CAN_CATCH_WITH_IMAM
            can_catch = True
            # Calculate minutes before Iqama (ensure both are timezone-aware)
            arrival_datetime = datetime.combine(arrival_time_mosque_tz.date(), arrival_time)
            if arrival_time_mosque_tz.tzinfo:
                arrival_datetime = arrival_datetime.replace(tzinfo=arrival_time_mosque_tz.tzinfo)
            minutes_before = int((iqama_datetime - arrival_datetime).total_seconds() / 60)
            message = f"Can catch {prayer.prayer_name.value} with Imam (arrives {minutes_before} min before Iqama)"
        elif arrival_time <= congregation_end_time:
            status = PrayerStatus.CAN_CATCH_AFTER_IMAM
            can_catch = True
            # Calculate minutes after Iqama
            arrival_datetime = datetime.combine(arrival_time_mosque_tz.date(), arrival_time)
            if arrival_time_mosque_tz.tzinfo:
                arrival_datetime = arrival_datetime.replace(tzinfo=arrival_time_mosque_tz.tzinfo)
            minutes_after = int((arrival_datetime - iqama_datetime).total_seconds() / 60)
            message = f"Can catch {prayer.prayer_name.value} after Imam started (arrives {minutes_after} min after Iqama)"
        else:
            # Check if can catch solo within prayer period
            next_prayer_adhan = self._get_next_prayer_adhan_time(prayer, prayers)
            if next_prayer_adhan and arrival_time < next_prayer_adhan:
                status = PrayerStatus.CAN_CATCH_AFTER_IMAM  # Solo prayer
                can_catch = True
                message = f"Can catch {prayer.prayer_name.value} solo (arrives after congregation)"
            else:
                status = PrayerStatus.CANNOT_CATCH
                can_catch = False
                message = f"Cannot catch {prayer.prayer_name.value} - prayer period will end before arrival"
        
        return NextPrayer(
            prayer=prayer.prayer_name,
            status=status,
            can_catch=can_catch,
            travel_time_minutes=user_travel_minutes,
            time_remaining_minutes=int(max(0, time_remaining)),
            arrival_time=arrival_time_mosque_tz,
            prayer_time=prayer.iqama_time or prayer.adhan_time,
            message=message
        )
    
    def _get_next_prayer_adhan_time(self, current_prayer: Prayer, prayers: List[Prayer]) -> Optional[time]:
        """Get the adhan time of the prayer that comes after current_prayer"""
        prayer_order = [PrayerName.FAJR, PrayerName.DHUHR, PrayerName.ASR, PrayerName.MAGHRIB, PrayerName.ISHA]
        
        try:
            current_index = prayer_order.index(current_prayer.prayer_name)
            if current_index < len(prayer_order) - 1:
                next_prayer_name = prayer_order[current_index + 1]
                next_prayer = next((p for p in prayers if p.prayer_name == next_prayer_name), None)
                if next_prayer:
                    return time.fromisoformat(next_prayer.adhan_time)
        except (ValueError, IndexError):
            pass
        
        # Special case: Fajr ends at sunrise (not next prayer)
        if current_prayer.prayer_name == PrayerName.FAJR:
            # Return estimated sunrise time (Fajr + 90 minutes)
            fajr_adhan = time.fromisoformat(current_prayer.adhan_time)
            fajr_dt = datetime.combine(datetime.now().date(), fajr_adhan)
            sunrise_dt = fajr_dt + timedelta(minutes=90)
            return sunrise_dt.time()
        
        return None
    
    def _find_makeup_prayer_opportunity(self, prayers: List[Prayer], user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """Check for make-up prayer opportunities (like Fajr after sunrise)"""
        from models import PrayerStatus
        
        current_time = user_current_mosque_tz.time()
        
        # Check if Fajr can be made up (after sunrise, before Dhuhr)
        fajr_prayer = next((p for p in prayers if p.prayer_name == PrayerName.FAJR), None)
        dhuhr_prayer = next((p for p in prayers if p.prayer_name == PrayerName.DHUHR), None)
        
        if fajr_prayer and dhuhr_prayer:
            fajr_adhan = time.fromisoformat(fajr_prayer.adhan_time)
            dhuhr_adhan = time.fromisoformat(dhuhr_prayer.adhan_time)
            
            # Estimate sunrise (Fajr + 90 minutes)
            fajr_dt = datetime.combine(user_current_mosque_tz.date(), fajr_adhan)
            estimated_sunrise = (fajr_dt + timedelta(minutes=90)).time()
            
            # If current time is after sunrise but before Dhuhr
            if estimated_sunrise < current_time < dhuhr_adhan:
                print("DEBUG: Fajr can be made up (after sunrise, before Dhuhr)")
                
                arrival_time = arrival_time_mosque_tz.time()
                if arrival_time < dhuhr_adhan:
                    can_catch = True
                    status = PrayerStatus.CAN_CATCH_DELAYED  # Using existing status for make-up
                    message = f"Can make up for Fajr prayer (missed - after sunrise)"
                else:
                    can_catch = False
                    status = PrayerStatus.CANNOT_CATCH
                    message = f"Cannot make up for Fajr - Dhuhr time will start before arrival"
                
                time_remaining = int((datetime.combine(user_current_mosque_tz.date(), dhuhr_adhan) - user_current_mosque_tz).total_seconds() / 60)
                
                return NextPrayer(
                    prayer=fajr_prayer.prayer_name,
                    status=status,
                    can_catch=can_catch,
                    travel_time_minutes=user_travel_minutes,
                    time_remaining_minutes=time_remaining,
                    arrival_time=arrival_time_mosque_tz,
                    prayer_time=fajr_prayer.adhan_time,
                    message=message,
                    is_delayed=True
                )
        
        return None
    
    # Old method removed - replaced by new timezone-aware logic above