# hawkeye
Police Pursuit Drone Fall 2026 Omicron

## Police Drone Frontend

React + Vite interface for a police drone that tracks vehicles during high-speed chases. It has three screens:

- **Live Pursuit**: pursuit status, recorded dashcam video with an in-browser car tracking box, and a Deploy button that is enabled only while a vehicle is locked.
- **Overhead Mapping**: map with a drone marker placed from its coordinates, movement updates, battery, and drone controls.
- **Visual Contact Loss**: alert and recovery actions.

All data is sample data until the backend is connected.

## Requirements

- Node.js 20.19+ or 22.12+
- npm

## Run Locally

```bash
npm install
npm run dev
```

Open the URL shown in the terminal, usually `http://localhost:5173/`.

## Project Structure

```text
src/
  App.jsx                  Page layout and button handling
  App.css                  Styles
  MockData/mission.js      Sample data and button definitions (method + endpoint)
  hooks/useCarTracking.js  Car tracking overlay for the pursuit video
  services/api.js          All backend requests
public/
  pursuit-video.mp4        Recorded pursuit footage
```

## Connecting the Backend

1. Copy `.env.example` to `.env` and set `VITE_API_BASE_URL` to the backend URL.
2. Without it, requests are mocked and the "Last Command" card shows `mocked`.
3. Button endpoints are defined in `src/MockData/mission.js`. Requests are sent from `src/services/api.js`.
4. To show live data, replace the sample values in `src/MockData/mission.js` with `fetchPursuitStatus()` and `fetchDroneLocation()` from `src/services/api.js`.

`VITE_` variables are included in the browser bundle. Do not put secret API keys in `.env`. Keep them on the backend.

## Build

```bash
npm run build
```
