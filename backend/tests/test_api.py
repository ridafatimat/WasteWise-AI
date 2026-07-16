import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{tempfile.gettempdir()}/wastewise-test.db"

from fastapi.testclient import TestClient
from app.database import Base, engine
from app.main import app


client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def auth_headers():
    response = client.post("/api/v1/auth/register", json={"name": "Rida", "email": "rida@example.com", "password": "safe-password", "household_name": "Rida's home"})
    assert response.status_code == 201
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_pantry_event_and_rescue_mode():
    headers = auth_headers()
    created = client.post("/api/v1/pantry-items", headers=headers, json={"product_name": "Milk", "quantity": 1, "unit": "litre", "purchase_date": "2026-07-16", "expiry_date": "2026-07-17"})
    assert created.status_code == 201
    item_id = created.json()["id"]
    event = client.post(f"/api/v1/pantry-items/{item_id}/events", headers=headers, json={"event_type": "consumed", "quantity": .5})
    assert event.status_code == 201
    assert client.get(f"/api/v1/pantry-items/{item_id}", headers=headers).json()["quantity_remaining"] == .5
    rescue = client.get("/api/v1/dashboard/rescue-mode", headers=headers)
    assert rescue.status_code == 200
    assert rescue.json()["items"][0]["product_name"] == "Milk"
    prediction = client.get("/api/v1/predictions/waste-risk", headers=headers)
    assert prediction.status_code == 200
    payload = prediction.json()[0]
    assert payload["model_version"] in {"rules-v1", "logistic-regression-v1", "xgboost-v1"}
    assert 0 <= payload["risk_score"] <= 1


def test_rejects_expiry_before_purchase():
    response = client.post("/api/v1/pantry-items", headers=auth_headers(), json={"product_name": "Yogurt", "quantity": 1, "unit": "pack", "purchase_date": "2026-07-16", "expiry_date": "2026-07-15"})
    assert response.status_code == 422


def test_pantry_requires_authentication():
    assert client.get("/api/v1/pantry-items").status_code == 403
