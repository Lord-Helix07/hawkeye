// TEACHING COPY: the original Dashboard, sized with fixed pixels.
// Compare with Dashboard.jsx / dashboard.css, which use fr, flex and aspect-ratio.
// Classes start with fixed- so they don't clash with the real Dashboard's styles.
import '../styles/dashboard-fixed.css'


export default function DashboardFixed() {

  return (
    <div className="fixed-dashboard-page">
      <h1>Flight Status</h1>
      <main>

        <div className="fixed-top-boxes">
    <div className="fixed-map-box">
      <div className="fixed-drone-marker"></div>

      <p className="fixed-drone-text">
        Drone
        <br />
        Deployed
      </p>
    </div>

    <div className="fixed-right-column">
      <div className="fixed-vehicle-box">
        <p className="fixed-box-title">VEHICLE EVIDENCE</p>
        <h3>Last Seen 02:02</h3>
        <h3></h3>
      </div>

      <div className="fixed-gps-box">
        <p className="fixed-box-title">CURRENT GPS LOCATION</p>

        <h3>W San Carlos St</h3>
        <p>San Jose, California</p>

        <p>COORDINATES</p>
        <p>1° N · 2° W</p>

        <p className="fixed-accuracy">ACCURACY</p>
        <p className="fixed-accuracy-value">±2.4 m</p>
      </div>
    </div>
  </div>

    <div className="fixed-bottom1-boxes">
         <div className="fixed-speed-box">
            <p className="fixed-box-title">SPEED</p>

          <h2>
            2 <span>km/h</span>
          </h2>

          <p className="fixed-speed-status">Within normal range</p>

          <div className="fixed-speed-line"></div>
        </div>

        <div className="fixed-battery-box">
          <p className="fixed-box-title">BATTERY</p>

          <h2>20%</h2>

          <p className="fixed-battery-status">Low Battery</p>

          <div className="fixed-battery-line"></div>
        </div>
        <div className="fixed-target-box">
          <p className="fixed-box-title">TARGET IN FRAME</p>
          <h2 className="fixed-target-status">Yes</h2>
        </div>
          
        </div>

    </main>
  </div>

      
  )
}