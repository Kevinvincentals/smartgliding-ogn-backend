#!/usr/bin/env python3
"""
WebSocket server module for the FLARM WebSocket Server
"""

import json
import logging
import asyncio
import websockets
from datetime import datetime

from services.config import WEBSOCKET_HOST, WEBSOCKET_PORT, aircraft_data
from services.models import DateTimeEncoder
from services.db import get_aircraft_track
from services.ogn_client import aircraft_update_queue, aircraft_removal_queue
from services.adsb_client import adsb_aircraft_queue, adsb_aircraft_data, set_client_count_callback

# Get logger
logger = logging.getLogger("plane-tracker")

# Store connected WebSocket clients
connected_clients = set()


def get_connected_clients_count():
    """Get the number of connected WebSocket clients"""
    return len(connected_clients)


def get_adsb_clients_count():
    """Get the number of clients that need ADSB data (full plane-tracker subscribers)"""
    # Count clients that want all aircraft data (like live map),
    # but not clients doing lightweight tracking
    count = 0
    for client in connected_clients:
        if hasattr(client, 'wants_all_adsb') and client.wants_all_adsb:
            count += 1
    logger.debug(f"ADSB client count check: {count} clients want ADSB")
    return count


async def broadcast_aircraft_update(aircraft_info):
    """Send aircraft update to all connected clients"""
    if not connected_clients:
        return

    aircraft_id = aircraft_info.get('id')

    # Check if any client is tracking this specific aircraft
    has_tracked_clients = any(
        hasattr(client, 'tracked_aircraft') and aircraft_id in client.tracked_aircraft
        for client in connected_clients
    )

    tasks = []

    # Only send updates for aircraft that someone is actually tracking
    if has_tracked_clients and aircraft_id:
        # Extract only essential data for lightweight tracking
        lightweight_data = {
            'id': aircraft_id,
            'latitude': aircraft_info.get('latitude'),
            'longitude': aircraft_info.get('longitude'),
            'altitude': aircraft_info.get('altitude'),
            'ground_speed': aircraft_info.get('ground_speed'),
            'track': aircraft_info.get('track'),
            'climb_rate': aircraft_info.get('climb_rate'),
            'timestamp': aircraft_info.get('timestamp')
        }
        tracked_message = json.dumps({
            'type': 'tracked_aircraft_update',
            'data': lightweight_data
        }, cls=DateTimeEncoder)

        # Send only to clients tracking this specific aircraft
        for client in connected_clients:
            if hasattr(client, 'tracked_aircraft') and aircraft_id in client.tracked_aircraft:
                tasks.append(client.send(tracked_message))

    # Only send full OGN updates to clients that explicitly want them
    full_message = json.dumps({
        'type': 'aircraft_update',
        'data': aircraft_info
    }, cls=DateTimeEncoder)

    for client in connected_clients:
        # Only send full aircraft updates if the client has explicitly subscribed to general tracking
        if hasattr(client, 'wants_all_aircraft') and client.wants_all_aircraft:
            tasks.append(client.send(full_message))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def broadcast_aircraft_removed(removed_info):
    """Send aircraft removed notification to all connected clients"""
    if connected_clients:
        message = json.dumps({
            'type': 'aircraft_removed',
            'data': removed_info
        }, cls=DateTimeEncoder)
        await asyncio.gather(
            *[client.send(message) for client in connected_clients],
            return_exceptions=True
        )


