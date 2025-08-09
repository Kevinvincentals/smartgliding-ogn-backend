#!/usr/bin/env python3
"""
ADSB.lol API client module for fetching aircraft data
"""

import asyncio
import logging
import requests
import threading
import time
import queue
from datetime import datetime
from typing import Dict, List, Optional, Any

from services.config import DENMARK_CENTER_LAT, DENMARK_CENTER_LON, DENMARK_RADIUS_KM, AIRCRAFT_REMOVAL_TIMEOUT

# Get logger
logger = logging.getLogger("plane-tracker")

# Queue for ADSB aircraft updates
adsb_aircraft_queue = queue.Queue()

# Store ADSB aircraft data
adsb_aircraft_data = {}

# ADSB.lol API configuration
ADSB_API_BASE_URL = "https://api.adsb.lol"
ADSB_UPDATE_INTERVAL = 5  # seconds
ADSB_TIMEOUT = 10  # seconds for HTTP requests

# Function to check if there are connected clients
# This will be set by the websocket server module
get_connected_clients_count = None


class AdsbClient:
    """Client for fetching data from adsb.lol API"""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.timeout = ADSB_TIMEOUT
        self.running = False
        
    def fetch_aircraft_in_area(self, lat: float, lon: float, radius_nm: int) -> Optional[List[Dict[str, Any]]]:
        """
        Fetch aircraft data for a specific area from adsb.lol API
        
        Args:
            lat: Latitude of center point
            lon: Longitude of center point
            radius_nm: Radius in nautical miles (max 250)
            
        Returns:
            List of aircraft data or None if error
        """
        try:
            # Convert km to nautical miles (1 km = 0.539957 nm)
            radius_nm = min(int(radius_nm * 0.539957), 250)
            
            url = f"{ADSB_API_BASE_URL}/v2/point/{lat}/{lon}/{radius_nm}"
            
            logger.debug(f"Fetching ADSB data from: {url}")
            response = self.session.get(url)
            response.raise_for_status()
            
            data = response.json()
            
            # The API returns different structures, handle both cases
            if isinstance(data, dict):
                # If it's a dict, look for 'ac' key (aircraft array)
                aircraft_list = data.get('ac', [])
            elif isinstance(data, list):
                # If it's already a list, use it directly
                aircraft_list = data
            else:
                logger.warning(f"Unexpected data format from ADSB API: {type(data)}")
                return []
            
            logger.info(f"Fetched {len(aircraft_list)} aircraft from ADSB.lol API")
            return aircraft_list
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching ADSB data: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error in ADSB fetch: {e}")
            return None
    
    def normalize_aircraft_data(self, aircraft: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize ADSB aircraft data to match our internal format
        
        Args:
            aircraft: Raw aircraft data from ADSB API
            
        Returns:
            Normalized aircraft data
        """
        try:
            # Map ADSB fields to our internal format
            normalized = {
                'source': 'adsb',
                'timestamp': datetime.utcnow(),
                'hex': aircraft.get('hex', '').upper(),
                'flight': aircraft.get('flight', '').strip(),
                'registration': aircraft.get('r', ''),
                'aircraft_type': aircraft.get('t', ''),
                'latitude': aircraft.get('lat'),
                'longitude': aircraft.get('lon'),
                'altitude': aircraft.get('alt_baro'),  # Barometric altitude
                'ground_speed': aircraft.get('gs'),  # Ground speed in knots
                'track': aircraft.get('track'),  # Track angle in degrees
                'vertical_rate': aircraft.get('baro_rate'),  # Vertical rate in ft/min
                'squawk': aircraft.get('squawk'),
                'emergency': aircraft.get('emergency'),
                'category': aircraft.get('category'),
                'nav_qnh': aircraft.get('nav_qnh'),
                'nav_altitude_mcp': aircraft.get('nav_altitude_mcp'),
                'nav_heading': aircraft.get('nav_heading'),
                'nic': aircraft.get('nic'),
                'rc': aircraft.get('rc'),
                'seen_pos': aircraft.get('seen_pos'),
                'seen': aircraft.get('seen'),
                'rssi': aircraft.get('rssi'),
                'alert': aircraft.get('alert'),
                'spi': aircraft.get('spi'),
                'nic_baro': aircraft.get('nic_baro'),
                'nac_p': aircraft.get('nac_p'),
                'nac_v': aircraft.get('nac_v'),
                'sil': aircraft.get('sil'),
                'sil_type': aircraft.get('sil_type'),
                'gva': aircraft.get('gva'),
                'sda': aircraft.get('sda'),
                'mlat': aircraft.get('mlat', []),
                'tisb': aircraft.get('tisb', []),
                'messages': aircraft.get('messages'),
                'version': aircraft.get('version'),
                'nic_a': aircraft.get('nic_a'),
                'nic_c': aircraft.get('nic_c'),
                'nic_s': aircraft.get('nic_s'),
                'cc': aircraft.get('cc'),  # Country code
                'mil': aircraft.get('mil', False),  # Military flag
                'pia': aircraft.get('pia', False),  # Privacy ICAO Address flag
            }
            
            # Add computed fields
            if normalized['hex']:
                normalized['aircraft_id'] = f"adsb_{normalized['hex']}"
            
            # Clean up None values and empty strings
            normalized = {k: v for k, v in normalized.items() if v is not None and v != ''}
            
            return normalized
            
        except Exception as e:
            logger.error(f"Error normalizing ADSB aircraft data: {e}")
            return {}
    
    def clear_aircraft_data(self):
        """Clear all aircraft data and send removal notifications"""
        global adsb_aircraft_data
        
        # Send removal notifications for all aircraft
        for aircraft_id, aircraft_data in adsb_aircraft_data.items():
            adsb_aircraft_queue.put({
                'type': 'remove',
                'data': {'aircraft_id': aircraft_id, 'hex': aircraft_data.get('hex')}
            })
        
        # Clear the data
        adsb_aircraft_data.clear()
        logger.info("Cleared all ADSB aircraft data due to no connected clients")
    
    def cleanup_old_aircraft(self):
        """Remove ADSB aircraft that haven't been seen for more than the timeout period"""
        global adsb_aircraft_data
        
        now = datetime.utcnow()
        to_remove = []
        
        for aircraft_id, aircraft_data in adsb_aircraft_data.items():
            last_seen = aircraft_data.get('timestamp')
            if last_seen and isinstance(last_seen, datetime):
                time_since_seen = (now - last_seen).total_seconds()
                if time_since_seen > AIRCRAFT_REMOVAL_TIMEOUT:
                    to_remove.append(aircraft_id)
        
        # Remove old aircraft
        for aircraft_id in to_remove:
            removed_data = adsb_aircraft_data.pop(aircraft_id)
            adsb_aircraft_queue.put({
                'type': 'remove',
                'data': {'aircraft_id': aircraft_id, 'hex': removed_data.get('hex')}
            })
            logger.info(f"Removed old ADSB aircraft {aircraft_id} (not seen for {AIRCRAFT_REMOVAL_TIMEOUT/60:.1f} minutes)")
    
    def fetch_and_process_data(self):
        """Fetch and process ADSB data in a loop"""
        global adsb_aircraft_data
        
        last_had_clients = False
        last_cleanup_time = time.time()
        
        while self.running:
            try:
                # Check if there are connected clients
                has_clients = False
                if get_connected_clients_count:
                    client_count = get_connected_clients_count()
                    has_clients = client_count > 0
                    
                    if has_clients and not last_had_clients:
                        logger.info(f"📡 ADSB client resuming data fetching - {client_count} clients connected")
                    elif not has_clients and last_had_clients:
                        logger.info("⏸️ ADSB client pausing data fetching - no clients connected")
                        self.clear_aircraft_data()
                
                last_had_clients = has_clients
                
                # Only fetch data if there are connected clients
                if has_clients:
                    # Fetch aircraft data for Denmark area
                    aircraft_list = self.fetch_aircraft_in_area(
                        DENMARK_CENTER_LAT, 
                        DENMARK_CENTER_LON, 
                        DENMARK_RADIUS_KM
                    )
                    
                    if aircraft_list is not None:
                        current_aircraft = {}
                        
                        # Process each aircraft
                        for aircraft in aircraft_list:
                            normalized = self.normalize_aircraft_data(aircraft)
                            if normalized and normalized.get('aircraft_id'):
                                # Filter out aircraft above 5000 feet
                                altitude = normalized.get('altitude')
                                if altitude is not None:
                                    try:
                                        altitude_ft = float(altitude)
                                        if altitude_ft > 5000:
                                            continue  # Skip this aircraft
                                    except (ValueError, TypeError):
                                        # If we can't parse altitude, include the aircraft
                                        pass
                                
                                # Filter out TWR (tower) aircraft
                                flight = normalized.get('flight', '').strip()
                                if flight == 'TWR':
                                    continue  # Skip TWR aircraft
                                
                                current_aircraft[normalized['aircraft_id']] = normalized
                        
                        # Find new/updated aircraft
                        for aircraft_id, aircraft_data in current_aircraft.items():
                            if aircraft_id not in adsb_aircraft_data or adsb_aircraft_data[aircraft_id] != aircraft_data:
                                # New or updated aircraft
                                adsb_aircraft_data[aircraft_id] = aircraft_data
                                adsb_aircraft_queue.put({
                                    'type': 'update',
                                    'data': aircraft_data
                                })
                        
                        # Find removed aircraft (not in current fetch but still in our data)
                        removed_aircraft = set(adsb_aircraft_data.keys()) - set(current_aircraft.keys())
                        for aircraft_id in removed_aircraft:
                            removed_data = adsb_aircraft_data.pop(aircraft_id)
                            adsb_aircraft_queue.put({
                                'type': 'remove',
                                'data': {'aircraft_id': aircraft_id, 'hex': removed_data.get('hex')}
                            })
                    
                    # Perform cleanup of old aircraft every minute (60 seconds)
                    current_time = time.time()
                    if current_time - last_cleanup_time >= 60:
                        self.cleanup_old_aircraft()
                        last_cleanup_time = current_time
                else:
                    # No clients connected, just wait
                    logger.debug("No clients connected, skipping ADSB API call")
                
                # Wait before next update
                time.sleep(ADSB_UPDATE_INTERVAL)
                
            except Exception as e:
                logger.error(f"Error in ADSB data fetch loop: {e}")
                time.sleep(ADSB_UPDATE_INTERVAL)
    
    def start(self):
        """Start the ADSB client"""
        self.running = True
        logger.info("🚀 Starting ADSB client...")
    
    def stop(self):
        """Stop the ADSB client"""
        self.running = False
        logger.info("🛑 Stopping ADSB client...")


# Global ADSB client instance
adsb_client = AdsbClient()


def start_adsb_client():
    """Start the ADSB client in a separate thread"""
    def run_client():
        adsb_client.start()
        adsb_client.fetch_and_process_data()
    
    thread = threading.Thread(target=run_client, daemon=True)
    thread.start()
    logger.info("✅ ADSB client thread started")
    return thread


def stop_adsb_client():
    """Stop the ADSB client"""
    adsb_client.stop()


def set_client_count_callback(callback_func):
    """Set the callback function to get connected client count"""
    global get_connected_clients_count
    get_connected_clients_count = callback_func
    logger.info("✅ ADSB client callback configured") 