#!/usr/bin/env python3
"""
OGN client module for processing FLARM beacon data
"""

import logging
import threading
import time
import queue
from datetime import datetime
from ogn.client import AprsClient
from ogn.parser import parse, ParseError

from services.config import (
    OGN_USER, COMBINED_FILTER, 
    DENMARK_CENTER_LAT, DENMARK_CENTER_LON, DENMARK_RADIUS_KM,
    FRANKFURT_CENTER_LAT, FRANKFURT_CENTER_LON, FRANKFURT_RADIUS_KM,
    aircraft_data, club_flarm_ids
)
from services.utils import get_aircraft_type_from_symbol, calculate_distance
from services.db import update_club_planes_cache, find_active_flight, store_aircraft_position
from services.flarm_database import get_flarm_info
from services.flight_events import process_flight_events, initialize_events_file, cleanup_state

# Get logger
logger = logging.getLogger("plane-tracker")

# Create queues for aircraft updates
aircraft_update_queue = queue.Queue()
aircraft_removal_queue = queue.Queue()


def process_beacon(raw_message):
    """Process OGN beacons and update aircraft data"""
    try:
        # Check if cache needs updating
        update_club_planes_cache()
            
        beacon = parse(raw_message)
        timestamp = beacon.get('timestamp', datetime.now())
        beacon_type = beacon.get('beacon_type', 'Unknown')
        
        # Only process aircraft beacons
        if beacon_type in ['aprs_aircraft', 'flarm', 'tracker']:
            # Skip beacons without position data
            if 'latitude' not in beacon or 'longitude' not in beacon:
                return
                
            # Get aircraft ID
            aircraft_id = None
            if 'address' in beacon:
                aircraft_id = beacon['address']
            elif 'name' in beacon:
                aircraft_id = beacon['name']
            else:
                return  # Skip if no identifier
            
            # Extract clean FLARM ID for filtering
            clean_flarm_id = aircraft_id
            if clean_flarm_id and clean_flarm_id.startswith('FLR'):
                clean_flarm_id = clean_flarm_id[3:]
            
            # Track all aircraft for WebSocket clients, but only store club planes in MongoDB
            store_in_mongodb = False
            if clean_flarm_id in club_flarm_ids:
                store_in_mongodb = True
            
            # Basic validation of coordinates
            lat = beacon['latitude']
            lon = beacon['longitude']
            alt = beacon.get('altitude')
            
            if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))):
                logger.warning(f"Invalid coordinates for aircraft {aircraft_id}: lat={lat}, lon={lon}")
                return
            
            # Calculate distance from both centers to identify which area this aircraft belongs to
            dist_from_denmark = calculate_distance(lat, lon, DENMARK_CENTER_LAT, DENMARK_CENTER_LON)
            dist_from_frankfurt = calculate_distance(lat, lon, FRANKFURT_CENTER_LAT, FRANKFURT_CENTER_LON)
            
            # Determine which region this aircraft belongs to
            in_denmark_radius = dist_from_denmark <= DENMARK_RADIUS_KM
            in_frankfurt_radius = dist_from_frankfurt <= FRANKFURT_RADIUS_KM
            region = "Unknown"
            if in_denmark_radius and in_frankfurt_radius:
                region = "Both Denmark and Frankfurt"
            elif in_denmark_radius:
                region = "Denmark"
            elif in_frankfurt_radius:
                region = "Frankfurt"
            
            # Get FLARM info
            flarm_info = get_flarm_info(aircraft_id) if aircraft_id else None
            
            # Get aircraft details
            aircraft_model = "Unknown"
            registration = ""
            if flarm_info:
                if flarm_info['aircraft_model']:
                    aircraft_model = flarm_info['aircraft_model']
                if flarm_info['registration']:
                    registration = flarm_info['registration']
            
            # Extract aircraft type from APRS symbols in the raw message
            aircraft_type = get_aircraft_type_from_symbol(raw_message)
            
            # Extract heading and speed from raw message if available
            raw_heading = None
            raw_speed = None
            raw_parts = raw_message.split("'")
            if len(raw_parts) > 1 and "/" in raw_parts[1]:
                try:
                    heading_speed = raw_parts[1].split("/")
                    if len(heading_speed) >= 2:
                        raw_heading = float(heading_speed[0].strip())
                        raw_speed = float(heading_speed[1].strip())
                except:
                    pass
            
            # Extract final values and ensure they're valid numbers
            track = raw_heading if raw_heading is not None else beacon.get('track', 0)
            track = float(track) if track is not None else 0.0
            
            ground_speed = raw_speed if raw_speed is not None else (beacon.get('ground_speed', 0) / 1.852 if beacon.get('ground_speed') else 0)
            ground_speed = float(ground_speed) if ground_speed is not None else 0.0
            
            climb_rate = beacon.get('climb_rate', 0)
            climb_rate = float(climb_rate) if climb_rate is not None else 0.0
            
            # Prepare aircraft data for websocket updates
            aircraft_data[aircraft_id] = {
                'id': aircraft_id,
                'timestamp': timestamp.isoformat(),
                'latitude': lat,
                'longitude': lon,
                'altitude': alt,
                'track': track,
                'ground_speed': ground_speed,
                'climb_rate': climb_rate,
                'turn_rate': beacon.get('turn_rate', 0),
                'aircraft_model': aircraft_model,
                'registration': registration,
                'aircraft_type': aircraft_type,
                'region': region,
                'last_seen': datetime.now().isoformat()
            }
            
            # Process flight events (detect takeoffs and landings)
            process_flight_events(aircraft_id, aircraft_data[aircraft_id])
            
            # Only store in MongoDB if it's a club aircraft and ground speed is above 10 km/h
            if store_in_mongodb and ground_speed > 10:
                # For club planes, check if there's an active flight
                flight_logbook_id = None
                if clean_flarm_id:
                    flight_logbook_id = find_active_flight(clean_flarm_id)
                    if flight_logbook_id:
                        # Add flight_logbook_id to websocket data too
                        aircraft_data[aircraft_id]['flight_logbook_id'] = flight_logbook_id
                
                # Prepare a separate object for MongoDB that matches the Prisma schema
                mongodb_data = {
                    'aircraft_id': aircraft_id,
                    'timestamp': timestamp,
                    'latitude': float(lat),
                    'longitude': float(lon),
                    'altitude': float(alt) if alt is not None else None,
                    'track': float(track) if track is not None else None,
                    'ground_speed': float(ground_speed) if ground_speed is not None else None,
                    'climb_rate': float(climb_rate) if climb_rate is not None else None,
                    'turn_rate': float(beacon.get('turn_rate', 0)) if beacon.get('turn_rate') is not None else None,
                    'aircraft_model': aircraft_model,
                    'registration': registration,
                    'aircraft_type': aircraft_type,
                }
                
                # Only add flight_logbook_id if there's an active flight
                if flight_logbook_id:
                    mongodb_data['flight_logbook_id'] = flight_logbook_id
                
                # Store position in MongoDB with the schema-aligned data
                store_aircraft_position(mongodb_data)
                if flight_logbook_id:
                    logger.info(f"✅ STORED club aircraft {aircraft_id} ({clean_flarm_id}) with active flight: {flight_logbook_id}, speed: {ground_speed} km/h")
                else:
                    logger.info(f"✅ STORED club aircraft {aircraft_id} ({clean_flarm_id}), speed: {ground_speed} km/h")
            
            # Put the update in the queue for the async task to handle
            aircraft_update_queue.put(aircraft_data[aircraft_id])
            
    except ParseError as e:
        logger.debug(f"Parse error: {e}")
    except Exception as e:
        logger.error(f"Error processing beacon: {e}")
        import traceback
        logger.error(traceback.format_exc())


