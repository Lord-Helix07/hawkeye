//register page
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBackToLanding, LANDING_BEHIND } from '../hooks/useBackToLanding.js'
import { signUp, friendlyError, passwordProblem, MIN_PASSWORD_LENGTH } from '../services/auth.js'
import '../styles/register.css'

export default function Register() {
  const navigate = useNavigate()
  useBackToLanding() // back button goes to the landing page
  const [badge, setBadge] = useState('')
  const [email, setEmail] = useState('')
  const [confirmEmail, setConfirmEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // the Register button (or Enter in any box) submits the form
  async function handleRegister(e) {
    e.preventDefault()
    if (!badge.trim() || !email.trim() || !password) {
      setError('Enter a badge number, email, and password.')
      return
    }
    if (email.trim().toLowerCase() !== confirmEmail.trim().toLowerCase()) {
      setError('Email addresses do not match.')
      return
    }
    const problem = passwordProblem(password)
    if (problem) {
      setError(problem)
      return
    }
    setError('')
    setSubmitting(true)
    try {
      await signUp(badge, email, confirmEmail, password) // saves the account in DynamoDB
      navigate('/login', { replace: true, state: LANDING_BEHIND })
    } catch (err) {
      setError(friendlyError(err))
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
          type="email"
          autoComplete="email"
          placeholder="Email..."
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="auth-input"
          type="email"
          autoComplete="email"
          placeholder="Confirm Email..."
          value={confirmEmail}
          onChange={(e) => setConfirmEmail(e.target.value)}
        />
        <input
          className="auth-input"
          type="password"
          autoComplete="new-password"
          placeholder={`Password (${MIN_PASSWORD_LENGTH}+ characters)...`}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit" className="auth-submit" disabled={submitting}>
          {submitting ? 'Registering...' : 'Register'}
        </button>
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
