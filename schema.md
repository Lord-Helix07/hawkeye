# HawkEye Data Schema — MVP

## Architecture decision

The HawkEye MVP will use **five DynamoDB tables** and **one S3 bucket**.

There will be **zero SQL tables in the MVP**. HawkEye's operational data is mostly event-based and needs fast writes, flexible fields, and low-latency reads during a pursuit. DynamoDB fits those requirements better than a relational database. S3 will hold large files such as images, video clips, and system logs; DynamoDB will store the metadata and S3 object locations.

| Storage | Count | Used for |
|---|---:|---|
| DynamoDB | 5 tables | Live operational data and queryable metadata |
| S3 | 1 bucket | Images, video, and log files |
| SQL database | 0 tables | Not required for the MVP |

## AWS data flow

```text
Drone / Operator Website
        |
        v
   API Gateway
        |
        v
      Lambda --------------> S3
        |                  images, video, logs
        v
    DynamoDB
 drones, telemetry, missions, alerts, media metadata
```

## DynamoDB tables

### 1. `Drones`

Stores one latest-known state record per drone. Historical readings belong in Telemetry.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `drone_id` | String | Partition key | Unique drone ID |
| `availability_status` | String | No | `AVAILABLE` or `UNAVAILABLE` |
| `connection_status` | String | No | `CONNECTED`, `DEGRADED`, or `DISCONNECTED` |
| `flight_status` | String | No | `IDLE`, `TAKEOFF`, `TRACKING`, `RETURNING`, or `LANDED` |
| `current_mission_id` | String or Null | No | Assigned mission, if any |
| `location` | Map or Null | No | Contains latitude, longitude, and altitude |
| `location.latitude` | Number | No | Latitude in degrees, -90 to 90 |
| `location.longitude` | Number | No | Longitude in degrees, -180 to 180 |
| `location.altitude` | Number | No | Altitude; units/reference follow the agreed convention |
| `battery_percent` | Number | No | Battery percentage, 0–100 |
| `last_seen_at` | String or Null | No | UTC time of the last received observation |
| `speed` | Number or Null | No | Latest speed; proposed unit is meters per second |
| `manual_override` | Boolean | No | Reported pilot override state; does not itself transfer control |

**How AWS uses it:** Lambda reads current drone state for the dashboard and updates it when new observations arrive. Mission assignment must remain consistent with the corresponding Missions record.

### 2. `Telemetry`

Stores the drone's frequently changing flight and tracking data.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `drone_id` | String | Partition key | Identifies the drone sending the reading |
| `timestamp` | String | Sort key | UTC time when the reading was recorded |
| `event_id` | String | No | Unique ID for the telemetry event |
| `mission_id` | String | No | Pursuit/mission connected to the reading |
| `location` | Map or Null | No | Contains latitude, longitude, and altitude |
| `location.latitude` | Number | No | Latitude in degrees, -90 to 90 |
| `location.longitude` | Number | No | Longitude in degrees, -180 to 180 |
| `location.altitude` | Number | No | Altitude; units/reference follow the agreed convention |
| `speed` | Number | No | Drone speed in meters per second |
| `battery_percent` | Number | No | Remaining battery percentage |
| `connection_status` | String | No | `CONNECTED`, `DEGRADED`, or `DISCONNECTED` |
| `flight_status` | String | No | `IDLE`, `TAKEOFF`, `TRACKING`, `RETURNING`, or `LANDED` |
| `heading` | Number | No | Degrees clockwise from north, 0 inclusive to 360 exclusive |

**How AWS uses it:** Lambda validates and writes telemetry received through API Gateway. The operator website reads the latest records to display location, speed, battery, and connection status. A future TTL can automatically remove old high-frequency records after the retention period.

### 3. `Missions`

