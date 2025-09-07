"""
Comprehensive test suite for mosque prayer time scraping functionality.
Tests the enhanced prayer scraper with various website formats and Jumaa information.
"""

import asyncio
import unittest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime, timedelta
from typing import List
import json

# Import our modules
from mosque_scraper import MosqueScraper
from models import Mosque, Location, Prayer, PrayerName, JumaaSession


class TestPrayerScrapingComprehensive(unittest.TestCase):
    """Comprehensive test suite for prayer time scraping"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.scraper = MosqueScraper()
        
        # Sample mosque for testing
        self.sample_mosque = Mosque(
            place_id="ChIJaS_test_mosque",
            name="Test Masjid",
            location=Location(latitude=37.7749, longitude=-122.4194, address="Test City"),
            website="https://testmasjid.org"
        )
    
    def test_time_normalization(self):
        """Test time format normalization"""
        test_cases = [
            ("6:30 AM", "06:30"),
            ("12:45 PM", "12:45"),
            ("6:30am", "06:30"),
            ("12:45pm", "12:45"),
            ("12:00 AM", "00:00"),
            ("12:00 PM", "12:00"),
            ("1:15 PM", "13:15")
        ]
        
        for input_time, expected in test_cases:
            with self.subTest(input=input_time):
                result = self.scraper._normalize_time(input_time)
                self.assertEqual(result, expected, f"Failed to normalize {input_time}")
    
    def test_prayer_name_parsing(self):
        """Test prayer name extraction from text"""
        test_cases = [
            ("Fajr", PrayerName.FAJR),
            ("Dawn Prayer", PrayerName.FAJR),
            ("Dhuhr", PrayerName.DHUHR),
            ("Zuhr", PrayerName.DHUHR),
            ("Noon Prayer", PrayerName.DHUHR),
            ("Asr", PrayerName.ASR),
            ("Afternoon", PrayerName.ASR),
            ("Maghrib", PrayerName.MAGHRIB),
            ("Sunset", PrayerName.MAGHRIB),
            ("Isha", PrayerName.ISHA),
            ("Night Prayer", PrayerName.ISHA),
            ("Jumaa", PrayerName.JUMAA),
            ("Jummah", PrayerName.JUMAA),
            ("Friday Prayer", PrayerName.JUMAA)
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._parse_prayer_name(input_text)
                self.assertEqual(result, expected, f"Failed to parse {input_text}")
    
    def test_imam_name_extraction(self):
        """Test imam name extraction from text"""
        test_cases = [
            ("Imam: Dr. Ahmed Ali", "Ahmed Ali"),
            ("Led by Sheikh Mohammed Hassan", "Mohammed Hassan"),
            ("Khatib: Ustaz Abdullah", "Abdullah"),
            ("Speaker: Professor Sarah Khan", "Sarah Khan"),
            ("Dr. Mohammed leads the prayer", "Mohammed"),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._extract_imam_name(input_text)
                self.assertIsNotNone(result, f"Failed to extract imam from {input_text}")
                self.assertIn(expected, result, f"Expected {expected} in {result}")
    
    def test_imam_title_extraction(self):
        """Test imam title extraction"""
        test_cases = [
            ("Dr. Ahmed Ali", "Dr"),
            ("Sheikh Mohammed", "Sheikh"),
            ("Imam Abdullah", "Imam"),
            ("Ustaz Hassan", "Ustaz"),
            ("Professor Sarah", "Professor")
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._extract_imam_title(input_text)
                self.assertIsNotNone(result, f"Failed to extract title from {input_text}")
                self.assertEqual(result.lower(), expected.lower())
    
    def test_language_detection(self):
        """Test language detection from text"""
        test_cases = [
            ("English Khutba at 12:30 PM", "English"),
            ("خطبة عربية الساعة ١:٣٠", "Arabic"),
            ("Urdu sermon اردو میں", "Urdu"),
            ("Bilingual Arabic/English", "Mixed"),
            ("Translation available", "Mixed"),
            ("Turkish language available", "Turkish")
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._detect_language(input_text)
                if expected:
                    self.assertIsNotNone(result, f"Failed to detect language in {input_text}")
                    self.assertEqual(result.lower(), expected.lower())
    
    def test_khutba_topic_extraction(self):
        """Test khutba topic extraction"""
        test_cases = [
            ("Topic: The Beauty of Islam", "The Beauty of Islam"),
            ("This Friday: Patience and Perseverance", "Patience and Perseverance"),
            ("Khutba: Community Unity", "Community Unity"),
            ("Sermon topic: Stories of the Prophets", "Stories of the Prophets"),
            ("Weekly theme: Charity in Islam", "Charity in Islam")
        ]
        
        mock_element = Mock()
        mock_element.parent = Mock()
        mock_element.parent.find_all = Mock(return_value=[])
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._extract_khutba_topic(input_text, mock_element)
                self.assertIsNotNone(result, f"Failed to extract topic from {input_text}")
                self.assertEqual(result, expected)
    
    def test_special_notes_extraction(self):
        """Test special notes extraction"""
        test_cases = [
            ("Sign language interpretation available", "Sign language"),
            ("Booking required for this session", "Booking required"),
            ("Livestream available on YouTube", "Livestream available"),
            ("Translation available in Urdu", "Translation available"),
            ("Capacity: 500 people", "Capacity")
        ]
        
        for input_text, expected_keyword in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._extract_special_notes(input_text)
                self.assertIsNotNone(result, f"Failed to extract notes from {input_text}")
                self.assertIn(expected_keyword.lower(), result.lower())

class TestTableExtractionMethods(unittest.TestCase):
    """Test table-based prayer time extraction"""
    
    def setUp(self):
        self.scraper = MosqueScraper()
    
    def test_simple_prayer_table_extraction(self):
        """Test extraction from simple HTML table"""
        html = """
        <table>
            <tr><th>Prayer</th><th>Adhan</th><th>Iqama</th></tr>
            <tr><td>Fajr</td><td>5:50 AM</td><td>6:00 AM</td></tr>
            <tr><td>Dhuhr</td><td>12:45 PM</td><td>1:00 PM</td></tr>
            <tr><td>Asr</td><td>4:15 PM</td><td>4:30 PM</td></tr>
            <tr><td>Maghrib</td><td>7:10 PM</td><td>7:20 PM</td></tr>
            <tr><td>Isha</td><td>8:30 PM</td><td>8:45 PM</td></tr>
        </table>
        """
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        prayers = self.scraper._extract_from_prayer_tables(soup, "test_url")
        
        self.assertEqual(len(prayers), 5)
        self.assertEqual(prayers[0].prayer_name, PrayerName.FAJR)
        self.assertEqual(prayers[0].adhan_time, "05:50")
        self.assertEqual(prayers[0].iqama_time, "06:00")
    
    def test_jumaa_table_extraction(self):
        """Test extraction of Jumaa sessions from table"""
        html = """
        <table class="jumaa-schedule">
            <tr><th>Time</th><th>Imam</th><th>Language</th><th>Topic</th></tr>
            <tr><td>12:30 PM</td><td>Dr. Ahmed Ali</td><td>English</td><td>The Importance of Prayer</td></tr>
            <tr><td>1:30 PM</td><td>Sheikh Mohammed</td><td>Arabic</td><td>الصبر في الإسلام</td></tr>
        </table>
        """
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        prayers = self.scraper._extract_from_prayer_tables(soup, "test_url")
        
        # Should extract Jumaa sessions
        self.assertTrue(len(prayers) > 0)

class TestJumaaSpecificExtraction(unittest.TestCase):
    """Test Jumaa-specific information extraction"""
    
    def setUp(self):
        self.scraper = MosqueScraper()
    
    def test_multi_session_jumaa_extraction(self):
        """Test extraction of multiple Jumaa sessions"""
        html = """
        <div class="jumaa-info">
            <h3>Friday Prayer Sessions</h3>
            <div class="session">
                <span class="time">12:30 PM</span>
                <span class="imam">Dr. Ahmed Ali</span>
                <span class="topic">The Beauty of Patience</span>
                <span class="language">English</span>
            </div>
            <div class="session">
                <span class="time">1:30 PM</span>
                <span class="imam">Sheikh Mohammed Hassan</span>
                <span class="topic">الأخلاق في الإسلام</span>
                <span class="language">Arabic</span>
            </div>
        </div>
        """
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        container = soup.find('div', class_='jumaa-info')
        
        jumaa_prayer = self.scraper._extract_jumaa_information(container)
        
        self.assertIsNotNone(jumaa_prayer)
        self.assertEqual(jumaa_prayer.prayer_name, PrayerName.JUMAA)
        self.assertEqual(len(jumaa_prayer.jumaa_sessions), 2)
        self.assertEqual(jumaa_prayer.jumaa_sessions[0].session_time, "12:30 PM")
        self.assertEqual(jumaa_prayer.jumaa_sessions[0].imam_name, "Ahmed Ali")
    
    def test_jumaa_session_parsing(self):
        """Test individual Jumaa session parsing"""
        html = """
        <div class="jumaa-session">
            <h4>First Session - 12:30 PM</h4>
            <p>Imam: Dr. Sarah Ahmed</p>
            <p>Topic: Community and Brotherhood in Islam</p>
            <p>Language: English with Arabic translation</p>
            <p>Special: Sign language interpretation available</p>
        </div>
        """
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        element = soup.find('div', class_='jumaa-session')
        
        session = self.scraper._parse_jumaa_session(element)
        
        self.assertIsNotNone(session)
        self.assertEqual(session.session_time, "12:30 PM")
        self.assertEqual(session.imam_name, "Sarah Ahmed")
        self.assertEqual(session.imam_title, "Dr")
        self.assertEqual(session.khutba_topic, "Community and Brotherhood in Islam")
        self.assertEqual(session.language, "English")
        self.assertIsNotNone(session.special_notes)

class TestWebsiteDiscovery(unittest.TestCase):
    """Test website link discovery for prayer pages"""
    
    def setUp(self):
        self.scraper = MosqueScraper()
    
    @patch('httpx.AsyncClient.get')
    async def test_prayer_page_discovery(self, mock_get):
        """Test discovery of prayer-related pages"""
        # Mock homepage with links to prayer pages
        homepage_html = """
        <html>
            <body>
                <nav>
                    <a href="/prayer-times">Prayer Times</a>
                    <a href="/schedule">Daily Schedule</a>
                    <a href="/jumaa">Friday Prayer</a>
                    <a href="/about">About Us</a>
                    <a href="/contact">Contact</a>
                </nav>
            </body>
        </html>
        """
        
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = homepage_html
        mock_get.return_value = mock_response
        
        client = Mock()
        client.get = mock_get
        
        prayer_urls = await self.scraper._discover_prayer_pages(client, "https://testmasjid.org")
        
        # Should find prayer-related URLs
        self.assertTrue(len(prayer_urls) > 0)
        prayer_related = [url for url in prayer_urls if any(
            keyword in url for keyword in ['prayer', 'schedule', 'jumaa']
        )]
        self.assertTrue(len(prayer_related) >= 3)

class TestErrorHandlingAndFallbacks(unittest.TestCase):
    """Test error handling and fallback mechanisms"""
    
    def setUp(self):
        self.scraper = MosqueScraper()
        self.mosque_with_website = Mosque(
            place_id="test_mosque",
            name="Test Mosque",
            location=Location(latitude=37.7749, longitude=-122.4194),
            website="https://testmasjid.org"
        )
        self.mosque_without_website = Mosque(
            place_id="test_mosque_no_site",
            name="Test Mosque No Website",
            location=Location(latitude=37.7749, longitude=-122.4194),
            website=None
        )
    
    async def test_fallback_to_defaults_no_website(self):
        """Test fallback to default prayers when no website"""
        prayers = await self.scraper.scrape_mosque_prayers(self.mosque_without_website)
        
        self.assertTrue(len(prayers) >= 5)  # Should have 5 daily prayers
        prayer_names = [p.prayer_name for p in prayers]
        self.assertIn(PrayerName.FAJR, prayer_names)
        self.assertIn(PrayerName.DHUHR, prayer_names)
        self.assertIn(PrayerName.ASR, prayer_names)
        self.assertIn(PrayerName.MAGHRIB, prayer_names)
        self.assertIn(PrayerName.ISHA, prayer_names)
    
    @patch('httpx.AsyncClient')
    async def test_network_error_handling(self, mock_client_class):
        """Test handling of network errors"""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.side_effect = Exception("Network error")
        mock_client_class.return_value = mock_client
        
        prayers = await self.scraper.scrape_mosque_prayers(self.mosque_with_website)
        
        # Should fallback to defaults
        self.assertTrue(len(prayers) >= 5)
    
    @patch('httpx.AsyncClient')
    async def test_http_error_handling(self, mock_client_class):
        """Test handling of HTTP errors"""
        mock_response = Mock()
        mock_response.status_code = 404
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        prayers = await self.scraper.scrape_mosque_prayers(self.mosque_with_website)
        
        # Should fallback to defaults
        self.assertTrue(len(prayers) >= 5)

class TestCacheManagement(unittest.TestCase):
    """Test caching functionality"""
    
    def setUp(self):
        self.scraper = MosqueScraper()
        self.mosque = Mosque(
            place_id="cache_test_mosque",
            name="Cache Test Mosque",
            location=Location(latitude=37.7749, longitude=-122.4194),
            website="https://cachetest.org"
        )
    
    @patch('httpx.AsyncClient')
    async def test_cache_hit(self, mock_client_class):
        """Test cache hit behavior"""
        # Mock successful response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = "<html><body>Fajr 5:30 AM</body></html>"
        
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get.return_value = mock_response
        mock_client_class.return_value = mock_client
        
        # First call should hit the network
        prayers1 = await self.scraper.scrape_mosque_prayers(self.mosque)
        
        # Second call should hit cache
        prayers2 = await self.scraper.scrape_mosque_prayers(self.mosque)
        
        self.assertEqual(len(prayers1), len(prayers2))
    
    def test_cache_expiry(self):
        """Test cache expiry logic"""
        # Set up expired cache entry
        cache_key = f"{self.mosque.place_id}_{datetime.now().date()}"
        expired_time = datetime.now() - timedelta(hours=7)  # Beyond 6-hour cache
        mock_prayers = [Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:30")]
        
        self.scraper.cache[cache_key] = (mock_prayers, expired_time)
        
        # Cache should be considered expired
        if cache_key in self.scraper.cache:
            cached_data, cached_time = self.scraper.cache[cache_key]
            is_expired = datetime.now() - cached_time >= self.scraper.cache_expiry
            self.assertTrue(is_expired)

class TestRealWorldScenarios(unittest.TestCase):
    """Test real-world mosque website scenarios"""
    
    def setUp(self):
        self.scraper = MosqueScraper()
    
    def test_complex_table_parsing(self):
        """Test parsing complex real-world table structures"""
        html = """
        <div class="prayer-timetable">
            <table border="1">
                <tr style="background-color: #f0f0f0;">
                    <td><strong>Prayer</strong></td>
                    <td><strong>Adhan</strong></td>
                    <td><strong>Iqama</strong></td>
                    <td><strong>Notes</strong></td>
                </tr>
                <tr>
                    <td>Fajr (Dawn)</td>
                    <td>5:50 am</td>
                    <td>6:00 am</td>
                    <td>Sunrise: 6:45 am</td>
                </tr>
                <tr bgcolor="#f9f9f9">
                    <td>Dhuhr (Noon)</td>
                    <td>12:45 pm</td>
                    <td>1:00 pm</td>
                    <td>Friday: See Jumaa times</td>
                </tr>
                <tr>
                    <td>Jumaa (Friday)</td>
                    <td>12:30 pm</td>
                    <td>12:30 pm</td>
                    <td>Imam: Dr. Ahmed Ali<br>Topic: Community Unity</td>
                </tr>
            </table>
        </div>
        """
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        prayers = self.scraper._extract_from_prayer_tables(soup, "test_url")
        
        self.assertTrue(len(prayers) >= 3)
        
        # Check that we got the expected prayers
        prayer_names = [p.prayer_name for p in prayers]
        self.assertIn(PrayerName.FAJR, prayer_names)
        self.assertIn(PrayerName.DHUHR, prayer_names)
        self.assertIn(PrayerName.JUMAA, prayer_names)

    def test_mixed_content_extraction(self):
        """Test extraction from mixed content (table + text + divs)"""
        html = """
        <div class="content">
            <h2>Daily Prayer Times</h2>
            <p>Fajr: 5:50 AM (Iqama: 6:00 AM)</p>
            <p>Dhuhr: 12:45 PM (Iqama: 1:00 PM)</p>
            
            <div class="special-prayers">
                <h3>Friday Prayer</h3>
                <div class="jumaa-session">
                    <strong>First Jumaa: 12:30 PM</strong><br>
                    Imam: Dr. Ahmed Ali<br>
                    Topic: "The Importance of Community"<br>
                    Language: English
                </div>
                <div class="jumaa-session">
                    <strong>Second Jumaa: 1:30 PM</strong><br>
                    Imam: Sheikh Mohammed<br>
                    Topic: "الصبر والشكر"<br>
                    Language: Arabic
                </div>
            </div>
            
            <table>
                <tr><td>Asr</td><td>4:15 PM</td></tr>
                <tr><td>Maghrib</td><td>7:20 PM</td></tr>
                <tr><td>Isha</td><td>8:45 PM</td></tr>
            </table>
        </div>
        """
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        # Try all extraction methods
        prayers = []
        extraction_methods = [
            self.scraper._extract_from_prayer_tables,
            self.scraper._extract_from_structured_divs,
            self.scraper._extract_from_text_patterns
        ]
        
        for method in extraction_methods:
            try:
                method_prayers = method(soup, "test_url")
                prayers.extend(method_prayers)
            except:
                continue
        
        # Should find prayers from multiple sources
        self.assertTrue(len(prayers) > 0)


def run_async_test(test_func):
    """Helper to run async test functions"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(test_func())
    finally:
        loop.close()


if __name__ == '__main__':
    # Custom test runner for async tests
    class AsyncTestResult(unittest.TextTestResult):
        def addTest(self, test):
            if hasattr(test, '_testMethodName'):
                method = getattr(test, test._testMethodName)
                if asyncio.iscoroutinefunction(method):
                    # Wrap async test method
                    original_method = method
                    def sync_wrapper(self):
                        return run_async_test(lambda: original_method())
                    setattr(test, test._testMethodName, sync_wrapper.__get__(test, test.__class__))
    
    class AsyncTestRunner(unittest.TextTestRunner):
        resultclass = AsyncTestResult
    
    # Run all tests
    unittest.main(testRunner=AsyncTestRunner(verbosity=2))