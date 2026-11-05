// Accounts: sign up (and later, log in).
import { API_URL } from './api.js'

// POST /signup -> saves { badge_num, password_hash } in the DynamoDB Users table
export async function signUp(badge, password) {
  const response = await fetch(`${API_URL}/signup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ badge_num: badge.trim(), password }),
  })
  if (response.status === 409) {
    throw new Error('That badge number is already registered.')
  }
  if (!response.ok) {
    // show the backend's reason (e.g. the AWS error behind a 503)
    const data = await response.json().catch(() => ({}))
    throw new Error(data.detail || `Could not create the account (${response.status})`)
  }
  return response.json()
}
