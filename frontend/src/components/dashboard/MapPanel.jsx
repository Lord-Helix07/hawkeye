// The big map. For now it's a placeholder grid and the marker moves by
// converting latitude/longitude into a position on the box.
// Later: swap this for a real map library (e.g. react-leaflet) using the same props.
import { formatCoordinates } from './format.js'

// how many degrees fit across the placeholder box
const SPAN = { latitude: 0.009, longitude: 0.012 }

// position on the box as a percent (50% = center), kept away from the edges
function toPercent(value, center, span, min, max) {
  const percent = 50 + ((value - center) / span) * 100
  return Math.min(max, Math.max(min, percent))
}

export function MapPanel({ latitude, longitude, center, label = 'Drone' }) {
  const left = toPercent(longitude, center.longitude, SPAN.longitude, 8, 92)
  // north is up; leaves room at the bottom for the label under the dot
  const top = 100 - toPercent(latitude, center.latitude, SPAN.latitude, 15, 92)

  return (
    <div className="map-box">
      <div className="drone-pin" style={{ left: `${left}%`, top: `${top}%` }}>
        <div className="drone-marker" />
        <p className="drone-text">{label}</p>
      </div>
      <p className="map-coords">{formatCoordinates(latitude, longitude)}</p>
    </div>
  )
}
