// logic to switch between pages
import { useState } from 'react'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Register from './pages/Register.jsx'
import Deploy from './pages/Deploy.jsx'
import Telemetry from './pages/Telemetry.jsx'

// Temporary dev nav: lets everyone view any page while it's being built.
// Replace with real navigation (login flow / React Router) later.
const pages = { Landing, Login, Register, Deploy, Telemetry }

export default function App() {
  const [page, setPage] = useState('Landing')
  const Page = pages[page]

  return (
    <>
      <nav>
        {Object.keys(pages).map((name) => (
          <button key={name} onClick={() => setPage(name)}>
            {name}
          </button>
        ))}
      </nav>
      <Page />
    </>
  )
}
