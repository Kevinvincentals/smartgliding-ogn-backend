#!/usr/bin/env python3
"""
Flight events detection module for the FLARM WebSocket Server
Detects takeoffs and landings for aircraft.
"""

import os
import json
import logging
import math
import requests
from datetime import datetime, timedelta
from collections import defaultdict
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from services.db import store_flight_event, is_registered_homefield

# Get logger
logger = logging.getLogger("plane-tracker")

# Constants for event detection
TAKEOFF_SPEED_THRESHOLD = 30  # km/h - lowered to be more sensitive
TAKEOFF_ALTITUDE_THRESHOLD = 20  # meters - lowered to be more sensitive
LANDING_SPEED_THRESHOLD = 40  # km/h
LANDING_ALTITUDE_THRESHOLD = 100  # meters
TAKEOFF_TOW_DISTANCE_THRESHOLD = 0.3  # km - max distance between glider and tow plane
TOW_START_TIME_WINDOW = 5  # seconds - time window to consider planes taking off together
EVENT_COOLDOWN = 10  # seconds - minimum time between events for the same aircraft

# Webhook configuration
WEBHOOK_URL = os.environ.get('WEBHOOK_URL', 'http://app.ekfs.dk/api/webhooks/flights')
WEBHOOK_API_KEY = os.environ.get('WEBHOOK_API_KEY', 'secret')  # Replace with actual API key in environment variable
WEBHOOK_ENABLED = os.environ.get('WEBHOOK_ENABLED', 'true').lower() == 'true'

# Known tow planes and motorgliders by model name parts
TOW_PLANE_MODELS = [
    "PA-25", "PAWNEE", "RALLYE", "DR-400", "ROBIN", "MAULE", "CUB", "WILGA", "HUSKY", 
    "SUPER CUB", "SCOUT", "CITABRIA", "CESSNA", "PIPER"
]

# Store flight states for each aircraft
aircraft_flight_states = defaultdict(lambda: {
    'is_airborne': None,  # None means we haven't determined the state yet
    'last_position': None,
    'last_update': None,
    'last_event': None,
    'takeoff_time': None,  # Record when the aircraft took off
    'start_type': None,    # 'tow', 'winch', or None
    'last_event_time': None  # Track when the last event was triggered
})

# Store recent takeoffs for tow/winch detection
recent_takeoffs = []  # List of (aircraft_id, time, position, aircraft_type, model) tuples

# File to store events - use environment variable if available
# Keeping this for backward compatibility
EVENTS_FILE = os.environ.get('EVENTS_FILE', 'flight_events.json')
AIRFIELDS_FILE = os.environ.get('AIRFIELDS_FILE', 'dk_airfields.json')

# Global variable to store the airfields data
airfields = []


def initialize_events_file():
    """Create or verify the events file exists"""
    global airfields
    
    # Load the airfields data
    try:
        with open(AIRFIELDS_FILE, 'r') as f:
            airfields = json.load(f)
        logger.info(f"Loaded {len(airfields)} airfields from {AIRFIELDS_FILE}")
    except Exception as e:
        logger.error(f"Error loading airfields file: {e}")
        airfields = []


def is_tow_plane(aircraft_type, aircraft_model):
    """Determine if this is a tow plane based on type and model"""
    # Check by APRS aircraft type first
    if aircraft_type in ["Drop plane/Powered aircraft"]:
        return True
    
    # Check by model name
    if aircraft_model:
        aircraft_model = aircraft_model.upper()
        for model_part in TOW_PLANE_MODELS:
            if model_part.upper() in aircraft_model:
                return True
    
    return False


def calculate_distance(lat1, lon1, lat2, lon2):
    """Calculate the distance between two points in kilometers using the Haversine formula"""
    # Convert latitude and longitude from degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    # Haversine formula
    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    # Earth radius in kilometers
    radius = 6371
    
    # Distance in kilometers
    distance = radius * c
    return distance


