#!/usr/bin/env python3
"""
Utility functions for the FLARM WebSocket Server
"""

import logging
import math
import re
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("plane-tracker")

# APRS symbols to aircraft type mapping
APRS_AIRCRAFT_TYPES = {
    "/z": "Unknown",
    "/'": "Glider",  # Also used for tow plane
    "/X": "Helicopter",
    "/g": "Parachute/Hang-glider/Para-glider",
    "\\^": "Drop plane/Powered aircraft",
    "/^": "Jet aircraft",
    "/O": "Balloon/Airship",
    "/D": "UAV",
    "\\n": "Static object"
}


def get_aircraft_type_from_symbol(raw_message):
    """Extract the aircraft type from APRS symbols in the raw message."""
    # Examples of APRS messages with symbols:
    # FLRDDE626>APRS,qAS,EGHL:/074548h5111.32N/00102.04W'086/007/A=000607 id0ADDE626 -019fpm +0.0rot 5.5dB 3e -4.3kHz
    # The symbols are the / after the coordinates and the ' before the course/speed
    
    try:
        # If we can find a pattern like "4254.53N/00203.90E&" or "5111.32N/00102.04W'"
        # the symbol is the character after the longitude
        parts = raw_message.split('>')
        if len(parts) > 1:
            # Look for coordinates pattern followed by a symbol
            coord_pattern = r'\d{4}\.\d{2}[NS]/\d{5}\.\d{2}[EW](.)'
            matches = re.search(coord_pattern, raw_message)
            if matches and matches.group(1):
                symbol = matches.group(1)
                
                # Check if we have another symbol after lat/lon
                position_report = matches.group(0)
                if position_report and len(position_report) > 0:
                    # Find where this part ends in the original message
                    pos_end = raw_message.find(position_report) + len(position_report)
                    if pos_end < len(raw_message) and raw_message[pos_end:pos_end+1] in ["'", "/"]:
                        second_symbol = raw_message[pos_end:pos_end+1]
                        combined_symbol = symbol + second_symbol
                        
                        # The full symbol is typically the combination of the two
                        if combined_symbol in APRS_AIRCRAFT_TYPES:
                            return APRS_AIRCRAFT_TYPES[combined_symbol]
                
                # If we just have one symbol
                basic_symbol = "/" + symbol
                if basic_symbol in APRS_AIRCRAFT_TYPES:
                    return APRS_AIRCRAFT_TYPES[basic_symbol]
                
                # Check for backslash symbol
                basic_symbol_alt = "\\" + symbol
                if basic_symbol_alt in APRS_AIRCRAFT_TYPES:
                    return APRS_AIRCRAFT_TYPES[basic_symbol_alt]
    except Exception as e:
        logger.debug(f"Error extracting aircraft type from symbol: {e}")
    
    return "Unknown"


def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate distance between two coordinates in kilometers"""
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    km = 6371 * c  # Earth radius in kilometers
    return km
