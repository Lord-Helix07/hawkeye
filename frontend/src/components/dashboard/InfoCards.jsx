// Right-column cards: Vehicle evidence, GPS location and Flight log.
import { formatCoordinates, formatTime } from './format.js'

const LOG_ROWS = 12 // rows the log shows; empty ones fill the space

export function EvidenceCard({ images, lastSeen, trackingStatus, targetInFrame }) {
  const active = trackingStatus === 'active'

  return (
    <div className="card">
      <div className="card-header">
        <p className="box-title">VEHICLE EVIDENCE</p>
        <span className={`badge ${targetInFrame ? '' : 'badge-muted'}`}>
          {targetInFrame ? 'TARGET DETECTED' : 'SEARCHING'}
        </span>
      </div>
      <div className="card-body">
        <div className="evidence-images">
          {images.slice(0, 2).map((image, i) =>
            image.url ? (
              <img key={image.media_id} className="evidence-image" src={image.url} alt={`Vehicle frame ${i + 1}`} />
            ) : (
              <div key={image.media_id} className="evidence-image">No image yet</div>
            ),
          )}
        </div>
        <div className="detail-row">
          <span className="detail-label">LAST SEEN</span>
          <span>{formatTime(lastSeen)}</span>
        </div>
        <div className="detail-row">
          <span className="detail-label">TRACKING STATUS</span>
          <span className={active ? 'good' : 'warn'}>{active ? 'Active' : 'Searching'}</span>
        </div>
      </div>
    </div>
  )
}

export function GpsCard({ latitude, longitude, location }) {
  return (
    <div className="card">
      <div className="card-header">
        <p className="box-title">CURRENT GPS LOCATION</p>
      </div>
      <div className="card-body">
        <p className="gps-street">{location?.street ?? 'Unknown street'}</p>
        <p className="gps-city">{location?.city ?? ''}</p>
        <p className="detail-label">COORDINATES</p>
        <p className="gps-value">{formatCoordinates(latitude, longitude)}</p>
        <p className="detail-label">ACCURACY</p>
        <p className="gps-value good">{location?.accuracy_m != null ? `±${location.accuracy_m} m` : '—'}</p>
      </div>
    </div>
  )
}

export function FlightLog({ entries }) {
  const emptyRows = Math.max(0, LOG_ROWS - entries.length)

  return (
    <div className="card flight-log">
      <div className="card-header">
        <p className="box-title">FLIGHT LOG</p>
      </div>
      <ul className="log-list">
        {entries.map((entry) => (
          <li key={`${entry.time}-${entry.message}`} className="log-row">
            <span className="log-time">{formatTime(entry.time)}</span>
            <span>{entry.message}</span>
          </li>
        ))}
        {Array.from({ length: emptyRows }, (_, i) => (
          <li key={`empty-${i}`} className="log-row" />
        ))}
      </ul>
    </div>
  )
}
