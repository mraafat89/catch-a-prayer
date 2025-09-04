import httpx
import asyncio
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, time, timedelta
from urllib.parse import urljoin, urlparse
import re
from models import Prayer, PrayerName, NextPrayer, Mosque, PrayerStatus

class EnhancedPrayerTimeService:
    def __init__(self):
        self.cache = {}  # Simple in-memory cache
        self.cache_expiry = timedelta(hours=24)
        
        # Sunrise calculation constants (approximate)
        self.FAJR_TO_SUNRISE_MINUTES = 90  # Typical time between Fajr and sunrise
        
    async def get_mosque_prayers(self, mosque: Mosque) -> List[Prayer]:
        """Get today's prayer times for a mosque with enhanced crawling"""
        if not mosque.website:
            return self._get_default_prayers()
        
        cache_key = f"{mosque.place_id}_{datetime.now().date()}"
        
        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if datetime.now() - cached_time < self.cache_expiry:
                return cached_data
        
        # Enhanced crawling for prayer times
        prayers = await self._crawl_for_prayer_times(mosque.website)
        if not prayers:
            prayers = self._get_default_prayers()
        
        # Cache results
        self.cache[cache_key] = (prayers, datetime.now())
        
        return prayers
    
    async def _crawl_for_prayer_times(self, base_url: str) -> List[Prayer]:
        """Crawl website to find prayer time pages"""
        try:
            # Step 1: Try main page first
            prayers = await self._scrape_prayer_times(base_url)
            if prayers:
                return prayers
            
            # Step 2: Look for prayer time links on main page
            prayer_page_urls = await self._find_prayer_time_pages(base_url)
            
            # Step 3: Try each found page
            for url in prayer_page_urls:
                prayers = await self._scrape_prayer_times(url)
                if prayers:
                    return prayers
            
            return []
            
        except Exception as e:
            print(f"Error crawling for prayer times: {e}")
            return []
    
    async def _find_prayer_time_pages(self, base_url: str) -> List[str]:
        """Find potential prayer time pages by analyzing links"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(base_url)
                if response.status_code != 200:
                    return []
                
                soup = BeautifulSoup(response.text, 'html.parser')
                prayer_urls = []
                
                # Look for links that might contain prayer times
                prayer_keywords = [
                    'prayer', 'salah', 'namaz', 'times', 'schedule', 'timetable',
                    'daily', 'monthly', 'iqama', 'adhan', 'jamaat'
                ]
                
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    text = link.get_text().lower()
                    
                    # Check if link text suggests prayer times
                    if any(keyword in text for keyword in prayer_keywords):
                        full_url = urljoin(base_url, href)
                        if self._is_valid_url(full_url):
                            prayer_urls.append(full_url)
                
                # Also check for common prayer time page patterns
                common_paths = ['/prayer-times', '/prayers', '/schedule', '/times', '/daily-prayers']
                for path in common_paths:
                    test_url = urljoin(base_url, path)
                    prayer_urls.append(test_url)
                
                return list(set(prayer_urls))  # Remove duplicates
                
        except Exception as e:
            print(f"Error finding prayer time pages: {e}")
            return []
    
    def _is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and not an external link"""
        try:
            parsed = urlparse(url)
            return parsed.scheme in ['http', 'https'] and parsed.netloc
        except:
            return False
    
    async def _scrape_prayer_times(self, url: str) -> List[Prayer]:
        """Enhanced prayer time scraping with multiple strategies"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(url)
                if response.status_code != 200:
                    return []
                
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Multiple extraction strategies in order of preference
                prayers = (
                    self._extract_from_monthly_table(soup) or
                    self._extract_from_daily_table(soup) or
                    self._extract_from_structured_divs(soup) or
                    self._extract_from_text_content(soup) or
                    []
                )
                
                return prayers
                
        except Exception as e:
            print(f"Error scraping prayer times from {url}: {e}")
            return []
    
    def _extract_from_monthly_table(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract current day's prayer times from monthly calendar table"""
        today = datetime.now().day
        prayers = []
        
        # Look for tables that might contain monthly schedules
        tables = soup.find_all('table')
        for table in tables:
            rows = table.find_all('tr')
            
            # Look for header row with prayer names
            header_row = None
            for row in rows:
                cells = row.find_all(['th', 'td'])
                if len(cells) >= 5:  # At least date + 4 prayers
                    cell_texts = [cell.get_text().strip().lower() for cell in cells]
                    if any('fajr' in text or 'dhuhr' in text for text in cell_texts):
                        header_row = cells
                        break
            
            if not header_row:
                continue
            
            # Find prayer columns
            prayer_columns = {}
            for i, cell in enumerate(header_row):
                prayer_name = self._parse_prayer_name(cell.get_text())
                if prayer_name:
                    prayer_columns[prayer_name] = i
            
            # Look for today's row
            for row in rows[1:]:  # Skip header
                cells = row.find_all(['td', 'th'])
                if len(cells) < len(header_row):
                    continue
                
                # Check if first cell contains today's date
                first_cell = cells[0].get_text().strip()
                if str(today) in first_cell or self._is_today_date(first_cell):
                    # Extract prayer times for today
                    for prayer_name, col_index in prayer_columns.items():
                        if col_index < len(cells):
                            time_text = cells[col_index].get_text().strip()
                            parsed_time = self._parse_time(time_text)
                            if parsed_time:
                                prayers.append(Prayer(
                                    prayer_name=prayer_name,
                                    adhan_time=parsed_time
                                ))
                    break
        
        return prayers
    
    def _is_today_date(self, text: str) -> bool:
        """Check if text represents today's date"""
        today = datetime.now()
        patterns = [
            str(today.day),
            today.strftime("%d"),
            today.strftime("%m/%d"),
            today.strftime("%d/%m"),
            today.strftime("%B %d").lower()
        ]
        text_lower = text.lower()
        return any(pattern in text_lower for pattern in patterns)
    
    def _extract_from_daily_table(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract prayer times from daily schedule table"""
        prayers = []
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    prayer_name = self._parse_prayer_name(cells[0].get_text().strip())
                    if prayer_name:
                        # Try to find both adhan and iqama times
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
    
    def _extract_from_structured_divs(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract from modern website layouts with divs/cards"""
        prayers = []
        
        # Look for prayer time containers
        prayer_containers = soup.find_all(['div', 'section'], class_=re.compile(r'prayer|salah|time', re.I))
        
        for container in prayer_containers:
            prayer_name = None
            adhan_time = None
            iqama_time = None
            
            # Look for prayer name in container
            text_content = container.get_text()
            for prayer in PrayerName:
                if prayer.value in text_content.lower():
                    prayer_name = prayer
                    break
            
            if prayer_name:
                # Look for time patterns
                time_patterns = re.findall(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?', text_content)
                if time_patterns:
                    adhan_time = self._parse_time(time_patterns[0])
                    if len(time_patterns) > 1:
                        iqama_time = self._parse_time(time_patterns[1])
                
                if adhan_time:
                    prayers.append(Prayer(
                        prayer_name=prayer_name,
                        adhan_time=adhan_time,
                        iqama_time=iqama_time
                    ))
        
        return prayers
    
    def _extract_from_text_content(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract from plain text content"""
        prayers = []
        text = soup.get_text()
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        for line in lines:
            prayer_name = None
            
            # Check if line contains prayer name and time
            lower_line = line.lower()
            for prayer in PrayerName:
                if prayer.value in lower_line:
                    prayer_name = prayer
                    break
            
            if prayer_name:
                # Look for time patterns in the same line
                time_matches = re.findall(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?', line)
                if time_matches:
                    adhan_time = self._parse_time(time_matches[0])
                    iqama_time = None
                    if len(time_matches) > 1:
                        iqama_time = self._parse_time(time_matches[1])
                    
                    if adhan_time:
                        prayers.append(Prayer(
                            prayer_name=prayer_name,
                            adhan_time=adhan_time,
                            iqama_time=iqama_time
                        ))
        
        return prayers
    
    def get_next_prayer_with_detailed_status(self, prayers: List[Prayer], user_travel_minutes: int) -> Optional[NextPrayer]:
        """Enhanced prayer status calculation with Islamic daily cycle timing rules"""
        if not prayers:
            return None
        
        current_datetime = datetime.now()
        current_time = current_datetime.time()
        
        # Create a prayer lookup
        prayer_dict = {p.prayer_name: p for p in prayers}
        
        # Define Islamic daily cycle order
        prayer_cycle = [PrayerName.FAJR, PrayerName.DHUHR, PrayerName.ASR, PrayerName.MAGHRIB, PrayerName.ISHA]
        
        # Find current prayer based on time and Islamic cycle
        current_prayer_info = self._find_current_prayer_in_cycle(prayer_dict, current_datetime, prayer_cycle)
        
        if current_prayer_info:
            prayer_name, is_tomorrow, is_delayed = current_prayer_info
            prayer = prayer_dict.get(prayer_name)
            if prayer:
                return self._calculate_prayer_status(
                    prayer, prayers, user_travel_minutes, current_datetime, 
                    is_tomorrow=is_tomorrow, is_delayed=is_delayed
                )
        
        return None
    
    def _find_current_prayer_in_cycle(self, prayer_dict: Dict[PrayerName, Prayer], 
                                    current_datetime: datetime, 
                                    prayer_cycle: List[PrayerName]) -> Optional[Tuple[PrayerName, bool, bool]]:
        """Find the current prayer in the Islamic daily cycle"""
        current_time = current_datetime.time()
        
        # Get prayer times for today
        prayer_times = {}
        for prayer_name in prayer_cycle:
            if prayer_name in prayer_dict:
                prayer_time_str = prayer_dict[prayer_name].iqama_time or prayer_dict[prayer_name].adhan_time
                prayer_times[prayer_name] = time.fromisoformat(prayer_time_str)
        
        # Special handling for Fajr (can be delayed until Dhuhr)
        fajr_time = prayer_times.get(PrayerName.FAJR)
        dhuhr_time = prayer_times.get(PrayerName.DHUHR)
        
        if fajr_time and dhuhr_time:
            # From midnight to Fajr time: Next prayer is Fajr (today)
            if current_time < fajr_time:
                return (PrayerName.FAJR, False, False)  # prayer_name, is_tomorrow, is_delayed
            
            # From Fajr time to Dhuhr time: Current prayer is still Fajr but might be delayed
            elif current_time < dhuhr_time:
                # Calculate sunrise (Fajr + 90 minutes)
                fajr_datetime = datetime.combine(current_datetime.date(), fajr_time)
                sunrise_time = (fajr_datetime + timedelta(minutes=90)).time()
                
                if current_time < sunrise_time:
                    # Can still catch Fajr normally
                    return (PrayerName.FAJR, False, False)
                else:
                    # Fajr is delayed (after sunrise)
                    return (PrayerName.FAJR, False, True)
        
        # For other prayers, find the next upcoming prayer
        upcoming_prayers = []
        for prayer_name in prayer_cycle:
            if prayer_name in prayer_times:
                prayer_time = prayer_times[prayer_name]
                if prayer_time > current_time:
                    upcoming_prayers.append((prayer_name, prayer_time))
        
        # If we have upcoming prayers today, return the next one
        if upcoming_prayers:
            upcoming_prayers.sort(key=lambda x: x[1])
            return (upcoming_prayers[0][0], False, False)
        
        # If no prayers left today, tomorrow's Fajr is next
        if PrayerName.FAJR in prayer_dict:
            return (PrayerName.FAJR, True, False)
        
        return None
    
    def _calculate_prayer_status(self, prayer: Prayer, all_prayers: List[Prayer], 
                               user_travel_minutes: int, current_datetime: datetime,
                               is_tomorrow: bool = False, is_delayed: bool = False) -> NextPrayer:
        """Calculate detailed prayer status with Islamic rules"""
        
        prayer_time_str = prayer.iqama_time or prayer.adhan_time
        prayer_time = time.fromisoformat(prayer_time_str)
        
        # Calculate prayer datetime (today or tomorrow)
        prayer_date = current_datetime.date()
        if is_tomorrow:
            prayer_date += timedelta(days=1)
        
        prayer_datetime = datetime.combine(prayer_date, prayer_time)
        time_remaining_seconds = (prayer_datetime - current_datetime).total_seconds()
        time_remaining_minutes = int(time_remaining_seconds / 60)
        
        arrival_time = current_datetime + timedelta(minutes=user_travel_minutes)
        
        # Determine status based on Islamic prayer timing rules
        status, message, can_catch, is_delayed_result = self._determine_prayer_status(
            prayer, arrival_time, prayer_datetime, all_prayers, time_remaining_minutes, user_travel_minutes, is_delayed
        )
        
        # Calculate time until next prayer for "can catch after imam" cases
        time_until_next_prayer = None
        if status == PrayerStatus.CAN_CATCH_AFTER_IMAM:
            time_until_next_prayer = self._get_time_until_next_prayer(prayer, all_prayers)
        
        return NextPrayer(
            prayer=prayer.prayer_name,
            status=status,
            can_catch=can_catch,
            travel_time_minutes=user_travel_minutes,
            time_remaining_minutes=time_remaining_minutes,
            arrival_time=arrival_time,
            prayer_time=prayer_time_str,
            message=message,
            is_delayed=is_delayed_result,
            time_until_next_prayer=time_until_next_prayer
        )
    
    def _determine_prayer_status(self, prayer: Prayer, arrival_time: datetime, 
                               prayer_datetime: datetime, all_prayers: List[Prayer],
                               time_remaining_minutes: int, user_travel_minutes: int, 
                               is_delayed: bool = False) -> Tuple[PrayerStatus, str, bool, bool]:
        """Determine prayer status with detailed Islamic timing rules"""
        
        buffer_minutes = 5  # Minimum buffer time
        prayer_name = prayer.prayer_name.value.title()
        
        # If this is already marked as delayed Fajr
        if is_delayed and prayer.prayer_name == PrayerName.FAJR:
            dhuhr_time = self._get_next_prayer_time(prayer, all_prayers)
            if dhuhr_time and arrival_time < dhuhr_time:
                message = f"🟠 You can catch {prayer_name} (delayed) until Dhuhr at {self._format_time(dhuhr_time.time())}"
                return PrayerStatus.CAN_CATCH_DELAYED, message, True, True
            else:
                message = f"❌ Cannot catch {prayer_name} - Dhuhr time has arrived"
                return PrayerStatus.CANNOT_CATCH, message, False, False
        
        # Case 1: Can catch with Imam (arrive before Iqama + buffer)
        if arrival_time <= prayer_datetime - timedelta(minutes=buffer_minutes):
            status = PrayerStatus.CAN_CATCH_WITH_IMAM
            message = f"✅ You can catch {prayer_name} with the Imam at {self._format_time(prayer_datetime.time())}"
            return status, message, True, False
        
        # Case 2: Can catch after Imam but before next prayer
        next_prayer_time = self._get_next_prayer_time(prayer, all_prayers)
        if next_prayer_time:
            # For Fajr, special rule: can pray until sunrise (but marked as delayed after sunrise)
            if prayer.prayer_name == PrayerName.FAJR:
                sunrise_time = self._estimate_sunrise_time(prayer_datetime)
                dhuhr_time = next_prayer_time  # Next prayer after Fajr is Dhuhr
                
                if arrival_time <= dhuhr_time:
                    if arrival_time <= sunrise_time:
                        message = f"🟡 You'll arrive after Iqama but can still catch {prayer_name} prayer"
                        return PrayerStatus.CAN_CATCH_AFTER_IMAM, message, True, False
                    else:
                        message = f"🟠 You can catch {prayer_name} (delayed) until Dhuhr at {self._format_time(dhuhr_time.time())}"
                        return PrayerStatus.CAN_CATCH_DELAYED, message, True, True
                else:
                    message = f"❌ Cannot catch {prayer_name} - Dhuhr time has arrived"
                    return PrayerStatus.CANNOT_CATCH, message, False, False
            
            # For other prayers: can pray until next prayer time (no delayed option)
            else:
                if arrival_time < next_prayer_time:
                    message = f"🟡 You'll arrive after Iqama but can still catch {prayer_name} prayer"
                    return PrayerStatus.CAN_CATCH_AFTER_IMAM, message, True, False
        
        # Case 3: Cannot catch this prayer, suggest next prayer
        next_prayer_name = self._get_next_prayer_name(prayer, all_prayers)
        if next_prayer_name:
            message = f"❌ Cannot catch {prayer_name} - try {next_prayer_name} instead"
        else:
            # After Isha, suggest tomorrow's Fajr
            message = f"❌ Cannot catch {prayer_name} - try tomorrow's Fajr"
        
        return PrayerStatus.CANNOT_CATCH, message, False, False
    
    def _get_next_prayer_time(self, current_prayer: Prayer, all_prayers: List[Prayer]) -> Optional[datetime]:
        """Get the next prayer time after current prayer"""
        prayer_order = [PrayerName.FAJR, PrayerName.DHUHR, PrayerName.ASR, PrayerName.MAGHRIB, PrayerName.ISHA]
        
        try:
            current_index = prayer_order.index(current_prayer.prayer_name)
            if current_index < len(prayer_order) - 1:
                next_prayer_name = prayer_order[current_index + 1]
                next_prayer = next((p for p in all_prayers if p.prayer_name == next_prayer_name), None)
                if next_prayer:
                    next_time = time.fromisoformat(next_prayer.iqama_time or next_prayer.adhan_time)
                    return datetime.combine(datetime.now().date(), next_time)
        except ValueError:
            pass
        
        return None
    
    def _get_next_prayer_name(self, current_prayer: Prayer, all_prayers: List[Prayer]) -> Optional[str]:
        """Get the name of the next prayer"""
        next_prayer_time = self._get_next_prayer_time(current_prayer, all_prayers)
        if next_prayer_time:
            prayer_order = [PrayerName.FAJR, PrayerName.DHUHR, PrayerName.ASR, PrayerName.MAGHRIB, PrayerName.ISHA]
            try:
                current_index = prayer_order.index(current_prayer.prayer_name)
                if current_index < len(prayer_order) - 1:
                    return prayer_order[current_index + 1].value.title()
            except ValueError:
                pass
        return None
    
    def _estimate_sunrise_time(self, fajr_datetime: datetime) -> datetime:
        """Estimate sunrise time (Fajr + ~90 minutes)"""
        return fajr_datetime + timedelta(minutes=self.FAJR_TO_SUNRISE_MINUTES)
    
    def _get_time_until_next_prayer(self, prayer: Prayer, all_prayers: List[Prayer]) -> Optional[int]:
        """Get minutes until next prayer"""
        next_prayer_time = self._get_next_prayer_time(prayer, all_prayers)
        if next_prayer_time:
            current_time = datetime.now()
            return int((next_prayer_time - current_time).total_seconds() / 60)
        return None
    
    def _format_time(self, time_obj: time) -> str:
        """Format time in 12-hour format"""
        return time_obj.strftime("%I:%M %p").lstrip('0')
    
    # Keep existing helper methods
    def _parse_prayer_name(self, text: str) -> Optional[PrayerName]:
        """Parse prayer name from text"""
        text_lower = text.lower().strip()
        
        prayer_mappings = {
            'fajr': PrayerName.FAJR, 'dawn': PrayerName.FAJR, 'subh': PrayerName.FAJR,
            'dhuhr': PrayerName.DHUHR, 'zuhr': PrayerName.DHUHR, 'noon': PrayerName.DHUHR,
            'asr': PrayerName.ASR, 'afternoon': PrayerName.ASR,
            'maghrib': PrayerName.MAGHRIB, 'sunset': PrayerName.MAGHRIB,
            'isha': PrayerName.ISHA, 'night': PrayerName.ISHA, 'esha': PrayerName.ISHA,
            'jumaa': PrayerName.JUMAA, 'jummah': PrayerName.JUMAA, 'friday': PrayerName.JUMAA
        }
        
        for key, prayer_name in prayer_mappings.items():
            if key in text_lower:
                return prayer_name
        
        return None
    
    def _parse_time(self, time_str: str) -> Optional[str]:
        """Parse time string and return in HH:MM format"""
        if not time_str:
            return None
            
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
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:30", iqama_time="05:45"),
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="12:30", iqama_time="12:45"),
            Prayer(prayer_name=PrayerName.ASR, adhan_time="15:30", iqama_time="15:45"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="18:00", iqama_time="18:15"),
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="19:30", iqama_time="19:45")
        ]