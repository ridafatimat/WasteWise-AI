"""Main FastAPI application for WasteWise AI."""

from __future__ import annotations

import os
from datetime import date

from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Response,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func
from sqlalchemy.orm import Session

from .auth import (
    HOUSEHOLD_INVITE_LIFETIME_HOURS,
    create_access_token,
    create_household_invite_token,
    decode_household_invite_token,
    get_current_household_id,
    get_current_membership,
    get_current_user,
    hash_password,
    verify_password,
)
from .database import Base, engine, get_db
from .ml import (
    ensure_training_sample,
    maybe_retrain_household_model,
    predict_risk,
    resolve_expired_samples,
    resolve_training_outcome,
    should_retrain_household,
)
from .grocery_routes import router as grocery_router
from .recipe_routes import router as recipe_router
from .models import (
    Household,
    HouseholdMember,
    HouseholdModel,
    InventoryEvent,
    MLTrainingSample,
    PantryItem,
    User,
)
from .grocery_purchase_routes import router as grocery_purchase_router
from .receipt_routes import router as receipt_router
from .schemas import (
    EventCreate,
    EventRead,
    HouseholdInviteRead,
    HouseholdModelStatusRead,
    LoginRequest,
    PantryItemCreate,
    PantryItemRead,
    PantryItemUpdate,
    RegisterRequest,
    TokenRead,
    UserRead,
)
from .services import (
    get_item_or_404,
    record_event,
    risk_for,
    update_item,
)


# Load values from backend/.env.
load_dotenv()

# Create database tables that do not already exist.
Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="WasteWise API",
    version="0.3.0",
    openapi_url="/api/v1/openapi.json",
    docs_url="/docs",
)


# Read comma-separated frontend origins from .env.
cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        (
            "http://localhost:5173,"
            "http://127.0.0.1:5173,"
            "http://localhost:8080,"
            "http://127.0.0.1:8080"
        ),
    ).split(",")
    if origin.strip()
]


app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    # Allows temporary Lovable preview subdomains during development.
    allow_origin_regex=r"https://.*\.lovable\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register receipt-scanning routes.
#
# receipt_routes.py already uses:
#     prefix="/receipts"
#
# This additional prefix creates:
#     POST /api/v1/receipts/scan
app.include_router(
    receipt_router,
    prefix="/api/v1",
)

# Register grocery-list and meal-planning routes.
app.include_router(
    grocery_router,
    prefix="/api/v1",
)


# Register Groq-powered expiry-rescue recipe routes.
#
# recipe_routes.py already uses:
#     prefix="/recommendations"
#
# This additional prefix creates:
#     POST /api/v1/recommendations/recipes
app.include_router(
    recipe_router,
    prefix="/api/v1",
)


# Register grocery-shopping purchase routes.
#
# These routes handle marking grocery-list items as purchased and
# inserting the purchased quantity into Smart Pantry.
app.include_router(
    grocery_purchase_router,
    prefix="/api/v1",
)


def get_risk_band(score: float) -> str:
    """Convert a risk probability into a user-facing risk band."""

    if score >= 0.70:
        return "high"

    if score >= 0.40:
        return "medium"

    return "low"


@app.get("/")
def root():
    """Basic API information."""

    return {
        "message": "WasteWise API is running",
        "docs": "/docs",
        "health": "/api/v1/health",
        "receipt_scan": "/api/v1/receipts/scan",
        "grocery_lists": "/api/v1/grocery-lists/active",
        "recipe_suggestions": "/api/v1/recommendations/recipes",
    }


@app.get("/api/v1/health")
def health():
    """Return API health status."""

    return {
        "status": "ok",
        "database": engine.dialect.name,
    }


