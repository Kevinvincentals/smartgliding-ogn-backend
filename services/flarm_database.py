#!/usr/bin/env python3
"""
OGN Database handling for the WebSocket Server
"""

import logging
import requests
import csv
import sys
from datetime import datetime
from io import StringIO

from services.db import mongo_client, db

# Get logger
logger = logging.getLogger("plane-tracker")

# OGN database collection
ogn_database_collection = db["ogn-database"]

# OGN database settings
OGN_DB_URL = "https://ddb.glidernet.org/download/"


def _print_progress_bar(current, total, prefix="Progress", suffix="", length=50, created=0, updated=0, unchanged=0):
    """Print a progress bar with statistics"""
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


def fetch_and_update_ogn_database():
    """Fetch OGN database from external URL and update MongoDB"""
    try:
        logger.info("🌐 Fetching OGN database...")
        
        # Download the database
        response = requests.get(OGN_DB_URL, timeout=30)
        response.raise_for_status()
        
        content = response.text
        
        # Parse the CSV content first to get total count
        reader = csv.reader(StringIO(content), delimiter=',', quotechar="'")
        all_rows = []
        for row in reader:
            # Skip header rows (starting with #) and invalid rows
            if len(row) >= 7 and not row[0].startswith('#'):
                device_id = row[1].strip("'")
                # Only include rows with valid device IDs (not header text)
                if device_id and device_id != 'DEVICE_ID':
                    all_rows.append(row)
        
        total_rows = len(all_rows)
        logger.info(f"Processing {total_rows} OGN entries...")
        
        # Pre-load existing records for faster comparison
        existing_records = {}
        for record in ogn_database_collection.find({}, {"deviceId": 1, "deviceType": 1, "aircraftModel": 1, "registration": 1, "cn": 1, "tracked": 1, "identified": 1}):
            device_id = record.get("deviceId")
            if device_id:
                existing_records[device_id] = {
                    "deviceType": record.get("deviceType"),
                    "deviceId": device_id,
                    "aircraftModel": record.get("aircraftModel"),
                    "registration": record.get("registration"),
                    "cn": record.get("cn"),
                    "tracked": record.get("tracked"),
                    "identified": record.get("identified")
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
        batch_size = 1000  # Process in batches of 1000
        progress_interval = max(1, total_rows // 100)  # Update progress bar every 1%
        
        # Initial progress bar
        _print_progress_bar(0, total_rows, "OGN Database", "", 50, created_count, updated_count, unchanged_count)
        
        for row in all_rows:
            try:
                processed_count += 1
                
                # Show progress
                if processed_count % progress_interval == 0 or processed_count == total_rows:
                    _print_progress_bar(processed_count, total_rows, "OGN Database", "", 50, created_count, updated_count, unchanged_count)
                
                # Parse the row data
                device_type = row[0].strip("'")
                device_id = row[1].strip("'")
                aircraft_model = row[2].strip("'") if row[2].strip("'") else None
                registration = row[3].strip("'") if row[3].strip("'") else None
                cn = row[4].strip("'") if row[4].strip("'") else None
                tracked = row[5].strip("'") == 'Y'
                identified = row[6].strip("'") == 'Y'
                
                if not device_id:
                    error_count += 1
                    continue  # Skip if no device ID
                
                # Prepare the new document data (excluding timestamps)
                new_data = {
                    "deviceType": device_type,
                    "deviceId": device_id,
                    "aircraftModel": aircraft_model,
                    "registration": registration,
                    "cn": cn,
                    "tracked": tracked,
                    "identified": identified
                }
                
                # Check if record exists and if it has changed
                existing_data = existing_records.get(device_id)
                
                if existing_data:
                    # Check if there are any actual changes
                    if existing_data == new_data:
                        unchanged_count += 1
                        continue  # No changes, skip update
                    
                    # Data has changed, prepare for batch update
                    update_doc = new_data.copy()
                    update_doc["updatedAt"] = datetime.now()
                    
                    batch_updates.append({
                        "filter": {"deviceId": device_id},
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
                    _execute_batch_updates(batch_updates)
                    batch_updates = []
                
                if len(batch_inserts) >= batch_size:
                    _execute_batch_inserts(batch_inserts)
                    batch_inserts = []
                    
            except Exception as e:
                logger.error(f"Error processing OGN device row: {e}")
                error_count += 1
        
        # Process remaining batches
        if batch_updates:
            _execute_batch_updates(batch_updates)
        
        if batch_inserts:
            _execute_batch_inserts(batch_inserts)
        
        # Create index for efficient lookups (only if collection has data)
        if created_count > 0 or updated_count > 0:
            ogn_database_collection.create_index("deviceId", unique=True)
        
        # Consolidated final message with checkmark
        total_changes = created_count + updated_count
        if total_changes > 0:
            logger.info(f"✅ OGN database: {created_count} created, {updated_count} updated, {unchanged_count} unchanged")
        else:
            logger.info(f"✅ OGN database: {unchanged_count} entries, no changes needed")
        
        return True
        
    except requests.RequestException as e:
        logger.error(f"Failed to fetch OGN database: {e}")
        return False
    except Exception as e:
        logger.error(f"Error updating OGN database: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def _execute_batch_updates(batch_updates):
    """Execute batch updates using bulk_write"""
    try:
        if not batch_updates:
            return
        
        from pymongo import UpdateOne
        operations = [UpdateOne(update["filter"], update["update"]) for update in batch_updates]
        
        result = ogn_database_collection.bulk_write(operations, ordered=False)
        logger.debug(f"Batch updated {result.modified_count} records")
        
    except Exception as e:
        logger.error(f"Error in batch updates: {e}")


def _execute_batch_inserts(batch_inserts):
    """Execute batch inserts"""
    try:
        if not batch_inserts:
            return
        
        result = ogn_database_collection.insert_many(batch_inserts, ordered=False)
        logger.debug(f"Batch inserted {len(result.inserted_ids)} records")
        
    except Exception as e:
        logger.error(f"Error in batch inserts: {e}")


def get_flarm_info(device_id):
    """Get FLARM/OGN device information from the database"""
    try:
        # Remove the 'FLR' prefix if present
        if device_id and device_id.startswith('FLR'):
            device_id = device_id[3:]
        
        if not device_id:
            return None
        
        # Query the database for the device
        device_info = ogn_database_collection.find_one({"deviceId": device_id})
        
        if not device_info:
            return None
        
        # Return in the expected format for backward compatibility
        return {
            'device_type': device_info.get('deviceType'),
            'aircraft_model': device_info.get('aircraftModel'),
            'registration': device_info.get('registration'),
            'competition_number': device_info.get('cn'),
            'tracked': device_info.get('tracked', False),
            'identified': device_info.get('identified', False)
        }
        
    except Exception as e:
        logger.error(f"Error retrieving OGN device info for {device_id}: {e}")
        return None


def get_ogn_device_by_registration(registration):
    """Get OGN device information by registration"""
    try:
        device_info = ogn_database_collection.find_one({"registration": registration})
        if device_info and "_id" in device_info:
            device_info["_id"] = str(device_info["_id"])
        return device_info
    except Exception as e:
        logger.error(f"Error retrieving OGN device for registration {registration}: {e}")
        return None


def get_ogn_device_by_competition_number(cn):
    """Get OGN device information by competition number"""
    try:
        device_info = ogn_database_collection.find_one({"cn": cn})
        if device_info and "_id" in device_info:
            device_info["_id"] = str(device_info["_id"])
        return device_info
    except Exception as e:
        logger.error(f"Error retrieving OGN device for CN {cn}: {e}")
        return None


# Legacy function names for backward compatibility
download_flarm_database = fetch_and_update_ogn_database
