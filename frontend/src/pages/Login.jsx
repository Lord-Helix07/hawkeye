import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { signIn } from '../services/auth.js'
import '../styles/login.css'

export default function Login() { //define login page
  const navigate = useNavigate()
  const [badge, setBadge] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [attemptsRemaining, setAttemptsRemaining] = useState(null)
  const [retryAfterSeconds, setRetryAfterSeconds] = useState(0)
  const [loading, setLoading] = useState(false)
//Store login inputs, errors, remaining attempts, lockout time, and loading state.
  useEffect(() => { //decrease the lockout timer every second and reset after done
    if (retryAfterSeconds <= 0) return

    const timer = setInterval(() => {
      setRetryAfterSeconds((seconds) => Math.max(0, seconds - 1))
    }, 1000)

    return () => clearInterval(timer)
  }, [retryAfterSeconds])

  async function handleLogin(e) { //submit login data
    e.preventDefault()

    setError('') //clear stuff from previous login
    setAttemptsRemaining(null)

    if (!badge.trim() || !password) { //validate both fields
      setError('Enter your badge number and password.')
      return
    }

    setLoading(true) //disable the form while checking

    try {
      await signIn(badge, password)
      navigate('/deploy')
    } catch (loginError) {
      const detail = loginError.detail
      if (typeof detail === 'object') {
        setError(detail.message || 'Login failed.')
        setAttemptsRemaining(detail.attempts_remaining ?? null)
        setRetryAfterSeconds(detail.retry_after_seconds ?? 0)
      } else {
        setError(loginError.message || 'Login failed.')
      }
    } finally { //reenable form after request finishes
      setLoading(false)
    }
  }

  const locked = retryAfterSeconds > 0 //determine if account is locked

  return ( //connect form submission to the login handler.
    <main className="auth-page"> 
      <h1 className="auth-title">Log in to Hawkeye</h1>

      <form className="auth-form" onSubmit={handleLogin}>  
        <input
          className="auth-input"
          placeholder="Badge Number..."
          value={badge}
          onChange={(e) => setBadge(e.target.value)}
          disabled={loading || locked}
        />

        <input
          className="auth-input"
          type="password"
          placeholder="Password..."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          disabled={loading || locked}
        />

        <button type="submit" disabled={loading || locked}>
          {loading ? 'Logging in...' : 'Log in'}
        </button>
      </form>

      {error && <p role="alert">{error}</p>}  

      {attemptsRemaining !== null && (
        <p>{attemptsRemaining} attempts remaining.</p>
      )}

      {locked && <p>Try again in {retryAfterSeconds} seconds.</p>}

      <p className="auth-switch">
        Don’t have an account?{' '}
        <button onClick={() => navigate('/register')}>
          Register now.
        </button>
      </p>
    </main>
  )
}
