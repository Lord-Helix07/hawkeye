// All backend calls go through this file.
// Set VITE_API_BASE_URL in .env to send real requests; when it is empty,
// requests are mocked so the UI works without a backend.
// Note: VITE_ variables are bundled into the browser code, so never put
// secret API keys here. Keep secrets on the backend.

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

async function request(endpoint, { method = 'GET', body } = {}) {
  if (!API_BASE_URL) {
    return { ok: true, mocked: true, method, endpoint, payload: body ?? null }
  }

  const hasBody = body !== undefined && method !== 'GET'
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    method,
    headers: hasBody ? { 'Content-Type': 'application/json' } : undefined,
    body: hasBody ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`)
  }

  return response.status === 204 ? { ok: true } : response.json()
}

// Sends a button command (deploy, return, land, cancel, ...).
export function runMissionAction(action, payload) {
  return request(action.endpoint, { method: action.method, body: payload })
}

// Read endpoints for replacing the sample data in src/MockData/mission.js.
export function fetchPursuitStatus() {
  return request('/api/pursuit/status')
}

export function fetchDroneLocation() {
  return request('/api/drone/location')
}
