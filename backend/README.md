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

## Who can register: the approved badge list

Only badge numbers on the approved list (DynamoDB table `ApprovedBadges`) can
register or log in. Hand out approved badge numbers to officers; anyone else
gets "This badge number isn't approved" on the Register page.

```bash
cd backend
python website/manage_badges.py add 1234 5678      # approve badges (any email can register them)
python website/manage_badges.py list               # what's approved, who has registered
python website/manage_badges.py remove 1234        # stop badge 1234 registering or logging in
python website/manage_badges.py approve-existing   # approve every badge that already has an account
```

After deploying this, run `approve-existing` once so current accounts can
still log in.
