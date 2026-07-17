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
GROUND_VEHICLES_COLLECTION_NAME = "ground_vehicles"

# Denmark configuration
DENMARK_CENTER_LAT = 55.923624
DENMARK_CENTER_LON = 9.755859
DENMARK_RADIUS_KM = 195
# Base APRS-IS range filter covering Denmark. The live filter is built at runtime by
# services.db.build_aprs_filter(), which appends one r/<lat>/<lon>/<radius> clause per
# registered club airfield (home + allowed) so away-fields outside Denmark get tracked too.
COMBINED_FILTER = f"r/{DENMARK_CENTER_LAT}/{DENMARK_CENTER_LON}/{DENMARK_RADIUS_KM}"

# Radius (km) emitted per registered airfield when building the dynamic APRS filter.
# Covers local soaring / circuits around an away-field; raise it for longer cross-country.
PER_AIRFIELD_RADIUS_KM = 80

# WebSocket server settings
WEBSOCKET_HOST = os.getenv("WEBSOCKET_HOST", "0.0.0.0")
WEBSOCKET_PORT = int(os.getenv("WEBSOCKET_PORT", "8765"))

# Club planes caching settings
CACHE_UPDATE_INTERVAL = 30 * 60  # 30 minutes in seconds
AIRCRAFT_REMOVAL_TIMEOUT = 600  # 10 minutes in seconds

# Global state
club_flarm_ids = set()  # Store club planes' FLARM IDs for filtering
last_planes_cache_update = datetime(1970, 1, 1)  # Initialize with old time to force first update
aircraft_data = {}  # Store the latest data for each aircraft
ground_vehicles = {}  # normalized OGN ID -> {"name", "icon", "club_id"} for registered ground vehicles

# OGN client settings
OGN_USER = "N0CALL"
