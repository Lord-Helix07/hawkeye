import { useEffect, useState } from 'react'
import './App.css'

const pursuit = {
  status: 'Pursuit Active',
  vehicleSpeed: '72 MPH',
  droneSpeed: '68 MPH',
  route: 'I-880 Northbound',
  unit: 'Drone Falcon-07',
  lastUpdate: 'Live fake data: 9:41 PM',
}

const vehicles = [
  { id: 'car-01', label: 'Car 01', plate: '8TRK221', className: 'box-left' },
  { id: 'car-02', label: 'Car 02', plate: '4NVL902', className: 'box-center' },
  { id: 'car-03', label: 'Car 03', plate: 'JAL13B2', className: 'box-target' },
]

const yoloDetections = [
  { vehicleId: 'car-03', className: 'box-target', confidence: '96%', visible: true, status: 'YOLO11 lock active' },
  { vehicleId: 'car-03', className: 'box-exiting', confidence: '82%', visible: true, status: 'Lock held while vehicle exits frame' },
  { vehicleId: null, className: '', confidence: '0%', visible: false, status: 'Vehicle left frame. Searching...' },
  { vehicleId: 'car-01', className: 'box-left', confidence: '93%', visible: true, status: 'YOLO11 lock active' },
]

const routeSteps = [
  { id: 'step-1', text: '0.5 mi E Reed St' },
  { id: 'step-2', text: '0.5 mi E Reed St' },
  { id: 'step-3', text: '0.5 mi E Reed St' },
]

const droneLocation = {
  latitude: 37.6879,
  longitude: -122.1359,
  top: '43%',
  left: '58%',
}

const droneActions = [
  { id: 'manual-override', label: 'Manual Override', className: 'manual-button', method: 'POST', endpoint: '/api/drone/manual-override' },
  { id: 'return', label: 'Return', className: 'soft-button', method: 'POST', endpoint: '/api/drone/return-to-base' },
  { id: 'land', label: 'Land', className: 'soft-button', method: 'POST', endpoint: '/api/drone/land' },
]

const alertActions = [
  { id: 'review-camera', label: 'Review Camera Feed', method: 'GET', endpoint: '/api/video/review-feed' },
  { id: 'select-target', label: 'Select Target Again', method: 'POST', endpoint: '/api/pursuit/reselect-target' },
  { id: 'recovery-point', label: 'Return To Recovery Point', method: 'POST', endpoint: '/api/drone/recovery-point' },
  { id: 'cancel-pursuit', label: 'Cancel Pursuit', className: 'cancel-button', method: 'POST', endpoint: '/api/pursuit/cancel' },
]