def find_nearest_airfield(latitude, longitude):
    """Find the nearest airfield to the given coordinates"""
    if not airfields:
        return None
    
    nearest_airfield = None
    min_distance = float('inf')
    
    for airfield in airfields:
        if 'latitude_deg' in airfield and 'longitude_deg' in airfield:
            airfield_lat = airfield.get('latitude_deg')
            airfield_lon = airfield.get('longitude_deg')
            
            distance = calculate_distance(latitude, longitude, airfield_lat, airfield_lon)
            
            if distance < min_distance:
                min_distance = distance
                nearest_airfield = {
                    'name': airfield.get('name'),
                    'icao': airfield.get('icao'),
                    'distance': distance  # Store the distance for threshold check
                }
    
    # If the closest airfield is more than 5 km away, return "unknown"
    if nearest_airfield and nearest_airfield.get('distance', 0) > 5:
        return {
            'name': 'UNKNOWN',
            'icao': 'UNKNOWN'
        }
    
    return nearest_airfield


def send_webhook(event_type, aircraft_id, airfield_icao):
    """Send a webhook to the configured URL"""
    if not WEBHOOK_ENABLED:
        return
    
    # Prepare payload as specified format
    payload = {
        "type": event_type,
        "origin": "FSK",
        "id": aircraft_id
    }
    
    # Only include airfield if it's known
    if airfield_icao and airfield_icao != "UNKNOWN":
        payload["airfield"] = airfield_icao
    
    # Set headers with API key
    headers = {
        'Content-Type': 'application/json',
        'X-api-key': WEBHOOK_API_KEY
    }
    
    # Send webhook
    try:
        response = requests.post(WEBHOOK_URL, json=payload, headers=headers, timeout=5)
        if response.status_code == 200:
            logger.info(f"Successfully sent {event_type} webhook for aircraft {aircraft_id}")
        else:
            logger.warning(f"Failed to send webhook: Status code {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending webhook: {str(e)}")


def log_event(event_type, aircraft_id, aircraft_data, start_type=None, paired_with=None):
    """Log a flight event to MongoDB"""
    latitude = aircraft_data.get('latitude')
    longitude = aircraft_data.get('longitude')
    
    event = {
        "type": event_type,
        "origin": "fsk-flarm-tracker",
        "id": aircraft_id,
        "timestamp": datetime.now().isoformat()
    }
    
    # Find the nearest airfield if coordinates are available
    airfield_icao = None
    if latitude is not None and longitude is not None:
        nearest = find_nearest_airfield(latitude, longitude)
        if nearest:
            event["airfield"] = nearest['name']
            if nearest['name'] != 'UNKNOWN':
                event["airfield_icao"] = nearest['icao']
                airfield_icao = nearest['icao']
            # If nearest airfield is UNKNOWN, include the coordinates
            else:
                event["latitude"] = latitude
                event["longitude"] = longitude
    else:
        event["airfield"] = "UNKNOWN"

    # Filter events by registered homefield ICAO
    if not airfield_icao or not is_registered_homefield(airfield_icao):
        logger.debug(f"Skipping event for aircraft {aircraft_id} at {airfield_icao} (not a registered homefield).")
        return None

    # Add aircraft information if available
    for field in ['aircraft_type', 'aircraft_model', 'registration']:
        if field in aircraft_data and aircraft_data[field]:
            event[field] = aircraft_data[field]
    
    # Add start type information if available
    if start_type:
        event["start_type"] = start_type
    
    # Add paired aircraft information if available
    if paired_with:
        event["paired_with"] = paired_with
    
    # Filter out None values
    event = {k: v for k, v in event.items() if v is not None}
    
    # Store in MongoDB
    result = store_flight_event(event)
    
    # Send webhook
    send_webhook(event_type, aircraft_id, airfield_icao)
    
    airfield_info = f" at {event.get('airfield', 'UNKNOWN')}" if "airfield" in event else ""
    logger.info(f"Logged {event_type} event for aircraft {aircraft_id}{airfield_info}" + 
                (f" ({start_type} start)" if start_type else ""))
    
    return result


