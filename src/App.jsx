import { useState } from 'react'
import {
  alertActions,
  deployAction,
  droneActions,
  droneLocation,
  mapBounds,
  pursuit,
  routeSteps,
  target,
} from './MockData/mission'
import { useCarTracking } from './hooks/useCarTracking'
import { runMissionAction } from './services/api'
import './App.css'

// Convert latitude/longitude into a percentage position on the map.
function toMapPosition({ latitude, longitude }, bounds) {
  const top = ((bounds.north - latitude) / (bounds.north - bounds.south)) * 100
  const left = ((longitude - bounds.west) / (bounds.east - bounds.west)) * 100
  return { top: `${top}%`, left: `${left}%` }
}

function App() {
  const { videoRef, canvasRef, carDetected } = useCarTracking()
  const [lastAction, setLastAction] = useState(null)
  const activeTarget = carDetected ? target : null

  const handleAction = async (action) => {
    const payload = {
      action: action.id,
      pursuitStatus: pursuit.status,
      target: activeTarget,
      droneUnit: pursuit.unit,
      droneLocation,
    }
    const record = { ...action, payload, timestamp: new Date().toLocaleTimeString() }
    setLastAction({ ...record, status: 'pending' })

    try {
      const response = await runMissionAction(action, payload)
      setLastAction({ ...record, status: response.mocked ? 'mocked' : 'success', response })
    } catch (error) {
      setLastAction({ ...record, status: 'error', error: error.message })
    }
  }

  const renderActionButton = (action) => (
    <button className={action.className} key={action.id} type="button" onClick={() => handleAction(action)}>
      {action.label}
    </button>
  )

  return (
    <main className="drone-app">
      <header className="browser-bar">
        <span className="time">9:41 PM</span>
        <div className="address-bar">https://pursuit.drone.gov/live</div>
        <div className="signal-icons" aria-hidden="true"><span></span><span></span><span></span></div>
      </header>

      <section className="interface-screen" aria-label="Live pursuit">
        <article className="live-card">
          <p className="section-label">Live Pursuit</p>
          <div className="status-row" data-testid="pursuit-status-panel">
            <div><span>Status</span><strong>{pursuit.status}</strong></div>
            <div><span>Target Speed</span><strong>{pursuit.vehicleSpeed}</strong></div>
            <div><span>Drone Speed</span><strong>{pursuit.droneSpeed}</strong></div>
            <div><span>Assigned Unit</span><strong>{pursuit.unit}</strong></div>
          </div>

          <div className="live-scene">
            <span className="live-badge">Recorded Video</span>
            <span className="tracking-badge">{carDetected ? 'Target acquired' : 'Searching'}</span>
            <video ref={videoRef} className="dashcam-video" controls muted loop playsInline data-testid="dashcam-video">
              <source src="/pursuit-video.mp4" type="video/mp4" />
              Your browser does not support the pursuit video.
            </video>
            <canvas ref={canvasRef} className="tracking-overlay" aria-hidden="true"></canvas>
          </div>

          <footer className="target-bar">
            <div>
              <span>Target:</span>
              <strong>{activeTarget ? activeTarget.label : 'No target'}</strong>
              <mark>{activeTarget ? `[${activeTarget.plate}]` : '[NO TARGET]'}</mark>
              <em>{carDetected ? 'Vehicle locked' : 'Searching for vehicle'}</em>
            </div>
            <button type="button" disabled={!activeTarget} onClick={() => handleAction(deployAction)}>
              {deployAction.label}
            </button>
          </footer>
        </article>
      </section>

      <section className="interface-screen" aria-label="Overhead mapping">
        <div className="tracking-panel">
          <p className="section-label panel-label">Overhead Mapping</p>
          <div className="map-card">
            <div className="bay-map" data-testid="fake-map">
              <span className="water water-left"></span>
              <span className="water water-right"></span>
              <span className="route-main"></span>
              <span className="route-branch"></span>
              <span className="target-pin">42s</span>
              <span className="drone-marker" data-testid="drone-marker" style={toMapPosition(droneLocation, mapBounds)}>DRONE</span>
              <span className="city city-one">San Francisco</span>
              <span className="city city-two">Oakland</span>
              <span className="city city-three">Hayward</span>
              <span className="legend">Legend<br />Drone highway<br />Vehicle route</span>
            </div>
          </div>

          <div className="right-stack">
            <div className="movement-card">
              <div className="movement-heading">Latest Movement</div>
              {routeSteps.map((step) => (
                <div className="movement-row" key={step.id}><span>{step.icon}</span><p>{step.text}</p></div>
              ))}
            </div>
            <div className="update-card">
              <span>Location Updates</span>
              <strong>Route</strong>
              <p>{pursuit.route}</p>
            </div>
            <div className="update-card coordinate-card">
              <span>Drone Coordinates</span>
              <strong>{droneLocation.latitude}, {droneLocation.longitude}</strong>
            </div>
            <div className="battery-card">
              <div><span>Drone battery</span><strong>{pursuit.battery}%</strong></div>
              <progress value={pursuit.battery} max="100">{pursuit.battery}%</progress>
            </div>
            {droneActions.map(renderActionButton)}
            <div className="backend-card">
              <span>Last Command</span>
              {lastAction ? (
                <>
                  <strong>{lastAction.method} {lastAction.endpoint}</strong>
                  <p>{lastAction.label} · {lastAction.status} · {lastAction.timestamp}</p>
                  {lastAction.error && <p>{lastAction.error}</p>}
                </>
              ) : (
                <p>No commands sent yet.</p>
              )}
            </div>
          </div>
        </div>
      </section>

      <section className="interface-screen" aria-label="Visual contact loss">
        <div className="alert-panel">
          <p className="section-label panel-label">Visual Contact Loss</p>
          <div className="alert-banner">
            <strong>Visual Contact Lost</strong>
            <span>Last confirmed sighting 18 seconds ago. Vehicle position no longer updating.</span>
            <small>{pursuit.lastUpdate}</small>
          </div>
          <div className="alert-actions">{alertActions.map(renderActionButton)}</div>
        </div>
      </section>
    </main>
  )
}

export default App