async def broadcast_adsb_aircraft_update(aircraft_info):
    """Send ADSB aircraft update to all connected clients"""
    if not connected_clients:
        return

    aircraft_id = aircraft_info.get('aircraft_id') or aircraft_info.get('id')

    # Check if any client is tracking this specific aircraft
    has_tracked_clients = any(
        hasattr(client, 'tracked_aircraft') and aircraft_id in client.tracked_aircraft
        for client in connected_clients
    )

    tasks = []

    # Only send updates for aircraft that someone is actually tracking
    if has_tracked_clients and aircraft_id:
        # Extract only essential data for lightweight tracking
        lightweight_data = {
            'id': aircraft_id,
            'latitude': aircraft_info.get('latitude'),
            'longitude': aircraft_info.get('longitude'),
            'altitude': aircraft_info.get('altitude'),
            'ground_speed': aircraft_info.get('ground_speed'),
            'track': aircraft_info.get('track'),
            'vertical_rate': aircraft_info.get('vertical_rate'),
            'timestamp': aircraft_info.get('timestamp')
        }
        tracked_message = json.dumps({
            'type': 'tracked_aircraft_update',
            'data': lightweight_data
        }, cls=DateTimeEncoder)

        # Send only to clients tracking this specific aircraft
        for client in connected_clients:
            if hasattr(client, 'tracked_aircraft') and aircraft_id in client.tracked_aircraft:
                tasks.append(client.send(tracked_message))

    # Only send full ADSB updates to clients that explicitly want them
    # (Don't send to clients that haven't made any subscription requests)
    full_message = json.dumps({
        'type': 'adsb_aircraft_update',
        'data': aircraft_info
    }, cls=DateTimeEncoder)

    for client in connected_clients:
        # Only send full ADSB updates if the client has explicitly subscribed to general tracking
        # Don't send to clients that are just connecting or haven't made subscription requests
        if hasattr(client, 'wants_all_adsb') and client.wants_all_adsb:
            tasks.append(client.send(full_message))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def broadcast_adsb_aircraft_removed(removed_info):
    """Send ADSB aircraft removed notification to all connected clients"""
    if connected_clients:
        message = json.dumps({
            'type': 'adsb_aircraft_removed',
            'data': removed_info
        }, cls=DateTimeEncoder)
        await asyncio.gather(
            *[client.send(message) for client in connected_clients],
            return_exceptions=True
        )


async def send_heartbeat(websocket):
    """Send periodic heartbeat message"""
    try:
        client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
        client_port = websocket.remote_address[1] if websocket.remote_address else 0
        client_info = f"{client_ip}:{client_port}"
        
        while True:
            try:
                # Check if the connection is still open by sending a message
                await websocket.send("Connected to plane tracker")
                await asyncio.sleep(5)
            except websockets.exceptions.ConnectionClosed:
                logger.info(f"Client {client_info} no longer connected, stopping heartbeat")
                break
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Connection closed while sending heartbeat")
    except Exception as e:
        logger.error(f"Error in heartbeat: {e}")
        import traceback
        logger.error(traceback.format_exc())


