// Wrap pages that only make sense when logged out (Login, Register).
// Already logged in -> go to ?next=<page> if there is one, otherwise the Dashboard.
import { Navigate, useSearchParams } from 'react-router-dom'
import { getSession, safeNextPath } from '../services/session.js'

export default function RedirectIfLoggedIn({ children }) {
  const [searchParams] = useSearchParams()
  if (!getSession()) return children
  return <Navigate to={safeNextPath(searchParams.get('next')) ?? '/dashboard'} replace />
}
