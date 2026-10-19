# HawkEye Data Schema — MVP

## Architecture decision

The HawkEye MVP will use **four DynamoDB tables** and **one S3 bucket**.

There will be **zero SQL tables in the MVP**. HawkEye's operational data is mostly event-based and needs fast writes, flexible fields, and low-latency reads during a pursuit. DynamoDB fits those requirements better than a relational database. S3 will hold large files such as images, video clips, and system logs; DynamoDB will store the metadata and S3 object locations.

| Storage | Count | Used for |
|---|---:|---|
| DynamoDB | 4 tables | Live operational data and queryable metadata |
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
 telemetry, missions, alerts, media metadata
```

## DynamoDB tables

### 1. `Telemetry`

Stores the drone's frequently changing flight and tracking data.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `drone_id` | String | Partition key | Identifies the drone sending the reading |
| `timestamp` | String | Sort key | UTC time when the reading was recorded |
| `event_id` | String | No | Unique ID for the telemetry event |
| `mission_id` | String | No | Pursuit/mission connected to the reading |
| `latitude` | Number | No | Drone latitude |
| `longitude` | Number | No | Drone longitude |
| `altitude_m` | Number | No | Drone altitude in meters |
| `speed_mps` | Number | No | Drone speed in meters per second |
| `battery_percent` | Number | No | Remaining battery percentage |
| `connection_status` | String | No | `CONNECTED`, `DEGRADED`, or `DISCONNECTED` |
| `flight_status` | String | No | `IDLE`, `TAKEOFF`, `TRACKING`, `RETURNING`, or `LANDED` |

**How AWS uses it:** Lambda validates and writes telemetry received through API Gateway. The operator website reads the latest records to display location, speed, battery, and connection status. A future TTL can automatically remove old high-frequency records after the retention period.

### 2. `Missions`

Stores one record for each pursuit or drone deployment.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `mission_id` | String | Partition key | Unique ID for the pursuit mission |
| `created_at` | String | No | Mission creation time |
| `status` | String | No | `PLANNED`, `ACTIVE`, `COMPLETED`, `ABORTED`, or `FAILED` |
| `assigned_drone_id` | String | No | Drone assigned to the mission |
| `target_vehicle_id` | String | No | Vehicle currently being tracked |
| `start_location` | Map | No | Mission starting coordinates |
| `end_location` | Map | No | Final or last-known coordinates |
| `started_at` | String | No | Time the drone launched |
| `ended_at` | String | No | Time the mission ended |
| `operator_id` | String | No | Operator who started or managed it |
| `termination_reason` | String | No | Why the mission ended or was aborted |

**How AWS uses it:** Lambda creates and updates mission records. The operator website reads the active mission. The mission record connects telemetry, alerts, target information, and stored media through `mission_id`.

### 3. `Alerts`

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

**How AWS uses it:** Lambda creates alerts when telemetry crosses a safety threshold or when the tracking system reports a problem. The operator website displays active alerts and can send an acknowledgement update through API Gateway.

### 4. `MediaMetadata`

Stores searchable information about files saved in S3. The actual files do not go into DynamoDB.

| Attribute | Type | Key? | Description |
|---|---|---|---|
| `media_id` | String | Partition key | Unique media record ID |
| `captured_at` | String | Sort key | Time the file was captured |
| `mission_id` | String | No | Mission connected to the file |
| `drone_id` | String | No | Drone that captured the file |
| `media_type` | String | No | `IMAGE` or `LOG` |
| `s3_bucket` | String | No | S3 bucket name |
| `s3_key` | String | No | Path/key of the file in S3 |
| `content_type` | String | No | MIME type such as `image/jpeg` |
| `file_size_bytes` | Number | No | File size |
| `retention_until` | String | No | Planned deletion/retention date |

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

> HawkEye will use four DynamoDB tables—`Telemetry`, `Missions`, `Alerts`, and `MediaMetadata`—plus one S3 bucket for images, video, and logs. API Gateway sends requests to Lambda. Lambda validates and processes the data, stores live operational records in DynamoDB, and stores large media files in S3. The MVP will not use SQL because its live workload is time-series and event-based; SQL or Athena can be considered later for analytics and reporting.
