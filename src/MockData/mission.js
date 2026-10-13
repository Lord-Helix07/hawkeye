// Sample data shown until the backend provides live values.
// Replace these with responses from src/services/api.js.

export const pursuit = {
  status: 'Pursuit Active',
  vehicleSpeed: '72 MPH',
  droneSpeed: '68 MPH',
  route: 'Heading north on highway 880',
  unit: 'Drone Falcon-07',
  battery: 42,
  lastUpdate: 'Last update: 9:41 PM',
}

export const target = {
  label: 'Car 03',
  plate: 'JAL13B2',
}

export const routeSteps = [
  { id: 'step-1', icon: '↑', text: '0.5 mi · E Reed St' },
  { id: 'step-2', icon: '↰', text: '0.3 mi · N 1st St' },
  { id: 'step-3', icon: '↱', text: '0.8 mi · I-880 N on-ramp' },
]

export const droneLocation = {
  latitude: 37.6879,
  longitude: -122.1359,
}

// Geographic area covered by the overhead map, used to place markers.
export const mapBounds = {
  north: 37.95,
  south: 37.34,
  west: -122.55,
  east: -121.85,
}

export const deployAction = {
  id: 'deploy-drone',
  label: 'Deploy Drone',
  method: 'POST',
  endpoint: '/api/drone/deploy',
}

export const droneActions = [
  { id: 'manual-override', label: 'Manual Override', className: 'manual-button', method: 'POST', endpoint: '/api/drone/manual-override' },
  { id: 'return', label: 'Return', className: 'soft-button', method: 'POST', endpoint: '/api/drone/return-to-base' },
  { id: 'land', label: 'Land', className: 'soft-button', method: 'POST', endpoint: '/api/drone/land' },
]

export const alertActions = [
  { id: 'review-camera', label: 'Review Camera Feed', method: 'GET', endpoint: '/api/video/review-feed' },
  { id: 'select-target', label: 'Select Target Again', method: 'POST', endpoint: '/api/pursuit/reselect-target' },
  { id: 'recovery-point', label: 'Return To Recovery Point', method: 'POST', endpoint: '/api/drone/recovery-point' },
  { id: 'cancel-pursuit', label: 'Cancel Pursuit', className: 'cancel-button', method: 'POST', endpoint: '/api/pursuit/cancel' },
]
