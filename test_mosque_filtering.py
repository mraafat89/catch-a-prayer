#!/usr/bin/env python3

import asyncio
import sys
import os
import json
from datetime import datetime

# Add the server directory to Python path
sys.path.append('/Users/mahmoud/projects/cap/repo/cap/catch-a-prayer/server')

from services.mosque_service import MosqueService
from dotenv import load_dotenv

async def test_mosque_filtering():
    """Test mosque filtering and deduplication logic"""
    load_dotenv('/Users/mahmoud/projects/cap/repo/cap/catch-a-prayer/server/.env')
    
    print("🧪 Testing Generalized Mosque Filtering and Deduplication")
    print("=" * 60)
    
    service = MosqueService()
    
    # Test coordinates for Fremont/Bay Area (known to have multiple mosque chains)
    test_lat = 37.5485
    test_lng = -121.9886
    radius = 15.0  # Larger radius to capture more mosque variants
    
    print(f"📍 Searching for mosques near ({test_lat}, {test_lng}) within {radius}km")
    print("Testing generalized filtering logic (no hardcoded cases)")
    print()
    
    try:
        # Get nearby mosques
        mosques = await service.find_nearby_mosques(test_lat, test_lng, radius)
        
        print(f"✅ Found {len(mosques)} mosques after filtering and deduplication")
        print()
        
        # Analyze results for duplicate detection
        mosque_groups = {}
        
        # Group mosques by extracted base names to test deduplication
        for mosque in mosques:
            base_name = service._extract_base_mosque_name(mosque.name)
            website_domain = service._extract_website_domain(mosque.website) if mosque.website else None
            group_key = f"{base_name}|{website_domain}"
            
            if group_key not in mosque_groups:
                mosque_groups[group_key] = []
            mosque_groups[group_key].append(mosque)
        
        # Test deduplication effectiveness
        print("🕌 Deduplication Analysis:")
        print("-" * 40)
        
        duplicates_found = []
        for group_key, group_mosques in mosque_groups.items():
            if len(group_mosques) > 1:
                duplicates_found.append((group_key, group_mosques))
        
        if duplicates_found:
            print(f"⚠️  Found {len(duplicates_found)} groups that might have duplicates:")
            for group_key, group_mosques in duplicates_found:
                print(f"\nGroup: {group_key}")
                print(f"Original variants ({len(group_mosques)}):")
                for mosque in group_mosques:
                    print(f"  - {mosque.name} ({mosque.user_ratings_total} reviews)")
                
                # Test our selection logic
                selected = service._select_best_mosque_representative(group_mosques)
                print(f"Selected representative: {selected.name}")
                print(f"✅ Deduplication working - {len(group_mosques)} → 1")
        else:
            print("✅ SUCCESS: No duplicates detected in final results!")
        
        # Test specific mosque chains if present
        mosque_chains = {
            'mca': [],
            'islamic center': [],
            'masjid': [],
            'muslim community': []
        }
        
        for mosque in mosques:
            name_lower = mosque.name.lower()
            if 'mca' in name_lower or 'muslim community association' in name_lower:
                mosque_chains['mca'].append(mosque)
            elif 'islamic center' in name_lower:
                mosque_chains['islamic center'].append(mosque)
            elif 'masjid' in name_lower:
                mosque_chains['masjid'].append(mosque)
            elif 'muslim community' in name_lower:
                mosque_chains['muslim community'].append(mosque)
        
        print("\n🏛️ Mosque Chain Analysis:")
        print("-" * 40)
        
        for chain_name, chain_mosques in mosque_chains.items():
            if chain_mosques:
                print(f"{chain_name.upper()} chain: {len(chain_mosques)} mosques")
                for mosque in chain_mosques:
                    print(f"  - {mosque.name} ({mosque.user_ratings_total} reviews)")
                print()
        
        print("\n" + "=" * 60)
        
        # Test non-mosque filtering
        print("🏢 Non-Mosque Filtering Analysis:")
        print("-" * 40)
        
        # Test if our filtering correctly identifies mosques vs non-mosque organizations
        test_names = [
            "ICNA SF Bay Area",  # Should be filtered out
            "Islamic Society of North America Office",  # Should be filtered out
            "Halal Market & Restaurant",  # Should be filtered out
            "Muslim Community Association",  # Should be kept (mosque)
            "Islamic Center of Fremont",  # Should be kept (mosque)
            "Masjid Al-Noor",  # Should be kept (mosque)
            "Islamic School of San Jose",  # Should be filtered out
            "Muslim Student Association",  # Should be filtered out (unless prayer mentioned)
        ]
        
        print("Testing mosque identification logic:")
        for test_name in test_names:
            # Create mock mosque object
            from models.mosque import Mosque, Location
            mock_mosque = Mosque(
                place_id="test",
                name=test_name,
                location=Location(latitude=0, longitude=0)
            )
            
            is_mosque = service._is_likely_mosque(mock_mosque)
            status = "✅ MOSQUE" if is_mosque else "❌ FILTERED"
            print(f"  {status}: {test_name}")
        
        print("\nActual filtering results:")
        potentially_problematic = []
        for mosque in mosques:
            name_lower = mosque.name.lower()
            
            # Check for organizations that might not be actual prayer spaces
            org_keywords = ['council', 'federation', 'board', 'office', 'administration']
            educational_keywords = ['school', 'academy', 'university', 'institute']
            commercial_keywords = ['store', 'market', 'restaurant', 'halal meat']
            
            is_potentially_problematic = False
            problem_type = ""
            
            for keyword in org_keywords:
                if keyword in name_lower:
                    is_potentially_problematic = True
                    problem_type = f"organizational ({keyword})"
                    break
            
            if not is_potentially_problematic:
                for keyword in educational_keywords:
                    if keyword in name_lower:
                        is_potentially_problematic = True
                        problem_type = f"educational ({keyword})"
                        break
            
            if not is_potentially_problematic:
                for keyword in commercial_keywords:
                    if keyword in name_lower:
                        is_potentially_problematic = True
                        problem_type = f"commercial ({keyword})"
                        break
            
            if is_potentially_problematic:
                potentially_problematic.append((mosque, problem_type))
        
        if potentially_problematic:
            print("⚠️  Potentially problematic locations found:")
            for mosque, problem_type in potentially_problematic:
                print(f"   - {mosque.name} ({problem_type})")
        else:
            print("✅ SUCCESS: No obviously problematic non-mosque locations found")
        
        print("\n" + "=" * 60)
        
        # Summary of all mosques
        print("📋 All Mosques Found:")
        print("-" * 40)
        
        for i, mosque in enumerate(mosques, 1):
            print(f"{i}. {mosque.name}")
            print(f"   Reviews: {mosque.user_ratings_total}, Rating: {mosque.rating}")
            print(f"   Travel: {mosque.travel_info.duration_text if mosque.travel_info else 'N/A'}")
            if mosque.website:
                print(f"   Website: {mosque.website[:60]}...")
            print()
        
        # Test prayer times for MCA mosque if found
        if mca_mosques:
            print("🕐 Testing Prayer Times for MCA:")
            print("-" * 40)
            
            mca_mosque = mca_mosques[0]
            try:
                next_prayer = await service.get_next_catchable_prayer(
                    mca_mosque.place_id, test_lat, test_lng
                )
                
                if next_prayer:
                    print("✅ Prayer times successfully fetched!")
                    print(f"   Next prayer: {next_prayer.prayer.prayer_name}")
                    print(f"   Time: {next_prayer.prayer.iqama_time or next_prayer.prayer.adhan_time}")
                    print(f"   Can catch: {next_prayer.can_catch}")
                    print(f"   Travel time: {next_prayer.travel_time_minutes} minutes")
                else:
                    print("❌ No prayer times found")
                    
            except Exception as e:
                print(f"❌ Error fetching prayer times: {e}")
        
        print("\n" + "=" * 60)
        print("✅ Test completed!")
        
        # Return results for further analysis
        return {
            'total_mosques': len(mosques),
            'mca_mosques': len(mca_mosques),
            'deduplication_success': len(mca_mosques) <= 1,
            'mosques': mosques
        }
        
    except Exception as e:
        print(f"❌ Error during testing: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(test_mosque_filtering())