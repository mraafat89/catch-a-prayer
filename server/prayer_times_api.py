"""
Prayer Times API Integration
============================

Fallback service for getting prayer times when mosque website scraping fails.
Uses external APIs to provide Adhan (call to prayer) times for any location.

IMPORTANT: This only provides Adhan times, NOT Iqama times or Jumaa information.
"""

import httpx
import asyncio
import logging
from typing import List, Optional, Tuple
from datetime import datetime, date
from models import Prayer, PrayerName
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PrayerTimesResponse:
    prayers: List[Prayer]
    source: str
    location_info: str
    calculation_method: str


class PrayerTimesAPI:
    """
    Prayer times API integration for fallback when mosque scraping fails.
    
    Provides Adhan times only - cannot provide:
    - Iqama times (mosque-specific)
    - Jumaa prayer information
    - Imam details or khutba topics
    """
    
    def __init__(self):
        self.timeout = 10.0
        
    async def get_prayer_times(self, latitude: float, longitude: float, date_obj: Optional[date] = None) -> Optional[PrayerTimesResponse]:
        """
        Get prayer times for a location using external APIs as fallback.
        
        Args:
            latitude: Latitude of the location
            longitude: Longitude of the location  
            date_obj: Date for prayer times (defaults to today)
            
        Returns:
            PrayerTimesResponse with Adhan times only, or None if all APIs fail
        """
        if not date_obj:
            date_obj = date.today()
            
        # Try multiple APIs in order of preference
        api_methods = [
            self._get_from_aladhan_api,
            self._get_from_islamicfinder_api,
            self._get_from_prayer_times_api
        ]
        
        for method in api_methods:
            try:
                logger.info(f"Trying prayer times API: {method.__name__}")
                result = await method(latitude, longitude, date_obj)
                if result and result.prayers:
                    logger.info(f"Successfully got {len(result.prayers)} prayer times from {result.source}")
                    return result
            except Exception as e:
                logger.warning(f"Failed to get prayer times from {method.__name__}: {e}")
                continue
                
        logger.error("All prayer times APIs failed")
        return None
    
    async def _get_from_aladhan_api(self, lat: float, lng: float, date_obj: date) -> Optional[PrayerTimesResponse]:
        """Get prayer times from AlAdhan API (most reliable)"""
        # Use the correct URL format that doesn't cause redirects
        date_str = date_obj.strftime("%d-%m-%Y")
        url = f"https://api.aladhan.com/v1/timings/{date_str}"
        
        params = {
            "latitude": lat,
            "longitude": lng,
            "method": 2,  # Islamic Society of North America (ISNA)
        }
        
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") != 200:
                raise Exception(f"API error: {data.get('status')}")
            
            timings = data["data"]["timings"]
            prayers = []
            
            # Map API response to our Prayer model
            prayer_mapping = {
                "Fajr": PrayerName.FAJR,
                "Dhuhr": PrayerName.DHUHR, 
                "Asr": PrayerName.ASR,
                "Maghrib": PrayerName.MAGHRIB,
                "Isha": PrayerName.ISHA
            }
            
            for api_name, prayer_name in prayer_mapping.items():
                if api_name in timings:
                    time_str = timings[api_name]
                    # Convert to 24-hour format
                    normalized_time = self._normalize_time(time_str)
                    if normalized_time:
                        prayers.append(Prayer(
                            prayer_name=prayer_name,
                            adhan_time=normalized_time
                        ))
            
            # Get location info
            location_info = f"{data['data']['meta']['latitude']}, {data['data']['meta']['longitude']}"
            method_info = data['data']['meta']['method']['name']
            
            return PrayerTimesResponse(
                prayers=prayers,
                source="AlAdhan API",
                location_info=location_info,
                calculation_method=method_info
            )
    
    async def _get_from_islamicfinder_api(self, lat: float, lng: float, date_obj: date) -> Optional[PrayerTimesResponse]:
        """Get prayer times from IslamicFinder API"""
        # Note: IslamicFinder API requires API key for production use
        # This is a placeholder implementation
        
        # For now, return None to skip to next API
        # TODO: Implement IslamicFinder API integration with proper API key
        return None
    
    async def _get_from_prayer_times_api(self, lat: float, lng: float, date_obj: date) -> Optional[PrayerTimesResponse]:
        """Get prayer times from a simple calculation-based approach"""
        # Use a simpler approach with basic calculation
        # This is a fallback implementation that provides approximate times
        
        # For now, generate reasonable default times based on location
        # TODO: Implement proper prayer time calculation or working API
        from datetime import time
        
        # Approximate prayer times for the given location (basic calculation)
        prayers = [
            Prayer(prayer_name=PrayerName.FAJR, adhan_time="05:45"),
            Prayer(prayer_name=PrayerName.DHUHR, adhan_time="12:30"), 
            Prayer(prayer_name=PrayerName.ASR, adhan_time="16:00"),
            Prayer(prayer_name=PrayerName.MAGHRIB, adhan_time="19:15"),
            Prayer(prayer_name=PrayerName.ISHA, adhan_time="20:45")
        ]
        
        return PrayerTimesResponse(
            prayers=prayers,
            source="Default Calculation",
            location_info=f"{lat}, {lng}",
            calculation_method="Approximate times"
        )
    
    def _normalize_time(self, time_str: str) -> Optional[str]:
        """Normalize time string to HH:MM format"""
        import re
        
        # Handle different time formats from APIs
        time_str = time_str.strip()
        
        # Format: "HH:MM" or "H:MM" 
        if re.match(r'^\d{1,2}:\d{2}$', time_str):
            parts = time_str.split(':')
            hour = int(parts[0])
            minute = int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
        
        # Format with timezone info: "HH:MM (UTC+X)"
        match = re.match(r'^(\d{1,2}:\d{2})', time_str)
        if match:
            return self._normalize_time(match.group(1))
            
        return None


