from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .models import InventoryEvent, PantryItem
from .schemas import EventCreate, EventRead, PantryItemCreate, PantryItemRead, PantryItemUpdate
from .services import get_item_or_404, record_event, risk_for, update_item

Base.metadata.create_all(bind=engine)
app = FastAPI(title="WasteWise API", version="0.1.0", openapi_url="/api/v1/openapi.json", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


@app.get("/")
def root():
    return {
        "message": "WasteWise API is running",
        "docs": "/docs",
        "health": "/api/v1/health",
    }


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/pantry-items", response_model=list[PantryItemRead])
def list_pantry_items(db: Session = Depends(get_db)):
    return db.query(PantryItem).order_by(PantryItem.expiry_date.is_(None), PantryItem.expiry_date).all()


@app.post("/api/v1/pantry-items", response_model=PantryItemRead, status_code=201)
def create_pantry_item(payload: PantryItemCreate, db: Session = Depends(get_db)):
    item = PantryItem(
        product_name=payload.product_name.strip(), category=payload.category, quantity_initial=payload.quantity,
        quantity_remaining=payload.quantity, unit=payload.unit, purchase_date=payload.purchase_date,
        expiry_date=payload.expiry_date, storage_location=payload.storage_location,
        price_amount=payload.price.amount if payload.price else None, currency=payload.price.currency if payload.price else None,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@app.get("/api/v1/pantry-items/{item_id}", response_model=PantryItemRead)
def get_pantry_item(item_id: str, db: Session = Depends(get_db)):
    return get_item_or_404(db, item_id)


@app.patch("/api/v1/pantry-items/{item_id}", response_model=PantryItemRead)
def patch_pantry_item(item_id: str, payload: PantryItemUpdate, db: Session = Depends(get_db)):
    return update_item(db, get_item_or_404(db, item_id), payload)


@app.delete("/api/v1/pantry-items/{item_id}", status_code=204)
def delete_pantry_item(item_id: str, db: Session = Depends(get_db)):
    db.delete(get_item_or_404(db, item_id)); db.commit()
    return Response(status_code=204)


@app.post("/api/v1/pantry-items/{item_id}/events", response_model=EventRead, status_code=201)
def create_event(item_id: str, payload: EventCreate, db: Session = Depends(get_db)):
    return record_event(db, get_item_or_404(db, item_id), payload)


@app.get("/api/v1/pantry-items/{item_id}/events", response_model=list[EventRead])
def list_events(item_id: str, db: Session = Depends(get_db)):
    get_item_or_404(db, item_id)
    return db.query(InventoryEvent).filter_by(pantry_item_id=item_id).order_by(InventoryEvent.occurred_at.desc()).all()


@app.get("/api/v1/dashboard/rescue-mode")
def rescue_mode(db: Session = Depends(get_db)):
    candidates = []
    for item in db.query(PantryItem).filter_by(status="active").all():
        score, reasons = risk_for(item, date.today())
        if score >= 0.45:
            candidates.append((item, score, reasons))
    candidates.sort(key=lambda x: x[1], reverse=True)
    items = [{"pantry_item_id": item.id, "product_name": item.product_name, "risk_score": score,
              "risk_band": "high" if score >= .75 else "medium", "reasons": reasons} for item, score, reasons in candidates]
    value = sum((item.price_amount or 0) * (item.quantity_remaining / item.quantity_initial) for item, _, _ in candidates)
    actions = []
    if items:
        names = ", ".join(x["product_name"] for x in items[:3])
        actions.append({"type": "recipe", "title": f"Use {names} soon", "reason": "Prioritizes pantry items approaching expiry"})
    return {"summary": f"{len(items)} items need attention", "estimated_value_at_risk": {"amount": round(value, 2), "currency": "PKR"}, "items": items, "actions": actions}
