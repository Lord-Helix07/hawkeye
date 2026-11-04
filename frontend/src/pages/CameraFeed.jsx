// TESTING PAGE: shows a live camera view, to check cameras work before a mission.
//
// Two sources:
//   1. "This computer"  - the laptop webcam or a plugged-in USB camera (browser camera access)
//   2. "Stream URL"     - an MJPEG stream, the usual format for a Raspberry Pi camera,
//                         e.g. http://raspberrypi.local:8000/stream.mjpg
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import '../styles/camera.css'

// turns the browser's camera errors into something readable
function cameraErrorMessage(err) {
  if (err.name === 'NotAllowedError') return 'Camera permission was denied. Allow camera access in the browser and try again.'
  if (err.name === 'NotFoundError') return 'No camera found. Plug one in and try again.'
  if (err.name === 'NotReadableError') return 'The camera is already being used by another app.'
  return `Could not start the camera: ${err.message}`
}

export default function CameraFeed() {
  const navigate = useNavigate()
  const videoRef = useRef(null)
  const streamRef = useRef(null) // the running webcam stream, so we can stop it

  const [source, setSource] = useState('device') // 'device' or 'url'
  const [devices, setDevices] = useState([]) // cameras plugged into this computer
  const [deviceId, setDeviceId] = useState('')
  const [streamUrl, setStreamUrl] = useState('')
  const [activeUrl, setActiveUrl] = useState('') // the URL actually being shown
  const [live, setLive] = useState(false)
  const [error, setError] = useState('')

  function stopCamera() {
    streamRef.current?.getTracks().forEach((track) => track.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setActiveUrl('')
    setLive(false)
  }

  // always turn the camera off when leaving the page
  useEffect(() => stopCamera, [])

  async function startDeviceCamera(id = deviceId) {
    stopCamera()
    setError('')
    if (!navigator.mediaDevices?.getUserMedia) {
      setError('This browser cannot access cameras. Open the app at http://localhost:5173.')
      return
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: id ? { deviceId: { exact: id } } : true,
        audio: false,
      })
      streamRef.current = stream
      videoRef.current.srcObject = stream
      setLive(true)

      // camera names are only available after permission is given
      const all = await navigator.mediaDevices.enumerateDevices()
      setDevices(all.filter((d) => d.kind === 'videoinput'))
      setDeviceId(stream.getVideoTracks()[0]?.getSettings().deviceId ?? id)
    } catch (err) {
      setError(cameraErrorMessage(err))
    }
  }

  function startStream() {
    stopCamera()
    setError('')
    const url = streamUrl.trim()
    if (!url) {
      setError('Enter the camera stream URL first.')
      return
    }
    setActiveUrl(url)
  }

  function switchSource(next) {
    stopCamera()
    setError('')
    setSource(next)
  }

  return (
    <div className="camera-page">
      <header className="camera-header">
        <span className="camera-logo">Hawkeye</span>
        <button className="camera-back" onClick={() => navigate('/deploy')}>
          ← Back to Deploy
        </button>
      </header>

      <main className="camera-main">
        <div className="camera-title-row">
      
          <span className={`camera-status ${live ? 'is-live' : ''}`}>
            <span className="camera-status-dot" aria-hidden="true" />
            {live ? 'LIVE' : 'OFF'}
          </span>
        </div>
       

        {/* the video itself */}
        <div className="camera-view">
          <video
            ref={videoRef}
            className={`camera-video ${source === 'device' && live ? '' : 'is-hidden'}`}
            autoPlay
            playsInline
            muted
          />
          {source === 'url' && activeUrl && (
            <img
              className="camera-video"
              src={activeUrl}
              alt="Live drone camera stream"
              onLoad={() => setLive(true)}
              onError={() => {
                setLive(false)
                setActiveUrl('') // back to "Camera is off" so they can fix the URL and retry
                setError('Could not load the stream. Check the URL and that the camera is streaming.')
              }}
            />
          )}
          {!live && !(source === 'url' && activeUrl) && <p className="camera-placeholder">Camera is off</p>}
        </div>

        {/* controls */}
        <div className="camera-controls">
          <div className="camera-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={source === 'device'}
              className={source === 'device' ? 'active' : ''}
              onClick={() => switchSource('device')}
            >
              This computer
            </button>
            <button
              role="tab"
              aria-selected={source === 'url'}
              className={source === 'url' ? 'active' : ''}
              onClick={() => switchSource('url')}
            >
              Stream URL
            </button>
          </div>

          {source === 'device' ? (
            <div className="camera-row">
              {devices.length > 1 && (
                <select
                  className="camera-input"
                  value={deviceId}
                  onChange={(e) => {
                    setDeviceId(e.target.value)
                    startDeviceCamera(e.target.value)
                  }}
                >
                  {devices.map((d, i) => (
                    <option key={d.deviceId} value={d.deviceId}>
                      {d.label || `Camera ${i + 1}`}
                    </option>
                  ))}
                </select>
              )}
              {live ? (
                <button className="camera-btn" onClick={stopCamera}>Stop camera</button>
              ) : (
                <button className="camera-btn primary" onClick={() => startDeviceCamera()}>Start camera</button>
              )}
            </div>
          ) : (
            <form
              className="camera-row"
              onSubmit={(e) => {
                e.preventDefault()
                startStream()
              }}
            >
              <input
                className="camera-input grow"
                placeholder="http://raspberrypi.local:8000/stream.mjpg"
                value={streamUrl}
                onChange={(e) => setStreamUrl(e.target.value)}
              />
              {activeUrl ? (
                <button type="button" className="camera-btn" onClick={stopCamera}>Disconnect</button>
              ) : (
                <button type="submit" className="camera-btn primary">Connect</button>
              )}
            </form>
          )}

          {error && (
            <p className="camera-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </main>
    </div>
  )
}
