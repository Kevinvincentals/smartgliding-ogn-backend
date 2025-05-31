#!/usr/bin/env python3
"""
Database operations for the FLARM WebSocket Server
"""

import logging
import pymongo
from datetime import datetime
from urllib.parse import urlparse

from services.config import (
    DATABASE_URL, 
    FLARM_COLLECTION_NAME, 
    PLANES_COLLECTION_NAME, 
    FLIGHT_LOGBOOK_COLLECTION_NAME,
    CLUBS_COLLECTION_NAME,
    club_flarm_ids, 
    last_planes_cache_update, 
    CACHE_UPDATE_INTERVAL
)

# Get logger
logger = logging.getLogger("plane-tracker")

# MongoDB client setup
mongo_client = pymongo.MongoClient(DATABASE_URL)

# Extract database name from the DATABASE_URL instead of hardcoding
parsed_url = urlparse(DATABASE_URL)
database_name = parsed_url.path.lstrip('/')
if not database_name:
    raise ValueError("No database name specified in DATABASE_URL")

db = mongo_client[database_name]
flarm_collection = db[FLARM_COLLECTION_NAME]
planes_collection = db[PLANES_COLLECTION_NAME]
flight_logbook_collection = db[FLIGHT_LOGBOOK_COLLECTION_NAME]
flight_events_collection = db["flight_events"]  # New collection for flight events
clubs_collection = db[CLUBS_COLLECTION_NAME]  # Add clubs collection

# Cache for registered homefields
registered_homefields = set()
last_homefields_cache_update = datetime(1970, 1, 1)

def update_registered_homefields_cache():
    """Update the cache of registered club homefields"""
    global registered_homefields, last_homefields_cache_update
    
    try:
        # Check if cache needs updating (every 5 minutes)
        current_time = datetime.now()
        if (current_time - last_homefields_cache_update).total_seconds() <= 300:
            return registered_homefields
            
        # Fetch all active clubs with homefields
        clubs = clubs_collection.find({
            "status": "active",
            "homefield": {"$exists": True, "$ne": ""}
        })
        
        # Extract homefields
        new_homefields = set()
        for club in clubs:
            if "homefield" in club and club["homefield"]:
                new_homefields.add(club["homefield"])
        
        # Update cache
        registered_homefields = new_homefields
        last_homefields_cache_update = current_time
        
        logger.info(f"Updated registered homefields cache: {len(registered_homefields)} homefields")
        return registered_homefields
    except Exception as e:
        logger.error(f"Error updating registered homefields cache: {e}")
        return registered_homefields

def is_registered_homefield(icao):
    """Check if an ICAO code is a registered club homefield"""
    # Update cache if needed
    update_registered_homefields_cache()
    return icao in registered_homefields

def init_database():
    """Initialize database connections and indexes"""
    try:
        # Test connection
        mongo_client.admin.command('ping')
        logger.info("Successfully connected to MongoDB")
        
        # Create index for efficient queries matching the Prisma schema's index
        flarm_collection.create_index([
            ("aircraft_id", pymongo.ASCENDING), 
            ("mongodb_timestamp", pymongo.DESCENDING)
        ])
        logger.info("Created MongoDB indexes for flarm_data collection")
        
        # Create index for flight events
        flight_events_collection.create_index([
            ("id", pymongo.ASCENDING),
            ("timestamp", pymongo.DESCENDING),
            ("type", pymongo.ASCENDING)
        ])
        logger.info("Created MongoDB indexes for flight_events collection")
        
        # Initialize club planes cache
        update_club_planes_cache()
        logger.info(f"Initialized club planes cache with {len(club_flarm_ids)} FLARM IDs")
        
        return True
    except Exception as e:
        logger.error(f"Failed to connect to MongoDB: {e}")
        return False


def update_club_planes_cache():
    """Fetch club planes from MongoDB and update the cache of FLARM IDs"""
    global club_flarm_ids, last_planes_cache_update
    
    try:
        # Check if cache needs updating
        current_time = datetime.now()
        if (current_time - last_planes_cache_update).total_seconds() <= CACHE_UPDATE_INTERVAL:
            return False  # Cache is still valid
            
        # Fetch all planes that have a flarm_id
        planes = planes_collection.find({"flarm_id": {"$exists": True, "$ne": ""}})
        
        # Extract and normalize FLARM IDs
        new_flarm_ids = set()
        count = 0
        
        for plane in planes:
            if "flarm_id" in plane and plane["flarm_id"]:
                flarm_id = plane["flarm_id"].upper()  # Normalize to uppercase
                new_flarm_ids.add(flarm_id)
                count += 1
        
        # Update the global set
        club_flarm_ids.clear()
        club_flarm_ids.update(new_flarm_ids)
        last_planes_cache_update = current_time
        
        logger.info(f"Updated club planes cache: {count} planes with FLARM IDs")
        return True
    except Exception as e:
        logger.error(f"Error updating club planes cache: {e}")
        return False