Stores one record for each pursuit or drone deployment.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `mission_id` | String | Partition key | Unique ID for the pursuit mission |
| `created_at` | String | No | Mission creation time |
| `status` | String | No | `PLANNED`, `ACTIVE`, `COMPLETED`, `ABORTED`, or `FAILED` |
| `drone_id` | String | No | Drone assigned to the mission |
| `target_vehicle_id` | String | No | Vehicle currently being tracked |
| `start_location` | Map | No | Mission starting coordinates |
| `start_location.latitude` | Number | No | Latitude in degrees |
| `start_location.longitude` | Number | No | Longitude in degrees |
| `end_location` | Map | No | Final or last-known coordinates |
| `end_location.latitude` | Number | No | Latitude in degrees |
| `end_location.longitude` | Number | No | Longitude in degrees |
| `started_at` | String | No | Time the drone launched |
| `ended_at` | String | No | Time the mission ended |
| `operator_id` | String | No | Operator who started or managed it |
| `termination_reason` | String | No | Why the mission ended or was aborted |
| `target_vehicle` | Map or Null | No | Target description and tracking state |
| `target_vehicle.make` | String | No | Vehicle manufacturer |
| `target_vehicle.model` | String | No | Vehicle model |
| `target_vehicle.color` | String | No | Vehicle color |
| `target_vehicle.license_plate` | String | No | Vehicle license plate |
| `target_vehicle.drone_track_id` | Number (integer) | No | Track identifier from the drone camera |
| `target_vehicle.camera_track_id` | Number (integer) | No | Track identifier from the source camera |
| `target_vehicle.tracking_status` | String | No | Target tracking state; allowed values need team agreement |
| `target_vehicle.estimated_location` | Map or Null | No | Estimated target coordinates |
| `target_vehicle.estimated_location.latitude` | Number | No | Latitude in degrees |
| `target_vehicle.estimated_location.longitude` | Number | No | Longitude in degrees |
| `target_vehicle.last_known_location` | Map or Null | No | Last known target coordinates |
| `target_vehicle.last_known_location.latitude` | Number | No | Latitude in degrees |
| `target_vehicle.last_known_location.longitude` | Number | No | Longitude in degrees |
| `target_vehicle.suggested_match` | Map or Null | No | Candidate match awaiting confirmation |
| `target_vehicle.suggested_match.camera_id` | String | No | Camera identifier for the candidate |
| `target_vehicle.suggested_match.track_id` | Number (integer) | No | Candidate track identifier |
| `target_vehicle.suggested_match.box_position` | Map | No | Bounding box; coordinate convention requires team agreement |
| `target_vehicle.suggested_match.box_position.x` | Number | No | Horizontal box position |
| `target_vehicle.suggested_match.box_position.y` | Number | No | Vertical box position |
| `target_vehicle.suggested_match.box_position.width` | Number | No | Box width |
| `target_vehicle.suggested_match.box_position.height` | Number | No | Box height |
| `target_vehicle.suggested_match.confidence` | Number | No | Candidate confidence from 0 to 1 |
| `target_vehicle.match_confirmed` | Boolean | No | Whether the proposed match was confirmed |
| `target_selection` | Map or Null | No | Officer selection details; |
| `target_selection.camera_id` | String | No | Camera providing the selection frame |
| `target_selection.frame_id` | Number (integer) | No | Frame identifier |
| `target_selection.timestamp` | String | No | UTC time of the selection frame |
| `target_selection.detected_cars` | List | No | Detected candidate vehicle objects |
| `target_selection.detected_cars[].camera_id` | String | No | Camera identifier for the candidate |
| `target_selection.detected_cars[].track_id` | Number (integer) | No | Candidate track identifier |
| `target_selection.detected_cars[].box_position` | Map | No | Bounding box; coordinate convention requires team agreement |
| `target_selection.detected_cars[].box_position.x` | Number | No | Horizontal box position |
| `target_selection.detected_cars[].box_position.y` | Number | No | Vertical box position |
| `target_selection.detected_cars[].box_position.width` | Number | No | Box width |
| `target_selection.detected_cars[].box_position.height` | Number | No | Box height |
| `target_selection.detected_cars[].confidence` | Number | No | Candidate confidence from 0 to 1 |
| `target_selection.selected_camera_track_id` | Number (integer) | No | Track selected by the operator |
| `request_location` | Map or Null | No | Location when the mission was requested:|
| `request_location.latitude` | Number | No | Latitude in degrees, -90 to 90 |
| `request_location.longitude` | Number | No | Longitude in degrees, -180 to 180 |
| `recovery_location` | Map or Null | No | Intended recovery coordinates |
| `recovery_location.latitude` | Number | No | Latitude in degrees, -90 to 90 |
| `recovery_location.longitude` | Number | No | Longitude in degrees, -180 to 180 |
| `return_route` | List or Null | No | Ordered list of coordinate maps | 
| `return_route[].latitude` | Number | No | Latitude of each waypoint |
| `return_route[].longitude` | Number | No | Longitude of each waypoint |
| `return_altitude` | Number or Null | No | Intended return altitude;| 

Dotted attribute names above document fields inside their parent objects. They are shown separately for readability, not stored as duplicate top-level attributes.

`[]` in an attribute path means each entry in a list. Coordinate units and track-ID scope must be agreed with the vision team.

**How AWS uses it:** Lambda creates and updates mission records. The operator website reads the active mission. The mission record connects telemetry, alerts, target information, and stored media through `mission_id`.

