// dashboard page (Flight Status)
//
// Shows one mission's live data. The mission number comes from the URL:
//   /dashboard/HWK-07-2410   (plain /dashboard shows the latest mission started
//   on this computer, or a "no mission yet" note if there isn't one)
// useMissionStatus refreshes the data every 2 seconds; every card just
// displays the props it's given.
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import '../styles/dashboard.css'
import AppHeader from '../components/AppHeader.jsx'
import { useMissionStatus } from '../hooks/useMissionStatus.js'
import { MOCK_MAP_CENTER } from '../services/missionStatus.js'
import { getLastMissionId } from '../services/missionNumbers.js'
import { MapPanel } from '../components/dashboard/MapPanel.jsx'
import { BatteryCard, SpeedCard, TargetCard } from '../components/dashboard/StatCards.jsx'
import { EvidenceCard, FlightLog, GpsCard } from '../components/dashboard/InfoCards.jsx'
import { LaunchControls } from '../components/dashboard/LaunchControls.jsx'
import { formatTime } from '../components/dashboard/format.js'

export default function Dashboard() {
  // no number in the URL: use the last mission started on this computer (null if none)
  const { missionId = getLastMissionId() } = useParams()
  const { status: liveStatus, error, notFound, refresh } = useMissionStatus(missionId)
  const status = liveStatus ?? {} // empty until the server answers
  const telemetry = status.telemetry ?? {} // empty until the drone sends data
  // set by the Deploy page when the automatic launch request didn't go through
  const launchError = useLocation().state?.launchError
  const navigate = useNavigate()

  return (
    <div className="dashboard-page">
      <AppHeader />
      <header className="dashboard-header">
        <h1 className="flight-status-title">Flight Status</h1>
        <div className="dashboard-header-right">
          {/* start a new mission: goes to the Deploy (Target Vehicle) page */}
          <button type="button" className="new-deploy-btn" onClick={() => navigate('/deploy')}>
            Deploy drone <span aria-hidden="true">→</span>
          </button>
          {missionId && !notFound && (
            <LaunchControls missionId={missionId} status={liveStatus} onChange={refresh} />
          )}
          <span className="mission-label">Mission: {missionId ?? '—'}</span>
        </div>
      </header>

      {!missionId && (
        <p className="dashboard-notice" role="status">
          No mission yet. Press Deploy drone to start one.
        </p>
      )}
      {error && (
        <p className="dashboard-alert" role="alert">
          {notFound ? error : `Lost connection to the server: ${error}`}
        </p>
      )}
      {launchError && !status?.launch_status && (
        <p className="dashboard-alert" role="alert">
          Couldn't launch a drone: {launchError}
        </p>
      )}
      {!error && status?.telemetry?.stale && (
        <p className="dashboard-alert" role="alert">
          No signal from {status.drone_id ?? 'the drone'} since {formatTime(telemetry.timestamp)}
        </p>
      )}

      {/* always show every card; each one shows "—" until its data arrives */}
      {!liveStatus && !error && <p className="dashboard-message">Loading mission…</p>}
      {(
        <main className="dashboard-grid">
          {/* ---------- left column ---------- */}
          <section className="left-column">
            <MapPanel
              latitude={telemetry.latitude}
              longitude={telemetry.longitude}
              center={MOCK_MAP_CENTER}
              label="Drone Deployed"
            />

            <div className="stat-row">
              <SpeedCard speedMps={telemetry.speed_mps} />
              <BatteryCard percent={telemetry.battery_pct} />
            </div>

            <TargetCard inFrame={status.target_in_frame} />
          </section>

          {/* ---------- right column ---------- */}
          <section className="right-column">
            <EvidenceCard
              images={status.images}
              lastSeen={status.last_seen}
              trackingStatus={status.tracking_status}
              targetInFrame={status.target_in_frame}
            />
            <GpsCard
              latitude={telemetry.latitude}
              longitude={telemetry.longitude}
              location={status.location}
            />
            <FlightLog entries={status.flight_log} />
          </section>
        </main>
      )}
    </div>
  )
}
