# WasteWise API

First backend slice for account authentication, household-isolated pantry tracking, inventory audit events, and expiry-based Rescue Mode.

## Run locally

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs` for Swagger. The local default is SQLite (`wastewise.db`); set `DATABASE_URL` to a PostgreSQL connection string when the shared database is ready.

## Authentication

Register with `POST /api/v1/auth/register`, copy its `access_token`, then use Swagger's **Authorize** button to enter `Bearer <access_token>`. Pantry, event, and dashboard endpoints are limited to the household created with that account.

Set a long random `JWT_SECRET` before deployment (see `.env.example`).

## Dataset

`food_expiry_tracker.csv` has normalised ML feature columns and a `used_before_expiry` label. It is reserved for the Phase 4 offline model-training pipeline; the current API deliberately uses transparent expiry rules until there is enough real household event data.
