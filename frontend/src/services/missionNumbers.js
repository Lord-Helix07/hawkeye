// Mission numbers: random codes like "HWK-07-2410" (backend/website/mission_numbers.py).
//
// The Deploy page gets a code to show, then sends that same code back with
// createMission, so the saved mission matches what the officer saw.
import { apiFetch } from './api.js'

const LAST_MISSION_KEY = 'hawkeye_last_mission_id'

// GET /missions/next-number -> "HWK-07-2410"
export async function fetchNextMissionId() {
  const response = await apiFetch('/missions/next-number')
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`)
  }
  const data = await response.json()
  return data.next_mission_id
}

// POST /missions -> the saved mission, e.g. { mission_id: "HWK-07-2410", status: "pending", ... }
// location ({ latitude, longitude } or null) is where the drone should fly to;
// the backend uses it to pick the nearest drone.
// missionId is the code shown on the Deploy page. The backend keeps it unless
// another mission already has it (very unlikely), then picks a new one.
export async function createMission(form, location = null, missionId = null) {
  const response = await apiFetch('/missions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      make: form.make.trim(),
      model: form.model.trim(),
      color: form.color.trim(),
      license_plate: form.plate.trim(), // the form calls it "plate", the backend "license_plate"
      latitude: location?.latitude ?? null,
      longitude: location?.longitude ?? null,
      mission_id: missionId,
    }),
  })
  if (response.status === 422) {
    throw new Error('Fill in all required fields.')
  }
  if (!response.ok) {
    throw new Error(`Could not create the mission (${response.status})`)
  }

  const mission = await response.json()
  localStorage.setItem(LAST_MISSION_KEY, mission.mission_id)
  return mission
}

// The last mission started on this computer, so plain /dashboard knows what to show.
// (Just a convenience for this browser; the real count lives in the backend.)
export function getLastMissionId() {
  return localStorage.getItem(LAST_MISSION_KEY)
}
