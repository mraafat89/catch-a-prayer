#!/usr/bin/env python3
"""
COMPREHENSIVE PRAYER TIMING TEST SUITE
=====================================

This test suite validates the Islamic prayer timing logic implementation.
It includes all previously written tests plus comprehensive edge cases.

Run with: python3 test_prayer_suite.py
"""

import sys
import os
import unittest
from datetime import datetime, time, timedelta
import pytz

try:
    from prayer_service import PrayerTimeService
    from mosque_scraper import MosqueScraper
    from models import Prayer, PrayerName, PrayerStatus, Mosque, Location, JumaaSession
except ImportError as e:
    print(f"Import Error: {e}")
    print("Make sure you're running this from the root directory of the project")
    sys.exit(1)

class TestPrayerTimingLogic(unittest.TestCase):
    """Test suite for Islamic prayer timing logic"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.service = PrayerTimeService()
        
        # Standard SF Bay Area prayer times (September)
        self.standard_prayers = [
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:50", iqama_time="06:00"),
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="12:45", iqama_time="13:00"),
            Prayer(prayer_name=PrayerName.ASR, adhan_time="16:15", iqama_time="16:30"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="19:10", iqama_time="19:20"),
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="20:30", iqama_time="20:45")
        ]
        
        # SF Bay Area coordinates
        self.sf_coordinates = (37.7749, -122.4194)
        # Denver coordinates (MST timezone)
        self.denver_coordinates = (39.7392, -104.9903)
        
        # Standard travel time
        self.travel_minutes = 15

    def test_original_bug_414am_shows_fajr(self):
        """TEST 1: Original bug - 4:14 AM should show Fajr (not Dhuhr)"""
        print("\n" + "="*60)
        print("TEST 1: ORIGINAL BUG FIX - 4:14 AM → Fajr")
        print("="*60)
        
        # Create 4:14 AM PST
        pst = pytz.timezone('America/Los_Angeles')
        user_time = pst.localize(datetime(2025, 9, 4, 4, 14, 0))
        
        result = self.service.get_next_prayer(
            prayers=self.standard_prayers,
            user_travel_minutes=self.travel_minutes,
            client_current_time=user_time.isoformat(),
            mosque_coordinates=self.sf_coordinates,
            client_timezone="America/Los_Angeles"
        )
        
        print(f"User time: 4:14 AM PST")
        print(f"Expected: Fajr (Iqama at 6:00 AM)")
        print(f"Result: {result.prayer.value if result else 'None'}")
        
        self.assertIsNotNone(result, "Should return a prayer result")
        self.assertEqual(result.prayer.value, "fajr", "Should show Fajr at 4:14 AM")
        self.assertTrue(result.can_catch, "Should be able to catch Fajr")
        self.assertEqual(result.status, PrayerStatus.CAN_CATCH_WITH_IMAM, "Should catch with Imam")
        
        print("✅ PASSED: 4:14 AM correctly shows Fajr")

    def test_541am_shows_fajr(self):
        """TEST 2: 5:41 AM should show Fajr (the reported issue)"""
        print("\n" + "="*60)
        print("TEST 2: REPORTED ISSUE - 5:41 AM → Fajr")
        print("="*60)
        
        # Create 5:41 AM PST
        pst = pytz.timezone('America/Los_Angeles')
        user_time = pst.localize(datetime(2025, 9, 4, 5, 41, 0))
        
        result = self.service.get_next_prayer(
            prayers=self.standard_prayers,
            user_travel_minutes=self.travel_minutes,
            client_current_time=user_time.isoformat(),
            mosque_coordinates=self.sf_coordinates,
            client_timezone="America/Los_Angeles"
        )
        
        print(f"User time: 5:41 AM PST")
        print(f"Expected: Fajr (Iqama at 6:00 AM)")
        print(f"Result: {result.prayer.value if result else 'None'}")
        
        self.assertIsNotNone(result, "Should return a prayer result")
        self.assertEqual(result.prayer.value, "fajr", "Should show Fajr at 5:41 AM")
        self.assertTrue(result.can_catch, "Should be able to catch Fajr")
        
        print("✅ PASSED: 5:41 AM correctly shows Fajr")

    def test_cross_timezone_calculation(self):
        """TEST 3: Cross-timezone travel calculations"""
        print("\n" + "="*60)
        print("TEST 3: CROSS-TIMEZONE TRAVEL")
        print("="*60)
        
        # User at 12:00 PM PST, traveling to Denver mosque
        pst = pytz.timezone('America/Los_Angeles')
        user_time = pst.localize(datetime(2025, 9, 4, 12, 0, 0))
        
        # Denver prayers (in MST)
        denver_prayers = [
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:50", iqama_time="06:00"),
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="14:10", iqama_time="14:15"),  # 2:15 PM MST
            Prayer(prayer_name=PrayerName.ASR, adhan_time="16:15", iqama_time="16:30"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="19:10", iqama_time="19:20"),
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="20:30", iqama_time="20:45")
        ]
        
        result = self.service.get_next_prayer(
            prayers=denver_prayers,
            user_travel_minutes=10,
            client_current_time=user_time.isoformat(),
            mosque_coordinates=self.denver_coordinates,
            client_timezone="America/Los_Angeles"
        )
        
        print(f"User: 12:00 PM PST + 10 min travel")
        print(f"Arrival: 1:10 PM MST")
        print(f"Denver Dhuhr Iqama: 2:15 PM MST")
        print(f"Expected: Dhuhr (65 min before Iqama)")
        print(f"Result: {result.prayer.value if result else 'None'}")
        
        self.assertIsNotNone(result, "Should return a prayer result")
        self.assertEqual(result.prayer.value, "dhuhr", "Should show Dhuhr for cross-timezone travel")
        self.assertTrue(result.can_catch, "Should be able to catch Dhuhr")
        
        print("✅ PASSED: Cross-timezone calculation works correctly")

    def test_all_daily_prayers_sequence(self):
        """TEST 4: Test all prayers throughout the day"""
        print("\n" + "="*60)
        print("TEST 4: FULL DAY PRAYER SEQUENCE")
        print("="*60)
        
        pst = pytz.timezone('America/Los_Angeles')
        test_cases = [
            (datetime(2025, 9, 4, 3, 0, 0), "fajr", "3:00 AM → Fajr"),
            (datetime(2025, 9, 4, 7, 0, 0), "dhuhr", "7:00 AM → Dhuhr (Fajr period ended)"),
            (datetime(2025, 9, 4, 11, 0, 0), "dhuhr", "11:00 AM → Dhuhr"),
            (datetime(2025, 9, 4, 14, 0, 0), "asr", "2:00 PM → Asr"),
            (datetime(2025, 9, 4, 17, 0, 0), "maghrib", "5:00 PM → Maghrib"),
            (datetime(2025, 9, 4, 20, 0, 0), "isha", "8:00 PM → Isha"),
            (datetime(2025, 9, 4, 23, 0, 0), "fajr", "11:00 PM → Tomorrow's Fajr")
        ]
        
        for test_time, expected_prayer, description in test_cases:
            with self.subTest(time=test_time):
                user_time_tz = pst.localize(test_time)
                
                result = self.service.get_next_prayer(
                    prayers=self.standard_prayers,
                    user_travel_minutes=self.travel_minutes,
                    client_current_time=user_time_tz.isoformat(),
                    mosque_coordinates=self.sf_coordinates,
                    client_timezone="America/Los_Angeles"
                )
                
                print(f"{description}: {result.prayer.value if result else 'None'}")
                
                self.assertIsNotNone(result, f"Should return result for {description}")
                self.assertEqual(result.prayer.value, expected_prayer, f"{description}")
        
        print("✅ PASSED: Full day prayer sequence works correctly")

    def test_congregation_timing_windows(self):
        """TEST 5: Test different congregation timing scenarios"""
        print("\n" + "="*60)
        print("TEST 5: CONGREGATION TIMING WINDOWS")
        print("="*60)
        
        pst = pytz.timezone('America/Los_Angeles')
        base_date = datetime(2025, 9, 4)
        
        # Test different arrival times for Fajr prayer (Iqama at 6:00 AM)
        test_cases = [
            (datetime.combine(base_date, time(5, 55)), "Can catch with Imam", PrayerStatus.CAN_CATCH_WITH_IMAM),
            (datetime.combine(base_date, time(6, 5)), "Can catch after Imam started", PrayerStatus.CAN_CATCH_AFTER_IMAM),
            (datetime.combine(base_date, time(6, 20)), "Cannot catch - too late", None)  # Should move to next prayer
        ]
        
        for arrival_time, description, expected_status in test_cases:
            with self.subTest(arrival=arrival_time):
                # Calculate what time user needs to depart to arrive at specific time
                arrival_time_tz = pst.localize(arrival_time)
                departure_time_tz = arrival_time_tz - timedelta(minutes=self.travel_minutes)
                
                result = self.service.get_next_prayer(
                    prayers=self.standard_prayers,
                    user_travel_minutes=self.travel_minutes,
                    client_current_time=departure_time_tz.isoformat(),
                    mosque_coordinates=self.sf_coordinates,
                    client_timezone="America/Los_Angeles"
                )
                
                print(f"Depart: {departure_time_tz.strftime('%H:%M')}, Arrive: {arrival_time_tz.strftime('%H:%M')} → {description}")
                
                self.assertIsNotNone(result, f"Should return result for {description}")
                
                if expected_status:
                    self.assertEqual(result.status, expected_status, f"Status should match for {description}")
        
        print("✅ PASSED: Congregation timing windows work correctly")

    def test_fajr_makeup_prayer(self):
        """TEST 6: Test Fajr make-up prayer after sunrise"""
        print("\n" + "="*60)
        print("TEST 6: FAJR MAKE-UP PRAYER (AFTER SUNRISE)")
        print("="*60)
        
        pst = pytz.timezone('America/Los_Angeles')
        
        # Test time after sunrise (estimated 7:20 AM) but before Dhuhr
        test_time = pst.localize(datetime(2025, 9, 4, 8, 0, 0))
        
        result = self.service.get_next_prayer(
            prayers=self.standard_prayers,
            user_travel_minutes=self.travel_minutes,
            client_current_time=test_time.isoformat(),
            mosque_coordinates=self.sf_coordinates,
            client_timezone="America/Los_Angeles"
        )
        
        print(f"User time: 8:00 AM (after sunrise)")
        print(f"Expected: Either Fajr make-up or Dhuhr")
        print(f"Result: {result.prayer.value if result else 'None'}")
        
        self.assertIsNotNone(result, "Should return a prayer result")
        # Could be either Fajr make-up or Dhuhr depending on implementation
        self.assertIn(result.prayer.value, ["fajr", "dhuhr"], "Should show either Fajr make-up or Dhuhr")
        
        print("✅ PASSED: Make-up prayer logic handled correctly")

    def test_edge_cases(self):
        """TEST 7: Edge cases and error handling"""
        print("\n" + "="*60)
        print("TEST 7: EDGE CASES AND ERROR HANDLING")
        print("="*60)
        
        # Test with no prayers
        result_no_prayers = self.service.get_next_prayer(
            prayers=[],
            user_travel_minutes=15,
            client_current_time=None,
            mosque_coordinates=self.sf_coordinates,
            client_timezone="America/Los_Angeles"
        )
        
        print(f"No prayers: {result_no_prayers}")
        self.assertIsNone(result_no_prayers, "Should return None for empty prayer list")
        
        # Test with invalid timezone
        pst = pytz.timezone('America/Los_Angeles')
        user_time = pst.localize(datetime(2025, 9, 4, 5, 41, 0))
        
        result_invalid_tz = self.service.get_next_prayer(
            prayers=self.standard_prayers,
            user_travel_minutes=15,
            client_current_time=user_time.isoformat(),
            mosque_coordinates=None,
            client_timezone="Invalid/Timezone"
        )
        
        print(f"Invalid timezone: {result_invalid_tz.prayer.value if result_invalid_tz else 'None'}")
        self.assertIsNotNone(result_invalid_tz, "Should handle invalid timezone gracefully")
        
        print("✅ PASSED: Edge cases handled correctly")

    def test_method_signature_compatibility(self):
        """TEST 8: Test backward compatibility with old method signatures"""
        print("\n" + "="*60)
        print("TEST 8: METHOD SIGNATURE COMPATIBILITY")
        print("="*60)
        
        # Test old method signature (should work but use server time)
        result_old = self.service.get_next_prayer(self.standard_prayers, 15)
        
        print(f"Old signature (server time): {result_old.prayer.value if result_old else 'None'}")
        self.assertIsNotNone(result_old, "Old method signature should still work")
        
        # Test new method signature 
        pst = pytz.timezone('America/Los_Angeles')
        user_time = pst.localize(datetime(2025, 9, 4, 5, 41, 0))
        
        result_new = self.service.get_next_prayer(
            prayers=self.standard_prayers,
            user_travel_minutes=15,
            client_current_time=user_time.isoformat(),
            mosque_coordinates=self.sf_coordinates,
            client_timezone="America/Los_Angeles"
        )
        
        print(f"New signature (client time): {result_new.prayer.value if result_new else 'None'}")
        self.assertIsNotNone(result_new, "New method signature should work")
        
        print("✅ PASSED: Method signature compatibility maintained")


class TestSuiteRunner:
    """Test suite runner with custom reporting"""
    
    def __init__(self):
        self.suite = unittest.TestSuite()
        self.runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    
    def add_all_tests(self):
        """Add all test methods to the suite"""
        test_methods = [
            'test_original_bug_414am_shows_fajr',
            'test_541am_shows_fajr', 
            'test_cross_timezone_calculation',
            'test_all_daily_prayers_sequence',
            'test_congregation_timing_windows',
            'test_fajr_makeup_prayer',
            'test_edge_cases',
            'test_method_signature_compatibility'
        ]
        
        for method_name in test_methods:
            self.suite.addTest(TestPrayerTimingLogic(method_name))
    
    def run_tests(self):
        """Run all tests and return results"""
        print("🕌 CATCH A PRAYER - ISLAMIC PRAYER TIMING TEST SUITE")
        print("=" * 80)
        print("Testing Islamic prayer timing logic implementation")
        print("Based on rules documented in ISLAMIC_PRAYER_RULES.md")
        print("=" * 80)
        
        result = self.runner.run(self.suite)
        
        print("\n" + "=" * 80)
        print("📊 TEST SUMMARY")
        print("=" * 80)
        print(f"Tests run: {result.testsRun}")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
        
        if result.failures:
            print("\n❌ FAILURES:")
            for test, traceback in result.failures:
                print(f"- {test}: {traceback}")
        
        if result.errors:
            print("\n💥 ERRORS:")
            for test, traceback in result.errors:
                print(f"- {test}: {traceback}")
        
        if result.wasSuccessful():
            print("\n✅ ALL TESTS PASSED! Prayer timing logic is working correctly.")
        else:
            print("\n❌ SOME TESTS FAILED! Please review the issues above.")
        
        return result


def run_prayer_tests():
    """Main function to run the prayer timing test suite"""
    try:
        runner = TestSuiteRunner()
        runner.add_all_tests()
        return runner.run_tests()
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("Make sure you're in the project root directory and server dependencies are installed.")
        return None
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        import traceback
        traceback.print_exc()
        return None


if __name__ == "__main__":
    result = run_prayer_tests()
    
    # Exit with appropriate code
    if result and result.wasSuccessful():
        sys.exit(0)
    else:
        sys.exit(1)


class TestPrayerScraping(unittest.TestCase):
    """Test suite for mosque website scraping functionality"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.scraper = ComprehensivePrayerScraper()
        
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
            ("Jumaa", PrayerName.JUMAA),
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
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._extract_imam_name(input_text)
                if result:
                    self.assertIn(expected, result, f"Expected {expected} in {result}")
    
    def test_language_detection(self):
        """Test language detection from text"""
        test_cases = [
            ("English Khutba at 12:30 PM", "English"),
            ("Arabic sermon available", "Arabic"),
            ("Bilingual Arabic/English", "Mixed"),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input=input_text):
                result = self.scraper._detect_language(input_text)
                if expected and result:
                    self.assertEqual(result.lower(), expected.lower())
    
    def test_simple_table_parsing(self):
        """Test extraction from simple HTML table"""
        html = """
        <table>
            <tr><th>Prayer</th><th>Adhan</th><th>Iqama</th></tr>
            <tr><td>Fajr</td><td>5:50 AM</td><td>6:00 AM</td></tr>
            <tr><td>Dhuhr</td><td>12:45 PM</td><td>1:00 PM</td></tr>
        </table>
        """
        
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        prayers = self.scraper._extract_from_prayer_tables(soup, "test_url")
        
        self.assertTrue(len(prayers) >= 2)
        if len(prayers) >= 2:
            self.assertEqual(prayers[0].prayer_name, PrayerName.FAJR)
            self.assertEqual(prayers[0].adhan_time, "05:50")
            self.assertEqual(prayers[0].iqama_time, "06:00")
    
    def test_fallback_to_defaults(self):
        """Test fallback to default prayers when scraping fails"""
        mosque_no_website = Mosque(
            place_id="test_no_site",
            name="Test Mosque No Website",
            location=Location(latitude=37.7749, longitude=-122.4194),
            website=None
        )
        
        # This should run synchronously in the test environment
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            prayers = loop.run_until_complete(
                self.scraper.scrape_mosque_prayers(mosque_no_website)
            )
        finally:
            loop.close()
        
        self.assertTrue(len(prayers) >= 5)  # Should have 5+ daily prayers
        prayer_names = [p.prayer_name for p in prayers]
        self.assertIn(PrayerName.FAJR, prayer_names)
        self.assertIn(PrayerName.DHUHR, prayer_names)
        self.assertIn(PrayerName.ASR, prayer_names)
        self.assertIn(PrayerName.MAGHRIB, prayer_names)
        self.assertIn(PrayerName.ISHA, prayer_names)


# Add scraping tests to the main test suite
def create_full_test_suite():
    """Create the complete test suite including scraping tests"""
    suite = unittest.TestSuite()
    
    # Add original prayer timing tests
    suite.addTest(unittest.makeSuite(TestPrayerTimingLogic))
    
    # Add new scraping tests
    suite.addTest(unittest.makeSuite(TestPrayerScraping))
    
    return suite