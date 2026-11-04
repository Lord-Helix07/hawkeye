// logic to switch between pages
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Deploy from './pages/Deploy.jsx'
import Dashboard from './pages/Dashboard.jsx'
import CameraFeed from './pages/CameraFeed.jsx' // testing: live camera view
import DashboardFixed from './pages/DashboardFixed.jsx' // teaching copy: fixed pixels

// Temporary dev nav: lets everyone jump to any page while it's being built.
function DevNav() {
  const navigate = useNavigate()

  return (
    <nav>
      <button onClick={() => navigate('/')}>Landing</button>
      <button onClick={() => navigate('/login')}>Login</button>
      <button onClick={() => navigate('/register')}>Register</button>
      <button onClick={() => navigate('/deploy')}>Deploy</button>
      <button onClick={() => navigate('/dashboard')}>Dashboard</button>
      <button onClick={() => navigate('/dashboard-fixed')}>Dashboard (fixed px)</button>
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
        <Route path="/deploy" element={<Deploy />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/dashboard/:missionId" element={<Dashboard />} />
        <Route path="/camera" element={<CameraFeed />} />
        <Route path="/dashboard-fixed" element={<DashboardFixed />} />
      </Routes>
    </BrowserRouter>
  )
}
