// page to launch the drone
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/deploy.css'
import AppHeader from '../components/AppHeader.jsx'
import { createMission, fetchNextMissionId } from '../services/missionNumbers.js'
import { launchMission } from '../services/launch.js'

// The officer's position, so the backend can send the nearest drone.
// Resolves to null if the browser can't or won't share it.
function getCurrentLocation() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null)
    navigator.geolocation.getCurrentPosition(
      (position) => resolve({ latitude: position.coords.latitude, longitude: position.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 8000, maximumAge: 60000 },
    )
  })
}

const emptyForm = { make: '', model: '', color: '', plate: '' }

const fields = [
  { name: 'make', label: 'Make' },
  { name: 'model', label: 'Model' },
  { name: 'color', label: 'Color' },
  { name: 'plate', label: 'License Plate' },
]

export default function Deploy() {
  const navigate = useNavigate()
  const [form, setForm] = useState(emptyForm)

  // preview of the number this mission will get, e.g. "0003" (null while loading)
  const [nextMissionId, setNextMissionId] = useState(null)
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  // ask the backend for the next mission number when the page opens
  useEffect(() => {
    let cancelled = false
    fetchNextMissionId()
      .then((id) => {
        if (!cancelled) setNextMissionId(id)
      })
      .catch(() => {
        if (!cancelled) setError('Could not reach the server. Is the backend running?')
      })
    return () => {
      cancelled = true
    }
  }, [])

  function handleChange(e) {
    setForm({ ...form, [e.target.name]: e.target.value })
  }

  async function handleDeploy(e) {
    e.preventDefault()
    if (submitting) return
    setError('')
    setSubmitting(true)
    try {
      // the backend saves the mission under the code shown on this page
      const location = await getCurrentLocation()
      const mission = await createMission(form, location, nextMissionId)

      // assign the nearest drone and ask it to start its pre-flight checks.
      // If that fails the mission still exists; the Dashboard shows why and a retry button.
      let launchError = ''
      try {
        await launchMission(mission.mission_id)
      } catch (err) {
        launchError = err.message === 'Failed to fetch' ? 'Could not reach the server.' : err.message
      }
      navigate(`/dashboard/${mission.mission_id}`, { state: { launchError } })
    } catch (err) {
      setError(err.message === 'Failed to fetch' ? 'Could not reach the server. Is the backend running?' : err.message)
      setSubmitting(false)
    }
  }

  return (
    <>
      <AppHeader>
        {/* TESTING: opens the camera test page */}
        <button className="live-btn" onClick={() => navigate('/camera')}>
          <span className="live-dot" aria-hidden="true" />
          Live feed
        </button>
      </AppHeader>

      <main className="deploy-main">
        {/* 3 columns: empty | title (centered) | mission number (right edge) */}
        <div className="deploy-title">
          <div className="deploy-title-text">
            <h1>Target Vehicle</h1>
            <p>Provide details below to start mission</p>
          </div>
          <span className="mission-id">
            Mission: <strong>{nextMissionId ?? '----'}</strong>
          </span>
        </div>

        <form onSubmit={handleDeploy}>
          <div className="deploy-card">
            {fields.map((field) => (
              <label key={field.name} className="deploy-field">
                {field.label}
                <input name={field.name} value={form[field.name]} onChange={handleChange} />
              </label>
            ))}
          </div>

          {error && (
            <p className="deploy-error" role="alert">
              {error}
            </p>
          )}

          <div className="deploy-actions">
            <button type="button" className="clear-btn" onClick={() => setForm(emptyForm)}>
              Clear
            </button>
            <button type="submit" className="deploy-btn" disabled={submitting}>
              {submitting ? 'Deploying…' : 'Deploy Drone'} <span aria-hidden="true">→</span>
            </button>
          </div>
        </form>
      </main>
    </>
  )
}
