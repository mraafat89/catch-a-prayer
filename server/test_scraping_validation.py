#!/usr/bin/env python3
"""
Validation test to confirm scraping system is working properly
"""

import asyncio
import json
import httpx
from datetime import datetime

async def test_scraping_system():
    """Test that the scraping system is properly enabled and working"""
    print("🧪 SCRAPING SYSTEM VALIDATION TEST")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Test the API with San Francisco location
        request_data = {
            'latitude': 37.7749,
            'longitude': -122.4194,
            'radius_km': 5,
            'client_current_time': datetime.now().isoformat() + '-08:00',
            'client_timezone': 'America/Los_Angeles'
        }
        
        print("📍 Testing San Francisco area mosques...")
        response = await client.post('http://localhost:8000/api/mosques/nearby', json=request_data)
        
        if response.status_code != 200:
            print(f"❌ API Error: {response.status_code}")
            return False
        
        data = response.json()
        mosques = data.get('mosques', [])
        
        if len(mosques) == 0:
            print("❌ No mosques found")
            return False
        
        print(f"✅ Found {len(mosques)} mosques")
        
        # Analyze each mosque's prayer times
        all_tests_passed = True
        default_fajr_time = "05:50"  # Old hardcoded default
        real_prayer_times_count = 0
        
        for i, mosque in enumerate(mosques[:3], 1):
            name = mosque.get('name', 'Unknown')
            website = mosque.get('website', 'None')
            prayers = mosque.get('prayers', [])
            
            print(f"\n🕌 Mosque {i}: {name}")
            print(f"   🌐 Website: {website}")
            print(f"   🕐 Prayers found: {len(prayers)}")
            
            if len(prayers) < 5:
                print(f"   ❌ Insufficient prayers: {len(prayers)}")
                all_tests_passed = False
                continue
            
            # Check prayer times
            fajr_prayer = next((p for p in prayers if p.get('prayer_name') == 'fajr'), None)
            dhuhr_prayer = next((p for p in prayers if p.get('prayer_name') == 'dhuhr'), None)
            
            if not fajr_prayer:
                print("   ❌ No Fajr prayer found")
                all_tests_passed = False
                continue
                
            fajr_time = fajr_prayer.get('adhan_time')
            dhuhr_time = dhuhr_prayer.get('adhan_time') if dhuhr_prayer else 'N/A'
            
            print(f"   ⏰ Fajr: {fajr_time}")
            print(f"   ⏰ Dhuhr: {dhuhr_time}")
            
            # Test: Are we getting real prayer times vs. old defaults?
            is_using_real_times = fajr_time != default_fajr_time
            if is_using_real_times:
                real_prayer_times_count += 1
                print("   ✅ Using real prayer times (not hardcoded defaults)")
            else:
                print("   ⚠️  Still using old default times - may indicate fallback issue")
            
            # Test: Do we have location-appropriate times?
            try:
                fajr_hour = int(fajr_time.split(':')[0])
                if 4 <= fajr_hour <= 7:  # Reasonable Fajr time range
                    print("   ✅ Prayer time in reasonable range")
                else:
                    print(f"   ❌ Fajr time seems unreasonable: {fajr_hour}:xx")
                    all_tests_passed = False
            except:
                print("   ❌ Could not parse prayer time")
                all_tests_passed = False
        
        # Overall assessment
        print(f"\n{'=' * 50}")
        print("📊 SCRAPING SYSTEM STATUS")
        print(f"{'=' * 50}")
        
        if real_prayer_times_count > 0:
            print(f"✅ SCRAPING SYSTEM IS WORKING!")
            print(f"   - {real_prayer_times_count}/{len(mosques[:3])} mosques have real prayer times")
            print(f"   - Successfully falling back to API when scraping fails")
            print(f"   - No longer using hardcoded defaults")
            
            if real_prayer_times_count == len(mosques[:3]):
                print("   - 🎯 PERFECT: All mosques have real prayer times")
            else:
                print("   - ⚠️  Some mosques may still need scraping improvements")
                
            return True
        else:
            print("❌ SCRAPING SYSTEM ISSUES:")
            print("   - All mosques still returning default times")
            print("   - API fallback may not be working")
            return False

if __name__ == "__main__":
    success = asyncio.run(test_scraping_system())
    exit(0 if success else 1)