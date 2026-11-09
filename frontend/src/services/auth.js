// Accounts: sign up, log in, and reset a forgotten password.
import { API_URL } from './api.js'

async function post(path, body) {
  return fetch(`${API_URL}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

// FastAPI errors come back as { detail: "..." } or { detail: { message: "..." } }
async function errorMessage(response, fallback) {
  const data = await response.json().catch(() => ({}))
  const detail = data.detail
  if (typeof detail === 'string') return detail
  if (detail?.message) return detail.message
  return `${fallback} (${response.status})`
}

// POST /signup -> saves { badge_num, email, password_hash } in the DynamoDB Users table
export async function signUp(badge, email, confirmEmail, password) {
  const response = await post('/signup', {
    badge_num: badge.trim(),
    email: email.trim(),
    confirm_email: confirmEmail.trim(),
    password,
  })
  if (!response.ok) {
    // show the backend's reason (badge/email taken, emails don't match, AWS error...)
    throw new Error(await errorMessage(response, 'Could not create the account'))
  }
  return response.json()
}

// POST /login -> checks badge number + password
export async function logIn(badge, password) {
  const response = await post('/login', { badge_num: badge.trim(), password })
  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Could not log in'))
  }
  return response.json()
}

// POST /forgot-password -> emails a reset link (same answer whether or not the email exists)
export async function requestPasswordReset(email) {
  const response = await post('/forgot-password', { email: email.trim() })
  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Could not send the reset link'))
  }
  return response.json()
}

// POST /reset-password -> sets a new password using the token from the email link
export async function resetPassword(badge, token, newPassword) {
  const response = await post('/reset-password', { badge_num: badge, token, new_password: newPassword })
  if (!response.ok) {
    throw new Error(await errorMessage(response, 'Could not reset the password'))
  }
  return response.json()
}

// fetch() throws "Failed to fetch" when the backend is down
export function friendlyError(err) {
  return err.message === 'Failed to fetch' ? 'Could not reach the server. Is the backend running?' : err.message
}
