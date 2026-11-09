// logic to switch between pages
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import ForgotPassword from './pages/ForgotPassword.jsx'
import ResetPassword from './pages/ResetPassword.jsx'
import Deploy from './pages/Deploy.jsx'
import Dashboard from './pages/Dashboard.jsx'
import CameraFeed from './pages/CameraFeed.jsx' // testing: live camera view
import RequireLogin from './components/RequireLogin.jsx'
import RedirectIfLoggedIn from './components/RedirectIfLoggedIn.jsx'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        {/* logged-out users only (logged in -> Dashboard) */}
        <Route path="/login" element={<RedirectIfLoggedIn><Login /></RedirectIfLoggedIn>} />
        <Route path="/register" element={<RedirectIfLoggedIn><Register /></RedirectIfLoggedIn>} />
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
