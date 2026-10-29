//login page
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/login.css'

export default function Login() {
  const navigate = useNavigate()
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
      <h1 className="auth-title">Log in to Hawkeye</h1>

      <form className="auth-form" onSubmit={handleLogin}>
        <input
          className="auth-input"
          placeholder="Badge number..."
          value={badge}
          onChange={(e) => setBadge(e.target.value)}
        />
        <input
          className="auth-input"
          type="password"
          placeholder="Officer Password..."
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {/* hidden button so Enter submits the form */}
        <button type="submit" hidden />
      </form>

      <p className="auth-switch">
        Don’t have an account?{' '}
        <button onClick={() => navigate('/register')}>Register now.</button>
      </p>
    </main>
  )
}