### 4. `Alerts`

Stores safety, system, and tracking warnings that need to be shown to the operator.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `mission_id` | String | Partition key | Mission associated with the alert |
| `alert_timestamp` | String | Sort key | Time the alert occurred |
| `alert_id` | String | No | Unique alert ID |
| `drone_id` | String | No | Drone that generated the alert |
| `alert_type` | String | No | `LOW_BATTERY`, `LOST_CONNECTION`, `TARGET_LOST`, `BOUNDARY`, or `SYSTEM_ERROR` |
| `severity` | String | No | `INFO`, `WARNING`, or `CRITICAL` |
| `message` | String | No | Human-readable explanation |
| `acknowledged` | Boolean | No | Whether the operator has seen it |
| `resolved_at` | String | No | Time the issue was resolved |
| `street_name` | String or Null | No | Street associated with the alert, if known |

**How AWS uses it:** Lambda creates alerts when telemetry crosses a safety threshold or when the tracking system reports a problem. The operator website displays active alerts and can send an acknowledgement update through API Gateway.

### 5. `MediaMetadata`

Stores searchable information about files saved in S3. The actual files do not go into DynamoDB.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `media_id` | String | Partition key | Unique media record ID |
| `captured_at` | String | Sort key | Time the file was captured |
| `mission_id` | String | No | Mission connected to the file |
| `drone_id` | String | No | Drone that captured the file |
| `media_type` | String | No | `IMAGE` or `LOG` |
| `s3_bucket` | String | No | S3 bucket name |
| `storage_key` | String | No | Path/key of the file in S3 |
| `content_type` | String | No | MIME type such as `image/jpeg` |
| `file_size_bytes` | Number | No | File size |
| `retention_until` | String | No | Planned deletion/retention date |
| `source` | String | No | Source such as DASHCAM or DRONE |
| `location` | Map or Null | No | Capture coordinates |
| `location.latitude` | Number | No | Capture latitude in degrees |
| `location.longitude` | Number | No | Capture longitude in degrees |
| `plate_text` | String or Null | No | Plate text associated with the media |

**How AWS uses it:** Lambda receives or creates the file, stores it in S3, and writes the S3 location and metadata to DynamoDB. The operator website uses the record to retrieve the correct image or video without scanning the bucket.

## S3 organization

The S3 bucket is for files only, not database records.

```text
s3://hawkeye-data/
  missions/{mission_id}/images/{media_id}.jpg
  missions/{mission_id}/video/{media_id}.mp4
  missions/{mission_id}/logs/{media_id}.json
```

## Why no SQL table in the MVP?

SQL would be useful for complex relational reporting, long-term analytics, or administrative records. It is not necessary for the first HawkEye prototype because:

1. Telemetry is written frequently and queried by drone and time.
2. Missions and alerts can be connected with IDs without requiring joins during live operation.
3. Media files belong in S3, while their metadata can be queried in DynamoDB.
4. Adding SQL now would introduce another service, schema, and failure point.

If the team later needs historical analytics, the recommended path is to export older DynamoDB/S3 data into S3 and query it with Athena, rather than adding SQL to the live MVP path.



## Endpoint-to-table mapping

| API operation | Lambda action | Data location |
|---|---|---|
| `GET /drones/{drone_id}` | Read current drone state | `Drones` |
| `POST /telemetry` | Validate and write a telemetry event | `Telemetry` |
| `GET /telemetry/latest` | Read recent readings for a drone or mission | `Telemetry` |
| `POST /missions` | Create a new mission | `Missions` |
| `PATCH /missions/{id}` | Update status, assignment, or end time | `Missions` |
| `GET /missions/{id}` | Load mission details for dashboard | `Missions` |
| `GET /missions/{id}/alerts` | Read mission alerts | `Alerts` |
| `PATCH /alerts/{id}` | Mark an alert acknowledged/resolved | `Alerts` |
| `POST /media` | Upload file to S3 and save metadata | S3 + `MediaMetadata` |
| `GET /missions/{id}/media` | Find media records and generate access links | `MediaMetadata` + S3 |

## MVP summary for review

> HawkEye will use five DynamoDB tables—`Drones`, `Telemetry`, `Missions`, `Alerts`, and `MediaMetadata`—plus one S3 bucket for images, video, and logs. API Gateway sends requests to Lambda. Lambda validates and processes the data, stores live operational records in DynamoDB, and stores large media files in S3. The MVP will not use SQL because its live workload is time-series and event-based; SQL or Athena can be considered later for analytics and reporting.