def detect_launch_type(aircraft_id, aircraft_data, takeoff_time):
    """Detect if this was a tow or winch launch by comparing with recent takeoffs"""
    global recent_takeoffs
    
    # Clean up old takeoffs (more than 30 seconds old)
    current_time = datetime.now()
    recent_takeoffs = [t for t in recent_takeoffs if 
                      (current_time - t[1]).total_seconds() < 30]
    
    aircraft_lat = aircraft_data.get('latitude')
    aircraft_lon = aircraft_data.get('longitude')
    aircraft_type = aircraft_data.get('aircraft_type')
    aircraft_model = aircraft_data.get('aircraft_model')
    
    # Calculate time window
    time_window_start = takeoff_time - timedelta(seconds=TOW_START_TIME_WINDOW)
    time_window_end = takeoff_time + timedelta(seconds=TOW_START_TIME_WINDOW)
    
    # Check if this is a glider or tow plane
    is_current_glider = aircraft_type == 'Glider' and not is_tow_plane(aircraft_type, aircraft_model)
    is_current_tow = is_tow_plane(aircraft_type, aircraft_model)
    
    # Look for potential tow planes or gliders
    for other_id, other_time, other_pos, other_type, other_model in recent_takeoffs:
        # Skip self-comparison
        if other_id == aircraft_id:
            continue
        
        # Check time window
        if not (time_window_start <= other_time <= time_window_end):
            continue
        
        # Check position proximity
        other_lat, other_lon = other_pos
        distance_km = calculate_distance(aircraft_lat, aircraft_lon, other_lat, other_lon)
        
        if distance_km <= TAKEOFF_TOW_DISTANCE_THRESHOLD:
            is_other_tow = is_tow_plane(other_type, other_model)
            is_other_glider = other_type == 'Glider' and not is_tow_plane(other_type, other_model)
            
            # If this is a glider and other is a tow plane
            if is_current_glider and is_other_tow:
                # Update the start type in aircraft_flight_states
                aircraft_flight_states[aircraft_id]['start_type'] = 'tow'
                logger.info(f"Detected tow launch for glider {aircraft_id} with tow plane {other_id}")
                return 'tow', other_id
            
            # If this is a tow plane and other is a glider
            elif is_current_tow and is_other_glider:
                # Update the start type in aircraft_flight_states
                aircraft_flight_states[aircraft_id]['start_type'] = 'tow_plane'
                logger.info(f"Detected tow plane {aircraft_id} launching with glider {other_id}")
                return 'tow_plane', other_id
    
    # If we found no matching aircraft, it's probably a winch launch for gliders
    if is_current_glider:
        aircraft_flight_states[aircraft_id]['start_type'] = 'winch'
        logger.info(f"Detected winch launch for glider {aircraft_id}")
        return 'winch', None
    
    return None, None


