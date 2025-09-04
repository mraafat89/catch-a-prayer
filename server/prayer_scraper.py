"""
Comprehensive mosque website scraping service for prayer times and Jumaa information.
Implements multi-level discovery and extraction strategies.
"""

import httpx
import asyncio
import re
import json
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Any, Set, Tuple
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
from models import Prayer, PrayerName, JumaaSession, Mosque
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ComprehensivePrayerScraper:
    def __init__(self):
        self.cache = {}  # Simple in-memory cache
        self.cache_expiry = timedelta(hours=6)  # Shorter cache for fresh data
        self.timeout = 15.0  # Increased timeout for complex sites
        
        # Prayer-related URL patterns
        self.prayer_url_patterns = [
            r'prayer[s]?[-_]?times?',
            r'salah[-_]?times?',
            r'schedule',
            r'timetable', 
            r'calendar',
            r'iqama',
            r'jamaat',
            r'jumaa?h?',
            r'friday[-_]?prayer[s]?',
            r'khutba',
            r'sermon'
        ]
        
        # Link text patterns for prayer pages
        self.prayer_link_texts = [
            'prayer times', 'salah times', 'namaz', 'schedule', 'timetable',
            'calendar', 'iqama times', 'jamaat', 'congregation', 'daily prayers',
            'monthly schedule', 'current times', 'jumaa', 'jummah', 'friday prayer',
            'khutba', 'sermon', 'imam schedule', 'this week\'s topic'
        ]
        
        # Imam title patterns
        self.imam_titles = [
            r'dr\.?', r'sheikh', r'shaykh', r'imam', r'ustaz', r'hafiz',
            r'maulana', r'professor', r'prof\.?', r'mufti'
        ]
        
        # Language detection patterns
        self.language_patterns = {
            'arabic': [r'عربي', r'العربية', r'arabic'],
            'english': [r'english', r'انجليزي'],
            'urdu': [r'urdu', r'اردو'],
            'turkish': [r'turkish', r'türkçe'],
            'french': [r'french', r'français'],
            'spanish': [r'spanish', r'español'],
            'mixed': [r'bilingual', r'mixed', r'translation']
        }
    
    async def scrape_mosque_prayers(self, mosque: Mosque) -> List[Prayer]:
        """Main entry point for scraping mosque prayer times"""
        if not mosque.website:
            return self._get_default_prayers()
        
        cache_key = f"{mosque.place_id}_{datetime.now().date()}"
        
        # Check cache
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if datetime.now() - cached_time < self.cache_expiry:
                logger.info(f"Cache hit for {mosque.name}")
                return cached_data
        
        logger.info(f"Scraping prayers for {mosque.name} - {mosque.website}")
        
        # Multi-level scraping strategy
        prayers = await self._comprehensive_scrape(mosque.website)
        
        if not prayers:
            logger.warning(f"No prayers found for {mosque.name}, using defaults")
            prayers = self._get_default_prayers()
        else:
            logger.info(f"Found {len(prayers)} prayers for {mosque.name}")
            
        # Cache results
        self.cache[cache_key] = (prayers, datetime.now())
        return prayers
    
    async def _comprehensive_scrape(self, base_url: str) -> List[Prayer]:
        """Comprehensive multi-strategy scraping"""
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers={'User-Agent': 'Mozilla/5.0 (compatible; PrayerTimeBot/1.0)'}
            ) as client:
                
                # Strategy 1: Try home page first
                prayers = await self._scrape_url(client, base_url)
                if prayers:
                    return prayers
                
                # Strategy 2: Discover and try prayer-related pages
                prayer_urls = await self._discover_prayer_pages(client, base_url)
                for url in prayer_urls[:5]:  # Limit to top 5 candidates
                    prayers = await self._scrape_url(client, url)
                    if prayers:
                        return prayers
                
                return []
                
        except Exception as e:
            logger.error(f"Error scraping {base_url}: {e}")
            return []
    
    async def _discover_prayer_pages(self, client: httpx.AsyncClient, base_url: str) -> List[str]:
        """Discover prayer-related pages through link analysis"""
        try:
            response = await client.get(base_url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            prayer_urls = set()
            
            # Find links with prayer-related text or URLs
            for link in soup.find_all('a', href=True):
                href = link.get('href')
                text = link.get_text().lower().strip()
                
                if not href:
                    continue
                
                # Convert relative URLs to absolute
                full_url = urljoin(base_url, href)
                
                # Check URL patterns
                for pattern in self.prayer_url_patterns:
                    if re.search(pattern, href.lower()) or re.search(pattern, full_url.lower()):
                        prayer_urls.add(full_url)
                        break
                
                # Check link text
                if any(phrase in text for phrase in self.prayer_link_texts):
                    prayer_urls.add(full_url)
            
            # Sort by relevance (prioritize certain patterns)
            priority_patterns = ['prayer', 'salah', 'jumaa', 'schedule']
            sorted_urls = []
            
            for pattern in priority_patterns:
                matching_urls = [url for url in prayer_urls if pattern in url.lower()]
                sorted_urls.extend(matching_urls)
                prayer_urls -= set(matching_urls)
            
            sorted_urls.extend(list(prayer_urls))
            
            logger.info(f"Discovered {len(sorted_urls)} potential prayer pages")
            return sorted_urls[:10]  # Return top 10
            
        except Exception as e:
            logger.error(f"Error discovering prayer pages: {e}")
            return []
    
    async def _scrape_url(self, client: httpx.AsyncClient, url: str) -> List[Prayer]:
        """Scrape a specific URL for prayer times"""
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try multiple extraction strategies in order of effectiveness
            extraction_methods = [
                self._extract_from_structured_data,
                self._extract_from_prayer_tables,
                self._extract_from_daily_schedule,
                self._extract_from_monthly_calendar,
                self._extract_from_structured_divs,
                self._extract_from_text_patterns,
                self._extract_from_json_data
            ]
            
            for method in extraction_methods:
                try:
                    prayers = method(soup, url)
                    if prayers:
                        logger.info(f"Extracted prayers using {method.__name__}")
                        return prayers
                except Exception as e:
                    logger.debug(f"Method {method.__name__} failed: {e}")
                    continue
            
            return []
            
        except Exception as e:
            logger.error(f"Error scraping URL {url}: {e}")
            return []
    
    def _extract_from_structured_data(self, soup: BeautifulSoup, url: str) -> List[Prayer]:
        """Extract from structured data (JSON-LD, microdata)"""
        prayers = []
        
        # JSON-LD structured data
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    data = data[0] if data else {}
                
                # Look for event data
                if data.get('@type') == 'Event' or 'prayer' in str(data).lower():
                    prayers.extend(self._parse_structured_prayer_data(data))
            except json.JSONDecodeError:
                continue
        
        return prayers
    
    def _extract_from_prayer_tables(self, soup: BeautifulSoup, url: str) -> List[Prayer]:
        """Extract from HTML tables containing prayer times"""
        prayers = []
        
        # Find tables that likely contain prayer times
        tables = soup.find_all('table')
        for table in tables:
            table_text = table.get_text().lower()
            
            # Skip tables that don't seem to contain prayer times
            prayer_indicators = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha', 'prayer', 'salah']
            if not any(indicator in table_text for indicator in prayer_indicators):
                continue
            
            rows = table.find_all('tr')
            headers = []
            
            # Identify header row
            for row in rows:
                cells = row.find_all(['th', 'td'])
                if len(cells) >= 2:
                    header_text = [cell.get_text().strip().lower() for cell in cells]
                    if any('prayer' in h or 'adhan' in h or 'iqama' in h for h in header_text):
                        headers = header_text
                        break
            
            # Process data rows
            for row in rows[1:]:  # Skip header
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    prayer_data = self._parse_table_row(cells, headers)
                    if prayer_data:
                        prayers.append(prayer_data)
        
        return prayers
    
    def _extract_from_daily_schedule(self, soup: BeautifulSoup, url: str) -> List[Prayer]:
        """Extract from daily prayer schedule layouts"""
        prayers = []
        
        # Look for daily schedule containers
        schedule_containers = soup.find_all(['div', 'section'], 
            class_=re.compile(r'schedule|daily|today|prayer', re.I))
        
        for container in schedule_containers:
            prayer_items = container.find_all(['div', 'li', 'p'])
            
            for item in prayer_items:
                text = item.get_text().strip()
                prayer = self._parse_prayer_text_line(text)
                if prayer:
                    prayers.append(prayer)
        
        return prayers
    
    def _extract_from_monthly_calendar(self, soup: BeautifulSoup, url: str) -> List[Prayer]:
        """Extract today's prayers from monthly calendar"""
        prayers = []
        today = datetime.now()
        
        # Look for calendar tables
        calendar_tables = soup.find_all('table', class_=re.compile(r'calendar', re.I))
        
        for table in calendar_tables:
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                for cell in cells:
                    # Check if this cell represents today
                    if self._is_today_cell(cell, today):
                        cell_prayers = self._extract_prayers_from_cell(cell)
                        prayers.extend(cell_prayers)
        
        return prayers
    
    def _extract_from_structured_divs(self, soup: BeautifulSoup, url: str) -> List[Prayer]:
        """Extract from structured div layouts"""
        prayers = []
        
        # Look for prayer time containers
        prayer_containers = soup.find_all(['div', 'section'], 
            class_=re.compile(r'prayer|salah|time', re.I))
        
        for container in prayer_containers:
            # Look for Jumaa-specific information
            if 'jumaa' in container.get_text().lower() or 'friday' in container.get_text().lower():
                jumaa_prayer = self._extract_jumaa_information(container)
                if jumaa_prayer:
                    prayers.append(jumaa_prayer)
            else:
                # Regular prayer extraction
                prayer_items = container.find_all(['div', 'span', 'p'])
                for item in prayer_items:
                    prayer = self._parse_prayer_element(item)
                    if prayer:
                        prayers.append(prayer)
        
        return prayers
    
    def _extract_jumaa_information(self, container) -> Optional[Prayer]:
        """Extract comprehensive Jumaa prayer information"""
        try:
            jumaa_sessions = []
            
            # Look for multiple session indicators
            session_containers = container.find_all(['div', 'li'], 
                class_=re.compile(r'session|time|jumaa', re.I))
            
            if not session_containers:
                # Fallback: treat entire container as single session
                session_containers = [container]
            
            for session_container in session_containers:
                session = self._parse_jumaa_session(session_container)
                if session:
                    jumaa_sessions.append(session)
            
            if jumaa_sessions:
                # Find the main Jumaa prayer time (usually first session)
                main_time = jumaa_sessions[0].session_time if jumaa_sessions else "12:30"
                
                return Prayer(
                    prayer_name=PrayerName.JUMAA,
                    adhan_time=main_time,
                    iqama_time=main_time,
                    jumaa_sessions=jumaa_sessions
                )
            
        except Exception as e:
            logger.debug(f"Error extracting Jumaa information: {e}")
        
        return None
    
    def _parse_jumaa_session(self, element) -> Optional[JumaaSession]:
        """Parse individual Jumaa session information"""
        try:
            text = element.get_text()
            
            # Extract time
            time_match = re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)', text)
            if not time_match:
                return None
            
            session_time = time_match.group()
            
            # Extract imam name
            imam_name = self._extract_imam_name(text)
            
            # Extract imam title
            imam_title = self._extract_imam_title(text)
            
            # Extract khutba topic
            topic = self._extract_khutba_topic(text, element)
            
            # Extract language
            language = self._detect_language(text)
            
            # Extract special notes
            notes = self._extract_special_notes(text)
            
            return JumaaSession(
                session_time=session_time,
                imam_name=imam_name,
                imam_title=imam_title,
                khutba_topic=topic,
                language=language,
                special_notes=notes
            )
            
        except Exception as e:
            logger.debug(f"Error parsing Jumaa session: {e}")
            return None
    
    def _extract_imam_name(self, text: str) -> Optional[str]:
        """Extract imam name from text"""
        # Look for patterns like "Imam: Dr. Ahmed Ali" or "Led by Sheikh Mohammed"
        patterns = [
            r'imam[:\s]+([^,\n]+)',
            r'led\s+by[:\s]+([^,\n]+)',
            r'khatib[:\s]+([^,\n]+)',
            r'speaker[:\s]+([^,\n]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                name = match.group(1).strip()
                # Clean up the name (remove extra titles, etc.)
                return self._clean_imam_name(name)
        
        return None
    
    def _extract_imam_title(self, text: str) -> Optional[str]:
        """Extract imam title (Dr., Sheikh, etc.)"""
        for title in self.imam_titles:
            if re.search(rf'\b{title}\b', text, re.I):
                return title.replace('.', '').title()
        return None
    
    def _extract_khutba_topic(self, text: str, element) -> Optional[str]:
        """Extract khutba/sermon topic"""
        # Look for topic indicators
        topic_patterns = [
            r'topic[:\s]+([^,\n]+)',
            r'khutba[:\s]+([^,\n]+)',
            r'sermon[:\s]+([^,\n]+)',
            r'theme[:\s]+([^,\n]+)',
            r'this\s+(?:week|friday)[:\s]+([^,\n]+)'
        ]
        
        for pattern in topic_patterns:
            match = re.search(pattern, text, re.I)
            if match:
                return match.group(1).strip()
        
        # Look in nearby elements for topic information
        parent = element.parent if element.parent else element
        siblings = parent.find_all(['p', 'div', 'span'])
        
        for sibling in siblings:
            sibling_text = sibling.get_text().lower()
            if 'topic' in sibling_text or 'khutba' in sibling_text:
                # Extract the actual topic
                clean_text = sibling.get_text().strip()
                topic_match = re.search(r'(?:topic|khutba|sermon)[:\s]*(.+)', clean_text, re.I)
                if topic_match:
                    return topic_match.group(1).strip()
        
        return None
    
    def _detect_language(self, text: str) -> Optional[str]:
        """Detect language from text"""
        text_lower = text.lower()
        
        for language, patterns in self.language_patterns.items():
            for pattern in patterns:
                if re.search(pattern, text_lower):
                    return language.title()
        
        return None
    
    def _extract_special_notes(self, text: str) -> Optional[str]:
        """Extract special notes like sign language, capacity, etc."""
        note_patterns = [
            r'sign\s+language',
            r'translation\s+available',
            r'capacity[:\s]+(\d+)',
            r'booking\s+required',
            r'registration\s+needed',
            r'livestream\s+available'
        ]
        
        notes = []
        for pattern in note_patterns:
            if re.search(pattern, text, re.I):
                match = re.search(pattern, text, re.I)
                notes.append(match.group().strip())
        
        return '; '.join(notes) if notes else None
    
    def _extract_from_text_patterns(self, soup: BeautifulSoup, url: str) -> List[Prayer]:
        """Extract from text using pattern matching"""
        prayers = []
        text = soup.get_text()
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        
        for line in lines:
            prayer = self._parse_prayer_text_line(line)
            if prayer:
                prayers.append(prayer)
        
        return prayers
    
    def _extract_from_json_data(self, soup: BeautifulSoup, url: str) -> List[Prayer]:
        """Extract from embedded JSON data"""
        prayers = []
        
        # Look for script tags with JSON data
        scripts = soup.find_all('script')
        for script in scripts:
            if not script.string:
                continue
            
            # Try to find JSON-like prayer data
            try:
                # Look for prayer time patterns in script content
                if any(prayer in script.string.lower() 
                      for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']):
                    
                    # Try to parse as JSON
                    json_match = re.search(r'\{.*\}', script.string)
                    if json_match:
                        data = json.loads(json_match.group())
                        prayers.extend(self._parse_json_prayer_data(data))
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return prayers
    
    def _parse_prayer_text_line(self, text: str) -> Optional[Prayer]:
        """Parse a single line of text for prayer information"""
        text_lower = text.lower()
        
        # Check for prayer name
        prayer_name = None
        for prayer in PrayerName:
            if prayer.value in text_lower:
                prayer_name = prayer
                break
        
        if not prayer_name:
            return None
        
        # Extract time
        time_match = re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?', text)
        if not time_match:
            return None
        
        adhan_time = self._normalize_time(time_match.group())
        
        # Look for iqama time (usually follows adhan)
        iqama_match = re.search(r'iqama[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)', text, re.I)
        iqama_time = None
        if iqama_match:
            iqama_time = self._normalize_time(iqama_match.group(1))
        
        return Prayer(
            prayer_name=prayer_name,
            adhan_time=adhan_time,
            iqama_time=iqama_time
        )
    
    def _normalize_time(self, time_str: str) -> str:
        """Normalize time to HH:MM format"""
        time_str = time_str.strip()
        
        # Parse 12-hour format
        match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?', time_str)
        if not match:
            return time_str
        
        hour = int(match.group(1))
        minute = int(match.group(2))
        ampm = match.group(3)
        
        if ampm:
            if ampm.upper() == 'PM' and hour != 12:
                hour += 12
            elif ampm.upper() == 'AM' and hour == 12:
                hour = 0
        
        return f"{hour:02d}:{minute:02d}"
    
    def _parse_table_row(self, cells, headers: List[str]) -> Optional[Prayer]:
        """Parse a table row for prayer information"""
        if len(cells) < 2:
            return None
        
        # First cell usually contains prayer name
        prayer_text = cells[0].get_text().strip()
        prayer_name = self._parse_prayer_name(prayer_text)
        
        if not prayer_name:
            return None
        
        # Second cell usually contains adhan time
        adhan_time = self._normalize_time(cells[1].get_text().strip())
        
        # Third cell might contain iqama time
        iqama_time = None
        if len(cells) > 2:
            iqama_candidate = self._normalize_time(cells[2].get_text().strip())
            # Validate that it looks like a time
            if re.match(r'\d{1,2}:\d{2}', iqama_candidate):
                iqama_time = iqama_candidate
        
        return Prayer(
            prayer_name=prayer_name,
            adhan_time=adhan_time,
            iqama_time=iqama_time
        )
    
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
    
    def _clean_imam_name(self, name: str) -> str:
        """Clean and format imam name"""
        # Remove common prefixes that might be included
        prefixes = ['imam', 'dr', 'sheikh', 'shaykh', 'ustaz', 'maulana', 'professor', 'prof', 'mufti']
        
        words = name.split()
        cleaned_words = []
        
        for word in words:
            word_clean = word.strip('.,():').lower()
            if word_clean not in prefixes:
                cleaned_words.append(word)
        
        return ' '.join(cleaned_words).strip()
    
    def _is_today_cell(self, cell, today: datetime) -> bool:
        """Check if a calendar cell represents today"""
        cell_text = cell.get_text().strip()
        
        # Check for today's date in various formats
        today_patterns = [
            str(today.day),
            today.strftime('%d'),
            today.strftime('%Y-%m-%d'),
            'today'
        ]
        
        return any(pattern in cell_text.lower() for pattern in today_patterns)
    
    def _extract_prayers_from_cell(self, cell) -> List[Prayer]:
        """Extract prayers from a calendar cell"""
        prayers = []
        cell_text = cell.get_text()
        lines = [line.strip() for line in cell_text.split('\n') if line.strip()]
        
        for line in lines:
            prayer = self._parse_prayer_text_line(line)
            if prayer:
                prayers.append(prayer)
        
        return prayers
    
    def _parse_prayer_element(self, element) -> Optional[Prayer]:
        """Parse a DOM element for prayer information"""
        text = element.get_text().strip()
        return self._parse_prayer_text_line(text)
    
    def _parse_structured_prayer_data(self, data: Dict) -> List[Prayer]:
        """Parse structured JSON-LD data for prayers"""
        prayers = []
        # Implementation depends on specific structured data format
        # This would need to be customized based on common schemas
        return prayers
    
    def _parse_json_prayer_data(self, data: Dict) -> List[Prayer]:
        """Parse JSON prayer data"""
        prayers = []
        # Implementation for parsing JSON prayer data
        # This would handle various JSON formats used by mosque websites
        return prayers
    
    def _get_default_prayers(self) -> List[Prayer]:
        """Return default prayer times when scraping fails"""
        return [
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:50", iqama_time="06:00"),
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="12:45", iqama_time="13:00"),
            Prayer(prayer_name=PrayerName.ASR, adhan_time="16:15", iqama_time="16:30"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="19:10", iqama_time="19:20"),
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="20:30", iqama_time="20:45"),
            Prayer(
                prayer_name=PrayerName.JUMAA,
                adhan_time="12:30",
                iqama_time="12:30",
                jumaa_sessions=[
                    JumaaSession(
                        session_time="12:30",
                        imam_name="Imam Abdullah",
                        language="English",
                        khutba_topic="Weekly Reminder"
                    )
                ]
            )
        ]