// Mission numbers: 0001, 0002, 0003...
//
// The backend hands out the numbers from one shared counter in DynamoDB
// (backend/mission_numbers.py), so every officer's computer sees the same count.
import { API_URL } from './api.js'

const LAST_MISSION_KEY = 'hawkeye_last_mission_id'

// 1 -> "0001"
export function formatMissionNumber(number) {
  return String(number).padStart(4, '0')
}

// GET /missions/next-number -> "0003"
// A preview for the Deploy page. If someone else deploys first, the real
// number (from createMission) will be higher.
export async function fetchNextMissionId() {
  const response = await fetch(`${API_URL}/missions/next-number`)
  if (!response.ok) {
    throw new Error(`Request failed (${response.status})`)
  }
  const data = await response.json()
  return data.next_mission_id
}

// POST /missions -> the saved mission, e.g. { mission_id: "0003", status: "pending", ... }
export async function createMission(form) {
  const response = await fetch(`${API_URL}/missions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      make: form.make.trim(),
      model: form.model.trim(),
      color: form.color.trim(),
      license_plate: form.plate.trim(), // the form calls it "plate", the backend "license_plate"
      direction: form.direction.trim() || null,
    }),
  })
  if (response.status === 422) {
    throw new Error('Fill in make, model, color and license plate.')
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
