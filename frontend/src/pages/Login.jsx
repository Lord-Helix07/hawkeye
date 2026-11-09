//login page
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useBackToLanding, LANDING_BEHIND } from '../hooks/useBackToLanding.js'
import { logIn, friendlyError } from '../services/auth.js'
import { safeNextPath, saveSession } from '../services/session.js'
import '../styles/login.css'

export default function Login() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams() // ?next=/dashboard/0001 when sent here by RequireLogin
  useBackToLanding() // back button goes to the landing page
  const [badge, setBadge] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // pressing Enter in any box submits the form
  async function handleLogin(e) {
    e.preventDefault()
    if (!badge.trim() || !password) {
      setError('Enter your badge number and password.')
      return
    }
    setError('')
    setSubmitting(true)
    try {
      const result = await logIn(badge, password) // checks the account in DynamoDB
      saveSession(result.badge_num ?? badge.trim(), result.token)
      // back to the page that sent us here (e.g. /dashboard/0001), otherwise Deploy
      navigate(safeNextPath(searchParams.get('next')) ?? '/deploy', { replace: true })
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">

  {/* Icon is centered above the login title */}
  <div className="auth-icon-center">
  <svg
    className="hawkeye-icon"
    viewBox="0 0 100 100"
    aria-hidden="true"
   >
    <path
      d="
    M50 6
    C54 25 62 38 94 50
    C75 54 63 62 50 94
    C46 75 38 62 6 50
    C25 46 38 38 50 6
    Z
  "
    />
  </svg>
</div>
      <h1 className="auth-title">Log in to Hawkeye</h1>

      <form className="auth-form" onSubmit={handleLogin}>
        <input
          className="auth-input"
          placeholder="Badge Number..."
          value={badge}
          onChange={(e) => setBadge(e.target.value)}
        />
        <input
          className="auth-input"
          type="password"
          autoComplete="current-password"
          placeholder="Password..."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {/* hidden button so Enter submits the form */}
        <button type="submit" hidden disabled={submitting} />
      </form>

      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}

      <p className="auth-switch">
        Don’t have an account?{' '}
        <button onClick={() => navigate('/register', { replace: true, state: LANDING_BEHIND })}>Register now.</button>
      </p>

      <button
        type="button"
        className="auth-forgot"
        onClick={() => navigate('/forgot-password', { replace: true, state: LANDING_BEHIND })}
      >
        Forgot your password?
      </button>
    </main>
  )
}
