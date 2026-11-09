// Wrap a page that only logged-in users may see.
// Logged out -> sent to /login?next=<this page>, and back here after logging in.
import { Navigate, useLocation } from 'react-router-dom'
import { getSession } from '../services/session.js'

export default function RequireLogin({ children }) {
  const location = useLocation()
  if (getSession()) return children

  const next = encodeURIComponent(location.pathname + location.search)
  return <Navigate to={`/login?next=${next}`} replace />
}
