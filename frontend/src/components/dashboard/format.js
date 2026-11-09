// Small helpers for turning raw data into what the cards display.

// "2026-11-04T21:41:05Z" -> "21:41:05"
export function formatTime(isoString) {
  if (!isoString) return '—'
  return new Date(isoString).toLocaleTimeString([], { hour12: false })
}

// 37.3352, -121.8811 -> "37.3352° N · 121.8811° W"
export function formatCoordinates(latitude, longitude) {
  if (latitude == null || longitude == null) return '—'
  const ns = latitude >= 0 ? 'N' : 'S'
  const ew = longitude >= 0 ? 'E' : 'W'
  return `${Math.abs(latitude).toFixed(4)}° ${ns} · ${Math.abs(longitude).toFixed(4)}° ${ew}`
}

// the database stores meters per second; the page shows km/h
export function metersPerSecondToKmh(speedMps) {
  return speedMps * 3.6
}
