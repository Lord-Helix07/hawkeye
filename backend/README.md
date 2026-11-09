This backend folder currently contains the initial local development work for object detection, bounding boxes, and database/schema design.

AWS/cloud implementation should NOT be started until the local schema/backend design has been reviewed and approved.

## Running the backend API

All routes (signup, missions, ...) live in ONE FastAPI app: `api.py`.

```bash
cd backend
source ../.venv/bin/activate
uvicorn api:app --reload --port 8000
```

- Check it's up: http://localhost:8000/api/server-status
- See and try every route: http://localhost:8000/api/docs
- New features: put routes in their own file as an `APIRouter`, then add `app.include_router(...)` in `api.py`.
