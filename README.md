# SmartGliding OGN Backend

## 🇩🇰 Dansk

### Hvad er dette?

SmartGliding OGN Backend er en tjeneste der fungere sammen med SmartGliding web applikationen, der automatisk sporer svævefly og andre luftfartøjer i Danmark i realtid. Systemet kan automatisk registrere:

- **🛫 Start** - Når et fly letter fra en flyveplads
- **🛬 Landing** - Når et fly lander på en flyveplads  
- **🪂 Start-type** - Om det er spilstart eller slæb
- **📍 Position** - Kontinuerlig GPS-tracking af fly i luften

### Hvorfor er dette nødvendigt?

Mange svæveflyverklubber har brug for at:
- Automatisk logge starter og landinger i deres flyvebøger
- Overvåge flyaktivitet på deres flyveplads i realtid
- Se hvor klubbens fly befinder sig på et live-kort
- Få automatisk besked når fly starter eller lander


## 🇬🇧 English

### What is this?

SmartGliding OGN Backend is a service that automatically tracks gliders and other aircraft in Denmark in real-time. The system can automatically detect:

- **🛫 Takeoffs** - When an aircraft departs from an airfield
- **🛬 Landings** - When an aircraft lands at an airfield
- **🪂 Launch types** - Whether it's winch launch or aerotow
- **📍 Position** - Continuous GPS tracking of aircraft in flight

### Why is this needed?

Many gliding clubs need to:
- Automatically log takeoffs and landings in their flight logbooks
- Monitor flight activity at their airfield in real-time
- See where club aircraft are located on a live map
- Get automatic notifications when aircraft take off or land

Previously, all of this had to be done manually, which was time-consuming and error-prone. This system automates the entire process by listening to FLARM signals from the Open Glider Network (OGN).

## 🏗️ Technical Architecture

### Core Components

- **OGN Client** - Connects to Open Glider Network for FLARM data
- **ADSB Client** - Fetches additional aircraft data from ADSB.lol API
- **Flight Event Detection** - Intelligent takeoff/landing detection
- **WebSocket Server** - Real-time data streaming to clients
- **MongoDB Integration** - Data storage and caching
- **Cache Management** - Efficient club planes and airfield caching

### Data Sources

1. **Open Glider Network (OGN)** - Primary source for FLARM-equipped aircraft
2. **ADSB.lol API** - Secondary source for transponder-equipped aircraft
3. **Danish Airfields Database** - Automated fetching from external API
4. **OGN Device Database** - Aircraft registration and model information

### Event Detection

The system intelligently detects:
- **Takeoffs**: Speed > 30 km/h AND altitude > 20m
- **Landings**: Speed < 40 km/h AND altitude < 100m
- **Launch Types**: 
  - Winch launch (single aircraft)
  - Aerotow (glider + tow plane detected together)
- **Airfield Association**: Automatic nearest airfield detection

## 🚀 Features

### Real-time Tracking
- Live aircraft positions via WebSocket
- Automatic aircraft state management
- Client connection monitoring
- Data cleanup for inactive aircraft

### Smart Filtering
- **Club Aircraft Only**: Only stores data for registered club planes
- **Registered Airfields**: Only logs events at registered club airfields
- **Geographic Filtering**: Currently hardcoded for Denmark region
- **Speed Filtering**: Ignores stationary aircraft

### Performance Optimization
- **Batch Database Operations**: Efficient bulk inserts/updates
- **Smart Caching**: 30-minute refresh cycle for all caches
- **Progress Bars**: Visual feedback during data imports
- **Background Processing**: Non-blocking cache updates

### Integration Capabilities
- **WebSocket API**: Real-time data streaming
- **MongoDB Storage**: Scalable data persistence
- **Webhook Support**: External system notifications
- **RESTful Patterns**: Standard data access patterns

## ⚙️ Configuration

### Geographic Region (Currently Hardcoded)

```python
# Denmark configuration
DENMARK_CENTER_LAT = 55.923624
DENMARK_CENTER_LON = 9.755859
DENMARK_RADIUS_KM = 195
```

*Note: Geographic filtering is currently hardcoded for Denmark. Future versions will make this configurable.*