def periodically_cleanup_state():
    """Periodically clean up flight states and recent takeoffs"""
    while True:
        try:
            cleanup_state()
            time.sleep(300)  # Run cleanup every 5 minutes
        except Exception as e:
            logger.error(f"Error in flight state cleanup: {e}")
            time.sleep(60)  # Longer delay on error


def start_ogn_client():
    """Start the OGN client in a separate thread"""
    client = AprsClient(aprs_user=OGN_USER, aprs_filter=COMBINED_FILTER)
    logger.info(f"Starting OGN client with combined filter:")
    logger.info(f"  - Denmark: Center({DENMARK_CENTER_LAT}, {DENMARK_CENTER_LON}), Radius: {DENMARK_RADIUS_KM}km")
    logger.info(f"  - Frankfurt: Center({FRANKFURT_CENTER_LAT}, {FRANKFURT_CENTER_LON}), Radius: {FRANKFURT_RADIUS_KM}km")
    logger.info(f"  - Full filter: {COMBINED_FILTER}")
    try:
        client.connect()
        client.run(callback=process_beacon, autoreconnect=True)
    except Exception as e:
        logger.error(f"Error in OGN client: {e}")
    finally:
        if hasattr(client, 'disconnect'):
            client.disconnect()


def cleanup_aircraft_data():
    """Clean up old aircraft data (aircraft not seen for more than 5 minutes)"""
    from services.config import AIRCRAFT_REMOVAL_TIMEOUT
    
    while True:
        try:
            now = datetime.now()
            to_delete = []
            
            for aircraft_id, data in aircraft_data.items():
                last_seen = datetime.fromisoformat(data['last_seen'])
                if (now - last_seen).total_seconds() > AIRCRAFT_REMOVAL_TIMEOUT:
                    to_delete.append(aircraft_id)
            
            for aircraft_id in to_delete:
                removed_data = {'id': aircraft_id, 'action': 'removed'}
                del aircraft_data[aircraft_id]
                # Queue the removal for the WebSocket server
                aircraft_removal_queue.put(removed_data)
            
            time.sleep(60)  # Run cleanup every minute
        except Exception as e:
            logger.error(f"Error in cleanup thread: {e}")
            time.sleep(60)


def start_ogn_threads():
    """Start OGN client and cleanup threads"""
    # Initialize the flight events file
    initialize_events_file()
    
    # Start the OGN client thread
    ogn_thread = threading.Thread(target=start_ogn_client)
    ogn_thread.daemon = True
    ogn_thread.start()
    
    # Start the cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_aircraft_data)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    # Start the flight state cleanup thread
    state_cleanup_thread = threading.Thread(target=periodically_cleanup_state)
    state_cleanup_thread.daemon = True
    state_cleanup_thread.start()
    
    return ogn_thread, cleanup_thread
