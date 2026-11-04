// Where the Dashboard gets its live data.
//
// The backend will serve one endpoint that returns everything the page shows:
//   GET /missions/{mission_id}/status
// Until that exists, USE_MOCK makes the page use fake data in the same shape,
// so the frontend can be built and tested now.

import { API_URL } from './api.js'

// Flip to false once the backend endpoint is ready. Nothing else needs to change.
export const USE_MOCK = true

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
//   mission_id, target_in_frame, tracking_status, last_seen,
//   location: { street, city, accuracy_m },              <- not stored yet
//   telemetry: { latitude, longitude, speed_mps, battery_pct, altitude_m, timestamp },
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
