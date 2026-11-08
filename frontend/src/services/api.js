// Where the backend lives.
//   - Local dev (npm run dev): uses http://localhost:8000 automatically.
//   - Deployed site (fly-hawkeye.com): set VITE_API_URL=https://api.fly-hawkeye.com
//     in Amplify's environment variables (or in frontend/.env.production).
// (Run the backend locally with: cd backend && uvicorn api:app --reload --port 8000)
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
