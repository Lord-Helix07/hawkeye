// Keeps a mission's live status in state, refreshing every few seconds.
//
//   const { status, error, notFound, refresh } = useMissionStatus('HWK-07-2410')
//
// status is null until the first answer arrives.
// error is '' when everything is fine, otherwise a message to show the officer.
// notFound is true when the server says the mission doesn't exist.
// No missionId (null): does nothing.
import { useCallback, useEffect, useState } from 'react'
import { USE_MOCK, createMockStatus, fetchMissionStatus } from '../services/missionStatus.js'

export function useMissionStatus(missionId, intervalMs = 2000) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')
  const [notFound, setNotFound] = useState(false)

  // switched to another mission (or to none): drop the old mission's data and errors
  const [shownMission, setShownMission] = useState(missionId)
  if (shownMission !== missionId) {
    setShownMission(missionId)
    setStatus(null)
    setError('')
    setNotFound(false)
  }
  const [refreshCount, setRefreshCount] = useState(0) // bump to load again right away

  useEffect(() => {
    if (!missionId) return undefined

    let tick = 0
    let cancelled = false // stops updates after leaving the page

    async function load() {
      try {
        const data = USE_MOCK
          ? await Promise.resolve(createMockStatus(missionId, tick++))
          : await fetchMissionStatus(missionId)
        if (!cancelled) {
          setStatus(data)
          setError('')
          setNotFound(false)
        }
      } catch (err) {
        // keep showing the last good data, just add the error message
        if (!cancelled) {
          setError(err.message)
          setNotFound(Boolean(err.notFound))
        }
      }
    }

    load() // once right away
    const timer = setInterval(load, intervalMs) // then on a timer
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [missionId, intervalMs, refreshCount])

  const refresh = useCallback(() => setRefreshCount((count) => count + 1), [])
  return { status, error, notFound, refresh }
}