@app.post(
    "/api/v1/auth/register",
    response_model=TokenRead,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    """
    Register a user using one household name.

    If the household already exists, the new account joins it as a member.
    If it does not exist, WasteWise creates it and assigns the new account
    as its owner.
    """

    email = payload.email.strip().lower()
    household_name = payload.household_name.strip()

    existing_user = (
        db.query(User)
        .filter(User.email == email)
        .first()
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        name=payload.name.strip(),
        email=email,
        password_hash=hash_password(payload.password),
    )

    try:
        household = (
            db.query(Household)
            .filter(
                func.lower(
                    func.trim(Household.name)
                )
                == household_name.lower()
            )
            .order_by(
                Household.created_at.asc(),
                Household.id.asc(),
            )
            .first()
        )

        if household is None:
            household = Household(
                name=household_name,
            )
            role = "owner"

            db.add_all([
                user,
                household,
            ])
            db.flush()
        else:
            role = "member"

            db.add(user)
            db.flush()

        membership = HouseholdMember(
            user_id=user.id,
            household_id=household.id,
            role=role,
        )

        db.add(membership)
        db.commit()
        db.refresh(user)

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise

    return TokenRead(
        access_token=create_access_token(user),
    )


@app.post(
    "/api/v1/auth/login",
    response_model=TokenRead,
)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    """Authenticate a user and issue a bearer token."""

    email = payload.email.strip().lower()

    user = (
        db.query(User)
        .filter_by(email=email)
        .first()
    )

    if (
        user is None
        or not verify_password(
            payload.password,
            user.password_hash,
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={
                "WWW-Authenticate": "Bearer",
            },
        )

    return TokenRead(
        access_token=create_access_token(user),
    )


@app.get(
    "/api/v1/auth/me",
    response_model=UserRead,
)
def me(
    user: User = Depends(get_current_user),
    membership: HouseholdMember = Depends(
        get_current_membership
    ),
    db: Session = Depends(get_db),
):
    """Return the authenticated user and their active household."""

    household = db.get(
        Household,
        membership.household_id,
    )

    if household is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The user's household no longer exists",
        )

    return UserRead(
        id=user.id,
        name=user.name,
        email=user.email,
        created_at=user.created_at,
        household_id=household.id,
        household_name=household.name,
        household_role=membership.role,
    )


@app.post(
    "/api/v1/households/invite",
    response_model=HouseholdInviteRead,
)
def create_household_invite(
    membership: HouseholdMember = Depends(
        get_current_membership
    ),
    db: Session = Depends(get_db),
):
    """Create a signed invite for the current household."""

    if membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a household owner can create invitations",
        )

    household = db.get(
        Household,
        membership.household_id,
    )

    if household is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The household no longer exists",
        )

    invite_token = create_household_invite_token(
        household_id=household.id,
        created_by_user_id=membership.user_id,
    )

    return HouseholdInviteRead(
        household_id=household.id,
        household_name=household.name,
        invite_token=invite_token,
        expires_in_hours=HOUSEHOLD_INVITE_LIFETIME_HOURS,
    )


