#!/usr/bin/env python3
"""
Position validation module to filter out fake/impossible aircraft positions
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from services.utils import calculate_distance

logger = logging.getLogger("position-validator")

# Maximum realistic speeds (km/h) for different aircraft types
MAX_SPEEDS = {
    'glider': 320,      # Max speed for high-performance gliders
    'tow_plane': 350,   # Max speed for tow planes
    'helicopter': 400,  # Max speed for helicopters
    'powered': 450,     # Max speed for powered aircraft
    'default': 500      # Absolute maximum for any aircraft
}

# Maximum climb/descent rates (m/s)
MAX_CLIMB_RATE = 30     # 30 m/s climb rate (extreme thermal/tow)
MAX_DESCENT_RATE = -50  # 50 m/s descent rate (emergency descent)

# Maximum altitude jump in 1 second (meters)
MAX_ALTITUDE_JUMP = 100

# Maximum distance between consecutive packets (km) - typically packets come every few seconds
MAX_PACKET_DISTANCE = 20

# Maximum altitude for any aircraft (meters) - commercial jets fly at ~13km, military ~25km
MAX_ALTITUDE = 15000  # 15km should cover all civilian aircraft

# Store last known valid positions for each aircraft
last_valid_positions: Dict[str, Dict] = {}

# Store suspicious aircraft IDs
suspicious_aircraft: Dict[str, int] = {}  # Count of suspicious events

# Blacklist for aircraft with impossible movements (1 hour expiry)
aircraft_blacklist: Dict[str, datetime] = {}  # aircraft_id -> blacklist_expiry_timestamp

# Blacklist duration in seconds (1 hour)
BLACKLIST_DURATION = 3600


def is_blacklisted(aircraft_id: str) -> bool:
    """Check if an aircraft is currently blacklisted"""
    if aircraft_id not in aircraft_blacklist:
        return False

    # Check if blacklist has expired
    now = datetime.now()
    if now >= aircraft_blacklist[aircraft_id]:
        # Blacklist expired, remove from blacklist
        del aircraft_blacklist[aircraft_id]
        logger.info(f"Aircraft {aircraft_id} removed from blacklist (expired)")
        return False

    return True


def add_to_blacklist(aircraft_id: str, reason: str):
    """Add an aircraft to the blacklist for 1 hour"""
    expiry_time = datetime.now() + timedelta(seconds=BLACKLIST_DURATION)
    aircraft_blacklist[aircraft_id] = expiry_time
    logger.warning(f"Aircraft {aircraft_id} added to blacklist until {expiry_time.strftime('%H:%M:%S')} - {reason}")


def get_max_speed_for_type(aircraft_type: str) -> float:
    """Get maximum speed for aircraft type"""
    # Handle non-string types (sometimes aircraft_type is an int from OGN parser)
    if not isinstance(aircraft_type, str):
        return MAX_SPEEDS['default']

    aircraft_type_lower = (aircraft_type or 'default').lower()

    if 'glider' in aircraft_type_lower or 'sailplane' in aircraft_type_lower:
        return MAX_SPEEDS['glider']
    elif 'tow' in aircraft_type_lower or 'tug' in aircraft_type_lower:
        return MAX_SPEEDS['tow_plane']
    elif 'helicopter' in aircraft_type_lower or 'heli' in aircraft_type_lower:
        return MAX_SPEEDS['helicopter']
    elif 'powered' in aircraft_type_lower or 'motor' in aircraft_type_lower:
        return MAX_SPEEDS['powered']

    return MAX_SPEEDS['default']


def validate_position(
    aircraft_id: str,
    lat: float,
    lon: float,
    alt: Optional[float],
    timestamp: datetime,
    aircraft_type: str = 'default',
    ground_speed: Optional[float] = None,
    climb_rate: Optional[float] = None
) -> Tuple[bool, Optional[str]]:
    """
    Validate aircraft position for impossible movements
    
    Returns:
        Tuple of (is_valid, reason_if_invalid)
    """
    
    # Basic coordinate validation
    if not (-90 <= lat <= 90):
        return False, f"Invalid latitude: {lat}"
    if not (-180 <= lon <= 180):
        return False, f"Invalid longitude: {lon}"

    # Check for impossible altitude (aircraft in space!)
    if alt is not None and alt > MAX_ALTITUDE:
        suspicious_aircraft[aircraft_id] = suspicious_aircraft.get(aircraft_id, 0) + 1
        reason = f"Impossible altitude: {alt:.0f}m (max: {MAX_ALTITUDE}m)"

        if suspicious_aircraft[aircraft_id] > 1:
            add_to_blacklist(aircraft_id, reason)
            logger.warning(f"Aircraft {aircraft_id} rejected and blacklisted - {reason}")
            return False, reason
        else:
            logger.info(f"Aircraft {aircraft_id} suspicious altitude - {reason}")

    # Check if we have a previous position for this aircraft
    if aircraft_id in last_valid_positions:
        last_pos = last_valid_positions[aircraft_id]
        last_lat = last_pos['latitude']
        last_lon = last_pos['longitude']
        last_alt = last_pos['altitude']
        last_time = last_pos['timestamp']
        
        # Calculate time difference
        time_diff = (timestamp - last_time).total_seconds()
        
        # Skip validation if timestamps are invalid or too old (> 5 minutes)
        if time_diff <= 0:
            return False, f"Invalid timestamp (non-positive time difference: {time_diff}s)"
        if time_diff > 300:  # More than 5 minutes - consider it a new track
            last_valid_positions[aircraft_id] = {
                'latitude': lat,
                'longitude': lon,
                'altitude': alt,
                'timestamp': timestamp
            }
            return True, None
        
        # Calculate distance traveled
        distance_km = calculate_distance(lat, lon, last_lat, last_lon)

        # Check if distance between packets is suspiciously large (>20 km jump in <60 seconds)
        # Only check if packets are recent (within 1 minute) to avoid false positives for long gaps
        if distance_km > MAX_PACKET_DISTANCE and time_diff < 60:
            suspicious_aircraft[aircraft_id] = suspicious_aircraft.get(aircraft_id, 0) + 1
            reason = (f"Suspicious position jump: {distance_km:.1f} km between packets "
                     f"(in {time_diff:.1f}s)")

            if suspicious_aircraft[aircraft_id] > 1:
                add_to_blacklist(aircraft_id, reason)
                logger.warning(f"Aircraft {aircraft_id} rejected and blacklisted - {reason}")
                return False, reason
            else:
                logger.info(f"Aircraft {aircraft_id} suspicious position jump - {reason}")

        # Calculate speed
        speed_kmh = (distance_km / time_diff) * 3600 if time_diff > 0 else 0

        # Get max speed for this aircraft type
        max_speed = get_max_speed_for_type(aircraft_type)
        
        # Check for impossible speed
        if speed_kmh > max_speed:
            suspicious_aircraft[aircraft_id] = suspicious_aircraft.get(aircraft_id, 0) + 1
            reason = (f"Impossible speed: {speed_kmh:.1f} km/h "
                     f"(traveled {distance_km:.2f} km in {time_diff:.1f}s, "
                     f"max for {aircraft_type}: {max_speed} km/h)")

            # If this aircraft has been suspicious multiple times, blacklist it
            if suspicious_aircraft[aircraft_id] > 1:
                add_to_blacklist(aircraft_id, reason)
                logger.warning(f"Aircraft {aircraft_id} rejected and blacklisted - {reason}")
                return False, reason
            else:
                logger.info(f"Aircraft {aircraft_id} suspicious movement - {reason}")
        
        # Check altitude changes if both altitudes are available
        if alt is not None and last_alt is not None:
            alt_change = alt - last_alt
            alt_change_rate = alt_change / time_diff if time_diff > 0 else 0
            
            # Check for impossible altitude jumps
            if abs(alt_change) > MAX_ALTITUDE_JUMP and time_diff <= 1:
                reason = f"Impossible altitude jump: {alt_change:.1f}m in {time_diff:.1f}s"
                suspicious_aircraft[aircraft_id] = suspicious_aircraft.get(aircraft_id, 0) + 1

                if suspicious_aircraft[aircraft_id] > 3:
                    add_to_blacklist(aircraft_id, reason)
                    logger.warning(f"Aircraft {aircraft_id} rejected and blacklisted - {reason}")
                    return False, reason
                else:
                    logger.info(f"Aircraft {aircraft_id} suspicious altitude - {reason}")

            # Check climb/descent rates
            if alt_change_rate > MAX_CLIMB_RATE or alt_change_rate < MAX_DESCENT_RATE:
                reason = f"Impossible climb/descent rate: {alt_change_rate:.1f} m/s"
                suspicious_aircraft[aircraft_id] = suspicious_aircraft.get(aircraft_id, 0) + 1

                if suspicious_aircraft[aircraft_id] > 3:
                    add_to_blacklist(aircraft_id, reason)
                    logger.warning(f"Aircraft {aircraft_id} rejected and blacklisted - {reason}")
                    return False, reason
                else:
                    logger.info(f"Aircraft {aircraft_id} suspicious climb rate - {reason}")
        
        # Check reported climb rate if available
        if climb_rate is not None:
            if climb_rate > MAX_CLIMB_RATE or climb_rate < MAX_DESCENT_RATE:
                reason = f"Reported climb rate out of range: {climb_rate:.1f} m/s"
                logger.info(f"Aircraft {aircraft_id} suspicious reported climb rate - {reason}")
        
        # Reset suspicious count if position is valid
        if aircraft_id in suspicious_aircraft and speed_kmh <= max_speed:
            suspicious_aircraft[aircraft_id] = max(0, suspicious_aircraft[aircraft_id] - 1)
    
    # Update last known valid position
    last_valid_positions[aircraft_id] = {
        'latitude': lat,
        'longitude': lon,
        'altitude': alt,
        'timestamp': timestamp
    }
    
    return True, None


def cleanup_old_positions():
    """Remove old position data for aircraft not seen recently and expired blacklist entries"""
    now = datetime.now()
    cutoff_time = now - timedelta(minutes=10)

    to_remove = []
    for aircraft_id, data in last_valid_positions.items():
        if data['timestamp'] < cutoff_time:
            to_remove.append(aircraft_id)

    for aircraft_id in to_remove:
        del last_valid_positions[aircraft_id]
        if aircraft_id in suspicious_aircraft:
            del suspicious_aircraft[aircraft_id]

    if to_remove:
        logger.info(f"Cleaned up {len(to_remove)} old aircraft positions")

    # Clean up expired blacklist entries
    expired_blacklist = []
    for aircraft_id, expiry_time in aircraft_blacklist.items():
        if now >= expiry_time:
            expired_blacklist.append(aircraft_id)

    for aircraft_id in expired_blacklist:
        del aircraft_blacklist[aircraft_id]

    if expired_blacklist:
        logger.info(f"Removed {len(expired_blacklist)} expired blacklist entries")