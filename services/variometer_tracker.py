#!/usr/bin/env python3
"""
Variometer tracking module for calculating running averages
"""

import logging
from datetime import datetime, timedelta
from collections import deque, defaultdict
import statistics

# Get logger
logger = logging.getLogger("plane-tracker")

# Store variometer history for each aircraft
# Key: aircraft_id, Value: deque of (timestamp, climb_rate) tuples
variometer_history = defaultdict(lambda: deque(maxlen=60))  # Store up to 60 seconds of data

def update_variometer(aircraft_id, climb_rate):
    """
    Update variometer data for an aircraft and calculate averages
    
    Returns:
        dict: Contains 30s and 60s averages
    """
    current_time = datetime.now()
    
    # Add new data point to history
    variometer_history[aircraft_id].append((current_time, climb_rate))
    
    # Calculate averages
    history = variometer_history[aircraft_id]
    
    # Filter data for last 30 seconds
    thirty_sec_ago = current_time - timedelta(seconds=30)
    thirty_sec_data = [rate for timestamp, rate in history if timestamp >= thirty_sec_ago]
    
    # Filter data for last 60 seconds
    sixty_sec_ago = current_time - timedelta(seconds=60)
    sixty_sec_data = [rate for timestamp, rate in history if timestamp >= sixty_sec_ago]
    
    # Calculate averages (using median for stability)
    thirty_sec_avg = statistics.median(thirty_sec_data) if len(thirty_sec_data) >= 3 else None
    sixty_sec_avg = statistics.median(sixty_sec_data) if len(sixty_sec_data) >= 5 else None
    
    return {
        'climb_rate_30s_avg': round(thirty_sec_avg, 2) if thirty_sec_avg is not None else None,
        'climb_rate_60s_avg': round(sixty_sec_avg, 2) if sixty_sec_avg is not None else None,
        'data_points_30s': len(thirty_sec_data),
        'data_points_60s': len(sixty_sec_data)
    }

def cleanup_old_data():
    """Remove old data from aircraft that haven't been seen recently"""
    current_time = datetime.now()
    cutoff_time = current_time - timedelta(minutes=5)
    
    to_remove = []
    for aircraft_id, history in variometer_history.items():
        if history and history[-1][0] < cutoff_time:
            to_remove.append(aircraft_id)
    
    for aircraft_id in to_remove:
        del variometer_history[aircraft_id]
        logger.debug(f"Removed old variometer data for {aircraft_id}")