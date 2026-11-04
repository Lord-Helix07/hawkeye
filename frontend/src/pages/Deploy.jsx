// page to launch the drone
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/deploy.css'
import { createMission, fetchNextMissionId } from '../services/missionNumbers.js'

const emptyForm = { make: '', model: '', color: '', direction: '', plate: '' }

const fields = [
  { name: 'make', label: 'Make' },
  { name: 'model', label: 'Model' },
  { name: 'color', label: 'Color' },
  { name: 'direction', label: 'Direction' },
  { name: 'plate', label: 'License plate' },
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
      // the backend saves the mission and gives it the next number
      const mission = await createMission(form)
      navigate(`/dashboard/${mission.mission_id}`)
    } catch (err) {
      setError(err.message === 'Failed to fetch' ? 'Could not reach the server. Is the backend running?' : err.message)
      setSubmitting(false)
    }
  }

  return (
    <>
      <header className="deploy-header">
        <span className="deploy-logo">
          <svg width="26" height="26" viewBox="0 0 24 24" aria-hidden="true">
            <path d="M4 4 L20 20 M20 4 L4 20" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
            <circle cx="12" cy="12" r="3" fill="currentColor" />
          </svg>
          Hawkeye
        </span>
        <nav className="deploy-nav">
          <button onClick={() => navigate('/dashboard')}>Live feed</button>
          <button>History</button>
          <button>Settings</button>
        </nav>
      </header>

      <main className="deploy-main">
        <div className="deploy-title">
          <h1>Target Vehicle</h1>
          <p>Provide details below to start mission</p>
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
