//reset password page: opened from the emailed link (/reset-password?badge=...&token=...)
import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { LANDING_BEHIND } from '../hooks/useBackToLanding.js'
import { resetPassword, friendlyError, passwordProblem } from '../services/auth.js'
import '../styles/login.css'

export default function ResetPassword() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const badge = params.get('badge') || ''
  const token = params.get('token') || ''
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  function goToLogin() {
    navigate('/login', { replace: true, state: LANDING_BEHIND })
  }

  // pressing Enter in either box submits the form
  async function handleSubmit(e) {
    e.preventDefault()
    if (!password) {
      setError('Enter a new password.')
      return
    }
    const problem = passwordProblem(password)
    if (problem) {
      setError(problem)
      return
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match.')
      return
    }
    setError('')
    setSubmitting(true)
    try {
      await resetPassword(badge, token, password)
      setDone(true)
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!badge || !token) {
    return (
      <main className="auth-page">
        <h1 className="auth-title">Reset link not valid</h1>
        <p className="auth-hint">Open the link from your email, or ask for a new one.</p>
        <p className="auth-switch">
          <button onClick={() => navigate('/forgot-password', { replace: true, state: LANDING_BEHIND })}>
            Send a new link.
          </button>
        </p>
      </main>
    )
  }

  if (done) {
    return (
      <main className="auth-page">
        <h1 className="auth-title">Password updated</h1>
        <p className="auth-switch">
          <button onClick={goToLogin}>Log in.</button>
        </p>
      </main>
    )
  }

  return (
    <main className="auth-page">
      <h1 className="auth-title">Choose a new password</h1>
      <p className="auth-hint">Badge {badge}</p>

      <form className="auth-form" onSubmit={handleSubmit}>
        <input
          className="auth-input"
          type="password"
          autoComplete="new-password"
          placeholder="New Password..."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <input
          className="auth-input"
          type="password"
          autoComplete="new-password"
          placeholder="Confirm New Password..."
          value={confirmPassword}
          onChange={(e) => setConfirmPassword(e.target.value)}
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
        <button onClick={goToLogin}>Back to log in.</button>
      </p>
    </main>
  )
}
