// The deployed frontend supplies VITE_API_BASE_URL. Local development uses port 8000.
export const API_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'
// The API URL for the backend server.