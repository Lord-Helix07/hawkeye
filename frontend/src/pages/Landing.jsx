// initial page u see
import '../styles/landing.css'
import { useNavigate } from 'react-router-dom'

export default function Landing() {
  const navigate = useNavigate()

  return (
    <>
      <header className="landing-header">
        <span className="landing-logo">Hawkeye</span>
        <div className="landing-auth">
          <button className="login-btn" onClick={() => navigate('/login')}>Login</button>
          <button className="signup-btn" onClick={() => navigate('/register')}>Sign up</button>
        </div>
      </header>

      <h1>The Autonomous pursuit drone for officers and the communities they protect</h1>
    </>
  )
}