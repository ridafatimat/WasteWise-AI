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


def test_pantry_event_and_rescue_mode():
    created = client.post("/api/v1/pantry-items", json={"product_name": "Milk", "quantity": 1, "unit": "litre", "purchase_date": "2026-07-16", "expiry_date": "2026-07-17"})
    assert created.status_code == 201
    item_id = created.json()["id"]
    event = client.post(f"/api/v1/pantry-items/{item_id}/events", json={"event_type": "consumed", "quantity": .5})
    assert event.status_code == 201
    assert client.get(f"/api/v1/pantry-items/{item_id}").json()["quantity_remaining"] == .5
    rescue = client.get("/api/v1/dashboard/rescue-mode")
    assert rescue.status_code == 200
    assert rescue.json()["items"][0]["product_name"] == "Milk"


def test_rejects_expiry_before_purchase():
    response = client.post("/api/v1/pantry-items", json={"product_name": "Yogurt", "quantity": 1, "unit": "pack", "purchase_date": "2026-07-16", "expiry_date": "2026-07-15"})
    assert response.status_code == 422
