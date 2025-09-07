#!/usr/bin/env python3
"""
Browser Simulation Test - Tests exactly what browser would do
============================================================

This test simulates the exact HTTP requests a browser would make,
including CORS preflight requests and proper headers.
"""

import asyncio
import json
import httpx
from datetime import datetime

async def simulate_browser_requests():
    """Simulate exact browser behavior"""
    print("🌐 Simulating Browser Requests")
    print("=" * 50)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        
        # Test 1: CORS Preflight Request (what browser does first)
        print("🔍 Test 1: CORS Preflight Request")
        try:
            response = await client.options(
                "http://localhost:8000/api/mosques/nearby",
                headers={
                    "Origin": "http://localhost:3000",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "Content-Type"
                }
            )
            print(f"✅ Preflight: {response.status_code}")
            print(f"CORS Headers: {response.headers.get('access-control-allow-origin')}")
        except Exception as e:
            print(f"❌ Preflight failed: {e}")
        
        print()
        
        # Test 2: Browser location request simulation
        print("🔍 Test 2: Frontend to Backend Request")
        
        # Simulate browser geolocation API providing these coordinates  
        request_data = {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "radius_km": 5,
            "client_current_time": datetime.now().isoformat() + "-08:00",
            "client_timezone": "America/Los_Angeles"
        }
        
        try:
            response = await client.post(
                "http://localhost:8000/api/mosques/nearby",
                json=request_data,
                headers={
                    "Content-Type": "application/json",
                    "Origin": "http://localhost:3000",  # Browser always sends this
                    "Referer": "http://localhost:3000/", # Browser always sends this
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
                }
            )
            
            print(f"📥 Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                mosques = data.get("mosques", [])
                print(f"✅ Browser would receive {len(mosques)} mosques")
                
                if len(mosques) > 0:
                    print("✅ SUCCESS: Browser would show mosques to user")
                    return True
                else:
                    print("❌ ISSUE: Browser would show 'no mosques found'")
                    return False
            else:
                print(f"❌ Browser would get HTTP error: {response.status_code}")
                print(f"Error response: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Browser request failed: {e}")
            return False

async def test_direct_frontend_backend():
    """Test if frontend can reach backend"""
    print("🔍 Test 3: Frontend Container to Backend Container")
    
    async with httpx.AsyncClient() as client:
        try:
            # Test from frontend container's perspective
            response = await client.get("http://catch-a-prayer-api-1:8000/health")
            print(f"✅ Frontend can reach backend: {response.status_code}")
            return response.status_code == 200
        except Exception as e:
            print(f"❌ Frontend cannot reach backend: {e}")
            
            # Try with localhost
            try:
                response = await client.get("http://localhost:8000/health")  
                print(f"✅ Localhost works: {response.status_code}")
                return response.status_code == 200
            except Exception as e2:
                print(f"❌ Even localhost fails: {e2}")
                return False

async def main():
    print("🚀 Browser Simulation Test Suite")
    print("This tests exactly what a real browser would do")
    print("=" * 60)
    
    # Test browser simulation
    browser_works = await simulate_browser_requests()
    print()
    
    # Test container communication  
    container_works = await test_direct_frontend_backend()
    
    print("\n" + "=" * 60)
    print("📊 BROWSER SIMULATION RESULTS")
    print("=" * 60)
    
    print(f"Browser Requests: {'✅ PASS' if browser_works else '❌ FAIL'}")
    print(f"Container Network: {'✅ PASS' if container_works else '❌ FAIL'}")
    
    if browser_works:
        print("\n✅ The app SHOULD work in the browser")
        print("If it doesn't, the issue is in the frontend JavaScript code")
    else:
        print("\n❌ The app will NOT work in the browser")
        print("Backend API issues need to be resolved")

if __name__ == "__main__":
    asyncio.run(main())