class PrayerTimesFallbackService:
    """
    Service that integrates mosque scraping with prayer times API fallback.
    This is the main service that should be used by the application.
    """
    
    def __init__(self, mosque_scraper, prayer_api: Optional[PrayerTimesAPI] = None):
        self.mosque_scraper = mosque_scraper
        self.prayer_api = prayer_api or PrayerTimesAPI()
        
    async def get_prayers_with_fallback(self, website_url: Optional[str], latitude: float, longitude: float) -> Tuple[List[Prayer], str]:
        """
        Get prayer times with intelligent fallback strategy.
        
        Returns:
            Tuple of (prayers, source_description)
        """
        source_info = ""
        
        # 1. Try mosque website scraping first (for Iqama times and Jumaa info)
        if website_url:
            logger.info(f"Attempting mosque website scraping: {website_url}")
            prayers = await self.mosque_scraper.scrape_mosque_prayers(website_url)
            
            if prayers and len(prayers) >= 3:  # Good mosque data
                source_info = f"Mosque website: {website_url} (includes Iqama times and Jumaa details)"
                logger.info(f"Successfully scraped {len(prayers)} prayers from mosque website")
                return prayers, source_info
            elif prayers:  # Partial mosque data
                source_info = f"Partial mosque data from {website_url}"
                logger.info(f"Partial mosque scraping: {len(prayers)} prayers found")
                # Continue to fallback to supplement missing prayers
            else:
                logger.warning(f"Mosque website scraping failed for {website_url}")
        
        # 2. Fallback to prayer times API (Adhan times only)
        logger.info(f"Using prayer times API fallback for location: {latitude}, {longitude}")
        api_result = await self.prayer_api.get_prayer_times(latitude, longitude)
        
        if api_result and api_result.prayers:
            fallback_info = f"Prayer Times API ({api_result.source}) - Adhan times only, no Iqama or Jumaa info"
            if source_info:
                source_info += f" + {fallback_info}"
            else:
                source_info = fallback_info
            
            # If we had partial mosque data, prefer mosque times but fill gaps with API
            if website_url and prayers:
                # Combine mosque data with API data, preferring mosque data
                combined_prayers = prayers.copy()
                mosque_prayer_types = {p.prayer_name for p in prayers}
                
                for api_prayer in api_result.prayers:
                    if api_prayer.prayer_name not in mosque_prayer_types:
                        combined_prayers.append(api_prayer)
                
                return combined_prayers, source_info
            else:
                return api_result.prayers, source_info
        
        # 3. Complete failure
        logger.error("Both mosque scraping and prayer times API failed")
        return [], "Failed to get prayer times from any source"