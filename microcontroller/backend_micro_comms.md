1. MY SYSTEM OUTPUT:

{
  "drone_id": "drone-01",
  "mission_id": null,
  "flight_controller": {
    "connected": true,
    "status": "connected",
    "flight_mode": "STABILIZE",
    "custom_mode": 0,
    "armed": false,
    "system_status": "STANDBY",
    "last_heartbeat": "2026-11-08T04:00:00Z",
    "stale": false,
    "error": null
  },
  "telemetry": {
    "latitude": 37.3352,
    "longitude": -121.8811,
    "altitude_m": 42.0,
    "speed_mps": 8.5,
    "heading_deg": 275,
    "gps_fix_type": 3,
    "satellites_visible": 12,
    "battery_pct": 91,
    "battery_voltage": 24.1,
    "battery_current": 5.2,
    "timestamp": "2026-11-08T04:00:00Z"
  },
  "readiness": {
    "ready_for_launch": false,
    "reasons": []
  }
}

2. TIMESTAMP:
"last_heartbeat": timestamp()

Does NOT match with a specific camera frame, it does NOT tell backend which camera frame was visible at the time of data


3. MICROCONTROLLER TEAM CAN CURRENTLY PROVIDE

FC connection status
Flight mode
Armed state
System status
Heartbeat timestamp
Latitude
Longitude
Relative altitude
Speed
Heading
GPS fix
Satellite count
Battery percentage
Battery voltage
Battery current
Telemetry snapshot timestamp

4. THE CAMERA SYSTEM MUST PROVIDE

Frame ID
Frame capture timestamp
Camera resolution
Camera calibration/intrinsic parameters
Bounding-box coordinates
Bounding-box confidence
Detected vehicle class

5. I WILL EXPAND MC CODE TO INCLUDE

Roll
Pitch
Yaw
Accelerometer readings
Gyroscope readings
Per-message timestamps
Frame-to-telemetry association

6.  BACKEND RECIEVES 1 UPDATE/STATE READING PER SECOND