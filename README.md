# Plane Tracker

A WebSocket relay server for aircraft tracking data from the Open Glider Network (OGN).

## Code Structure

The application has been modularized into the following components:

### `main.py`
The entry point for the application that initializes all services and handles signals.

### `services/` Directory

#### `config.py`
Contains all configuration settings for the application:
- MongoDB connection settings
- Geographic regions (Denmark and Frankfurt)
- FLARM database settings
- WebSocket server settings 
- Caching parameters

#### `db.py`
Database operations including:
- MongoDB connection handling
- Club plane caching (updated every 30 minutes)
- Aircraft position storage
- Flight tracking functionality

#### `flarm_database.py`
Handles FLARM device database operations:
- Downloading device information from ddb.glidernet.org
- Parsing and storing device data
- Lookup functionality for device details

#### `flight_events.py`
Detects and logs takeoffs and landings:
- Tracks aircraft state changes
- Identifies when aircraft take off or land
- Detects tow plane takeoffs with gliders
- Logs events to a JSON file

#### `ogn_client.py`
Processes data from the Open Glider Network:
- Connects to OGN's APRS servers
- Processes incoming aircraft beacons
- Updates aircraft data
- Cleans up stale aircraft data
- Triggers flight event detection

#### `websocket_server.py`
Manages WebSocket connections:
- Client connection handling
- Broadcasting updates to connected clients
- Handling track requests
- Processing update queues

#### `models.py`
Contains data models and serialization:
- JSON encoding for datetime objects
- Helper functions for serializing MongoDB data

#### `utils.py`
Utility functions:
- Aircraft type detection from APRS symbols
- Geographic distance calculations
- Logging configuration

## Configuration

### Environment Variables

The application uses the following environment variables:

- `DATABASE_URL`: MongoDB connection string (**required**)
- `FLARM_DB_FILE`: Location of the FLARM database file (default: "flarm-database.csv")
- `EVENTS_FILE`: Location of the flight events JSON file (default: "flight_events.json")
- `MONGO_INITDB_DATABASE`: MongoDB initial database name (for Docker setup)

### Geographic Regions

The application monitors aircraft in two regions:

1. **Denmark:**
   - Center: 55.923624, 9.755859
   - Radius: 195 km

2. **Frankfurt:**
   - Center: 50.110980, 8.664145  
   - Radius: 120 km

These are configured in `services/config.py` and can be modified if needed.

### Flight Events Detection

The application detects and logs the following events:

- **Takeoffs**: When an aircraft reaches a speed of 30 km/h and altitude of 40m
- **Landings**: When an aircraft drops below 30 km/h and altitude of 100m
- **Tow Takeoffs**: When a glider and tow plane take off in close proximity

Events are stored in a JSON file with the following format:
```json
{
  "type": "takeoff|landing|tow_takeoff",
  "origin": "fsk-flarm-tracker",
  "airfield": "UNKNOWN",
  "id": "FLRXXXXXX",
  "aircraft_type": "Glider",
  "aircraft_model": "ASK 21",
  "registration": "OY-XYZ",
  "timestamp": "2023-05-08T09:29:45.282915Z"
}
```

### Caching

- Club plane information is cached and refreshed every 30 minutes
- Aircraft are removed from active tracking after 5 minutes of inactivity

### WebSocket Server

- Listens on: 0.0.0.0:8765
- Sends heartbeat messages every 5 seconds
- Provides real-time aircraft updates and responds to track requests

## Docker Setup

### Prerequisites

- Docker
- Docker Compose

### Environment Setup

1. Copy the example environment file:
```bash
cp .env.example .env
```

2. Edit the `.env` file to set your environment variables

### Running with Docker Compose

1. Clone this repository
2. Navigate to the project directory
3. Set up environment variables (see above)
4. Run the application:

```bash
docker-compose up -d
```

This will:
- Build the plane-tracker container
- Start a MongoDB instance
- Connect the plane-tracker to MongoDB
- Expose the WebSocket server on port 8765

### Accessing the WebSocket Server

The WebSocket server will be available at:

```
ws://localhost:8765
```

### Viewing logs

```bash
docker-compose logs -f plane-tracker
```

### Stopping the application

```bash
docker-compose down
```

## Data Persistence

Data is stored in Docker volumes:
- `data-volume`: Stores the FLARM database
- `mongo-data`: Stores MongoDB data 
- `events-volume`: Stores flight events data

## WebSocket API

The WebSocket server provides the following message types:

- `aircraft_data`: Initial data with all currently tracked aircraft
- `aircraft_update`: Real-time updates for individual aircraft
- `aircraft_removed`: Notification when aircraft are no longer being tracked
- `aircraft_track`: Historical track data in response to track requests

To request historical track data for an aircraft, send:
```json
{
  "type": "track_request",
  "aircraft_id": "FLRXXXXXX"
}
```

### For Coolify Deployment

When deploying with Coolify:

1. Create a new service using the Dockerfile
2. Set the required environment variables in the Coolify dashboard
3. No need to modify the Dockerfile as environment variables are injected at runtime 