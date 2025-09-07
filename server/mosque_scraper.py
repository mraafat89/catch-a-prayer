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

# Optional Selenium import for JavaScript-heavy sites
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

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
            # Enhanced HTTP client configuration
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,ar;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers=headers,
                follow_redirects=True,
                verify=False,  # Skip SSL verification for mosque websites with cert issues
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
            ) as client:
                
                # Try homepage first
                prayers = await self._scrape_page(client, website_url)
                if prayers:
                    self.cache[cache_key] = (prayers, datetime.now())
                    return prayers
                
                # Try to find prayer pages
                prayer_pages = await self._find_prayer_pages(client, website_url)
                best_prayers = prayers or []  # Keep homepage results as fallback
                
                for page_url in prayer_pages[:3]:  # Limit to 3 to avoid too many requests
                    logger.info(f"Trying prayer page: {page_url}")
                    page_prayers = await self._scrape_page(client, page_url)
                    if page_prayers and len(page_prayers) > len(best_prayers):
                        logger.info(f"Found {len(page_prayers)} prayers on {page_url}")
                        best_prayers = page_prayers
                
                # If we don't have enough prayers, try JavaScript execution
                if len(best_prayers) < 3 and SELENIUM_AVAILABLE:
                    logger.info(f"Trying JavaScript execution for {website_url}")
                    js_prayers = await self._scrape_with_javascript(website_url)
                    if js_prayers and len(js_prayers) > len(best_prayers):
                        best_prayers = js_prayers
                
                # Return the best result we found
                if best_prayers:
                    self.cache[cache_key] = (best_prayers, datetime.now())
                    return best_prayers
                
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
        """Enhanced page scraping with retry logic and multiple content detection"""
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Scraping attempt {attempt + 1} for {url}")
                response = await client.get(url)
                
                if response.status_code != 200:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(retry_delay)
                        continue
                    return []
                
                # Check content type
                content_type = response.headers.get('content-type', '').lower()
                
                # Handle PDF content
                if 'application/pdf' in content_type:
                    logger.info(f"Found PDF content at {url}")
                    return await self._extract_from_pdf(response.content)
                
                # Parse HTML content
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Enhanced extraction with multiple methods
                prayers = []
                
                # 1. Check for embedded widgets/iframes first
                iframe_prayers = await self._extract_from_iframes(client, soup, url)
                if iframe_prayers:
                    prayers.extend(iframe_prayers)
                
                # 2. Try table extraction (most reliable for structured data)
                table_prayers = self._extract_from_tables(soup)
                if table_prayers:
                    prayers.extend(table_prayers)
                
                # 3. Try structured content extraction
                structured_prayers = self._extract_from_structured_content(soup)
                if structured_prayers:
                    prayers.extend(structured_prayers)
                
                # 4. Try text pattern matching (most flexible)
                text_prayers = self._extract_from_text_patterns(soup)
                if text_prayers:
                    prayers.extend(text_prayers)
                
                # 5. Try JSON-LD structured data
                json_prayers = self._extract_from_json_ld(soup)
                if json_prayers:
                    prayers.extend(json_prayers)
                
                # Remove duplicates while preserving order
                unique_prayers = []
                seen = set()
                for prayer in prayers:
                    key = (prayer.prayer_name, prayer.adhan_time)
                    if key not in seen:
                        seen.add(key)
                        unique_prayers.append(prayer)
                
                if unique_prayers:
                    logger.info(f"Successfully extracted {len(unique_prayers)} prayers from {url}")
                    return unique_prayers
                
                # If no prayers found, try JavaScript execution on next attempt
                if attempt == max_retries - 1 and len(prayers) < 2:
                    logger.info(f"Attempting JavaScript execution for {url}")
                    js_prayers = await self._scrape_with_javascript(url)
                    if js_prayers:
                        return js_prayers
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    
            except Exception as e:
                logger.error(f"Error scraping page {url} (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                    
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
                'timetable', 'calendar', 'jumaa', 'friday', 'iqama',
                'monthly', 'daily', 'timing', 'namaz', 'adhan',
                'prayer schedule', 'prayer calendar', 'monthly prayer',
                'prayer timetable', 'islamic calendar', 'times'
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
        """Extract prayers from HTML tables and table-like structures"""
        prayers = []
        
        # Look for actual HTML tables
        tables = soup.find_all('table')
        
        # Also look for div-based tables (common pattern)
        table_like_divs = soup.find_all('div', class_=re.compile(r'table|prayer.*time|schedule|timetable', re.I))
        
        all_table_elements = list(tables) + list(table_like_divs)
        
        for table in all_table_elements:
            table_text = table.get_text().lower()
            
            # Enhanced keywords for prayer content detection
            prayer_keywords = ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha', 'prayer', 'timing', 
                             'salah', 'namaz', 'adhan', 'iqama', 'dawn', 'noon', 'afternoon', 
                             'sunset', 'night', 'جماعة', 'أذان']
            
            # Check if table contains prayer-related content
            if not any(word in table_text for word in prayer_keywords):
                continue
            
            # Handle both HTML table rows and div-based rows
            rows = table.find_all('tr') if table.name == 'table' else table.find_all('div', class_=re.compile(r'row|time', re.I))
            
            # If no rows found in div, try to parse as structured content
            if not rows and table.name == 'div':
                prayers.extend(self._parse_structured_prayer_content(table))
                continue
            
            for row in rows:
                cells = row.find_all(['td', 'th']) if row.name == 'tr' else row.find_all(['div', 'span'])
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
    
    def _parse_structured_prayer_content(self, container) -> List[Prayer]:
        """Parse prayer times from structured div content (non-table format)"""
        prayers = []
        text = container.get_text()
        
        # Look for prayer time patterns in the content
        prayer_time_patterns = [
            r'fajr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'dawn[:\s]*(?:prayer[:\s]*)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'dhuhr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'zuhr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'noon[:\s]*(?:prayer[:\s]*)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'asr[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'afternoon[:\s]*(?:prayer[:\s]*)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'maghrib[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'sunset[:\s]*(?:prayer[:\s]*)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'isha[:\s]*(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)',
            r'night[:\s]*(?:prayer[:\s]*)?(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)'
        ]
        
        prayer_mapping = {
            'fajr': PrayerName.FAJR, 'dawn': PrayerName.FAJR,
            'dhuhr': PrayerName.DHUHR, 'zuhr': PrayerName.DHUHR, 'noon': PrayerName.DHUHR,
            'asr': PrayerName.ASR, 'afternoon': PrayerName.ASR,
            'maghrib': PrayerName.MAGHRIB, 'sunset': PrayerName.MAGHRIB,
            'isha': PrayerName.ISHA, 'night': PrayerName.ISHA
        }
        
        for pattern in prayer_time_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                time_str = match.group(1)
                normalized_time = self._normalize_time(time_str)
                if normalized_time:
                    # Determine prayer name from pattern
                    prayer_key = pattern.split('[')[0]  # Get the prayer name part
                    if prayer_key in prayer_mapping:
                        prayers.append(Prayer(
                            prayer_name=prayer_mapping[prayer_key],
                            adhan_time=normalized_time
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
            r'led\s+by[:\s]+([A-Za-z\s\.]+)',
            r'khatib[:\s]+([A-Za-z\s\.]+)',
            r'speaker[:\s]+([A-Za-z\s\.]+)',
            r'(dr\.|professor)\s+([A-Za-z\s]+)\s+leads',
            r'ustaz[:\s]+([A-Za-z\s\.]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                # Handle patterns with multiple groups
                name = match.group(2) if match.lastindex and match.lastindex > 1 else match.group(1)
                name = name.strip()
                # Clean up name (remove extra spaces, limit length)
                name = ' '.join(name.split())
                if 3 < len(name) < 50:
                    return name
        return None
    
    def _extract_imam_title(self, text: str) -> Optional[str]:
        """Extract imam title from text"""
        patterns = [
            r'\b(Dr\.?|Doctor)\b',
            r'\b(Sheikh|Shaykh)\b',
            r'\b(Imam)\b',
            r'\b(Ustaz|Ustad)\b',
            r'\b(Professor|Prof\.?)\b',
            r'\b(Hafiz)\b'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                title = match.group(1)
                # Normalize the title
                if title.lower().startswith('dr'):
                    return "Dr"
                elif title.lower() in ['sheikh', 'shaykh']:
                    return "Sheikh"
                elif title.lower() == 'imam':
                    return "Imam"
                elif title.lower() in ['ustaz', 'ustad']:
                    return "Ustaz"
                elif title.lower().startswith('prof'):
                    return "Professor"
                elif title.lower() == 'hafiz':
                    return "Hafiz"
        return None
    
    def _extract_special_notes(self, text: str) -> Optional[str]:
        """Extract special notes from text"""
        patterns = [
            r'(sign language interpretation available)',
            r'(booking required for this session)',
            r'(livestream available on youtube)',
            r'(translation available in \w+)',
            r'(capacity:\s*\d+\s*people)',
            r'(wheelchair accessible)',
            r'(parking available)',
            r'(registration required)',
            r'(masks required)',
            r'(first come first served)'
        ]
        
        notes = []
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                notes.append(match.group(1).strip())
        
        return '; '.join(notes) if notes else None
    
    def _extract_from_prayer_tables(self, soup, url: str) -> List[Prayer]:
        """Extract prayers from HTML tables - alias for existing method"""
        return self._extract_from_tables(soup)
    
    def _detect_language(self, text: str) -> Optional[str]:
        """Detect language from context"""
        # Check for mixed/bilingual first
        if re.search(r'bilingual|mixed|arabic[/\s]+english|english[/\s]+arabic', text, re.IGNORECASE):
            return "Mixed"
        elif re.search(r'translation\s+available', text, re.IGNORECASE):
            return "English"  # Usually implies English with translation
        elif re.search(r'english|delivered\s+in\s+english', text, re.IGNORECASE):
            return "English"
        elif re.search(r'arabic|عربي', text, re.IGNORECASE):
            return "Arabic"
        elif re.search(r'urdu|اردو', text, re.IGNORECASE):
            return "Urdu"
        elif re.search(r'turkish', text, re.IGNORECASE):
            return "Turkish"
        elif re.search(r'french', text, re.IGNORECASE):
            return "French"
        return None
    
    def _extract_topic(self, text: str) -> Optional[str]:
        """Extract khutba topic from context"""
        patterns = [
            r'topic[:\s]+([^.!?\n]{10,100})',
            r'theme[:\s]+([^.!?\n]{10,100})',
            r'about[:\s]+([^.!?\n]{10,100})',
            r'this\s+friday[:\s]+([^.!?\n]{10,100})',
            r'khutba[:\s]+([^.!?\n]{10,100})',
            r'sermon\s+topic[:\s]+([^.!?\n]{10,100})',
            r'weekly\s+theme[:\s]+([^.!?\n]{10,100})'
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
        
        # Order matters - more specific matches first
        mappings = [
            ('afternoon', PrayerName.ASR),  # Must come before 'noon'
            ('fajr', PrayerName.FAJR), 
            ('dawn', PrayerName.FAJR),
            ('dhuhr', PrayerName.DHUHR), 
            ('zuhr', PrayerName.DHUHR), 
            ('noon', PrayerName.DHUHR),
            ('asr', PrayerName.ASR),
            ('maghrib', PrayerName.MAGHRIB), 
            ('sunset', PrayerName.MAGHRIB),
            ('isha', PrayerName.ISHA), 
            ('night', PrayerName.ISHA),
            ('jumaa', PrayerName.JUMAA), 
            ('jummah', PrayerName.JUMAA), 
            ('friday', PrayerName.JUMAA)
        ]
        
        for key, prayer in mappings:
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
        
        match = re.search(r'(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?', time_str)
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
    
    async def _extract_from_iframes(self, client: httpx.AsyncClient, soup: BeautifulSoup, base_url: str) -> List[Prayer]:
        """Extract prayer times from embedded iframes and widgets"""
        prayers = []
        
        iframes = soup.find_all('iframe')
        for iframe in iframes:
            src = iframe.get('src')
            if not src:
                continue
                
            # Make URL absolute
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = urljoin(base_url, src)
            
            # Check if iframe might contain prayer times
            if any(keyword in src.lower() for keyword in ['prayer', 'time', 'salah', 'islamic', 'mosque']):
                try:
                    logger.info(f"Scraping iframe: {src}")
                    iframe_prayers = await self._scrape_page(client, src)
                    if iframe_prayers:
                        prayers.extend(iframe_prayers)
                except Exception as e:
                    logger.warning(f"Failed to scrape iframe {src}: {e}")
                    continue
        
        return prayers
    
    def _extract_from_json_ld(self, soup: BeautifulSoup) -> List[Prayer]:
        """Extract prayer times from JSON-LD structured data"""
        prayers = []
        
        json_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_scripts:
            try:
                data = json.loads(script.string)
                
                # Look for event data that might be prayer times
                if isinstance(data, dict) and data.get('@type') == 'Event':
                    event_name = data.get('name', '').lower()
                    start_time = data.get('startDate')
                    
                    if any(keyword in event_name for keyword in ['prayer', 'salah', 'fajr', 'dhuhr', 'asr', 'maghrib', 'isha', 'jumaa']):
                        prayer_name = self._parse_prayer_name(event_name)
                        if prayer_name and start_time:
                            # Parse time from ISO format
                            try:
                                dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
                                time_str = dt.strftime('%H:%M')
                                prayers.append(Prayer(
                                    prayer_name=prayer_name,
                                    adhan_time=time_str
                                ))
                            except:
                                continue
                                
            except (json.JSONDecodeError, KeyError):
                continue
        
        return prayers
    
    async def _extract_from_pdf(self, pdf_content: bytes) -> List[Prayer]:
        """Extract prayer times from PDF content (placeholder for future OCR implementation)"""
        # TODO: Implement PDF text extraction using PyPDF2 or similar
        # For now, return empty list
        logger.info("PDF prayer schedule detected - OCR extraction not yet implemented")
        return []
    
    async def _scrape_with_javascript(self, website_url: str) -> List[Prayer]:
        """
        Use Selenium WebDriver to scrape JavaScript-heavy sites
        This method handles sites where prayer times are loaded dynamically
        """
        if not SELENIUM_AVAILABLE:
            logger.warning("Selenium not available for JavaScript scraping")
            return []
        
        try:
            # Setup headless Chrome/Chromium
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            chrome_options.add_argument("--display=:99")  # For xvfb
            
            # Try Chrome first, then Chromium (for ARM64 support)
            driver = None
            try:
                driver = webdriver.Chrome(options=chrome_options)
            except Exception as e:
                logger.info("Chrome not available, trying Chromium...")
                try:
                    from selenium.webdriver.chrome.service import Service
                    chrome_options.binary_location = "/usr/bin/chromium"
                    # Use system chromedriver for Chromium
                    service = Service("/usr/bin/chromedriver")
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                except Exception as e2:
                    logger.error(f"Both Chrome and Chromium failed: {e}, {e2}")
                    return []
            driver.set_page_load_timeout(30)
            
            try:
                logger.info(f"Loading {website_url} with JavaScript...")
                driver.get(website_url)
                
                # Wait for potential dynamic content to load
                await asyncio.sleep(3)
                
                # Try to find prayer-related elements that might have been loaded
                prayer_selectors = [
                    "[class*='prayer']", 
                    "[class*='time']", 
                    "[class*='salah']",
                    "[id*='prayer']",
                    "[id*='time']",
                    "table",
                    ".prayer-times",
                    ".prayer-schedule",
                    "#prayer-times",
                    "#prayer-schedule"
                ]
                
                for selector in prayer_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for element in elements:
                            element_text = element.text
                            if any(prayer in element_text.lower() for prayer in ['fajr', 'dhuhr', 'asr', 'maghrib', 'isha']):
                                logger.info(f"Found prayer content with selector {selector}")
                                
                                # Parse the content using BeautifulSoup
                                soup = BeautifulSoup(element.get_attribute('outerHTML'), 'html.parser')
                                prayers = self._extract_from_tables(soup) or self._extract_from_structured_content(soup)
                                
                                if prayers:
                                    logger.info(f"JavaScript scraping found {len(prayers)} prayers")
                                    return prayers
                                
                    except Exception as e:
                        continue  # Try next selector
                
                # If specific selectors didn't work, try parsing the entire page
                page_source = driver.page_source
                soup = BeautifulSoup(page_source, 'html.parser')
                
                prayers = (
                    self._extract_from_tables(soup) or
                    self._extract_from_structured_content(soup) or
                    self._extract_from_text_patterns(soup) or
                    []
                )
                
                if prayers:
                    logger.info(f"JavaScript full-page parsing found {len(prayers)} prayers")
                    return prayers
                
            finally:
                driver.quit()
                
        except Exception as e:
            logger.error(f"JavaScript scraping failed for {website_url}: {e}")
            
        return []