function App() {
  const [detectionIndex, setDetectionIndex] = useState(0)
  const [lastAction, setLastAction] = useState(null)
  const activeDetection = yoloDetections[detectionIndex]
  const detectedVehicle = vehicles.find((vehicle) => vehicle.id === activeDetection.vehicleId)
  const selectedVehicle = activeDetection.visible ? detectedVehicle : null

  useEffect(() => {
    const timer = window.setInterval(() => {
      setDetectionIndex((index) => (index + 1) % yoloDetections.length)
    }, 4500)

    return () => window.clearInterval(timer)
  }, [])

  const buildActionPayload = (action) => ({
    action: action.id,
    pursuitStatus: pursuit.status,
    selectedVehicleId: selectedVehicle?.id ?? null,
    selectedPlate: selectedVehicle?.plate ?? null,
    detectionModel: 'YOLO11 simulated frontend detection',
    yoloLockStatus: activeDetection.status,
    droneUnit: pursuit.unit,
    droneLocation: {
      latitude: droneLocation.latitude,
      longitude: droneLocation.longitude,
    },
  })

  const handleAction = (action) => {
    setLastAction({
      ...action,
      payload: buildActionPayload(action),
      timestamp: new Date().toLocaleTimeString(),
    })
  }

  return (
    <main className="drone-app">
      <header className="browser-bar" aria-label="Application browser header">
        <span className="time">9:41 PM</span>
        <div className="address-bar">https://pursuit.drone.gov/live</div>
        <div className="signal-icons" aria-hidden="true"><span></span><span></span><span></span></div>
      </header>

      <section className="landing-page" aria-label="Police Drone website homepage">
        <div>
          <p>High Speed Chase UI Prototype</p>
          <h1>Police Drone</h1>
          <span>
            Example interface for a police drone that locks onto cars during high-speed chases
            and follows at 60-80 MPH using fake pursuit, dashcam, detection, and map data.
          </span>
          <div className="home-status" data-testid="pursuit-status">
            <strong>{pursuit.status}</strong>
            <span>{pursuit.route}</span>
            <span>{pursuit.vehicleSpeed} target speed</span>
          </div>
        </div>
        <a href="#interfaces">View Interface</a>
      </section>

      <section className="interfaces-intro" id="interfaces">
        <p>Mission Interface</p>
        <h2>Fake pursuit data, YOLO11-style locking, backend-ready actions, and drone map.</h2>
      </section>

      <section className="interface-screen" aria-label="Live pursuit interface">
        <article className="live-card">
          <div className="status-row" data-testid="pursuit-status-panel">
            <div><span>Status</span><strong>{pursuit.status}</strong></div>
            <div><span>Target Speed</span><strong>{pursuit.vehicleSpeed}</strong></div>
            <div><span>Drone Speed</span><strong>{pursuit.droneSpeed}</strong></div>
            <div><span>Assigned Unit</span><strong>{pursuit.unit}</strong></div>
          </div>

          <div className="live-scene video-scene">
            <span className="live-badge">Recorded Dashcam</span>
            <div className="yolo-status" data-testid="yolo11-status">
              <strong>YOLO11</strong>
              <span>{activeDetection.status}</span>
              <span>Confidence: {activeDetection.confidence}</span>
            </div>
            <video className="dashcam-video" controls muted loop playsInline data-testid="dashcam-video">
              <source src="/dashcam-pursuit.webm" type="video/webm" />
              Your browser does not support the pursuit video.
            </video>

            {activeDetection.visible && detectedVehicle && (
              <button
                className={`vehicle-box ${activeDetection.className} selected`}
                type="button"
                aria-pressed="true"
                onClick={() => handleAction({ id: 'confirm-yolo-lock', label: 'Confirm YOLO11 Lock', method: 'POST', endpoint: '/api/detections/confirm-lock' })}
              >
                <span>{detectedVehicle.label} Locked</span>
                <small>YOLO11 {activeDetection.confidence}</small>
              </button>
            )}
          </div>

          <footer className="target-bar">
            <div>
              <span>Target:</span>
              <strong>{selectedVehicle ? selectedVehicle.label : 'Select Vehicle'}</strong>
              <mark>{selectedVehicle ? `[${selectedVehicle.plate}]` : '[NO TARGET]'}</mark>
              <em>{activeDetection.visible ? 'Lock retained until vehicle leaves frame' : 'No car in frame'}</em>
            </div>
            <button
              type="button"
              disabled={!selectedVehicle}
              data-endpoint="/api/drone/deploy"
              onClick={() => handleAction({ id: 'deploy-drone', label: 'Deploy Drone', method: 'POST', endpoint: '/api/drone/deploy' })}
            >
              Deploy Drone
            </button>
          </footer>
        </article>
      </section>

      <section className="interface-screen" aria-label="Route tracking interface">
        <aside className="tracking-panel">
          <div className="map-card">
            <div className="bay-map" aria-label="Route tracking map" data-testid="fake-map">
              <span className="water water-left"></span>
              <span className="water water-right"></span>
              <span className="route-main"></span>
              <span className="route-branch"></span>
              <span className="target-pin">42s</span>
              <span className="drone-marker" data-testid="drone-marker" style={{ top: droneLocation.top, left: droneLocation.left }}>DRONE</span>
              <span className="city city-one">San Francisco</span>
              <span className="city city-two">Oakland</span>
              <span className="city city-three">Hayward</span>
              <span className="legend">Legend<br />Drone highway<br />Vehicle route</span>
            </div>
          </div>

          <div className="right-stack">
            <div className="movement-card">
              <div className="movement-heading">Latest Movement</div>
              {routeSteps.map((step) => <div className="movement-row" key={step.id}><span>↗</span><p>{step.text}</p></div>)}
            </div>
            <div className="update-card"><span>Location Updates</span><strong>Route</strong><p>Heading north on highway 880</p></div>
            <div className="update-card coordinate-card"><span>Drone Coordinates</span><strong>{droneLocation.latitude}, {droneLocation.longitude}</strong><p>Coordinates place the drone marker on the fake map.</p></div>
            <div className="battery-card"><div><span>Drone battery</span><strong>42%</strong></div><progress value="42" max="100">42%</progress></div>
            {droneActions.map((action) => (
              <button className={action.className} data-endpoint={action.endpoint} key={action.id} type="button" onClick={() => handleAction(action)}>{action.label}</button>
            ))}
            <div className="backend-card">
              <span>Backend Hook Preview</span>
              {lastAction ? <><strong>{lastAction.method} {lastAction.endpoint}</strong><p>Last action: {lastAction.label} at {lastAction.timestamp}</p></> : <p>Click any action button to preview the backend request payload.</p>}
            </div>
          </div>
        </aside>
      </section>

      <section className="interface-screen" aria-label="Visual contact lost interface">
        <section className="alert-panel" aria-label="Visual contact lost controls">
          <div className="alert-banner"><strong>Visual Contact Lost</strong><span>Last confirmed sighting 18 seconds ago. Vehicle position no longer updating.</span><small>{pursuit.lastUpdate}</small></div>
          <div className="alert-actions">
            {alertActions.map((action) => <button className={action.className} data-endpoint={action.endpoint} key={action.id} type="button" onClick={() => handleAction(action)}>{action.label}</button>)}
          </div>
        </section>
      </section>

      <section className="payload-screen" aria-label="Backend action payload preview">
        <div className="payload-card">
          <p>Open Ended Backend Integration</p>
          <h2>Buttons are ready to connect to APIs.</h2>
          <span>Each button stores its method, endpoint, and payload in one place. Replace the preview handler with a real fetch call when the backend is ready.</span>
          <pre>{JSON.stringify(lastAction?.payload ?? buildActionPayload({ id: 'waiting-for-action' }), null, 2)}</pre>
        </div>
      </section>
    </main>
  )
}

export default App
