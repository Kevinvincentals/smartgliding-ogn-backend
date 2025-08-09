#!/usr/bin/env python3
"""
Database operations for the FLARM WebSocket Server
"""

import logging
import pymongo
import requests
import json
import sys
from datetime import datetime, timedelta
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
dk_airfields_collection = db["dk_airfields"]  # Collection for Danish airfields

# Cache for registered homefields
registered_homefields = set()
last_homefields_cache_update = datetime(1970, 1, 1)

def _print_airfields_progress_bar(current, total, prefix="Airfields", suffix="", length=30, created=0, updated=0, unchanged=0):
    """Print a progress bar with statistics for airfields"""
    percent = f"{100 * (current / float(total)):.1f}"
    filled_length = int(length * current // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    
    # Create stats string
    stats = f"Created: {created}, Updated: {updated}, Unchanged: {unchanged}"
    
    # Print with carriage return to overwrite the same line
    print(f'\r{prefix} |{bar}| {percent}% ({current}/{total}) - {stats} {suffix}', end='', flush=True)
    
    # Print newline when complete
    if current == total:
        print()


def fetch_and_update_dk_airfields():
    """Fetch Danish airfield data from external URL and update database"""
    try:
        logger.info("🌐 Fetching Danish airfields...")
        
        # Fetch data from the URL
        response = requests.get("https://tideo.dk/smartgliding/dk_airfields.json", timeout=30)
        response.raise_for_status()
        
        airfields_data = response.json()
        total_airfields = len(airfields_data)
        
        # Pre-load existing records for faster comparison
        existing_records = {}
        for record in dk_airfields_collection.find({}, {"ident": 1, "type": 1, "name": 1, "municipality": 1, "icao": 1, "latitude_deg": 1, "longitude_deg": 1}):
            ident = record.get("ident")
            if ident:
                existing_records[ident] = {
                    "ident": ident,
                    "type": record.get("type"),
                    "name": record.get("name"),
                    "municipality": record.get("municipality"),
                    "icao": record.get("icao"),
                    "latitude_deg": record.get("latitude_deg"),
                    "longitude_deg": record.get("longitude_deg")
                }
        
        # Track statistics
        updated_count = 0
        created_count = 0
        error_count = 0
        unchanged_count = 0
        processed_count = 0
        
        # Batch operations for better performance
        batch_updates = []
        batch_inserts = []
        batch_size = 100  # Smaller batch size for airfields since there are fewer
        progress_interval = max(1, total_airfields // 20)  # Update every 5% for smaller datasets
        
        # Initial progress bar
        _print_airfields_progress_bar(0, total_airfields, "Airfields", "", 30, created_count, updated_count, unchanged_count)
        
        for airfield_data in airfields_data:
            try:
                processed_count += 1
                
                # Show progress
                if processed_count % progress_interval == 0 or processed_count == total_airfields:
                    _print_airfields_progress_bar(processed_count, total_airfields, "Airfields", "", 30, created_count, updated_count, unchanged_count)
                
                ident = airfield_data.get("ident")
                if not ident:
                    logger.warning("Airfield missing ident, skipping")
                    error_count += 1
                    continue
                
                # Prepare the new document data (excluding timestamps)
                new_data = {
                    "ident": ident,
                    "type": airfield_data.get("type"),
                    "name": airfield_data.get("name"),
                    "municipality": airfield_data.get("municipality"),
                    "icao": airfield_data.get("icao"),
                    "latitude_deg": float(airfield_data.get("latitude_deg", 0)),
                    "longitude_deg": float(airfield_data.get("longitude_deg", 0))
                }
                
                # Check if record exists and if it has changed
                existing_data = existing_records.get(ident)
                
                if existing_data:
                    # Check if there are any actual changes
                    if existing_data == new_data:
                        unchanged_count += 1
                        continue  # No changes, skip update
                    
                    # Data has changed, prepare for batch update
                    update_doc = new_data.copy()
                    update_doc["updatedAt"] = datetime.now()
                    
                    batch_updates.append({
                        "filter": {"ident": ident},
                        "update": {"$set": update_doc}
                    })
                    updated_count += 1
                
                else:
                    # New record, prepare for batch insert
                    create_doc = new_data.copy()
                    create_doc["createdAt"] = datetime.now()
                    create_doc["updatedAt"] = datetime.now()
                    
                    batch_inserts.append(create_doc)
                    created_count += 1
                
                # Process batch when it reaches batch_size
                if len(batch_updates) >= batch_size:
                    _execute_airfields_batch_updates(batch_updates)
                    batch_updates = []
                
                if len(batch_inserts) >= batch_size:
                    _execute_airfields_batch_inserts(batch_inserts)
                    batch_inserts = []
                    
            except Exception as e:
                logger.error(f"Error processing airfield {airfield_data.get('ident', 'unknown')}: {e}")
                error_count += 1
        
        # Process remaining batches
        if batch_updates:
            _execute_airfields_batch_updates(batch_updates)
        
        if batch_inserts:
            _execute_airfields_batch_inserts(batch_inserts)
        
        # Create index for efficient lookups (only if collection has data)
        if created_count > 0 or updated_count > 0:
            try:
                dk_airfields_collection.create_index("ident", unique=True)
            except pymongo.errors.OperationFailure as e:
                if e.code != 85:  # Only raise if not IndexOptionsConflict
                    raise
            
            try:
                dk_airfields_collection.create_index("icao")
            except pymongo.errors.OperationFailure as e:
                if e.code != 85:
                    raise
            
            try:
                dk_airfields_collection.create_index([("latitude_deg", 1), ("longitude_deg", 1)])
            except pymongo.errors.OperationFailure as e:
                if e.code != 85:
                    raise
        
        # Consolidated final message with checkmark
        total_changes = created_count + updated_count
        if total_changes > 0:
            logger.info(f"✅ Airfields: {created_count} created, {updated_count} updated, {unchanged_count} unchanged")
        else:
            logger.info(f"✅ Airfields: {unchanged_count} entries, no changes needed")
        
        return True
        
    except requests.RequestException as e:
        logger.error(f"Failed to fetch Danish airfield data: {e}")
        return False
    except Exception as e:
        logger.error(f"Error updating Danish airfield data: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def _execute_airfields_batch_updates(batch_updates):
    """Execute batch updates for airfields using bulk_write"""
    try:
        if not batch_updates:
            return
        
        import pymongo
        operations = [pymongo.UpdateOne(update["filter"], update["update"]) for update in batch_updates]
        
        result = dk_airfields_collection.bulk_write(operations, ordered=False)
        logger.debug(f"Batch updated {result.modified_count} airfield records")
        
    except Exception as e:
        logger.error(f"Error in airfields batch updates: {e}")


def _execute_airfields_batch_inserts(batch_inserts):
    """Execute batch inserts for airfields"""
    try:
        if not batch_inserts:
            return
        
        result = dk_airfields_collection.insert_many(batch_inserts, ordered=False)
        logger.debug(f"Batch inserted {len(result.inserted_ids)} airfield records")
        
    except Exception as e:
        logger.error(f"Error in airfields batch inserts: {e}")

def get_dk_airfield_by_icao(icao_code):
    """Get Danish airfield information by ICAO code"""
    try:
        airfield = dk_airfields_collection.find_one({"icao": icao_code})
        if airfield and "_id" in airfield:
            airfield["_id"] = str(airfield["_id"])
        return airfield
    except Exception as e:
        logger.error(f"Error retrieving airfield for ICAO {icao_code}: {e}")
        return None

def get_dk_airfield_by_ident(ident):
    """Get Danish airfield information by identifier"""
    try:
        airfield = dk_airfields_collection.find_one({"ident": ident})
        if airfield and "_id" in airfield:
            airfield["_id"] = str(airfield["_id"])
        return airfield
    except Exception as e:
        logger.error(f"Error retrieving airfield for ident {ident}: {e}")
        return None

def find_nearest_dk_airfields(latitude, longitude, max_distance_km=50, limit=10):
    """Find nearest Danish airfields to given coordinates"""
    try:
        # Convert km to degrees (approximate)
        max_distance_deg = max_distance_km / 111.0  # 1 degree ≈ 111 km
        
        # Query airfields within bounding box
        airfields = dk_airfields_collection.find({
            "latitude_deg": {
                "$gte": latitude - max_distance_deg,
                "$lte": latitude + max_distance_deg
            },
            "longitude_deg": {
                "$gte": longitude - max_distance_deg,
                "$lte": longitude + max_distance_deg
            }
        }).limit(limit)
        
        # Convert to list and calculate distances
        result = []
        for airfield in airfields:
            if "_id" in airfield:
                airfield["_id"] = str(airfield["_id"])
            
            # Calculate approximate distance
            lat_diff = airfield["latitude_deg"] - latitude
            lon_diff = airfield["longitude_deg"] - longitude
            distance_km = ((lat_diff ** 2 + lon_diff ** 2) ** 0.5) * 111.0
            airfield["distance_km"] = round(distance_km, 2)
            
            if distance_km <= max_distance_km:
                result.append(airfield)
        
        # Sort by distance
        result.sort(key=lambda x: x["distance_km"])
        return result
        
    except Exception as e:
        logger.error(f"Error finding nearest airfields: {e}")
        return []

def update_registered_homefields_cache():
    """Update the cache of registered club homefields"""
    global registered_homefields, last_homefields_cache_update
    
    try:
        # Check if cache needs updating (every 30 minutes, same as club planes)
        current_time = datetime.now()
        if (current_time - last_homefields_cache_update).total_seconds() <= CACHE_UPDATE_INTERVAL:
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
        
        # Check for changes
        is_initialization = last_homefields_cache_update == datetime(1970, 1, 1)
        changes_detected = registered_homefields != new_homefields
        
        # Update the cache
        registered_homefields = new_homefields
        last_homefields_cache_update = current_time
        
        # Log changes if not during initialization
        if changes_detected and not is_initialization:
            logger.info(f"✅ Updated registered homefields cache: {len(new_homefields)} homefields")
        else:
            logger.debug(f"Updated registered homefields cache: {len(new_homefields)} homefields")
        
        return registered_homefields
    except Exception as e:
        logger.error(f"Error updating registered homefields cache: {e}")
        return registered_homefields

def is_registered_homefield(icao):
    """Check if an ICAO code is a registered club homefield"""
    return icao in registered_homefields

def init_database():
    """Initialize database connections and indexes"""
    try:
        # Test connection
        mongo_client.admin.command('ping')
        logger.info("✅ Connected to MongoDB")
        
        # Create indexes with error handling for existing indexes
        try:
            # Create index for efficient queries matching the Prisma schema's index
            # The Prisma schema has this index: @@index([aircraft_id, mongodb_timestamp(sort: Desc)])
            flarm_collection.create_index([
                ("aircraft_id", pymongo.ASCENDING), 
                ("mongodb_timestamp", pymongo.DESCENDING)
            ], name="flarm_data_aircraft_id_mongodb_timestamp_idx")
        except pymongo.errors.OperationFailure as e:
            if e.code == 85:  # IndexOptionsConflict
                logger.debug("Index already exists on flarm_data collection, skipping creation")
            else:
                raise
        
        try:
            # Create index for flight events
            flight_events_collection.create_index([
                ("id", pymongo.ASCENDING),
                ("timestamp", pymongo.DESCENDING),
                ("type", pymongo.ASCENDING)
            ])
        except pymongo.errors.OperationFailure as e:
            if e.code == 85:  # IndexOptionsConflict
                logger.debug("Index already exists on flight_events collection, skipping creation")
            else:
                raise
                
        logger.info("✅ Database indexes verified")
        
        # Initialize club planes cache
        update_club_planes_cache()
        logger.info(f"✅ Loaded {len(club_flarm_ids)} club planes")
        
        # Initialize registered homefields cache
        update_registered_homefields_cache()
        logger.info(f"✅ Loaded {len(registered_homefields)} registered homefields")
        
        # Start cache refresh background thread
        start_cache_refresh_thread()
        
        # Fetch and update Danish airfield data
        if fetch_and_update_dk_airfields():
            logger.info("✅ Danish airfields updated")
        else:
            logger.warning("⚠️ Failed to update Danish airfield data")
        
        # Fetch and update OGN database
        from services.flarm_database import fetch_and_update_ogn_database
        if fetch_and_update_ogn_database():
            logger.info("✅ OGN database updated")
        else:
            logger.warning("⚠️ Failed to update OGN database")
        
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
            
        # Calculate 3 days ago for guest aircraft filtering (date only)
        three_days_ago = (current_time - timedelta(days=3)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Fetch all planes that have a flarm_id and are either:
        # 1. Not guest aircraft (club aircraft)
        # 2. Guest aircraft created within the last 3 days
        planes = planes_collection.find({
            "flarm_id": {"$exists": True, "$ne": ""},
            "$or": [
                {"is_guest": {"$ne": True}},  # Club aircraft
                {
                    "is_guest": True,
                    "createdAt": {"$gte": three_days_ago}  # Active guest aircraft
                }
            ]
        })
        
        # Extract and normalize FLARM IDs
        new_flarm_ids = set()
        plane_details = []  # Store for logging
        count = 0
        
        for plane in planes:
            if "flarm_id" in plane and plane["flarm_id"]:
                flarm_id = plane["flarm_id"].upper()  # Normalize to uppercase
                # Get registration and model from database fields
                registration = plane.get("registration_id", "Unknown")
                model = plane.get("type", "Unknown")
                is_guest = plane.get("is_guest", False)
                new_flarm_ids.add(flarm_id)
                plane_details.append((registration, model, flarm_id, is_guest))
                count += 1
        
        # Check for changes
        is_initialization = last_planes_cache_update == datetime(1970, 1, 1)
        changes_detected = club_flarm_ids != new_flarm_ids
        
        # Update the global set
        club_flarm_ids.clear()
        club_flarm_ids.update(new_flarm_ids)
        last_planes_cache_update = current_time
        
        # Log changes if not during initialization
        if changes_detected and not is_initialization:
            logger.info(f"✅ Updated club planes cache: {count} planes with FLARM IDs")
        else:
            logger.debug(f"Updated club planes cache: {count} planes with FLARM IDs")
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


def update_flight_winch_altitude(flight_logbook_id, winch_altitude):
    """Update flight with winch launch altitude"""
    try:
        from bson import ObjectId
        
        result = flight_logbook_collection.update_one(
            {"_id": ObjectId(flight_logbook_id)},
            {
                "$set": {
                    "winch_launch_altitude": winch_altitude,
                    "updatedAt": datetime.now()
                }
            }
        )
        
        if result.modified_count > 0:
            logger.info(f"Updated flight {flight_logbook_id} with winch altitude: {winch_altitude}m")
            return True
        return False
    except Exception as e:
        logger.error(f"Error updating flight with winch altitude: {e}")
        return False


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

def refresh_all_caches():
    """Refresh all cached data"""
    try:
        logger.debug("🔄 Refreshing all caches...")
        
        # Refresh club planes cache
        club_planes_updated = update_club_planes_cache()
        
        # Refresh registered homefields cache
        homefields_updated = update_registered_homefields_cache()
        
        # Log summary
        if club_planes_updated or homefields_updated:
            logger.debug("✅ Cache refresh completed")
        else:
            logger.debug("✅ Cache refresh completed (no updates needed)")
        
        return True
    except Exception as e:
        logger.error(f"Error refreshing caches: {e}")
        return False

def start_cache_refresh_thread():
    """Start a background thread to refresh caches every 30 minutes"""
    import threading
    import time
    
    def cache_refresh_worker():
        """Background worker to refresh caches periodically"""
        while True:
            try:
                # Wait 30 minutes
                time.sleep(CACHE_UPDATE_INTERVAL)
                
                # Refresh all caches
                refresh_all_caches()
                
            except Exception as e:
                logger.error(f"Error in cache refresh worker: {e}")
                # Wait a bit before retrying
                time.sleep(60)
    
    # Start the background thread
    cache_thread = threading.Thread(target=cache_refresh_worker, daemon=True)
    cache_thread.start()
    logger.info(f"✅ Cache refresh thread started (every {CACHE_UPDATE_INTERVAL//60} minutes)")
    return cache_thread
