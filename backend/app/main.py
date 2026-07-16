from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Response, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from .database import Base, engine, get_db
from .auth import create_access_token, get_current_household_id, get_current_user, hash_password, verify_password
from .models import Household, HouseholdMember, InventoryEvent, PantryItem, User
from .ml import predict_risk
from .schemas import EventCreate, EventRead, LoginRequest, PantryItemCreate, PantryItemRead, PantryItemUpdate, RegisterRequest, TokenRead, UserRead
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


@app.post("/api/v1/auth/register", response_model=TokenRead, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if db.query(User).filter_by(email=email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    user = User(name=payload.name.strip(), email=email, password_hash=hash_password(payload.password))
    household = Household(name=payload.household_name.strip())
    db.add_all([user, household])
    db.flush()
    db.add(HouseholdMember(user_id=user.id, household_id=household.id, role="owner"))
    db.commit()
    return TokenRead(access_token=create_access_token(user))


@app.post("/api/v1/auth/login", response_model=TokenRead)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=payload.email.strip().lower()).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password", {"WWW-Authenticate": "Bearer"})
    return TokenRead(access_token=create_access_token(user))


@app.get("/api/v1/auth/me", response_model=UserRead)
def me(user: User = Depends(get_current_user)):
    return user


@app.get("/api/v1/pantry-items", response_model=list[PantryItemRead])
def list_pantry_items(household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    return db.query(PantryItem).filter_by(household_id=household_id).order_by(PantryItem.expiry_date.is_(None), PantryItem.expiry_date).all()


@app.post("/api/v1/pantry-items", response_model=PantryItemRead, status_code=201)
def create_pantry_item(payload: PantryItemCreate, household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    item = PantryItem(
        product_name=payload.product_name.strip(), category=payload.category, quantity_initial=payload.quantity,
        quantity_remaining=payload.quantity, unit=payload.unit, purchase_date=payload.purchase_date,
        expiry_date=payload.expiry_date, storage_location=payload.storage_location,
        price_amount=payload.price.amount if payload.price else None, currency=payload.price.currency if payload.price else None, household_id=household_id,
    )
    db.add(item); db.commit(); db.refresh(item)
    return item


@app.get("/api/v1/pantry-items/{item_id}", response_model=PantryItemRead)
def get_pantry_item(item_id: str, household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    if item.household_id != household_id: raise HTTPException(404, "Pantry item not found")
    return item


@app.patch("/api/v1/pantry-items/{item_id}", response_model=PantryItemRead)
def patch_pantry_item(item_id: str, payload: PantryItemUpdate, household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    if item.household_id != household_id: raise HTTPException(404, "Pantry item not found")
    return update_item(db, item, payload)


@app.delete("/api/v1/pantry-items/{item_id}", status_code=204)
def delete_pantry_item(item_id: str, household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    if item.household_id != household_id: raise HTTPException(404, "Pantry item not found")
    db.delete(item); db.commit()
    return Response(status_code=204)


@app.post("/api/v1/pantry-items/{item_id}/events", response_model=EventRead, status_code=201)
def create_event(item_id: str, payload: EventCreate, household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    if item.household_id != household_id: raise HTTPException(404, "Pantry item not found")
    return record_event(db, item, payload)


@app.get("/api/v1/pantry-items/{item_id}/events", response_model=list[EventRead])
def list_events(item_id: str, household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    item = get_item_or_404(db, item_id)
    if item.household_id != household_id: raise HTTPException(404, "Pantry item not found")
    return db.query(InventoryEvent).filter_by(pantry_item_id=item_id).order_by(InventoryEvent.occurred_at.desc()).all()


@app.get("/api/v1/dashboard/rescue-mode")
def rescue_mode(household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    candidates = []
    for item in db.query(PantryItem).filter_by(status="active", household_id=household_id).all():
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


@app.get("/api/v1/predictions/waste-risk")
def waste_risk_predictions(household_id: str = Depends(get_current_household_id), db: Session = Depends(get_db)):
    predictions = []
    for item in db.query(PantryItem).filter_by(status="active", household_id=household_id).all():
        score, model_version, reasons = predict_risk(item, date.today())
        predictions.append({"pantry_item_id": item.id, "product_name": item.product_name, "risk_score": score,
                            "risk_band": "high" if score >= .75 else "medium" if score >= .45 else "low",
                            "model_version": model_version, "reasons": reasons})
    return sorted(predictions, key=lambda prediction: prediction["risk_score"], reverse=True)
