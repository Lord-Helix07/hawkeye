// Top bar for the logged-in pages (Deploy, Dashboard):
//   [◆ Hawkeye]   Dashboard  Deploy            {page extras}  Badge 1234 ▾
// The logo goes to the landing page; the badge menu has Log out (back to the landing page).
// Anything passed as children (e.g. the Live feed button) sits before the badge menu.
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, useNavigate } from 'react-router-dom'
import { clearSession, getSession } from '../services/session.js'
import '../styles/app-header.css'

export default function AppHeader({ children }) {
  const navigate = useNavigate()
  const badge = getSession()?.badge_num
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  // close the badge menu on a click outside it or on Escape
  useEffect(() => {
    if (!menuOpen) return
    const onClick = (e) => {
      if (!menuRef.current?.contains(e.target)) setMenuOpen(false)
    }
    const onKey = (e) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [menuOpen])

  function logOut() {
    clearSession()
    navigate('/', { replace: true })
  }

  return (
    <header className="app-header">
      <div className="app-header-left">
        <Link to="/" className="app-logo">
          <svg className="app-logo-icon" viewBox="0 0 100 100" aria-hidden="true">
            <path d="M50 6 C54 25 62 38 94 50 C75 54 63 62 50 94 C46 75 38 62 6 50 C25 46 38 38 50 6 Z" />
          </svg>
          Hawkeye
        </Link>

        <nav className="app-nav" aria-label="Main">
          <NavLink to="/" end>Home</NavLink>
          <NavLink to="/dashboard">Dashboard</NavLink>
          <NavLink to="/deploy">Deploy</NavLink>
        </nav>
      </div>

      <div className="app-header-right">
        {children}

        {badge && (
          <div className="account-menu" ref={menuRef}>
            <button
              type="button"
              className="account-btn"
              aria-haspopup="menu"
              aria-expanded={menuOpen}
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span className="account-label">Badge </span>
              {badge} <span className="account-caret" aria-hidden="true">▾</span>
            </button>
            {menuOpen && (
              <div className="account-dropdown" role="menu">
                <button type="button" role="menuitem" onClick={logOut}>
                  Log out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  )
}
