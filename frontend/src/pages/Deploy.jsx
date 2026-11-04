// page to launch the drone
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/deploy.css'
import { createMission, fetchNextMissionId } from '../services/missionNumbers.js'

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
          {/* empty space saved for the real logo; put an <img> here later */}
          <span className="deploy-logo-placeholder" aria-hidden="true" />
          Hawkeye
        </span>
      </header>

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
