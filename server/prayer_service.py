import httpx
import asyncio
import logging
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any
from datetime import datetime, time, timedelta
from models import Prayer, PrayerName, NextPrayer, Mosque
from mosque_scraper import MosqueScraper
from prayer_times_api import PrayerTimesFallbackService

logger = logging.getLogger(__name__)

class PrayerTimeService:
    def __init__(self):
        self.cache = {}  # Simple in-memory cache
        self.cache_expiry = timedelta(hours=24)
        self.scraper = MosqueScraper()
        self.fallback_service = PrayerTimesFallbackService(self.scraper)
    
    async def get_mosque_prayers(self, mosque: Mosque) -> List[Prayer]:
        """Get today's prayer times for a mosque with fast response and background scraping"""
        print(f"DEBUG: get_mosque_prayers called for {mosque.name} with website: {mosque.website}")
        
        # Fast path: Check if we have recent scraped data in cache
        if mosque.website:
            cache_key = f"{mosque.website}_{datetime.now().date()}"
            if cache_key in self.cache:
                cached_prayers, cached_time = self.cache[cache_key]
                if datetime.now() - cached_time < self.cache_expiry:
                    print(f"DEBUG: Using cached scraped prayers for {mosque.website}")
                    return cached_prayers
        
        # Fast fallback: Return API-based prayer times immediately for responsiveness
        # This ensures the frontend gets a fast response while background scraping can happen later
        api_prayers = await self._get_enhanced_fallback_prayers(mosque.location.latitude, mosque.location.longitude)
        
        # Background task: Try to scrape and cache for future requests (don't wait for this)
        if mosque.website and api_prayers:
            # Schedule background scraping task but don't wait for it
            import asyncio
            asyncio.create_task(self._background_scrape_and_cache(mosque.website, cache_key))
            print(f"DEBUG: Background scraping scheduled for {mosque.website}")
        
        return api_prayers
    
    async def _background_scrape_and_cache(self, website_url: str, cache_key: str):
        """Background task to scrape mosque website and cache results"""
        try:
            print(f"DEBUG: Background scraping started for {website_url}")
            scraped_prayers = await self.scraper.scrape_mosque_prayers(website_url)
            if scraped_prayers and len(scraped_prayers) >= 3:
                # Filter out invalid Jumaa prayers (common scraping error)
                filtered_prayers = self._filter_invalid_jumaa_prayers(scraped_prayers)
                # Cache the successful scraping result
                self.cache[cache_key] = (filtered_prayers, datetime.now())
                print(f"DEBUG: Background scraping successful for {website_url} - cached {len(filtered_prayers)} prayers (filtered from {len(scraped_prayers)})")
            else:
                print(f"DEBUG: Background scraping failed for {website_url} - insufficient prayers ({len(scraped_prayers) if scraped_prayers else 0})")
        except Exception as e:
            print(f"DEBUG: Background scraping error for {website_url}: {e}")
    
    def _filter_invalid_jumaa_prayers(self, prayers: List[Prayer]) -> List[Prayer]:
        """Filter out invalid Jumaa prayers that are scraping errors"""
        from models import PrayerName
        from datetime import datetime
        
        # Remove multiple Jumaa prayers (scraping error)
        # Valid: Only 1-3 Jumaa sessions on Friday, replacing Dhuhr
        jumaa_prayers = [p for p in prayers if p.prayer_name == PrayerName.JUMAA]
        other_prayers = [p for p in prayers if p.prayer_name != PrayerName.JUMAA]
        
        if len(jumaa_prayers) > 3:
            # Too many Jumaa prayers - likely scraping error, remove all
            print(f"DEBUG: Removed {len(jumaa_prayers)} invalid Jumaa prayers (too many)")
            return other_prayers
        elif len(jumaa_prayers) > 0:
            # Check if today is Friday (Jumaa should only be on Friday)
            today = datetime.now().weekday()  # Monday=0, Sunday=6
            is_friday = today == 4  # Friday=4
            
            if not is_friday:
                # Remove Jumaa prayers on non-Friday days
                print(f"DEBUG: Removed {len(jumaa_prayers)} Jumaa prayers (not Friday)")
                return other_prayers
            else:
                # Keep reasonable Jumaa prayers on Friday
                print(f"DEBUG: Kept {len(jumaa_prayers)} Jumaa prayers (Friday)")
                return other_prayers + jumaa_prayers
        else:
            # No Jumaa prayers to filter
            return prayers
    
    async def get_monthly_prayers(self, mosque: Mosque, year: int, month: int) -> Optional[Dict]:
        """Get monthly prayer schedule for a mosque"""
        if not mosque.website:
            return None
        
        monthly_data = await self.scraper.scrape_monthly_prayers(mosque.website, year, month)
        return monthly_data
    
    def _get_default_prayers(self) -> List[Prayer]:
        """Return default prayer times when scraping fails"""
        prayers = [
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:50", iqama_time="06:00"),
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="12:45", iqama_time="13:00"),
            Prayer(prayer_name=PrayerName.ASR, adhan_time="16:15", iqama_time="16:30"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="19:10", iqama_time="19:20"),
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="20:30", iqama_time="20:45")
        ]
        
        # Only include Jumaa on Fridays
        if datetime.now().weekday() == 4:  # Friday is day 4 (Monday=0)
            prayers.append(Prayer(
                prayer_name=PrayerName.JUMAA,
                adhan_time="12:30",
                iqama_time="12:30"
            ))
        
        return prayers
    
    async def _get_enhanced_fallback_prayers(self, latitude: float, longitude: float) -> List[Prayer]:
        """Get fallback prayers using prayer times API, then defaults"""
        
        # Use regional caching - round coordinates to reduce cache misses
        rounded_lat = round(latitude * 10) / 10  # 0.1 degree precision (~11km)
        rounded_lng = round(longitude * 10) / 10
        cache_key = f"api_prayers_{int(rounded_lat * 10)}_{int(rounded_lng * 10)}_{datetime.now().date()}"
        
        if cache_key in self.cache:
            cached_result = self.cache[cache_key]
            if datetime.now() - cached_result['timestamp'] < self.cache_expiry:
                print(f"DEBUG: Using cached regional API prayers for ~{latitude}, {longitude}")
                return cached_result['prayers']
        
        # Try to get prayer times from API with timeout
        print(f"DEBUG: Attempting to get API prayers for {latitude}, {longitude}")
        try:
            # Use a shorter timeout for faster response
            import asyncio
            api_prayers, source_info = await asyncio.wait_for(
                self.fallback_service.get_prayers_with_fallback(None, latitude, longitude),
                timeout=6.0  # Max 6 seconds for API call
            )
            if api_prayers and len(api_prayers) >= 5:
                print(f"DEBUG: Successfully got {len(api_prayers)} prayers from API: {source_info}")
                # Cache the result for the region
                self.cache[cache_key] = {
                    'prayers': api_prayers,
                    'timestamp': datetime.now()
                }
                return api_prayers
        except asyncio.TimeoutError:
            print(f"DEBUG: API prayer times timed out for {latitude}, {longitude}")
        except Exception as e:
            print(f"DEBUG: API prayer times failed: {e}")
        
        # If API fails, use defaults (last resort)
        print(f"DEBUG: Using default prayers for {latitude}, {longitude}")
        return self._get_default_prayers()
    
    # Old scraping methods removed - now using ComprehensivePrayerScraper
    
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
        Find the best prayer opportunity using Smart Prayer Recommendation Strategy.
        All calculations done in mosque's timezone.
        
        Priority Order:
        1. Current Prayer in Progress (Highest Priority)
        2. Recently Ended Prayer (High Priority) 
        3. Next Prayer Today (Medium Priority)
        4. Make-Up Prayer Opportunity (Medium Priority)
        5. Tomorrow's First Prayer (Low Priority)
        """
        from models import PrayerStatus
        
        current_time = user_current_mosque_tz.time()
        arrival_time = arrival_time_mosque_tz.time()
        current_date = user_current_mosque_tz.date()
        
        print(f"DEBUG: Smart prayer selection for current time: {current_time}, arrival time: {arrival_time}")
        
        # 1. HIGHEST PRIORITY: Check if we can catch any prayer that's currently happening
        current_prayer = self._find_current_prayer_in_progress(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        if current_prayer:
            print(f"DEBUG: Smart recommendation: Current prayer in progress")
            return current_prayer
        
        # 2. HIGH PRIORITY: Check for active prayer periods (congregation ended but prayer period continues)
        active_prayer = self._find_active_prayer_period(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        if active_prayer:
            print(f"DEBUG: Smart recommendation: Active prayer period (can pray solo)")
            return active_prayer
        
        # 3. MEDIUM PRIORITY: Find next upcoming prayer today
        upcoming_prayer = self._find_next_upcoming_prayer_today_only(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        if upcoming_prayer:
            print(f"DEBUG: Smart recommendation: Next prayer today")
            return upcoming_prayer
        
        # 4. MEDIUM PRIORITY: Check for make-up prayer opportunities
        makeup_prayer = self._find_makeup_prayer_opportunity(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        if makeup_prayer:
            print(f"DEBUG: Smart recommendation: Make-up prayer opportunity")
            return makeup_prayer
        
        # 5. LOW PRIORITY: Consider tomorrow's Fajr only if it's late night
        if self._is_late_night_for_tomorrow_fajr(user_current_mosque_tz):
            tomorrow_fajr = self._find_tomorrow_fajr(prayers, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
            if tomorrow_fajr:
                print(f"DEBUG: Smart recommendation: Tomorrow's Fajr (late night)")
                return tomorrow_fajr
        
        print(f"DEBUG: Smart recommendation: No suitable prayer found")
        return None
    
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
                print(f"DEBUG: {prayer.prayer_name.value} congregation is currently in progress")
                
                # Check if user can arrive within congregation window
                arrival_time = arrival_time_mosque_tz.time()
                if arrival_time <= iqama_end_time:
                    can_catch = True
                    
                    if arrival_time <= iqama_time:
                        # Can catch with Imam from beginning (best case)
                        status = PrayerStatus.CAN_CATCH_WITH_IMAM
                        message = f"🕌 Can catch {prayer.prayer_name.value} WITH congregation - arrive by {iqama_time.strftime('%I:%M %p')}"
                    else:
                        # Can join congregation in progress
                        status = PrayerStatus.CAN_CATCH_AFTER_IMAM
                        minutes_left = int((iqama_end_datetime_tz - user_current_mosque_tz).total_seconds() / 60)
                        message = f"🕌 Can join {prayer.prayer_name.value} congregation in progress - hurry! {minutes_left} minutes left"
                else:
                    can_catch = False
                    status = PrayerStatus.CANNOT_CATCH
                    message = f"⚠️ Cannot reach mosque before {prayer.prayer_name.value} congregation ends - pray at nearby clean location"
                
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
    
    def _find_active_prayer_period(self, prayers: List[Prayer], user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """Check for prayers whose period is currently active (congregation ended but prayer period continues)"""
        from models import PrayerStatus, PrayerName
        
        current_time = user_current_mosque_tz.time()
        current_date = user_current_mosque_tz.date()
        
        for prayer in prayers:
            adhan_time = time.fromisoformat(prayer.adhan_time)
            iqama_time = time.fromisoformat(prayer.iqama_time or prayer.adhan_time)
            
            # Calculate congregation end time (Iqama + ~15 minutes)
            congregation_end_time = (datetime.combine(current_date, iqama_time) + timedelta(minutes=15)).time()
            
            # Determine prayer period end time
            if prayer.prayer_name == PrayerName.FAJR:
                # Fajr period ends at sunrise (approximate: Dhuhr - 6 hours)
                dhuhr_prayer = next((p for p in prayers if p.prayer_name == PrayerName.DHUHR), None)
                if dhuhr_prayer:
                    dhuhr_time = time.fromisoformat(dhuhr_prayer.adhan_time)
                    # Approximate sunrise as 6 hours before Dhuhr
                    sunrise_dt = datetime.combine(current_date, dhuhr_time) - timedelta(hours=6)
                    prayer_period_end_time = sunrise_dt.time()
                else:
                    prayer_period_end_time = time(6, 30)  # Default sunrise
            else:
                # For other prayers, period ends at next prayer's Adhan time
                next_prayer_idx = None
                for i, p in enumerate(prayers):
                    if p.prayer_name == prayer.prayer_name:
                        next_prayer_idx = (i + 1) % len(prayers)
                        break
                
                if next_prayer_idx is not None:
                    next_prayer = prayers[next_prayer_idx]
                    next_adhan_time = time.fromisoformat(next_prayer.adhan_time)
                    
                    # Handle day boundary (e.g., Isha until next day's Fajr)
                    if next_adhan_time < adhan_time:
                        # Next prayer is tomorrow
                        tomorrow = current_date + timedelta(days=1)
                        prayer_period_end_dt = datetime.combine(tomorrow, next_adhan_time)
                        
                        # Check if we're within the prayer period
                        if current_time >= adhan_time:
                            # We're in today's prayer period
                            prayer_period_end_time = time(23, 59)  # Until end of day
                        else:
                            prayer_period_end_time = next_adhan_time
                    else:
                        prayer_period_end_time = next_adhan_time
                else:
                    continue
            
            # Check if congregation ended but prayer period is still active
            if (adhan_time <= current_time and  # Prayer period has started
                congregation_end_time < current_time and  # Congregation has ended
                current_time < prayer_period_end_time):  # Prayer period still active
                
                print(f"DEBUG: {prayer.prayer_name.value} prayer period active (congregation ended but can pray solo)")
                
                arrival_time = arrival_time_mosque_tz.time()
                
                # Calculate time remaining in prayer period
                if prayer_period_end_time == time(23, 59):
                    # Handle day boundary case
                    prayer_period_end_dt = datetime.combine(current_date + timedelta(days=1), time.fromisoformat(prayers[0].adhan_time))  # Next day's Fajr
                else:
                    prayer_period_end_dt = datetime.combine(current_date, prayer_period_end_time)
                
                if user_current_mosque_tz.tzinfo:
                    prayer_period_end_dt = prayer_period_end_dt.replace(tzinfo=user_current_mosque_tz.tzinfo)
                
                minutes_remaining = int((prayer_period_end_dt - user_current_mosque_tz).total_seconds() / 60)
                
                if arrival_time < prayer_period_end_time:
                    can_catch = True
                    status = PrayerStatus.CAN_CATCH_AFTER_IMAM  # Solo prayer
                    hours_remaining = minutes_remaining // 60
                    
                    if hours_remaining > 2:
                        message = f"🤲 Can catch {prayer.prayer_name.value} at mosque (pray solo) - congregation ended but prayer period active ({hours_remaining}+ hours left)"
                    else:
                        message = f"🤲 Can catch {prayer.prayer_name.value} at mosque (pray solo) - congregation ended but {minutes_remaining} min left in prayer period"
                else:
                    can_catch = False
                    status = PrayerStatus.CANNOT_CATCH
                    
                    # Calculate time remaining in prayer period for user guidance
                    time_left_hours = minutes_remaining // 60
                    if time_left_hours > 2:
                        message = f"⚠️ Cannot reach mosque in time - pray {prayer.prayer_name.value} at nearby clean location ({time_left_hours}+ hours left in prayer period)"
                    else:
                        message = f"⚠️ Cannot reach mosque in time - pray {prayer.prayer_name.value} at nearby clean location ({minutes_remaining} min left in prayer period)"
                
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
    
    def _find_next_upcoming_prayer_today_only(self, prayers: List[Prayer], user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """Find the next upcoming prayer today only (don't jump to tomorrow)"""
        from models import PrayerStatus
        
        current_time = user_current_mosque_tz.time()
        
        # Check remaining prayers today
        for prayer in prayers:
            iqama_time = time.fromisoformat(prayer.iqama_time or prayer.adhan_time)
            
            if iqama_time > current_time:
                print(f"DEBUG: Found next prayer today: {prayer.prayer_name.value} at {iqama_time}")
                return self._evaluate_prayer_catchability(prayer, user_current_mosque_tz, arrival_time_mosque_tz, user_travel_minutes)
        
        return None
    
    def _is_late_night_for_tomorrow_fajr(self, user_current_mosque_tz: datetime) -> bool:
        """Determine if it's late enough at night to recommend tomorrow's Fajr"""
        current_time = user_current_mosque_tz.time()
        
        # Consider it "late night" after 10:30 PM or before 4:00 AM
        late_night_start = time(22, 30)  # 10:30 PM
        early_morning_end = time(4, 0)   # 4:00 AM
        
        is_late_night = current_time >= late_night_start or current_time <= early_morning_end
        print(f"DEBUG: Current time {current_time}, is late night: {is_late_night}")
        return is_late_night
    
    def _find_tomorrow_fajr(self, prayers: List[Prayer], user_current_mosque_tz: datetime, arrival_time_mosque_tz: datetime, user_travel_minutes: int) -> Optional[NextPrayer]:
        """Find tomorrow's Fajr prayer"""
        from models import PrayerStatus
        
        fajr_prayer = next((p for p in prayers if p.prayer_name == PrayerName.FAJR), None)
        if fajr_prayer:
            print("DEBUG: Considering tomorrow's Fajr")
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
            message = f"All today's prayers completed. Next: Tomorrow's Fajr at {fajr_prayer.iqama_time or fajr_prayer.adhan_time}"
            
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
            message = f"🕌 Next prayer: {prayer.prayer_name.value} WITH congregation (arrive {minutes_before} min before Iqama)"
        elif arrival_time <= congregation_end_time:
            status = PrayerStatus.CAN_CATCH_AFTER_IMAM
            can_catch = True
            # Calculate minutes after Iqama
            arrival_datetime = datetime.combine(arrival_time_mosque_tz.date(), arrival_time)
            if arrival_time_mosque_tz.tzinfo:
                arrival_datetime = arrival_datetime.replace(tzinfo=arrival_time_mosque_tz.tzinfo)
            minutes_after = int((arrival_datetime - iqama_datetime).total_seconds() / 60)
            message = f"🕌 Can join {prayer.prayer_name.value} congregation (arrive {minutes_after} min after Iqama starts)"
        else:
            # Check if can catch solo within prayer period
            next_prayer_adhan = self._get_next_prayer_adhan_time(prayer, prayers)
            if next_prayer_adhan and arrival_time < next_prayer_adhan:
                status = PrayerStatus.CAN_CATCH_AFTER_IMAM  # Solo prayer
                can_catch = True
                message = f"🤲 Can catch {prayer.prayer_name.value} at mosque (pray solo) - will miss congregation"
            else:
                status = PrayerStatus.CANNOT_CATCH
                can_catch = False
                message = f"⚠️ Cannot reach mosque for {prayer.prayer_name.value} - pray at nearby clean location when time comes"
        
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