// Who is logged in on this browser.
//
// Saved in localStorage after a successful /login and cleared on log out.
// token is the signed login token from /login; apiFetch (api.js) sends it to
// the officer-only backend routes, which reject requests without a valid one.
const KEY = 'hawkeye.session'
const MAX_AGE_MS = 12 * 60 * 60 * 1000 // log out automatically after 12 hours

export function getSession() {
  try {
    const session = JSON.parse(localStorage.getItem(KEY))
    if (!session?.badge_num || !session.token || Date.now() - session.logged_in_at > MAX_AGE_MS) return null
    return session
  } catch {
    return null
  }
}

export function saveSession(badgeNum, token) {
  try {
    localStorage.setItem(KEY, JSON.stringify({ badge_num: badgeNum, token, logged_in_at: Date.now() }))
  } catch {
    // storage blocked (private mode etc.): the user just has to log in again next time
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(KEY)
  } catch {
    // nothing to clear
  }
}

// only allow redirecting back to a page on this site (e.g. "/dashboard/0001")
export function safeNextPath(next) {
  return typeof next === 'string' && next.startsWith('/') && !next.startsWith('//') ? next : null
}
