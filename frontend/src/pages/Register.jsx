//register page
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBackToLanding, LANDING_BEHIND } from '../hooks/useBackToLanding.js'
import { signUp } from '../services/auth.js'
import '../styles/register.css'

export default function Register() {
  const navigate = useNavigate()
  useBackToLanding() // back button goes to the landing page
  const [badge, setBadge] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // pressing Enter in either box submits the form
  async function handleRegister(e) {
    e.preventDefault()
    if (!badge.trim() || !password) {
      setError('Enter a badge number and password.')
      return
    }
    setError('')
    setSubmitting(true)
    try {
      await signUp(badge, password) // saves the account in DynamoDB
      navigate('/login', { replace: true, state: LANDING_BEHIND })
    } catch (err) {
      setError(err.message === 'Failed to fetch' ? 'Could not reach the server. Is the backend running?' : err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page register-page">
      
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
      <h1 className="auth-title">Register for Hawkeye</h1>

      <form className="auth-form" onSubmit={handleRegister}>
        <input
          className="auth-input"
          placeholder="Badge Number..."
          value={badge}
          onChange={(e) => setBadge(e.target.value)}
        />
        <input
          className="auth-input"
          type="password"
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
        Already have an account?{' '}
        <button onClick={() => navigate('/login', { replace: true, state: LANDING_BEHIND })}>Sign in.</button>
      </p>
    </main>
  )
}
