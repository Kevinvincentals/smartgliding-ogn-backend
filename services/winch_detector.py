#!/usr/bin/env python3
"""
Winch launch detection module for tracking maximum altitude during winch launches
"""

import logging
from datetime import datetime, timedelta
from collections import defaultdict

# Get logger
logger = logging.getLogger("plane-tracker")

# Constants for winch detection
WINCH_CLIMB_RATE_THRESHOLD = 5.0  # m/s - minimum climb rate to consider it's still in winch launch
WINCH_DETECTION_TIMEOUT = 120  # seconds - maximum duration of a winch launch
WINCH_MIN_ALTITUDE_GAIN = 100  # meters - minimum altitude gain to consider it a valid winch launch

# Store winch launch tracking data
winch_launch_data = defaultdict(lambda: {
    'is_in_winch': False,
    'launch_start_time': None,
    'launch_start_altitude': None,
    'max_altitude': None,
    'last_update': None,
    'detected_release': False
})

def start_winch_tracking(aircraft_id, altitude):
    """Start tracking a winch launch"""
    winch_launch_data[aircraft_id] = {
        'is_in_winch': True,
        'launch_start_time': datetime.now(),
        'launch_start_altitude': altitude,
        'max_altitude': altitude,
        'last_update': datetime.now(),
        'detected_release': False
    }
    logger.info(f"Started winch tracking for {aircraft_id} at altitude {altitude}m")

def update_winch_tracking(aircraft_id, altitude, climb_rate):
    """
    Update winch launch tracking for an aircraft
    
    Returns:
        dict or None: Contains winch launch data if release is detected, None otherwise
    """
    if aircraft_id not in winch_launch_data:
        return None
    
    data = winch_launch_data[aircraft_id]
    
    # Skip if not currently tracking a winch launch
    if not data['is_in_winch']:
        return None
    
    current_time = datetime.now()
    data['last_update'] = current_time
    
    # Update max altitude
    if altitude > data['max_altitude']:
        data['max_altitude'] = altitude
    
    # Check for timeout
    if (current_time - data['launch_start_time']).total_seconds() > WINCH_DETECTION_TIMEOUT:
        logger.info(f"Winch launch timeout for {aircraft_id}")
        data['is_in_winch'] = False
        return None
    
    # Detect winch release (climb rate drops below threshold or becomes negative)
    if climb_rate < WINCH_CLIMB_RATE_THRESHOLD and not data['detected_release']:
        altitude_gain = data['max_altitude'] - data['launch_start_altitude']
        
        # Only consider it a valid winch launch if there was significant altitude gain
        if altitude_gain >= WINCH_MIN_ALTITUDE_GAIN:
            data['detected_release'] = True
            data['is_in_winch'] = False
            
            launch_duration = (current_time - data['launch_start_time']).total_seconds()
            
            result = {
                'winch_launch_altitude': round(data['max_altitude'], 0),
                'winch_launch_duration': round(launch_duration, 1)
            }
            
            logger.info(f"Detected winch release for {aircraft_id}: max altitude {data['max_altitude']}m, "
                       f"gain {altitude_gain}m, duration {launch_duration}s")
            
            # Clean up the tracking data
            del winch_launch_data[aircraft_id]
            
            return result
        else:
            logger.debug(f"Insufficient altitude gain for winch launch: {altitude_gain}m")
            data['is_in_winch'] = False
    
    return None

def cleanup_old_winch_data():
    """Remove old winch tracking data"""
    current_time = datetime.now()
    cutoff_time = current_time - timedelta(minutes=10)
    
    to_remove = []
    for aircraft_id, data in winch_launch_data.items():
        if data['last_update'] < cutoff_time:
            to_remove.append(aircraft_id)
    
    for aircraft_id in to_remove:
        del winch_launch_data[aircraft_id]
        logger.debug(f"Removed old winch data for {aircraft_id}")