// initial page u see
import '../styles/landing.css'
import { useNavigate } from 'react-router-dom'

export default function Landing() {
  const navigate = useNavigate()

  return (
    <>
      <header className="landing-header">
        <span className="landing-logo">Hawkeye</span>
        <div className="landing-auth">
          <button className="login-btn" onClick={() => navigate('/login')}>Login</button>
          <button className="signup-btn" onClick={() => navigate('/register')}>Sign up</button>
        </div>
      </header>
      <h1>The Autonomous pursuit drone for officers and the communities they protect</h1>
      <h3>Built to catch fleeing vehicles. Designed to keep chases off the streets. <div className="new-loop">New <span className="gray-text"> Loops &rarr;</span></div></h3>
      <div className="target-selection">
      <h4>Target lock: silver grey sedan, northbound</h4>

      <h5>Activity</h5>
      <p>21:04:12 Officer input data: [silver sedan], [JLS24K], [northbound]</p>
      <p>21:06:24 Hawkeye-02 deployed</p>
      <p>21:07:48 Hawkeye reached optimal height</p>

      <p className="font-mono small-text">target = vehicle(plate = <span className="yellow-text">"[JLS24K]"</span>,</p>
      <p className="font-mono small-text">color = <span className="yellow-text">"[silver]"</span>, body = <span className="yellow-text">"[sedan]"</span>)</p>

      <p className="font-mono small-text"><span className="purple-text">for</span> frame <span className="purple-text">in</span> camera.stream():</p>
      <p className="font-mono small-text"><span className="purple-text">for</span> car <span className="purple-text">in</span> find_cars(frame):</p>
      <p className="font-mono small-text"><span className="purple-text">if</span> car.color == target.color:</p>
      <p className="font-mono small-text">plate = read_plate(car)</p>
      <p className="font-mono small-text"><span className="purple-text">if</span> plate == target.plate:</p>
      <p className="font-mono small-text">drone.ring_sirens()</p>
      <p className="font-mono small-text"><span className="purple-text">elif</span> looks_like(car, target):</p>
      <p className="font-mono small-text">officer.confirm(car)</p>
      </div>
    </>
  )
}