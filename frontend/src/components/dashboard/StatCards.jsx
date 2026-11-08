// Speed, Battery and Target-in-frame cards. Each one only shows what it's given.
import { metersPerSecondToKmh } from './format.js'

const MAX_SPEED_KMH = 100 // speed bar is full at this speed
const SPEED_LIMIT_KMH = 80 // above this the speed shows as a warning
const LOW_BATTERY_PERCENT = 20 // same rule as backend/view_drone.py

function ProgressBar({ percent, tone }) {
  const width = Math.min(100, Math.max(0, percent))
  return (
    <div className="bar">
      <div className={`bar-fill ${tone}`} style={{ width: `${width}%` }} />
    </div>
  )
}

// shown before the drone has sent that number
function EmptyStat({ title }) {
  return (
    <div className="card stat-card">
      <p className="box-title">{title}</p>
      <p className="stat-value">—</p>
      <p className="stat-note">No data yet</p>
      <ProgressBar percent={0} tone="good" />
    </div>
  )
}

export function SpeedCard({ speedMps }) {
  if (speedMps == null) return <EmptyStat title="SPEED" />
  const kmh = metersPerSecondToKmh(speedMps)
  const tooFast = kmh > SPEED_LIMIT_KMH
  const tone = tooFast ? 'warn' : 'good'

  return (
    <div className="card stat-card">
      <p className="box-title">SPEED</p>
      <p className="stat-value">
        {Math.round(kmh)} <span className="stat-unit">km/h</span>
      </p>
      <p className={`stat-note ${tone}`}>{tooFast ? 'Above normal range' : 'Within normal range'}</p>
      <ProgressBar percent={(kmh / MAX_SPEED_KMH) * 100} tone={tone} />
    </div>
  )
}

export function BatteryCard({ percent }) {
  if (percent == null) return <EmptyStat title="BATTERY" />
  const low = percent <= LOW_BATTERY_PERCENT
  const tone = low ? 'warn' : 'good'

  return (
    <div className="card stat-card">
      <p className="box-title">BATTERY</p>
      <p className="stat-value">{Math.round(percent)}%</p>
      <p className={`stat-note ${tone}`}>{low ? 'Low Battery' : 'Battery OK'}</p>
      <ProgressBar percent={percent} tone={tone} />
    </div>
  )
}

export function TargetCard({ inFrame }) {
  return (
    <div className="card stat-card">
      <p className="box-title">TARGET IN FRAME</p>
      {inFrame == null ? (
        <p className="target-status">—</p>
      ) : (
        <p className={`target-status ${inFrame ? 'good' : 'warn'}`}>{inFrame ? 'Yes' : 'No'}</p>
      )}
    </div>
  )
}
