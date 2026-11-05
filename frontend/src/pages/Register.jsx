//register page
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { signUp } from '../services/auth.js'
import '../styles/register.css'

export default function Register() {
  const navigate = useNavigate()
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
      navigate('/login')
    } catch (err) {
      setError(err.message === 'Failed to fetch' ? 'Could not reach the server. Is the backend running?' : err.message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page register-page">
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
        <button onClick={() => navigate('/login')}>Sign in.</button>
      </p>
    </main>
  )
}