def find_active_flight(flarm_id):
    """Find active flight in logbook for the given FLARM ID"""
    try:
        # Query for active flight with this FLARM ID
        flight = flight_logbook_collection.find_one({
            "flarm_id": flarm_id,
            "status": "INFLIGHT", 
            "deleted": False
        })
        
        if flight and "_id" in flight:
            return str(flight["_id"])
        return None
    except Exception as e:
        logger.error(f"Error finding active flight for {flarm_id}: {e}")
        return None


def store_aircraft_position(aircraft_info):
    """Store aircraft position in MongoDB"""
    try:
        # Make a copy to avoid modifying the original
        db_data = aircraft_info.copy()
        
        # Parse timestamp if it's a string
        if 'timestamp' in db_data and isinstance(db_data['timestamp'], str):
            try:
                db_data['timestamp'] = datetime.fromisoformat(db_data['timestamp'])
            except ValueError:
                # If parsing fails, use current time
                db_data['timestamp'] = datetime.now()
        
        # Add timestamp for MongoDB
        db_data['mongodb_timestamp'] = datetime.now()
        
        # Store in MongoDB
        flarm_collection.insert_one(db_data)
        logger.debug(f"Stored position for aircraft {db_data.get('aircraft_id', 'unknown')} in MongoDB")
    except Exception as e:
        logger.error(f"Error storing aircraft position in MongoDB: {e}")


def store_flight_event(event_data):
    """Store flight event in MongoDB"""
    try:
        # Make a copy to avoid modifying the original
        db_data = event_data.copy()
        
        # Parse timestamp if it's a string
        if 'timestamp' in db_data and isinstance(db_data['timestamp'], str):
            try:
                db_data['timestamp'] = datetime.fromisoformat(db_data['timestamp'])
            except ValueError:
                # If parsing fails, use current time
                db_data['timestamp'] = datetime.now()
        else:
            db_data['timestamp'] = datetime.now()
        
        # Add MongoDB timestamp
        db_data['mongodb_timestamp'] = datetime.now()
        
        # Store in MongoDB
        flight_events_collection.insert_one(db_data)
        
        event_type = db_data.get('type', 'unknown')
        aircraft_id = db_data.get('id', 'unknown')
        airfield = db_data.get('airfield', 'unknown')
        
        logger.info(f"Stored {event_type} event for aircraft {aircraft_id} at {airfield} in MongoDB")
        return True
    except Exception as e:
        logger.error(f"Error storing flight event in MongoDB: {e}")
        return False


def get_aircraft_track(aircraft_id, limit=100):
    """Get historical track for an aircraft from MongoDB"""
    try:
        # Query MongoDB for recent positions of this aircraft
        cursor = flarm_collection.find(
            {"aircraft_id": aircraft_id},
            sort=[("mongodb_timestamp", pymongo.DESCENDING)],
            limit=limit
        )
        
        # Convert to list and return
        track = list(cursor)
        
        # Convert ObjectId to string for JSON serialization
        for point in track:
            if "_id" in point:
                point["_id"] = str(point["_id"])
                
        return track
    except Exception as e:
        logger.error(f"Error retrieving aircraft track from MongoDB: {e}")
        return []


def get_recent_flight_events(limit=100):
    """Get recent flight events from MongoDB"""
    try:
        # Query MongoDB for recent flight events
        cursor = flight_events_collection.find(
            {},
            sort=[("timestamp", pymongo.DESCENDING)],
            limit=limit
        )
        
        # Convert to list and return
        events = list(cursor)
        
        # Convert ObjectId to string for JSON serialization
        for event in events:
            if "_id" in event:
                event["_id"] = str(event["_id"])
                
        return events
    except Exception as e:
        logger.error(f"Error retrieving flight events from MongoDB: {e}")
        return []


def close_database_connection():
    """Close MongoDB connection"""
    mongo_client.close()
    logger.info("MongoDB connection closed")
