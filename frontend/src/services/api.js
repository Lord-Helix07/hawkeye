// Where the backend lives.
//   - Local dev (npm run dev): uses http://localhost:8000 automatically.
//   - Deployed site (fly-hawkeye.com): uses /api on the same domain, set in
//     frontend/.env.production. Vercel sends /api/* to the backend.
// (Run the backend locally with: cd backend && uvicorn api:app --reload --port 8000)
export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
