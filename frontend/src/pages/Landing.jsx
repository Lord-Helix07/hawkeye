// initial page u see
import '../styles/landing.css'
import { useNavigate } from 'react-router-dom'

const activity = [
  { time: '21:04:12', text: 'Officer input data: [silver sedan], [JLS24K], [northbound]' },
  { time: '21:06:24', text: 'Hawkeye-02 deployed' },
  { time: '21:07:48', text: 'Hawkeye reached optimal height' },
]

// small helpers to color the code preview
const K = ({ children }) => <span className="code-keyword">{children}</span>
const S = ({ children }) => <span className="code-string">{children}</span>

// mark: '+' added line, '-' removed line, '' unchanged. indent = number of spaces
const codeLines = [
  { mark: '', indent: 0, code: <>target = vehicle(plate = <S>"[JLS24K]"</S>,</> },
  { mark: '', indent: 17, code: <>color = <S>"silver"</S>, body = <S>"sedan"</S>)</> },
  { mark: '', indent: 0, code: '' },
  { mark: '', indent: 0, code: <><K>for</K> frame <K>in</K> camera.stream():</> },
  { mark: '', indent: 4, code: <><K>for</K> car <K>in</K> find_cars(frame):</> },
  { mark: '-', indent: 8, code: <><K>if</K> car.color == target.color:</> },
  { mark: '+', indent: 12, code: <>plate = read_plate(car)</> },
  { mark: '+', indent: 12, code: <><K>if</K> plate == target.plate:</> },
  { mark: '', indent: 16, code: <>drone.lock(car)</> },
  { mark: '+', indent: 8, code: <><K>elif</K> looks_like(car, target):</> },
  { mark: '+', indent: 12, code: <>officer.confirm(car)</> },
]

const sidebarItems = ['Live feed', 'Missions', 'Drones', 'Alerts']

export default function Landing() {
  const navigate = useNavigate()

  return (
    <div className="landing">
      <header className="landing-header">
        <span className="landing-logo">Hawkeye</span>
        <div className="landing-auth">
          <button className="login-btn" onClick={() => navigate('/login')}>Log in</button>
          <button className="signup-btn" onClick={() => navigate('/register')}>Sign up</button>
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
          {sidebarItems.map((item) => (
            <p key={item} className={item === 'Live feed' ? 'console-item active' : 'console-item'}>
              {item}
            </p>
          ))}
          <p className="console-section">Active drones</p>
          <p className="console-item">
            <span className="status-dot" /> Hawkeye-02
          </p>
        </aside>

        <div className="console-main">
          <p className="console-crumb">HWK-07-2410 · Live pursuit</p>

          <h2 className="console-title">Target lock: silver sedan, northbound</h2>

          <h3 className="console-heading">Activity</h3>
          <ul className="activity-list">
            {activity.map((entry) => (
              <li key={entry.time}>
                <span className="activity-time">{entry.time}</span>
                <span>{entry.text}</span>
              </li>
            ))}
          </ul>

          <pre className="code-block">
            {codeLines.map((line, i) => (
              <div key={i} className={`code-line ${line.mark === '+' ? 'added' : ''} ${line.mark === '-' ? 'removed' : ''}`}>
                <span className="code-mark">{line.mark}</span>
                <code>
                  {' '.repeat(line.indent)}
                  {line.code}
                </code>
              </div>
            ))}
          </pre>
        </div>
      </section>
    </div>
  )
}
