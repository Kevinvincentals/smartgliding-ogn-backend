#!/usr/bin/env python3
"""
Test script for ADSB.lol API integration
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from services.adsb_client import AdsbClient
from services.config import DENMARK_CENTER_LAT, DENMARK_CENTER_LON, DENMARK_RADIUS_KM

def test_adsb_api():
    """Test the ADSB API integration"""
    print("Testing ADSB.lol API integration...")
    
    client = AdsbClient()
    
    # Test fetching aircraft data
    print(f"Fetching aircraft data for Denmark area:")
    print(f"  Center: {DENMARK_CENTER_LAT}, {DENMARK_CENTER_LON}")
    print(f"  Radius: {DENMARK_RADIUS_KM} km")
    
    aircraft_list = client.fetch_aircraft_in_area(
        DENMARK_CENTER_LAT, 
        DENMARK_CENTER_LON, 
        DENMARK_RADIUS_KM
    )
    
    if aircraft_list is not None:
        print(f"✅ Successfully fetched {len(aircraft_list)} aircraft")
        
        if aircraft_list:
            # Test normalization with first aircraft
            first_aircraft = aircraft_list[0]
            print(f"\nFirst aircraft raw data: {first_aircraft}")
            
            normalized = client.normalize_aircraft_data(first_aircraft)
            print(f"\nNormalized data: {normalized}")
        else:
            print("No aircraft found in the area")
    else:
        print("❌ Failed to fetch aircraft data")

if __name__ == "__main__":
    test_adsb_api() 