// Keeps a mission's live status in state, refreshing every few seconds.
//
//   const { status, error } = useMissionStatus('0001')
//
// status is null until the first answer arrives.
// error is '' when everything is fine, otherwise a message to show the officer.
import { useEffect, useState } from 'react'
import { USE_MOCK, createMockStatus, fetchMissionStatus } from '../services/missionStatus.js'

export function useMissionStatus(missionId, intervalMs = 2000) {
  const [status, setStatus] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
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
        }
      } catch (err) {
        // keep showing the last good data, just add the error message
        if (!cancelled) setError(err.message)
      }
    }

    load() // once right away
    const timer = setInterval(load, intervalMs) // then on a timer
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [missionId, intervalMs])

  return { status, error }
}
