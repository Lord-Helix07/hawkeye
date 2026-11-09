import { clearSession, getSession } from './session.js'

// Where the backend lives.
//   - Local dev (npm run dev): uses http://localhost:8000 automatically.
//   - Deployed site (fly-hawkeye.com): uses /api on the same domain, set in
//     frontend/.env.production. Vercel sends /api/* to the backend.
// (Run the backend locally with: cd backend && uvicorn api:app --reload --port 8000)
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

// fetch() for officer-only routes: sends the login token from /login.
// If the backend says the login is missing or expired (401), log out and go
// to the login page, coming back to this page afterwards.
export async function apiFetch(path, options = {}) {
  const token = getSession()?.token
  const headers = { ...options.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) }
  const response = await fetch(`${API_URL}${path}`, { ...options, headers })

  if (response.status === 401) {
    clearSession()
    const next = encodeURIComponent(window.location.pathname + window.location.search)
    window.location.assign(`/login?next=${next}`)
  }
  return response
}
