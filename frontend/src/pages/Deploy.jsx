// page to launch the drone
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/deploy.css'

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

  // placeholder until the backend creates real mission IDs
  const missionId = 'HWK-07-2410'

  function handleChange(e) {
    setForm({ ...form, [e.target.name]: e.target.value })
  }

  function handleDeploy(e) {
    e.preventDefault()
    // TODO: send `form` to the backend to start the mission
    navigate('/dashboard')
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
          <h1>Target vehicle</h1>
          <p>Provide details below to start mission</p>
          <span className="mission-id">
            MISSION: <strong>{missionId}</strong>
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

          <div className="deploy-actions">
            <button type="button" className="clear-btn" onClick={() => setForm(emptyForm)}>
              Clear
            </button>
            <button type="submit" className="deploy-btn">
              Deploy Drone <span aria-hidden="true">→</span>
            </button>
          </div>
        </form>
      </main>
    </>
  )
}
