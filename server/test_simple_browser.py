#!/usr/bin/env python3
"""
Simple Browser Test - Uses curl to test what browser sees
"""

import asyncio
import httpx
import json
from datetime import datetime

async def test_browser_perspective():
    print("🌐 Testing from Browser Perspective")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30) as client:
        
        # Test 1: Can browser reach frontend?
        print("🔍 Test 1: Frontend Accessibility")
        try:
            response = await client.get("http://localhost:3000")
            if response.status_code == 200:
                print("✅ Frontend accessible at http://localhost:3000")
            else:
                print(f"❌ Frontend error: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Frontend not accessible: {e}")
            return False
        
        # Test 2: Can browser reach backend directly?
        print("\n🔍 Test 2: Backend Direct Access")
        try:
            response = await client.get("http://localhost:8000/health")
            if response.status_code == 200:
                print("✅ Backend accessible at http://localhost:8000")
                print(f"Health: {response.json()}")
            else:
                print(f"❌ Backend error: {response.status_code}")
                return False
        except Exception as e:
            print(f"❌ Backend not accessible: {e}")
            return False
            
        # Test 3: Full API call from browser perspective
        print("\n🔍 Test 3: Frontend API Call Simulation")
        request_data = {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "radius_km": 5,
            "client_timezone": "America/Los_Angeles",
            "client_current_time": datetime.now().isoformat() + "-08:00"
        }
        
        try:
            # This is exactly what the browser's JavaScript would do
            response = await client.post(
                "http://localhost:8000/api/mosques/nearby",
                json=request_data,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "http://localhost:3000",
                    "Referer": "http://localhost:3000/"
                }
            )
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                mosques = data.get("mosques", [])
                print(f"✅ Browser would see {len(mosques)} mosques")
                
                if len(mosques) == 0:
                    print("❌ PROBLEM: No mosques returned to browser!")
                    print("Response:", json.dumps(data, indent=2)[:500])
                    return False
                else:
                    first_mosque = mosques[0]
                    print(f"First mosque: {first_mosque.get('name')}")
                    print(f"Prayers: {len(first_mosque.get('prayers', []))}")
                    return True
            else:
                print(f"❌ API call failed: {response.status_code}")
                print(f"Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ API call exception: {e}")
            import traceback
            traceback.print_exc()
            return False

async def main():
    print("🚀 Simple Browser Test")
    print("Testing what the browser actually sees")
    print("=" * 60)
    
    success = await test_browser_perspective()
    
    print("\n" + "=" * 60)
    print("📊 RESULT")
    print("=" * 60)
    
    if success:
        print("✅ Browser should work perfectly!")
        print("If user still sees issues, the problem is in frontend JavaScript")
    else:
        print("❌ Browser will fail - backend/network issue identified")

if __name__ == "__main__":
    asyncio.run(main())