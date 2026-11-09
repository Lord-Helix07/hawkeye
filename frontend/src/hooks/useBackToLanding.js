// makes the browser back button on login/register always go to the landing page
import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

// pass this as navigate state when the page right before is already the landing page
export const LANDING_BEHIND = { landingBehind: true }

export function useBackToLanding() {
  const navigate = useNavigate()
  const location = useLocation()
  const done = useRef(false) // StrictMode runs effects twice in dev

  useEffect(() => {
    if (done.current || location.state?.landingBehind) return
    done.current = true
    // swap the current history entry for landing, then put this page back on top,
    // so pressing back lands on '/'
    navigate('/', { replace: true })
    navigate(location.pathname + location.search, { state: LANDING_BEHIND }) // keep ?next=...
  }, [location, navigate])
}
