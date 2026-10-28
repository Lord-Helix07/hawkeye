// logic to switch between pages
import { BrowserRouter, Routes, Route, useNavigate } from 'react-router-dom'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Deploy from './pages/Deploy.jsx'
import Telemetry from './pages/Telemetry.jsx'

// Temporary dev nav: lets everyone jump to any page while it's being built.
function DevNav() {
  const navigate = useNavigate()

  return (
    <nav>
      <button onClick={() => navigate('/')}>Landing</button>
      <button onClick={() => navigate('/login')}>Login</button>
      <button onClick={() => navigate('/register')}>Register</button>
      <button onClick={() => navigate('/deploy')}>Deploy</button>
      <button onClick={() => navigate('/telemetry')}>Telemetry</button>
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
        <Route path="/telemetry" element={<Telemetry />} />
      </Routes>
    </BrowserRouter>
  )
}
