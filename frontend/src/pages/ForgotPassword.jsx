//forgot password page: asks for the account email and sends a reset link
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBackToLanding, LANDING_BEHIND } from '../hooks/useBackToLanding.js'
import { requestPasswordReset, friendlyError } from '../services/auth.js'
import '../styles/login.css'

export default function ForgotPassword() {
  const navigate = useNavigate()
  useBackToLanding() // back button goes to the landing page
  const [email, setEmail] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // pressing Enter in the box submits the form
  async function handleSubmit(e) {
    e.preventDefault()
    if (!email.trim()) {
      setError('Enter your email address.')
      return
    }
    setError('')
    setNotice('')
    setSubmitting(true)
    try {
      const data = await requestPasswordReset(email)
      setNotice(data.message)
    } catch (err) {
      setError(friendlyError(err))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page forgot-page">
      <h1 className="auth-title">Forgot Password</h1>
      <p className="auth-hint">Enter the email on your account and we’ll send you a reset link.</p>

      <form className="auth-form" onSubmit={handleSubmit}>
        <input
          className="auth-input"
          type="email"
          autoComplete="email"
          placeholder="Email..."
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <button type="submit" className="auth-submit" disabled={submitting}>
          {submitting ? 'Sending...' : 'Reset'}
        </button>
      </form>

      {notice && (
        <p className="auth-notice" role="status">
          {notice}
        </p>
      )}
      {error && (
        <p className="auth-error" role="alert">
          {error}
        </p>
      )}

      <p className="auth-switch">
        Remembered it?{' '}
        <button onClick={() => navigate('/login', { replace: true, state: LANDING_BEHIND })}>Log in.</button>
      </p>
    </main>
  )
}
