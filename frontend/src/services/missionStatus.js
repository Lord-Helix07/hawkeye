// Where the Dashboard gets its live data.
//
// The backend serves one endpoint that returns everything the page shows:
//   GET /missions/{mission_id}/status   (backend/mission_status.py)
// USE_MOCK = true swaps in fake data in the same shape, for working on the
// page without the backend or a drone.

import { API_URL } from './api.js'

export const USE_MOCK = false

// ---------- real backend ----------
export async function fetchMissionStatus(missionId) {
  const response = await fetch(`${API_URL}/missions/${missionId}/status`)
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`)
  }
  return response.json()
}

// ---------- fake data (same shape as the real endpoint) ----------
//
// The agreed JSON shape. Field names match the database tables in
// backend/database/sample_data.json (Telemetry, MediaMetadata, Alerts).
//
// {
//   mission_id, drone_id, launch_status, launch_reason, launch_reasons, landing_status,
//   target_in_frame, tracking_status, last_seen,          <- null until the camera sends them
//   location: { street, city, accuracy_m },              <- not stored yet
//   telemetry: { latitude, longitude, speed_mps, battery_pct, altitude_m, timestamp, stale }
//              or null before the drone has sent anything,
//   images: [{ media_id, url, captured_at }],
//   flight_log: [{ time, message }]
// }

const START = { latitude: 37.3305, longitude: -121.89 }

export function createMockStatus(missionId, tick) {
  const now = new Date()
  const step = tick % 100 // loop the route every 100 updates

  const inFrame = tick % 15 < 12 // loses the target for a few updates every 30s
  const lastSeen = inFrame ? now : new Date(now.getTime() - ((tick % 15) - 11) * 2000)

  return {
    mission_id: missionId,
    drone_id: 'drone-01',
    launch_status: 'launched',
    launch_reason: null,
    launch_reasons: null,
    landing_status: null,
    target_in_frame: inFrame,
    tracking_status: inFrame ? 'active' : 'searching',
    last_seen: lastSeen.toISOString(),
    location: {
      street: 'W San Carlos St',
      city: 'San Jose, California',
      accuracy_m: 2.4,
    },
    telemetry: {
      latitude: START.latitude - 0.003 + step * 0.00006, // heading north
      longitude: START.longitude + Math.sin(step / 6) * 0.002,
      speed_mps: 8 + Math.sin(tick / 3) * 2,
      battery_pct: Math.max(5, 64 - Math.floor(tick / 5)),
      altitude_m: 42,
      timestamp: now.toISOString(),
      stale: false,
    },
    images: [
      { media_id: 'med-1', url: null, captured_at: lastSeen.toISOString() },
      { media_id: 'med-2', url: null, captured_at: lastSeen.toISOString() },
    ],
    flight_log: [
      { time: '2026-11-04T21:04:12Z', message: 'Officer input data: silver sedan, JLS24K, northbound' },
      { time: '2026-11-04T21:06:24Z', message: 'Hawkeye-02 deployed' },
      { time: '2026-11-04T21:07:48Z', message: 'Hawkeye reached optimal height' },
    ],
  }
}

// Center of the placeholder map, so the marker can move around it.
export const MOCK_MAP_CENTER = START