@app.get(
    "/api/v1/pantry-items",
    response_model=list[PantryItemRead],
)
def list_pantry_items(
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Return pantry items belonging to the active household."""

    return (
        db.query(PantryItem)
        .filter_by(household_id=household_id)
        .order_by(
            PantryItem.expiry_date.is_(None),
            PantryItem.expiry_date,
        )
        .all()
    )


@app.post(
    "/api/v1/pantry-items",
    response_model=PantryItemRead,
    status_code=status.HTTP_201_CREATED,
)
def create_pantry_item(
    payload: PantryItemCreate,
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Create a pantry item for the active household."""

    item = PantryItem(
        product_name=payload.product_name.strip(),
        category=payload.category,
        quantity_initial=payload.quantity,
        quantity_remaining=payload.quantity,
        unit=payload.unit,
        purchase_date=payload.purchase_date,
        expiry_date=payload.expiry_date,
        storage_location=payload.storage_location,
        price_amount=(
            payload.price.amount
            if payload.price
            else None
        ),
        currency=(
            payload.price.currency
            if payload.price
            else None
        ),
        household_id=household_id,
    )

    db.add(item)
    db.flush()
    ensure_training_sample(db, item)
    db.commit()
    db.refresh(item)

    return item


@app.get(
    "/api/v1/pantry-items/{item_id}",
    response_model=PantryItemRead,
)
def get_pantry_item(
    item_id: str,
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Return one pantry item."""

    item = get_item_or_404(
        db,
        item_id,
    )

    if item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pantry item not found",
        )

    return item


@app.patch(
    "/api/v1/pantry-items/{item_id}",
    response_model=PantryItemRead,
)
def patch_pantry_item(
    item_id: str,
    payload: PantryItemUpdate,
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Update supplied pantry-item fields."""

    item = get_item_or_404(
        db,
        item_id,
    )

    if item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pantry item not found",
        )

    updated_item = update_item(
        db,
        item,
        payload,
    )

    ensure_training_sample(db, updated_item)
    db.commit()
    db.refresh(updated_item)

    return updated_item


@app.delete(
    "/api/v1/pantry-items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_pantry_item(
    item_id: str,
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Delete a pantry item belonging to the active household."""

    item = get_item_or_404(
        db,
        item_id,
    )

    if item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pantry item not found",
        )

    db.delete(item)
    db.commit()

    return Response(
        status_code=status.HTTP_204_NO_CONTENT
    )


@app.post(
    "/api/v1/pantry-items/{item_id}/events",
    response_model=EventRead,
    status_code=status.HTTP_201_CREATED,
)
def create_event(
    item_id: str,
    payload: EventCreate,
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Record consumption, waste, expiry, or adjustment."""

    item = get_item_or_404(
        db,
        item_id,
    )

    if item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pantry item not found",
        )

    event = record_event(
        db,
        item,
        payload,
    )

    db.refresh(item)
    outcome_resolved = resolve_training_outcome(
        db,
        item,
        payload.event_type,
    )

    if outcome_resolved:
        maybe_retrain_household_model(
            db,
            household_id,
        )

    db.commit()
    db.refresh(event)
    return event


@app.get(
    "/api/v1/pantry-items/{item_id}/events",
    response_model=list[EventRead],
)
def list_events(
    item_id: str,
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Return the event history for one pantry item."""

    item = get_item_or_404(
        db,
        item_id,
    )

    if item.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pantry item not found",
        )

    return (
        db.query(InventoryEvent)
        .filter_by(pantry_item_id=item_id)
        .order_by(
            InventoryEvent.occurred_at.desc()
        )
        .all()
    )


@app.get("/api/v1/dashboard/rescue-mode")
def rescue_mode(
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """
    Return the rules-based Rescue Mode view.

    The ML prediction endpoint remains available separately.
    """

    candidates = []

    active_items = (
        db.query(PantryItem)
        .filter_by(
            status="active",
            household_id=household_id,
        )
        .all()
    )

    for item in active_items:
        score, reasons = risk_for(
            item,
            date.today(),
        )

        if score >= 0.40:
            candidates.append(
                (
                    item,
                    score,
                    reasons,
                )
            )

    candidates.sort(
        key=lambda candidate: candidate[1],
        reverse=True,
    )

    items = [
        {
            "pantry_item_id": item.id,
            "product_name": item.product_name,
            "risk_score": round(score, 4),
            "risk_band": get_risk_band(score),
            "reasons": reasons,
        }
        for item, score, reasons in candidates
    ]

    estimated_value = sum(
        (
            item.price_amount or 0
        )
        * (
            item.quantity_remaining
            / item.quantity_initial
        )
        for item, _, _ in candidates
        if item.quantity_initial
    )

    actions = []

    if items:
        product_names = ", ".join(
            item["product_name"]
            for item in items[:3]
        )

        actions.append(
            {
                "type": "recipe",
                "title": (
                    f"Use {product_names} soon"
                ),
                "reason": (
                    "Prioritizes pantry items "
                    "approaching expiry"
                ),
            }
        )

    return {
        "summary": (
            f"{len(items)} items need attention"
        ),
        "estimated_value_at_risk": {
            "amount": round(
                float(estimated_value),
                2,
            ),
            "currency": "PKR",
        },
        "items": items,
        "actions": actions,
    }


@app.get("/api/v1/predictions/waste-risk")
def waste_risk_predictions(
    household_id: str = Depends(
        get_current_household_id
    ),
    db: Session = Depends(get_db),
):
    """Return ML and Rescue Mode risk predictions."""

    predictions = []

    expired_resolved = resolve_expired_samples(
        db,
        household_id=household_id,
        today=date.today(),
    )
    if expired_resolved:
        maybe_retrain_household_model(db, household_id)
        db.commit()

    active_items = (
        db.query(PantryItem)
        .filter_by(
            status="active",
            household_id=household_id,
        )
        .all()
    )

    for item in active_items:
        score, model_version, reasons = (
            predict_risk(
                item,
                date.today(),
                db=db,
            )
        )

        predictions.append(
            {
                "pantry_item_id": item.id,
                "product_name": item.product_name,
                "risk_score": round(score, 4),
                "risk_band": get_risk_band(score),
                "model_version": model_version,
                "reasons": reasons,
            }
        )

    return sorted(
        predictions,
        key=lambda prediction: (
            prediction["risk_score"]
        ),
        reverse=True,
    )

@app.get(
    "/api/v1/ml/household-model/status",
    response_model=HouseholdModelStatusRead,
)
def household_model_status(
    household_id: str = Depends(get_current_household_id),
    db: Session = Depends(get_db),
):
    """Return family-model progress without exposing the artifact itself."""

    state = (
        db.query(HouseholdModel)
        .filter_by(household_id=household_id)
        .first()
    )

    total_resolved = (
        db.query(MLTrainingSample)
        .filter(
            MLTrainingSample.household_id == household_id,
            MLTrainingSample.label.is_not(None),
        )
        .count()
    )

    samples_at_last_training = (
        state.samples_at_last_training if state else 0
    )
    new_outcomes = max(
        0,
        total_resolved - samples_at_last_training,
    )

    should_train, trigger_reason, _ = should_retrain_household(
        db,
        household_id,
    )

    if should_train:
        next_trigger = "Ready for retraining"
    elif new_outcomes < 5:
        next_trigger = (
            f"Collect {5 - new_outcomes} more resolved outcome(s) "
            "for the 2-day trigger"
        )
    else:
        next_trigger = (
            f"Retrains at 25 outcomes or after 2 days; "
            f"current trigger status: {trigger_reason}"
        )

    return HouseholdModelStatusRead(
        household_id=household_id,
        model_source=(
            "household"
            if state and state.artifact_path
            else "global"
        ),
        version=state.version if state else 0,
        total_resolved_outcomes=total_resolved,
        new_outcomes_since_training=new_outcomes,
        last_trained_at=(state.last_trained_at if state else None),
        next_trigger=next_trigger,
        metrics=state.metrics if state else None,
    )