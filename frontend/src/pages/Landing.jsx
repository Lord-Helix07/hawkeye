// initial page u see
import '../styles/landing.css'
import { useNavigate } from 'react-router-dom'
import { LANDING_BEHIND } from '../hooks/useBackToLanding.js'
import { useState } from 'react'
import { clearSession, getSession } from '../services/session.js'

const imageModules = import.meta.glob('./images/*', {
  eager: true,
  import: 'default',
  query: '?url',
})

const carouselPhotos = Object.entries(imageModules)
  .sort(([firstPath], [secondPath]) => firstPath.localeCompare(secondPath))
  .map(([path, src]) => ({
    src,
    alt: path.split('/').pop().replace(/\.[^/.]+$/, '').replace(/[-_]/g, ' '),
  }))

export default function Landing() {
  const navigate = useNavigate()
  const [activePhoto, setActivePhoto] = useState(0)
  const [loggedIn, setLoggedIn] = useState(() => Boolean(getSession()))

  function logOut() {
    clearSession()
    setLoggedIn(false)
  }

  const showPhoto = (index) => {
    setActivePhoto((index + carouselPhotos.length) % carouselPhotos.length)
  }

  return (
    <div className="landing">
      <header className="landing-header">
        <span className="landing-logo">
          <svg
            className="landing-logo-icon"
            viewBox="0 0 100 100"
            aria-hidden="true"
          >
        <path
         d="
            M50 6
            C54 25 62 38 94 50
           C75 54 63 62 50 94
           C46 75 38 62 6 50
           C25 46 38 38 50 6
           Z
         "
        />
      </svg>
          Hawkeye</span>
        <div className="landing-auth">
          {loggedIn ? (
            <>
              <button className="login-btn" onClick={logOut}>Log out</button>
              <button className="signup-btn" onClick={() => navigate('/dashboard')}>Go to Dashboard</button>
            </>
          ) : (
            <>
              <button className="login-btn" onClick={() => navigate('/login', { state: LANDING_BEHIND })}>Log in</button>
              <button className="signup-btn" onClick={() => navigate('/register', { state: LANDING_BEHIND })}>Sign up</button>
            </>
          )}
        </div>
      </header>

      <main className="landing-hero">
        <h1 className="hero-title">
          The autonomous pursuit drone
          <br />
          for officers and the communities they protect
        </h1>

        <div className="hero-subrow">
          <p className="hero-subtitle">
            Eyes in the sky for every pursuit. Fewer high-speed chases on the streets.
          </p>
       
        </div>
      </main>

      {/* app-window preview */}
      <section className="console" aria-label="Hawkeye mission preview">
        <aside className="console-sidebar">
          <p className="console-brand">Hawkeye</p>
          {['Live feed', 'Missions', 'Drones', 'Alerts'].map((item) => (
            <p key={item} className={item === 'Live feed' ? 'console-item active' : 'console-item'}>
              {item}
            </p>
          ))}
          <p className="console-section">Active Drones</p>
          <p className="console-item">
            <span className="status-dot" /> Drone 1
          </p>
        </aside>

        <div className="console-main">
          <p className="console-crumb">HWK-67-6767 · Live pursuit</p>
          <h2 className="console-title">Target lock: silver sedan, northbound</h2>
          <h3 className="console-heading">Activity</h3>
          <ul className="activity-list">
            <li><span className="activity-time">21:04:12</span><span>Officer input data: [silver sedan], [JLS24K], [northbound]</span></li>
            <li><span className="activity-time">21:06:24</span><span>Hawkeye 1 deployed</span></li>
            <li><span className="activity-time">21:07:48</span><span>Hawkeye reached optimal height</span></li>
          </ul>
          <pre className="code-block">
            <div className="code-line"><span className="code-mark" /> <code>target = vehicle(plate = <span className="code-string">"[JLS24K]"</span>,</code></div>
            <div className="code-line"><span className="code-mark" /> <code>{' '.repeat(17)}color = <span className="code-string">"silver"</span>, body = <span className="code-string">"sedan"</span>)</code></div>
            <div className="code-line"><span className="code-mark" /> <code /></div>
            <div className="code-line"><span className="code-mark" /> <code><span className="code-keyword">for</span> frame <span className="code-keyword">in</span> camera.stream():</code></div>
            <div className="code-line"><span className="code-mark" /> <code>{' '.repeat(4)}<span className="code-keyword">for</span> car <span className="code-keyword">in</span> find_cars(frame):</code></div>
            <div className="code-line removed"><span className="code-mark">-</span> <code>{' '.repeat(8)}<span className="code-keyword">if</span> car.color == target.color:</code></div>
            <div className="code-line added"><span className="code-mark">+</span> <code>{' '.repeat(12)}plate = read_plate(car)</code></div>
            <div className="code-line added"><span className="code-mark">+</span> <code>{' '.repeat(12)}<span className="code-keyword">if</span> plate == target.plate:</code></div>
            <div className="code-line"><span className="code-mark" /> <code>{' '.repeat(16)}drone.lock(car)</code></div>
            <div className="code-line added"><span className="code-mark">+</span> <code>{' '.repeat(8)}<span className="code-keyword">elif</span> looks_like(car, target):</code></div>
            <div className="code-line added"><span className="code-mark">+</span> <code>{' '.repeat(12)}officer.confirm(car)</code></div>
          </pre>
        </div>
      </section>

      <section className="photo-carousel" aria-label="Hawkeye in action">
        <div className="carousel-heading-row">
          <div>
            <h2 className="carousel-title">Meet Our Team</h2>
          </div>
          <p className="carousel-counter" aria-live="polite">
            {String(activePhoto + 1).padStart(2, '0')} <span>/</span> {String(carouselPhotos.length).padStart(2, '0')}
          </p>
        </div>

        <div className="carousel-frame">
          <img
            className="carousel-image"
            src={carouselPhotos[activePhoto].src}
            alt={carouselPhotos[activePhoto].alt}
          />
          <div className="carousel-overlay">
            <div className="carousel-controls">
              <button type="button" className="carousel-button" onClick={() => showPhoto(activePhoto - 1)} aria-label="Previous photo">
                <span aria-hidden="true">←</span>
              </button>
              <button type="button" className="carousel-button" onClick={() => showPhoto(activePhoto + 1)} aria-label="Next photo">
                <span aria-hidden="true">→</span>
              </button>
            </div>
          </div>
        </div>

        <div className="carousel-dots" role="tablist" aria-label="Choose a photo">
          {carouselPhotos.map((photo, index) => (
            <button
              key={photo.src}
              type="button"
              className={`carousel-dot ${index === activePhoto ? 'active' : ''}`}
              onClick={() => showPhoto(index)}
              role="tab"
              aria-selected={index === activePhoto}
              aria-label={`Show photo ${index + 1}`}
            />
          ))}
        </div>
      </section>
      
    </div>

  )
}