def process_flight_events(aircraft_id, aircraft_data):
    """
    Process aircraft data to detect takeoffs and landings
    Returns True if an event was detected, False otherwise
    """
    # Get current state for this aircraft
    state = aircraft_flight_states[aircraft_id]
    current_time = datetime.now()
    
    # Check if we're in cooldown period
    if state['last_event_time'] is not None:
        time_since_last_event = (current_time - state['last_event_time']).total_seconds()
        if time_since_last_event < EVENT_COOLDOWN:
            logger.debug(f"Aircraft {aircraft_id} in cooldown period ({time_since_last_event:.1f}s remaining)")
            return False
    
    # Extract relevant data
    ground_speed = aircraft_data.get('ground_speed', 0)
    altitude = aircraft_data.get('altitude', 0)
    aircraft_type = aircraft_data.get('aircraft_type')
    aircraft_model = aircraft_data.get('aircraft_model')
    
    # Skip if essential data is missing
    if ground_speed is None or altitude is None:
        return False
    
    # Add debug logging to show what we're receiving
    logger.debug(f"Aircraft {aircraft_id} update: speed={ground_speed}km/h, altitude={altitude}m, type={aircraft_type}")
    
    # Create a current airborne state based on thresholds
    current_airborne = ground_speed >= TAKEOFF_SPEED_THRESHOLD and altitude >= TAKEOFF_ALTITUDE_THRESHOLD
    
    # First time we've seen this aircraft - just set the initial state and don't log
    if state['is_airborne'] is None:
        state['is_airborne'] = current_airborne
        state['last_position'] = {
            'latitude': aircraft_data.get('latitude'),
            'longitude': aircraft_data.get('longitude'),
            'altitude': altitude,
            'ground_speed': ground_speed
        }
        state['last_update'] = current_time
        
        # If the aircraft is already airborne on first detection, don't trigger a takeoff event
        if current_airborne:
            logger.debug(f"Aircraft {aircraft_id} first detected already airborne at altitude {altitude}m and speed {ground_speed}km/h")
        else:
            logger.debug(f"Aircraft {aircraft_id} first detected on ground at altitude {altitude}m and speed {ground_speed}km/h")
        
        return False
    
    # For debugging
    prev_altitude = state['last_position'].get('altitude', 0)
    prev_speed = state['last_position'].get('ground_speed', 0)
    prev_airborne = state['is_airborne']
    
    # Update the last position regardless
    state['last_position'] = {
        'latitude': aircraft_data.get('latitude'),
        'longitude': aircraft_data.get('longitude'),
        'altitude': altitude,
        'ground_speed': ground_speed
    }
    state['last_update'] = current_time
    
    # Detect takeoff - transitioned from not airborne to airborne
    if not prev_airborne and current_airborne:
        # Debug the transition
        logger.debug(f"Aircraft {aircraft_id} potential takeoff: prev_speed={prev_speed}→{ground_speed}km/h, prev_alt={prev_altitude}→{altitude}m")
        
        # Ensure the previous values were below the threshold (using OR instead of AND)
        if prev_speed < TAKEOFF_SPEED_THRESHOLD or prev_altitude < TAKEOFF_ALTITUDE_THRESHOLD:
            state['is_airborne'] = True
            state['last_event'] = 'takeoff'
            takeoff_time = current_time
            state['takeoff_time'] = takeoff_time
            state['last_event_time'] = takeoff_time  # Set the cooldown timer
            
            # Add to recent takeoffs for launch type detection
            recent_takeoffs.append((
                aircraft_id, 
                takeoff_time, 
                (aircraft_data.get('latitude'), aircraft_data.get('longitude')),
                aircraft_type,
                aircraft_model
            ))
            
            # Detect if this was a tow or winch launch
            start_type, paired_with = detect_launch_type(aircraft_id, aircraft_data, takeoff_time)
            
            # Log a single takeoff event with start type if detected
            event_type = 'takeoff'
            logger.info(f"Detected takeoff for aircraft {aircraft_id} at altitude {altitude}m and speed {ground_speed}km/h")
            
            # Log the takeoff event with start type information
            log_event(
                event_type, 
                aircraft_id, 
                aircraft_data,
                start_type=start_type,
                paired_with=paired_with
            )
            
            return True
    
    # Detect landing - transitioned from airborne to not airborne
    elif prev_airborne and not current_airborne:
        # Debug the transition
        logger.debug(f"Aircraft {aircraft_id} potential landing: prev_speed={prev_speed}→{ground_speed}km/h, prev_alt={prev_altitude}→{altitude}m")
        
        # IMPORTANT: Also check actual altitude to ensure it's close to ground level
        if altitude <= LANDING_ALTITUDE_THRESHOLD:
            state['is_airborne'] = False
            state['last_event'] = 'landing'
            state['last_event_time'] = current_time  # Set the cooldown timer
            
            # Get the start type if it was recorded
            start_type = state.get('start_type')
            
            # Log the landing event with start type if available
            log_event(
                'landing', 
                aircraft_id, 
                aircraft_data,
                start_type=start_type
            )
            logger.info(f"Detected landing for aircraft {aircraft_id} at altitude {altitude}m and speed {ground_speed}km/h")
            
            # Reset start type for next flight
            if 'start_type' in state:
                del state['start_type']
            
            return True
    
    # If state changed, log it for debugging
    if prev_airborne != current_airborne:
        logger.debug(f"Aircraft {aircraft_id} state changed: {prev_airborne} → {current_airborne} without triggering event")
    
    # Otherwise, just update the state without logging an event
    return False


def cleanup_state():
    """Clean up flight states for old aircraft"""
    current_time = datetime.now()
    to_remove = []
    
    for aircraft_id, state in aircraft_flight_states.items():
        # If we haven't seen this aircraft for more than 30 minutes, remove it
        if state['last_update'] and (current_time - state['last_update']).total_seconds() > 1800:
            to_remove.append(aircraft_id)
    
    for aircraft_id in to_remove:
        del aircraft_flight_states[aircraft_id]
    
    # Also clean up recent takeoffs older than 1 minute
    global recent_takeoffs
    recent_takeoffs = [t for t in recent_takeoffs if 
                      (current_time - t[1]).total_seconds() < 60] 