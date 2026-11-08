//login page
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useBackToLanding, LANDING_BEHIND } from '../hooks/useBackToLanding.js'
import '../styles/login.css'

export default function Login() {
  const navigate = useNavigate()
  useBackToLanding() // back button goes to the landing page
  const [badge, setBadge] = useState('')
  const [password, setPassword] = useState('')

  // pressing Enter in either box submits the form
  function handleLogin(e) {
    e.preventDefault()
    // TODO: check badge + password with the backend before letting them in
    navigate('/deploy')
  }

  return (
    <main className="auth-page">
      <div className="auth-brand">
        <svg
          className="auth-brand-icon"
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

        <span>Hawkeye</span>
      </div>

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
          placeholder="Password..."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {/* hidden button so Enter submits the form */}
        <button type="submit" hidden />
      </form>

      <p className="auth-switch">
        Don’t have an account?{' '}
        <button onClick={() => navigate('/register', { replace: true, state: LANDING_BEHIND })}>Register now.</button>
      </p>
    </main>
  )
}
