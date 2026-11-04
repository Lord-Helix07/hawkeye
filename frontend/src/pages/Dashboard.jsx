// dashboard page (Flight Status)
//
// Shows one mission's live data. The mission number comes from the URL:
//   /dashboard/0001   (plain /dashboard shows the latest mission started)
// useMissionStatus refreshes the data every 2 seconds; every card just
// displays the props it's given.
import { useParams } from 'react-router-dom'
import '../styles/dashboard.css'
import { useMissionStatus } from '../hooks/useMissionStatus.js'
import { MOCK_MAP_CENTER } from '../services/missionStatus.js'
import { getLastMissionId } from '../services/missionNumbers.js'
import { MapPanel } from '../components/dashboard/MapPanel.jsx'
import { BatteryCard, SpeedCard, TargetCard } from '../components/dashboard/StatCards.jsx'
import { EvidenceCard, FlightLog, GpsCard } from '../components/dashboard/InfoCards.jsx'

export default function Dashboard() {
  // no number in the URL: use the last mission started on this computer (or 0001)
  const { missionId = getLastMissionId() ?? '0001' } = useParams()
  const { status, error } = useMissionStatus(missionId)

  return (
    <div className="dashboard-page">
      <header className="dashboard-header">
        <h1 className="flight-status-title">Flight Status</h1>
        <span className="mission-label">Mission: {missionId}</span>
      </header>

      {error && (
        <p className="dashboard-alert" role="alert">
          Lost connection to the drone: {error}
        </p>
      )}

      {/* nothing has arrived yet */}
      {!status ? (
        <p className="dashboard-message">Waiting for telemetry…</p>
      ) : (
        <main className="dashboard-grid">
          {/* ---------- left column ---------- */}
          <section className="left-column">
            <MapPanel
              latitude={status.telemetry.latitude}
              longitude={status.telemetry.longitude}
              center={MOCK_MAP_CENTER}
              label="Drone Deployed"
            />

            <div className="stat-row">
              <SpeedCard speedMps={status.telemetry.speed_mps} />
              <BatteryCard percent={status.telemetry.battery_pct} />
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
              latitude={status.telemetry.latitude}
              longitude={status.telemetry.longitude}
              location={status.location}
            />
            <FlightLog entries={status.flight_log} />
          </section>
        </main>
      )}
    </div>
  )
}
