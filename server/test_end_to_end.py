#!/usr/bin/env python3
"""
End-to-End Test Suite - Simulates Real Browser User Experience
==============================================================

This test suite simulates exactly what a real user would experience 
when using the Catch a Prayer app in a browser.
"""

import asyncio
import json
import sys
import time
from datetime import datetime
import httpx
from typing import Dict, List, Any

class EndToEndTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.client = None
        
    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()
    
    async def test_health_check(self):
        """Test 1: Basic health check - what browser does first"""
        print("🔍 Test 1: Health Check")
        try:
            response = await self.client.get(f"{self.base_url}/health")
            if response.status_code != 200:
                print(f"❌ Health check failed: HTTP {response.status_code}")
                return False
                
            data = response.json()
            print(f"✅ Health: {data}")
            
            if not data.get("services", {}).get("maps"):
                print("❌ Google Maps service not available")
                return False
            if not data.get("services", {}).get("prayers"):
                print("❌ Prayer service not available")
                return False
                
            print("✅ All services healthy")
            return True
        except Exception as e:
            print(f"❌ Health check exception: {e}")
            return False
    
    async def test_find_nearby_mosques(self, lat: float = 37.7749, lng: float = -122.4194, radius: int = 5):
        """Test 2: Find nearby mosques - core functionality"""
        print(f"🔍 Test 2: Find Nearby Mosques (lat={lat}, lng={lng}, radius={radius}km)")
        
        # Simulate what the frontend sends
        request_data = {
            "latitude": lat,
            "longitude": lng,
            "radius_km": radius,
            "client_current_time": datetime.now().isoformat() + "-08:00",
            "client_timezone": "America/Los_Angeles"
        }
        
        print(f"📤 Sending request: {json.dumps(request_data, indent=2)}")
        
        try:
            start_time = time.time()
            response = await self.client.post(
                f"{self.base_url}/api/mosques/nearby",
                json=request_data,
                headers={"Content-Type": "application/json"}
            )
            end_time = time.time()
            
            print(f"⏱️ Response time: {end_time - start_time:.2f}s")
            print(f"📥 Status: {response.status_code}")
            
            if response.status_code != 200:
                print(f"❌ HTTP Error: {response.status_code}")
                print(f"Response: {response.text}")
                return False, None
            
            data = response.json()
            mosques = data.get("mosques", [])
            user_location = data.get("user_location", {})
            
            print(f"✅ Found {len(mosques)} mosques")
            print(f"📍 User location confirmed: {user_location}")
            
            if len(mosques) == 0:
                print("❌ CRITICAL: No mosques found - this is the main issue!")
                return False, data
            
            # Analyze each mosque
            for i, mosque in enumerate(mosques[:3]):  # Check first 3
                print(f"\n🕌 Mosque {i+1}: {mosque.get('name', 'Unknown')}")
                print(f"  📍 Location: {mosque.get('location', {})}")
                print(f"  🌐 Website: {mosque.get('website', 'None')}")
                print(f"  🚗 Travel: {mosque.get('travel_info', {})}")
                
                prayers = mosque.get('prayers', [])
                print(f"  🕐 Prayers: {len(prayers)} found")
                
                if prayers:
                    for prayer in prayers:
                        prayer_name = prayer.get('prayer_name', 'unknown')
                        adhan = prayer.get('adhan_time', 'N/A')
                        iqama = prayer.get('iqama_time', 'N/A')
                        print(f"    • {prayer_name}: Adhan {adhan}, Iqama {iqama}")
                
                next_prayer = mosque.get('next_prayer')
                if next_prayer:
                    print(f"  ⏰ Next prayer: {next_prayer.get('prayer')} - {next_prayer.get('message')}")
            
            return True, data
            
        except Exception as e:
            print(f"❌ Find mosques exception: {e}")
            import traceback
            traceback.print_exc()
            return False, None
    
    async def test_google_maps_integration(self):
        """Test 3: Verify Google Maps API is working"""
        print("🔍 Test 3: Google Maps Integration")
        
        # Check if API key is configured
        import os
        api_key = os.getenv("GOOGLE_MAPS_API_KEY")
        if not api_key:
            print("❌ GOOGLE_MAPS_API_KEY not set in environment")
            return False
        
        print(f"✅ API key configured: {api_key[:10]}...{api_key[-5:]}")
        
        # Test if we can make a simple request to Google Maps
        try:
            import googlemaps
            gmaps = googlemaps.Client(key=api_key)
            
            # Test geocoding (what the app uses)
            result = gmaps.places_nearby(
                location=(37.7749, -122.4194),
                radius=1000,
                keyword="mosque"
            )
            
            places = result.get('results', [])
            print(f"✅ Google Maps returned {len(places)} places")
            
            if len(places) == 0:
                print("❌ No places found in Google Maps - API quota or location issue?")
                return False
            
            # Show first result
            if places:
                place = places[0]
                print(f"📍 First result: {place.get('name')} at {place.get('geometry', {}).get('location')}")
            
            return True
            
        except Exception as e:
            print(f"❌ Google Maps test failed: {e}")
            return False
    
    async def test_prayer_times_fallback(self):
        """Test 4: Prayer times API fallback"""
        print("🔍 Test 4: Prayer Times API Fallback")
        
        try:
            # Test prayer times API directly
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.aladhan.com/v1/timings/05-01-2025",
                    params={"latitude": 37.7749, "longitude": -122.4194, "method": 2}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get("code") == 200:
                        timings = data["data"]["timings"]
                        print(f"✅ Prayer API working: Fajr={timings.get('Fajr')}, Dhuhr={timings.get('Dhuhr')}")
                        return True
                    else:
                        print(f"❌ Prayer API error: {data.get('status')}")
                        return False
                else:
                    print(f"❌ Prayer API HTTP error: {response.status_code}")
                    return False
                    
        except Exception as e:
            print(f"❌ Prayer API test failed: {e}")
            return False
    
    async def run_full_test_suite(self):
        """Run complete end-to-end test suite"""
        print("🚀 Starting End-to-End Test Suite")
        print("=" * 60)
        
        results = {}
        
        # Test 1: Health Check
        results["health"] = await self.test_health_check()
        print()
        
        # Test 2: Google Maps Integration  
        results["maps"] = await self.test_google_maps_integration()
        print()
        
        # Test 3: Prayer Times Fallback
        results["prayer_api"] = await self.test_prayer_times_fallback()
        print()
        
        # Test 4: Find Nearby Mosques (THE CRITICAL TEST)
        results["mosques"], mosque_data = await self.test_find_nearby_mosques()
        
        print("\n" + "=" * 60)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 60)
        
        all_passed = True
        for test_name, passed in results.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{test_name.upper()}: {status}")
            if not passed:
                all_passed = False
        
        print(f"\n🎯 OVERALL RESULT: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
        
        if not results.get("mosques"):
            print("\n🚨 CRITICAL ISSUE IDENTIFIED:")
            print("The app cannot find nearby mosques - this is the root cause of the user's issue.")
            print("Investigation needed in:")
            print("- Google Maps API configuration")
            print("- Mosque search queries and filters")
            print("- Network connectivity from container")
        
        return all_passed, results

async def main():
    """Main test runner"""
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    else:
        base_url = "http://localhost:8000"
    
    print(f"🎯 Testing against: {base_url}")
    
    async with EndToEndTester(base_url) as tester:
        success, results = await tester.run_full_test_suite()
        
        if not success:
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())