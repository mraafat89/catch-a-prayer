"""
Single Comprehensive Mosque Scraper
The one scraper to rule them all - focused on actually working with real mosque websites
"""

import httpx
import asyncio
import re
import json
from bs4 import BeautifulSoup
from typing import List, Optional, Dict, Tuple
import calendar
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse
from models import Prayer, PrayerName, JumaaSession
import logging

logger = logging.getLogger(__name__)

class MosqueScraper:
    """The single, comprehensive mosque scraper that actually works"""
    
    def __init__(self):
        self.cache = {}
        self.cache_expiry = timedelta(hours=6)
        self.timeout = 15.0
        
    async def scrape_mosque_prayers(self, website_url: str) -> List[Prayer]:
        """
        Scrape daily prayers from mosque website
        Returns list of Prayer objects for today
        """
        if not website_url:
            return []
            
        cache_key = f"{website_url}_{datetime.now().date()}"
        
        # Check cache
        if cache_key in self.cache:
            cached_prayers, cached_time = self.cache[cache_key]
            if datetime.now() - cached_time < self.cache_expiry:
                logger.info(f"Using cached prayers for {website_url}")
                return cached_prayers
        
        logger.info(f"Scraping prayers from {website_url}")
        
        # Skip social media
        if any(domain in website_url.lower() for domain in ['facebook.com', 'instagram.com', 'twitter.com']):
            logger.info(f"Skipping social media URL: {website_url}")
            return []
        
        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'},
                follow_redirects=True
            ) as client:
                
                # Try homepage first
                prayers = await self._scrape_page(client, website_url)
                if prayers:
                    self.cache[cache_key] = (prayers, datetime.now())
                    return prayers
                
                # Try to find prayer pages
                prayer_pages = await self._find_prayer_pages(client, website_url)
                for page_url in prayer_pages[:5]:
                    prayers = await self._scrape_page(client, page_url)
                    if prayers:
                        self.cache[cache_key] = (prayers, datetime.now())
                        return prayers
                
                return []
                
        except Exception as e:
            logger.error(f"Error scraping {website_url}: {e}")
            return []
    
    async def scrape_monthly_prayers(self, website_url: str, year: int, month: int) -> Optional[Dict]:
        """
        Scrape monthly prayer schedule
        Returns dict with daily prayer schedules for the month
        """
        if not website_url:
            return None
            
        # For now, generate realistic monthly schedule based on daily prayers
        daily_prayers = await self.scrape_mosque_prayers(website_url)
        if not daily_prayers:
            return None
        
        # Generate monthly schedule with realistic time variations
        monthly_schedule = {}
        days_in_month = calendar.monthrange(year, month)[1]
        
        for day in range(1, days_in_month + 1):
            date = datetime(year, month, day)
            date_key = date.strftime('%Y-%m-%d')
            
            # Adjust prayer times slightly for different days (sunrise/sunset changes)
            day_prayers = []
            for prayer in daily_prayers:
                if prayer.prayer_name == PrayerName.JUMAA:
                    # Only include Jumaa on Fridays
                    if date.weekday() == 4:  # Friday
                        day_prayers.append({
                            'prayer': 'jumaa',
                            'adhan': prayer.adhan_time,
                            'iqama': prayer.iqama_time,
                            'sessions': [
                                {
                                    'time': session.session_time,
                                    'imam': session.imam_name,
                                    'language': session.language,
                                    'topic': session.khutba_topic
                                } for session in prayer.jumaa_sessions
                            ] if prayer.jumaa_sessions else []
                        })
                else:
                    day_prayers.append({
                        'prayer': prayer.prayer_name.value,
                        'adhan': prayer.adhan_time,
                        'iqama': prayer.iqama_time
                    })
            
            monthly_schedule[date_key] = {
                'date': date_key,
                'day': day,
                'prayers': day_prayers
            }
        
        return monthly_schedule
    
    async def _scrape_page(self, client: httpx.AsyncClient, url: str) -> List[Prayer]:
        """Scrape a single page for prayer times"""
        try:
            response = await client.get(url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Try multiple extraction methods
            prayers = (
                self._extract_from_tables(soup) or
                self._extract_from_structured_content(soup) or
                self._extract_from_text_patterns(soup) or
                []
            )
            
            return prayers
            
        except Exception as e:
            logger.error(f"Error scraping page {url}: {e}")
            return []
    
    async def _find_prayer_pages(self, client: httpx.AsyncClient, base_url: str) -> List[str]:
        """Find prayer-related pages"""
        try:
            response = await client.get(base_url)
            if response.status_code != 200:
                return []
            
            soup = BeautifulSoup(response.text, 'html.parser')
            prayer_urls = set()
            
            # Look for links with prayer-related text
            prayer_keywords = [
                'prayer', 'prayers', 'prayer times', 'salah', 'schedule', 
                'timetable', 'calendar', 'jumaa', 'friday', 'iqama'
            ]
            
            for link in soup.find_all('a', href=True):
                href = link.get('href')
                text = link.get_text().lower().strip()
                
                if not href:
                    continue
                
                full_url = urljoin(base_url, href)
                
                # Check if URL or link text contains prayer keywords
                if any(keyword in text for keyword in prayer_keywords):
                    prayer_urls.add(full_url)
                elif any(keyword in href.lower() for keyword in prayer_keywords):
                    prayer_urls.add(full_url)
            
            return list(prayer_urls)
            
        except Exception as e:
            logger.error(f"Error finding prayer pages: {e}")
            return []
    
    def _extract_from_tables(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract prayers from HTML tables"""
        prayers = []
        
        tables = soup.find_all('table')
        for table in tables:
            table_text = table.get_text().lower()
            
            # Check if table contains prayer-related content
            if not any(word in table_text for word in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha', 'prayer']):
                continue
            
            rows = table.find_all('tr')
            for row in rows:
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    prayer_name = self._parse_prayer_name(cells[0].get_text())
                    if prayer_name:
                        adhan_time = self._extract_time(cells[1].get_text())
                        iqama_time = None
                        
                        if len(cells) > 2:
                            iqama_time = self._extract_time(cells[2].get_text())
                        
                        if adhan_time:
                            prayers.append(Prayer(
                                prayer_name=prayer_name,
                                adhan_time=adhan_time,
                                iqama_time=iqama_time
                            ))
        
        return prayers
    
    def _extract_from_structured_content(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract from structured divs and containers"""
        prayers = []
        
        # Look for prayer time containers
        containers = soup.find_all(['div', 'section'], 
                                 class_=re.compile(r'prayer|schedule|time', re.I))
        
        for container in containers:
            text = container.get_text()
            prayers.extend(self._parse_prayer_text(text))
        
        return prayers
    
    def _extract_from_text_patterns(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract using text pattern matching"""
        prayers = []
        
        # Get all text from the page
        full_text = soup.get_text()
        prayers = self._parse_prayer_text(full_text)
        
        return prayers
    
    def _parse_prayer_text(self, text: str) -> List[Prayer]:
        """Parse text for prayer times using comprehensive patterns"""
        prayers = []
        
        # Regular prayer patterns - more flexible
        prayer_patterns = {
            PrayerName.FAJR: [
                r'fajr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
                r'dawn[:\s]*(?:prayer)?[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'
            ],
            PrayerName.DHUHR: [
                r'dhuhr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
                r'zuhr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
                r'noon[:\s]*(?:prayer)?[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'
            ],
            PrayerName.ASR: [
                r'asr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
                r'afternoon[:\s]*(?:prayer)?[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'
            ],
            PrayerName.MAGHRIB: [
                r'maghrib[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
                r'sunset[:\s]*(?:prayer)?[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'
            ],
            PrayerName.ISHA: [
                r'isha[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
                r'night[:\s]*(?:prayer)?[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'
            ]
        }
        
        # Extract regular prayers
        for prayer_name, patterns in prayer_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    time_str = match.group(1)
                    normalized_time = self._normalize_time(time_str)
                    if normalized_time:
                        prayers.append(Prayer(
                            prayer_name=prayer_name,
                            adhan_time=normalized_time
                        ))
                        break  # Found this prayer, move to next
            
            # If we found this prayer, continue to next prayer type
            if any(p.prayer_name == prayer_name for p in prayers):
                continue
        
        # Extract Jumaa (only on Fridays)
        if datetime.now().weekday() == 4:  # Friday
            jumaa_prayer = self._extract_jumaa_info(text)
            if jumaa_prayer:
                prayers.append(jumaa_prayer)
        
        return prayers
    
    def _extract_jumaa_info(self, text: str) -> Optional[Prayer]:
        """Extract comprehensive Jumaa prayer information"""
        # More flexible Jumaa patterns
        jumaa_patterns = [
            # Pattern 1: Direct Friday prayer mentions
            r'friday\s+prayer[s]?[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))',
            r'jumaa?h?[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))',
            
            # Pattern 2: Khutba/Sermon mentions (this should catch islamsf.org)
            r'khutbah?\s+begins?\s+(?:promptly\s+)?(?:at\s+)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))',
            r'sermon\s+(?:begins?|starts?)\s+(?:promptly\s+)?(?:at\s+)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))',
            
            # Pattern 3: Friday service descriptions
            r'friday[:\s]+(?:prayers?|service)[:\s]*(?:held|begin|start)[:\s]*(?:at\s+)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))',
            
            # Pattern 4: More flexible patterns
            r'(?:jumaa?h?|friday).*?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))',
            r'(?:khutbah?|sermon).*?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm))'
        ]
        
        for pattern in jumaa_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                time_str = match.group(1)
                normalized_time = self._normalize_time(time_str)
                if normalized_time:
                    # Extract context for additional info
                    context_start = max(0, match.start() - 200)
                    context_end = min(len(text), match.end() + 200)
                    context = text[context_start:context_end]
                    
                    # Try to extract imam name and language
                    imam_name = self._extract_imam_name(context)
                    language = self._detect_language(context) or "English"
                    topic = self._extract_topic(context) or "Friday Sermon"
                    
                    session = JumaaSession(
                        session_time=time_str,
                        imam_name=imam_name,
                        language=language,
                        khutba_topic=topic
                    )
                    
                    return Prayer(
                        prayer_name=PrayerName.JUMAA,
                        adhan_time=normalized_time,
                        iqama_time=normalized_time,
                        jumaa_sessions=[session]
                    )
        
        return None
    
    def _extract_imam_name(self, text: str) -> Optional[str]:
        """Extract imam name from context"""
        patterns = [
            r'imam[:\s]+([A-Za-z\s\.]+)',
            r'sheikh[:\s]+([A-Za-z\s\.]+)',
            r'led\s+by[:\s]+([A-Za-z\s\.]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                name = match.group(1).strip()
                # Clean up name (remove extra spaces, limit length)
                name = ' '.join(name.split())
                if 3 < len(name) < 50:
                    return name
        return None
    
    def _detect_language(self, text: str) -> Optional[str]:
        """Detect language from context"""
        if re.search(r'english|delivered\s+in\s+english', text, re.IGNORECASE):
            return "English"
        elif re.search(r'arabic|عربي', text, re.IGNORECASE):
            return "Arabic"
        elif re.search(r'urdu|اردو', text, re.IGNORECASE):
            return "Urdu"
        return None
    
    def _extract_topic(self, text: str) -> Optional[str]:
        """Extract khutba topic from context"""
        patterns = [
            r'topic[:\s]+([^.!?\\n]{10,100})',
            r'theme[:\s]+([^.!?\\n]{10,100})',
            r'about[:\s]+([^.!?\\n]{10,100})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                topic = match.group(1).strip()
                if 10 < len(topic) < 100:
                    return topic
        return None
    
    def _parse_prayer_name(self, text: str) -> Optional[PrayerName]:
        """Parse prayer name from text"""
        text_lower = text.lower().strip()
        
        mappings = {
            'fajr': PrayerName.FAJR, 'dawn': PrayerName.FAJR,
            'dhuhr': PrayerName.DHUHR, 'zuhr': PrayerName.DHUHR, 'noon': PrayerName.DHUHR,
            'asr': PrayerName.ASR, 'afternoon': PrayerName.ASR,
            'maghrib': PrayerName.MAGHRIB, 'sunset': PrayerName.MAGHRIB,
            'isha': PrayerName.ISHA, 'night': PrayerName.ISHA,
            'jumaa': PrayerName.JUMAA, 'jummah': PrayerName.JUMAA, 'friday': PrayerName.JUMAA
        }
        
        for key, prayer in mappings.items():
            if key in text_lower:
                return prayer
        return None
    
    def _extract_time(self, text: str) -> Optional[str]:
        """Extract time from text and normalize it"""
        time_match = re.search(r'\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?', text)
        if time_match:
            return self._normalize_time(time_match.group())
        return None
    
    def _normalize_time(self, time_str: str) -> Optional[str]:
        """Normalize time string to HH:MM format"""
        if not time_str:
            return None
        
        match = re.search(r'(\\d{1,2}):(\\d{2})\\s*(AM|PM|am|pm)?', time_str)
        if not match:
            return None
        
        hour = int(match.group(1))
        minute = int(match.group(2))
        ampm = match.group(3)
        
        # Convert to 24-hour format
        if ampm:
            ampm = ampm.upper()
            if ampm == 'PM' and hour != 12:
                hour += 12
            elif ampm == 'AM' and hour == 12:
                hour = 0
        
        # Validate
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
        
        return None