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


async def broadcast_aircraft_update(aircraft_info):
    """Send aircraft update to all connected clients"""
    if connected_clients:
        # Use the custom encoder for datetime objects
        message = json.dumps({
            'type': 'aircraft_update',
            'data': aircraft_info
        }, cls=DateTimeEncoder)
        await asyncio.gather(
            *[client.send(message) for client in connected_clients],
            return_exceptions=True
        )


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
    if connected_clients:
        # Use the custom encoder for datetime objects
        message = json.dumps({
            'type': 'adsb_aircraft_update',
            'data': aircraft_info
        }, cls=DateTimeEncoder)
        await asyncio.gather(
            *[client.send(message) for client in connected_clients],
            return_exceptions=True
        )


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
                logger.debug(f"Sent heartbeat to {client_info}")
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
    
    # Register client
    connected_clients.add(websocket)
    
    try:
        # Send current aircraft data (OGN data)
        if aircraft_data:
            message = json.dumps({
                'type': 'aircraft_data',
                'data': list(aircraft_data.values())
            }, cls=DateTimeEncoder)  # Use custom encoder
            logger.info(f"Sending initial OGN aircraft data to {client_info}: {len(aircraft_data)} aircraft")
            await websocket.send(message)
        else:
            logger.info(f"No OGN aircraft data to send to {client_info}")
        
        # Send current ADSB aircraft data
        if adsb_aircraft_data:
            adsb_message = json.dumps({
                'type': 'adsb_aircraft_data',
                'data': list(adsb_aircraft_data.values())
            }, cls=DateTimeEncoder)
            logger.info(f"Sending initial ADSB aircraft data to {client_info}: {len(adsb_aircraft_data)} aircraft")
            await websocket.send(adsb_message)
        else:
            logger.info(f"No ADSB aircraft data to send to {client_info}")
        
        # Start heartbeat
        heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
        
        # Keep connection open and handle messages
        async for message in websocket:
            logger.info(f"Received message from {client_info}: {message[:100]}")
            
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
    # Set up the ADSB client callback to check connected clients
    set_client_count_callback(get_connected_clients_count)
    
    # Start the queue processing task
    queue_task = asyncio.create_task(process_update_queues())
    
    # Set up WebSocket server with cors headers
    logger.info(f"🚀 Starting WebSocket server on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT} with CORS support")
    async with websockets.serve(
        handle_client, 
        WEBSOCKET_HOST, 
        WEBSOCKET_PORT,
        # Add origins to allow cross-origin connections
        origins=None  # None allows all origins
    ):
        logger.info(f"✅ WebSocket server started on ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}")
        await asyncio.Future()  # Run forever
