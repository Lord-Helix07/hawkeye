// Launch and landing buttons -> backend/launch.py
//
// The drone (Raspberry Pi) reads and answers these through the mission's row:
//   launch_status:  requested -> ready / not_ready -> confirmed -> launched / failed
//   landing_status: requested -> (Pi) landing / landed / failed
import { API_URL } from './api.js'

async function post(path) {
  const response = await fetch(`${API_URL}${path}`, { method: 'POST' })
  if (!response.ok) {
    const data = await response.json().catch(() => ({}))
    throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`)
  }
  return response.json()
}

// assigns the nearest drone if needed, then sets launch_status = requested
export function launchMission(missionId) {
  return post(`/missions/${missionId}/launch`)
}

// operator OK after the drone reported ready
export function confirmLaunch(missionId) {
  return post(`/missions/${missionId}/confirm-launch`)
}

export function requestLanding(missionId) {
  return post(`/missions/${missionId}/request-landing`)
}
