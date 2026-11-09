// Launch and landing controls in the Dashboard's top bar.
//
// What shows depends on the mission's launch_status / landing_status:
//   nothing yet, not_ready, failed  -> "Launch drone"
//   requested                        -> waiting for the drone's checks
//   ready                            -> "Confirm takeoff"
// "Land drone" is always shown and clickable (POST /missions/{id}/request-landing);
// the backend only accepts it once launch_status is confirmed/launched.
//   landing requested                -> waiting for the drone
import { useState } from 'react'
import { confirmLaunch, launchMission, requestLanding } from '../../services/launch.js'

const LAUNCH_LABELS = {
  requested: { text: 'Checking drone…', tone: 'pending' },
  ready: { text: 'Ready for takeoff', tone: 'good' },
  not_ready: { text: 'Drone not ready', tone: 'warn' },
  confirmed: { text: 'Taking off…', tone: 'pending' },
  launched: { text: 'In flight', tone: 'good' },
  failed: { text: 'Launch failed', tone: 'warn' },
}

const LANDING_LABELS = {
  requested: { text: 'Landing requested', tone: 'pending' },
  landing: { text: 'Landing…', tone: 'pending' },
  landed: { text: 'Landed', tone: 'good' },
  failed: { text: 'Landing failed', tone: 'warn' },
}

export function LaunchControls({ missionId, status, onChange }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const launch = status?.launch_status ?? null
  const landing = status?.landing_status ?? null
  const canLaunch = status && (!launch || launch === 'not_ready' || launch === 'failed')

  async function run(action) {
    setBusy(true)
    setError('')
    try {
      await action(missionId)
      onChange?.() // refresh the dashboard right away instead of waiting for the next poll
    } catch (err) {
      setError(err.message === 'Failed to fetch' ? 'Could not reach the server.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  function handleLanding() {
    if (window.confirm('Ask the drone to land now?')) run(requestLanding)
  }

  const pill = (landing && LANDING_LABELS[landing]) || (launch && LAUNCH_LABELS[launch])
  const reasons = launch === 'not_ready' ? status.launch_reasons ?? [status.launch_reason] : []

  return (
    <div className="launch-controls">
      <div className="launch-row">
        {status?.drone_id && <span className="launch-drone">{status.drone_id}</span>}
        {pill && <span className={`launch-pill ${pill.tone}`}>{pill.text}</span>}

        {canLaunch && (
          <button className="launch-btn" onClick={() => run(launchMission)} disabled={busy}>
            {launch ? 'Retry launch' : 'Launch drone'}
          </button>
        )}
        {launch === 'ready' && (
          <button className="launch-btn" onClick={() => run(confirmLaunch)} disabled={busy}>
            Confirm takeoff
          </button>
        )}
        {/* always shown and clickable; the backend says why if it can't land right now */}
        <button className="land-btn" onClick={handleLanding} disabled={busy}>
          Land Drone
        </button>
      </div>

      {reasons.filter(Boolean).length > 0 && (
        <p className="launch-note warn">{reasons.filter(Boolean).join(' · ')}</p>
      )}
      {error && (
        <p className="launch-note error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
