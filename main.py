#!/usr/bin/env python3
"""
OGN Denmark Aircraft Tracker - WebSocket Relay Server

This script creates a WebSocket server that relays aircraft tracking data
from the Open Glider Network to connected clients.
"""

import asyncio
import logging
import signal
import sys

from services.db import init_database, close_database_connection
from services.ogn_client import start_ogn_threads
from services.adsb_client import start_adsb_client, stop_adsb_client
from services.websocket_server import start_websocket_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Get logger
logger = logging.getLogger("SmartGliding")


def signal_handler(sig, frame):
    """Handle keyboard interrupt and other signals"""
    logger.info("Shutdown signal received, closing connections...")
    stop_adsb_client()
    close_database_connection()
    logger.info("Server stopped")
    sys.exit(0)


async def main():
    """Main entry point"""
    try:
        # Test MongoDB connection and initialize all databases (airfields, OGN database, etc.)
        if not init_database():
            logger.error("Failed to initialize database connections")
            return
        
        # Start the OGN client threads
        ogn_thread, cleanup_thread = start_ogn_threads()
        
        # Start the ADSB client
        adsb_thread = start_adsb_client()
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Start the WebSocket server (this will run until interrupted)
        await start_websocket_server()
    except KeyboardInterrupt:
        logger.info("Server stopped by keyboard interrupt")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        # Close MongoDB connection
        stop_adsb_client()
        close_database_connection()
        logger.info("Server stopped")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Server stopped by keyboard interrupt")
