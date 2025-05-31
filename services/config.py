#!/usr/bin/env python3
"""
Configuration settings for the FLARM WebSocket Server
"""

import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Get MongoDB connection string from environment
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in environment variables")

# Collection names
FLARM_COLLECTION_NAME = "flarm_data"
PLANES_COLLECTION_NAME = "planes"
FLIGHT_LOGBOOK_COLLECTION_NAME = "flight_logbook"
CLUBS_COLLECTION_NAME = "clubs"

# Denmark configuration
DENMARK_CENTER_LAT = 55.923624
DENMARK_CENTER_LON = 9.755859
DENMARK_RADIUS_KM = 195
DENMARK_FILTER = f"r/{DENMARK_CENTER_LAT}/{DENMARK_CENTER_LON}/{DENMARK_RADIUS_KM}"

# Frankfurt configuration (currently not active)
FRANKFURT_CENTER_LAT = 50.110980
FRANKFURT_CENTER_LON = 8.664145
FRANKFURT_RADIUS_KM = 120
FRANKFURT_FILTER = f"r/{FRANKFURT_CENTER_LAT}/{FRANKFURT_CENTER_LON}/{FRANKFURT_RADIUS_KM}"

# Only tracking Denmark region for now
COMBINED_FILTER = DENMARK_FILTER

# FLARM database settings
FLARM_DB_URL = "https://ddb.glidernet.org/download/"
FLARM_DB_FILE = "flarm-database.csv"

# WebSocket server settings
WEBSOCKET_HOST = "0.0.0.0"
WEBSOCKET_PORT = 8765

# Club planes caching settings
CACHE_UPDATE_INTERVAL = 30 * 60  # 30 minutes in seconds
AIRCRAFT_REMOVAL_TIMEOUT = 600  # 10 minutes in seconds

# Global state
flarm_db = {}  # Store FLARM device information
club_flarm_ids = set()  # Store club planes' FLARM IDs for filtering
last_planes_cache_update = datetime(1970, 1, 1)  # Initialize with old time to force first update
aircraft_data = {}  # Store the latest data for each aircraft

# OGN client settings
OGN_USER = "N0CALL"
