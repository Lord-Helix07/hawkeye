// logic to switch between pages
import { BrowserRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import ForgotPassword from './pages/ForgotPassword.jsx'
import ResetPassword from './pages/ResetPassword.jsx'
import Deploy from './pages/Deploy.jsx'
import Dashboard from './pages/Dashboard.jsx'
import CameraFeed from './pages/CameraFeed.jsx' // testing: live camera view
import RequireLogin from './components/RequireLogin.jsx'
import { clearSession, getSession } from './services/session.js'

// Temporary dev nav: lets everyone jump to any page while it's being built.
// Deploy/Dashboard send you to the login page when you're logged out.
function DevNav() {
  const navigate = useNavigate()
  useLocation() // re-render on every page change so the log out button stays in sync

  function logOut() {
    clearSession()
    navigate('/login')
  }

  return (
    <nav>
      <button onClick={() => navigate('/')}>Landing</button>
      <button onClick={() => navigate('/login')}>Login</button>
      <button onClick={() => navigate('/register')}>Register</button>
      <button onClick={() => navigate('/deploy')}>Deploy</button>
      <button onClick={() => navigate('/dashboard')}>Dashboard</button>
      {getSession() && <button onClick={logOut}>Log out</button>}
    </nav>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <DevNav />

      <Routes>
        <Route path="/" element={<Landing />} />
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/reset-password" element={<ResetPassword />} />
        {/* logged-in users only */}
        <Route path="/deploy" element={<RequireLogin><Deploy /></RequireLogin>} />
        <Route path="/dashboard" element={<RequireLogin><Dashboard /></RequireLogin>} />
        <Route path="/dashboard/:missionId" element={<RequireLogin><Dashboard /></RequireLogin>} />
        <Route path="/camera" element={<CameraFeed />} />
      </Routes>
    </BrowserRouter>
  )
}
