#!/usr/bin/env python3
"""
FLARM database handling for the WebSocket Server
"""

import os
import csv
import logging
import requests
from io import StringIO

from services.config import FLARM_DB_URL, FLARM_DB_FILE, flarm_db

# Get logger
logger = logging.getLogger("plane-tracker")


def save_flarm_database(content):
    """Save the FLARM database to a local file."""
    try:
        with open(FLARM_DB_FILE, 'w', encoding='utf-8') as file:
            file.write(content)
        logger.info(f"FLARM database saved to {FLARM_DB_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error saving FLARM database to file: {e}")
        return False


def load_flarm_database_from_file():
    """Load the FLARM database from the local file."""
    global flarm_db
    
    if not os.path.exists(FLARM_DB_FILE):
        logger.warning(f"Local FLARM database file {FLARM_DB_FILE} not found")
        return False
    
    try:
        logger.info(f"Loading FLARM database from local file {FLARM_DB_FILE}")
        with open(FLARM_DB_FILE, 'r', encoding='utf-8') as file:
            content = file.read()
            
        # Parse the CSV-like content
        reader = csv.reader(StringIO(content), delimiter=',', quotechar="'")
        count = 0
        
        # Reset the database
        flarm_db.clear()
        
        for row in reader:
            if len(row) >= 7:
                device_type = row[0].strip("'")
                device_id = row[1].strip("'")
                aircraft_model = row[2].strip("'")
                registration = row[3].strip("'")
                competition_number = row[4].strip("'")
                tracked = row[5].strip("'") == 'Y'
                identified = row[6].strip("'") == 'Y'
                
                # Store in the database dictionary
                flarm_db[device_id] = {
                    'device_type': device_type,
                    'aircraft_model': aircraft_model,
                    'registration': registration,
                    'competition_number': competition_number,
                    'tracked': tracked,
                    'identified': identified
                }
                count += 1
        
        logger.info(f"Successfully loaded {count} aircraft from local FLARM database file")
        return True
    except Exception as e:
        logger.error(f"Error loading FLARM database from file: {e}")
        return False


def download_flarm_database():
    """Download, parse, and save the FLARM database."""
    global flarm_db
    
    logger.info("Downloading FLARM database...")
    try:
        response = requests.get(FLARM_DB_URL, timeout=15)
        if response.status_code == 200:
            content = response.text
            
            # Save the database to a local file
            save_flarm_database(content)
            
            # Parse the CSV-like content
            reader = csv.reader(StringIO(content), delimiter=',', quotechar="'")
            count = 0
            
            # Reset the database
            flarm_db.clear()
            
            for row in reader:
                if len(row) >= 7:
                    device_type = row[0].strip("'")
                    device_id = row[1].strip("'")
                    aircraft_model = row[2].strip("'")
                    registration = row[3].strip("'")
                    competition_number = row[4].strip("'")
                    tracked = row[5].strip("'") == 'Y'
                    identified = row[6].strip("'") == 'Y'
                    
                    # Store in the database dictionary
                    flarm_db[device_id] = {
                        'device_type': device_type,
                        'aircraft_model': aircraft_model,
                        'registration': registration,
                        'competition_number': competition_number,
                        'tracked': tracked,
                        'identified': identified
                    }
                    count += 1
            
            logger.info(f"Successfully loaded {count} aircraft from online FLARM database")
            return True
        else:
            logger.error(f"Failed to download FLARM database. Status code: {response.status_code}")
            # Try to load from local file as fallback
            return load_flarm_database_from_file()
    except Exception as e:
        logger.error(f"Error downloading FLARM database: {e}")
        # Try to load from local file as fallback
        return load_flarm_database_from_file()


def get_flarm_info(device_id):
    """Get FLARM device information from the database."""
    # Remove the 'FLR' prefix if present
    if device_id and device_id.startswith('FLR'):
        device_id = device_id[3:]
    
    # Check if the device ID exists in the database
    return flarm_db.get(device_id, None)