### Database Collections

- `flarm_data` - Aircraft position data
- `flight_events` - Takeoff/landing events
- `planes` - Club aircraft registry
- `clubs` - Club information and homefields
- `dk_airfields` - Danish airfields database
- `ogn-database` - OGN device registry

## 📡 WebSocket API

### Connection
```
ws://localhost:8765
```

### Message Types

#### Outbound (Server → Client)
```json
{
  "type": "aircraft_data",
  "data": [/* array of aircraft */]
}

{
  "type": "aircraft_update", 
  "data": {/* single aircraft update */}
}

{
  "type": "aircraft_removed",
  "data": {"id": "FLRXXXXXX"}
}

{
  "type": "adsb_aircraft_update",
  "data": {/* ADSB aircraft data */}
}
```

#### Inbound (Client → Server)
```json
{
  "type": "track_request",
  "aircraft_id": "FLRXXXXXX"
}
```

### Response
```json
{
  "type": "aircraft_track",
  "data": [/* historical positions */]
}
```

## 🚧 Current Limitations & Future Work

### Hardcoded Elements
- **Geographic Region**: Denmark coordinates are hardcoded
- **Airfield Sources**: Fixed API endpoints
- **Detection Thresholds**: Flight event detection parameters
- **Webhook URLs**: Currently hardcoded endpoint

### Known Issues
- Code cleanup needed in several modules
- Better error handling required
- Configuration should be externalized
- Documentation needs expansion

### Planned Features
- Configurable geographic regions
- Multiple country support
- Advanced launch detection algorithms
- Enhanced webhook customization
## 🐳 Docker Deployment

**Important**: This service is designed to run as an **internal backend service**. For a complete deployment including the web frontend, database, and all related services, please visit:

**👉 [SmartGliding Web GitHub Repository](https://github.com/Kevinvincentals/smartgliding-web)**

The web repository contains a complete `docker-compose.yml` that orchestrates all services together.

### Standalone Docker Build
```bash
docker build -t smartgliding-ogn-backend .
docker run -d \
  --name smartgliding-backend \
  -p 8765:8765 \
  -e DATABASE_URL=mongodb://mongo:27017/smartgliding \
  smartgliding-ogn-backend
```

## 🔧 Development

### Requirements
- Python 3.11+
- MongoDB
- Internet connection (for OGN and ADSB data)

### Local Setup
```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your configuration
python main.py
```

### Cache Management
The system automatically refreshes caches every 30 minutes:
- Club aircraft FLARM IDs
- Registered club homefields
- All background processes are managed automatically


## ⚠️ Important Notes

- **Work in Progress**: This project is under active development
- **Breaking Changes**: Expect significant changes in future versions
- **Internal Service**: WebSocket server is designed for internal network use
- **Security**: No authentication implemented! Local use only
- **Performance**: Optimized for club scale operations (not national scale)

## 🤝 Contributing

This is an open-source project for SmartGliding. Contributions, issues, and feature requests are welcome!

Feel free to check the [issues page](https://github.com/Kevinvincentals/smartgliding-ogn-backend/issues) if you want to contribute.

## 📄 License

**MIT License** ✅

```
MIT License

Copyright (c) 2024-2025 Kevin Vincent Als <kevin@connect365.dk>
SmartGliding - Digital tool for soaring clubs

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Why MIT License?

✅ **Permissions**: Allows reuse, modification, and commercial use with minimal restrictions

✅ **Requirements**: Must include the original license and copyright notice

✅ **Best For**: Projects where you want to maximize adoption and don't care if others use your code in proprietary software

✅ **Perfect For**: Open source projects that want maximum flexibility and adoption

### Usage Rights

- ✅ **Commercial use** - Use for commercial purposes
- ✅ **Modification** - Modify and create derivative works
- ✅ **Distribution** - Distribute original or modified versions
- ✅ **Private use** - Use privately without restrictions
- ✅ **Patent use** - Grant of patent rights from contributors

### Requirements

- 📋 **License and copyright notice** - Include in all copies or substantial portions
- 📋 **State changes** - Document significant changes made to the software

---

*Last updated: June 2025* 