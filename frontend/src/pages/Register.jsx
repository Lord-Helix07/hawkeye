//register page
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/register.css'

export default function Register() {
  const navigate = useNavigate()
  const [badge, setBadge] = useState('')
  const [password, setPassword] = useState('')

  // pressing Enter in either box submits the form
  function handleRegister(e) {
    e.preventDefault()
    // TODO: send badge + password to the backend to create the account
    navigate('/login')
  }

  return (
    <main className="auth-page">
      <h1 className="auth-title">Register for Hawkeye</h1>

      <form className="auth-form" onSubmit={handleRegister}>
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
        Already have an account?{' '}
        <button onClick={() => navigate('/login')}>Sign in.</button>
      </p>
    </main>
  )
}
