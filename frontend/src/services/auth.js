// Accounts: sign up (and later, log in).
import { API_URL } from './api.js'

export async function signIn(badge, password) { // Sign in a user with badge number and password
  let response
  try {
    response = await fetch(`${API_URL}/login`, { // Send a POST request to the login endpoint
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ badge_num: badge.trim(), password }),// Send the badge number and password as JSON
    })
  } catch {
    throw new Error('Unable to reach the server.') // Throw an error if the server cannot be reached
  }

  let data
  try {
    data = await response.json() // Parse the response as JSON
  } catch {
    throw new Error('The server returned an invalid response.')
  }

  if (!response.ok) { //throw an error if the response is not OK
    const error = new Error(
      typeof data.detail === 'object'
        ? data.detail.message || 'Login failed.'
        : data.detail || `Could not log in (${response.status})`,
    )
    error.detail = data.detail
    throw error
  }

  if (typeof data.access_token !== 'string' || !data.access_token) { // Check if the access token is valid
    throw new Error('The login response did not include an access token.') // Throw an error if the access token is missing
  }

  sessionStorage.setItem('hawkeye_access_token', data.access_token) // Store the access token in session storage
  return data // Return the login response data
}

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