async def handle_client(websocket):
    """Handle WebSocket client connection"""
    global connected_clients

    # Log the remote address
    client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
    client_port = websocket.remote_address[1] if websocket.remote_address else 0
    client_info = f"{client_ip}:{client_port}"
    logger.info(f"New client connected: {client_info}")

    # Register client with tracking info
    connected_clients.add(websocket)
    # Store tracked aircraft IDs for this client
    websocket.tracked_aircraft = set()
    
    try:
        # Send current aircraft data (OGN data)
        if aircraft_data:
            message = json.dumps({
                'type': 'aircraft_data',
                'data': list(aircraft_data.values())
            }, cls=DateTimeEncoder)  # Use custom encoder
            await websocket.send(message)

        # Send current ADSB aircraft data
        if adsb_aircraft_data:
            adsb_message = json.dumps({
                'type': 'adsb_aircraft_data',
                'data': list(adsb_aircraft_data.values())
            }, cls=DateTimeEncoder)
            await websocket.send(adsb_message)
        # Start heartbeat
        heartbeat_task = asyncio.create_task(send_heartbeat(websocket))

        # Keep connection open and handle messages
        async for message in websocket:
            # Try to parse JSON messages
            try:
                data = json.loads(message)
                message_type = data.get('type')

                # Handle track request
                if message_type == 'track_request':
                    aircraft_id = data.get('aircraft_id')
                    if aircraft_id:
                        track_data = get_aircraft_track(aircraft_id)
                        track_message = json.dumps({
                            'type': 'aircraft_track',
                            'data': track_data
                        }, cls=DateTimeEncoder)  # Use custom encoder
                        await websocket.send(track_message)

                # Handle lightweight tracking subscription
                elif message_type == 'subscribe_aircraft':
                    aircraft_ids = data.get('aircraft_ids', [])
                    if isinstance(aircraft_ids, str):
                        aircraft_ids = [aircraft_ids]
                    for aircraft_id in aircraft_ids:
                        websocket.tracked_aircraft.add(aircraft_id)
                        # Send current data for this aircraft if available
                        if aircraft_id in aircraft_data:
                            await websocket.send(json.dumps({
                                'type': 'tracked_aircraft_update',
                                'data': aircraft_data[aircraft_id]
                            }, cls=DateTimeEncoder))
                    await websocket.send(json.dumps({
                        'type': 'subscription_confirmed',
                        'aircraft_ids': list(websocket.tracked_aircraft)
                    }))

                # Handle unsubscribe from aircraft
                elif message_type == 'unsubscribe_aircraft':
                    aircraft_ids = data.get('aircraft_ids', [])
                    if isinstance(aircraft_ids, str):
                        aircraft_ids = [aircraft_ids]
                    for aircraft_id in aircraft_ids:
                        websocket.tracked_aircraft.discard(aircraft_id)
                    await websocket.send(json.dumps({
                        'type': 'unsubscription_confirmed',
                        'aircraft_ids': aircraft_ids
                    }))

                # Handle subscription to all aircraft updates
                elif message_type == 'subscribe_all':
                    websocket.wants_all_aircraft = True
                    logger.info(f"Client {client_info} subscribed to all aircraft updates")
                    await websocket.send(json.dumps({
                        'type': 'subscription_confirmed',
                        'message': 'Subscribed to all aircraft updates'
                    }))

                # Handle ADSB preference from Next.js proxy
                elif message_type == 'client_wants_adsb':
                    wants_adsb = data.get('wants_adsb', False)
                    websocket.wants_all_adsb = wants_adsb
                    logger.info(f"Client {client_info} ADSB preference set to: {wants_adsb}")
                    logger.info(f"Total ADSB clients now: {get_adsb_clients_count()}")
            except json.JSONDecodeError:
                logger.warning(f"Received non-JSON message from client")
            except Exception as e:
                logger.error(f"Error handling client message: {e}")
            
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client disconnected: {client_info}")
    except Exception as e:
        logger.error(f"Error in client handler for {client_info}: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # Unregister client and cancel tasks
        if websocket in connected_clients:
            connected_clients.remove(websocket)
        logger.info(f"Removed client {client_info}, remaining clients: {len(connected_clients)}")


async def process_update_queues():
    """Process the aircraft update and removal queues"""
    while True:
        # Process OGN aircraft updates
        while not aircraft_update_queue.empty():
            try:
                update = aircraft_update_queue.get_nowait()
                await broadcast_aircraft_update(update)
                aircraft_update_queue.task_done()
            except Exception as e:
                logger.error(f"Error processing OGN aircraft update: {e}")
                break
        
        # Process OGN aircraft removals
        while not aircraft_removal_queue.empty():
            try:
                removal = aircraft_removal_queue.get_nowait()
                await broadcast_aircraft_removed(removal)
                aircraft_removal_queue.task_done()
            except Exception as e:
                logger.error(f"Error processing OGN aircraft removal: {e}")
                break
        
        # Process ADSB aircraft updates and removals
        while not adsb_aircraft_queue.empty():
            try:
                adsb_update = adsb_aircraft_queue.get_nowait()
                if adsb_update['type'] == 'update':
                    # Send ADSB aircraft update
                    await broadcast_adsb_aircraft_update(adsb_update['data'])
                elif adsb_update['type'] == 'remove':
                    # Send ADSB aircraft removal
                    await broadcast_adsb_aircraft_removed(adsb_update['data'])
                adsb_aircraft_queue.task_done()
            except Exception as e:
                logger.error(f"Error processing ADSB aircraft update: {e}")
                break
        
        # Small delay to prevent CPU hogging
        await asyncio.sleep(0.1)


async def start_websocket_server():
    """Start the WebSocket server"""
    # Set up the ADSB client callback to check for clients that need ADSB data
    set_client_count_callback(get_adsb_clients_count)
    
    # Start the queue processing task
    queue_task = asyncio.create_task(process_update_queues())
    
    # Set up WebSocket server with cors headers
    logger.info(f"Starting WebSocket server on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
    async with websockets.serve(
        handle_client, 
        WEBSOCKET_HOST, 
        WEBSOCKET_PORT,
        # Add origins to allow cross-origin connections
        origins=None  # None allows all origins
    ):
        logger.info(f"WebSocket server started successfully")
        await asyncio.Future()  # Run forever
