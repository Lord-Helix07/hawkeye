// dashboard page
import '../styles/dashboard.css'


export default function dashboard() {

  return (
    <div className ="dashboard-page">
      <h1>Flight Status</h1>
      <main>

        <div className="top-boxes">
    <div className="map-box">
      <div className="drone-marker"></div>

      <p className="drone-text">
        Drone
        <br />
        Deployed
      </p>
    </div>

    <div className="right-column">
      <div className="vehicle-box">
        <p className="box-title">VEHICLE EVIDENCE</p>
        <h3>Last Seen 02:02</h3>
        <h3></h3>
      </div>

      <div className="gps-box">
        <p className="box-title">CURRENT GPS LOCATION</p>

        <h3>W San Carlos St</h3>
        <p>San Jose, California</p>

        <p>COORDINATES</p>
        <p>1° N · 2° W</p>

        <p className="accuracy">ACCURACY</p>
        <p className="accuracy-value">±2.4 m</p>
      </div>
    </div>
  </div>

    <div className="bottom1-boxes">
         <div className="speed-box">
            <p className="box-title">SPEED</p>

          <h2>
            2 <span>km/h</span>
          </h2>

          <p className="speed-status">Within normal range</p>

          <div className="speed-line"></div>
        </div>

        <div className="battery-box">
          <p className="box-title">BATTERY</p>

          <h2>20%</h2>

          <p className="battery-status">Low Battery</p>

          <div className="battery-line"></div>
        </div>
        <div className="target-box">
          <p className="box-title">TARGET IN FRAME</p>
          <h2 className ="target-status">Yes</h2>
        </div>
          
        </div>

    </main>
  </div>

      
  )
}