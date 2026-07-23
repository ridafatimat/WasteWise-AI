"""Four high-value automated tests for WasteWise AI.

Coverage:

1. Authentication, JWT and household isolation.
2. Pantry lifecycle and inventory history.
3. Receipt processing and duplicate protection.
4. Waste-risk and Groq recipe recommendation workflow.

External Groq calls are mocked, so the test suite does not use
the internet or consume API credits.
"""

from __future__ import annotations

from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)

import jwt
import pytest
from fastapi.security import (
    HTTPAuthorizationCredentials,
)
from sqlalchemy.orm import Session

import app.receipt_pantry_service as receipt_pantry_service
import app.services as services_module
from app.auth import (
    JWT_ALGORITHM,
    JWT_SECRET,
    TOKEN_LIFETIME_HOURS,
    create_access_token,
    get_current_household_id,
    get_current_membership,
    get_current_user,
    hash_password,
)
from app.models import (
    EventType,
    GroceryList,
    Household,
    HouseholdMember,
    InventoryEvent,
    MLTrainingSample,
    PantryItem,
    PantryStatus,
    ProcessedReceipt,
    User,
)
from app.receipt_pantry_service import (
    DuplicateReceiptError,
    process_receipt_into_pantry,
)
from app.schemas import (
    EventCreate,
    GroqRecipePayload,
    ReceiptData,
    ReceiptItem,
    RecipeIngredientRead,
    RecipeRead,
    RecipeSuggestionRequest,
)
from app.services import (
    generate_expiry_rescue_recipes,
    get_urgent_recipe_items,
    record_event,
    risk_for,
)


# ============================================================
# Shared helpers
# ============================================================


def create_household(
    db: Session,
    name: str,
) -> Household:
    """Create and save a household."""

    household = Household(
        name=name,
        timezone="Asia/Karachi",
    )

    db.add(household)
    db.commit()
    db.refresh(household)

    return household


def create_user_with_membership(
    db: Session,
    *,
    name: str,
    email: str,
    household: Household,
    role: str = "owner",
) -> User:
    """Create a user and attach them to a household."""

    user = User(
        name=name,
        email=email,
        password_hash=hash_password(
            "SecurePassword123"
        ),
    )

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

    return user


def create_pantry_item(
    db: Session,
    *,
    household_id: str,
    product_name: str,
    quantity: float,
    expiry_date: date,
    category: str = "other",
    storage_location: str = "pantry",
    unit: str = "item",
    price_amount: float | None = None,
) -> PantryItem:
    """Create and save one pantry item."""

    item = PantryItem(
        household_id=household_id,
        product_name=product_name,
        category=category,
        quantity_initial=quantity,
        quantity_remaining=quantity,
        unit=unit,
        purchase_date=date.today(),
        expiry_date=expiry_date,
        storage_location=storage_location,
        price_amount=price_amount,
        currency="PKR",
        status=PantryStatus.active,
    )

    db.add(item)
    db.commit()
    db.refresh(item)

    return item


# ============================================================
# Test 1
# Authentication, JWT and household isolation
# ============================================================


def test_authentication_jwt_and_household_isolation(
    db: Session,
):
    """
    Verify that:

    - access tokens identify the correct user;
    - the JWT lasts 24 hours;
    - the user resolves to the correct household;
    - household-scoped pantry queries do not expose another
      household's records.
    """

    household_one = create_household(
        db,
        "Rida's House",
    )

    household_two = create_household(
        db,
        "Another Family",
    )

    user_one = create_user_with_membership(
        db,
        name="Rida",
        email="rida@example.com",
        household=household_one,
    )

    create_user_with_membership(
        db,
        name="Other User",
        email="other@example.com",
        household=household_two,
    )

    own_item = create_pantry_item(
        db,
        household_id=household_one.id,
        product_name="Milk",
        quantity=2,
        expiry_date=date.today()
        + timedelta(days=3),
        category="dairy",
        storage_location="fridge",
        unit="litre",
    )

    create_pantry_item(
        db,
        household_id=household_two.id,
        product_name="Private Chicken",
        quantity=1,
        expiry_date=date.today()
        + timedelta(days=2),
        category="meat",
        storage_location="fridge",
        unit="kg",
    )

    access_token = create_access_token(
        user_one
    )

    credentials = (
        HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=access_token,
        )
    )

    authenticated_user = get_current_user(
        credentials=credentials,
        db=db,
    )

    membership = get_current_membership(
        user=authenticated_user,
        db=db,
    )

    household_id = get_current_household_id(
        membership=membership,
    )

    assert authenticated_user.id == user_one.id
    assert authenticated_user.email == "rida@example.com"
    assert household_id == household_one.id

    payload = jwt.decode(
        access_token,
        JWT_SECRET,
        algorithms=[JWT_ALGORITHM],
    )

    issued_at = datetime.fromtimestamp(
        payload["iat"],
        tz=timezone.utc,
    )

    expires_at = datetime.fromtimestamp(
        payload["exp"],
        tz=timezone.utc,
    )

    token_lifetime = (
        expires_at - issued_at
    )

    assert token_lifetime == timedelta(
        hours=TOKEN_LIFETIME_HOURS
    )

    visible_items = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id
            == household_id
        )
        .all()
    )

    visible_names = {
        item.product_name
        for item in visible_items
    }

    assert visible_names == {
        "Milk"
    }

    assert own_item.household_id == household_one.id

    assert (
        "Private Chicken"
        not in visible_names
    )


# ============================================================
# Test 2
# Pantry lifecycle and inventory history
# ============================================================


def test_pantry_lifecycle_and_inventory_history(
    db: Session,
):
    """
    Verify that:

    - a pantry quantity can be consumed;
    - quantity is reduced correctly;
    - status remains active while stock remains;
    - consuming the remainder marks the item consumed;
    - both events are written to inventory history.
    """

    household = create_household(
        db,
        "Pantry Test Household",
    )

    item = create_pantry_item(
        db,
        household_id=household.id,
        product_name="Eggs",
        quantity=12,
        expiry_date=date.today()
        + timedelta(days=10),
        category="dairy",
        storage_location="fridge",
        unit="pieces",
    )

    first_event = record_event(
        db=db,
        item=item,
        event=EventCreate(
            event_type="consumed",
            quantity=4,
            notes="Used for breakfast",
        ),
    )

    db.refresh(item)

    assert first_event.event_type == EventType.consumed
    assert first_event.quantity == 4
    assert item.quantity_remaining == 8
    assert item.status == PantryStatus.active

    second_event = record_event(
        db=db,
        item=item,
        event=EventCreate(
            event_type="consumed",
            quantity=8,
            notes="Used the remaining eggs",
        ),
    )

    db.refresh(item)

    assert second_event.quantity == 8
    assert item.quantity_remaining == 0
    assert item.status == PantryStatus.consumed

    history = (
        db.query(InventoryEvent)
        .filter(
            InventoryEvent.pantry_item_id
            == item.id
        )
        .order_by(
            InventoryEvent.occurred_at
        )
        .all()
    )

    assert len(history) == 2

    assert [
        event.quantity
        for event in history
    ] == [
        4,
        8,
    ]

    assert all(
        event.event_type
        == EventType.consumed
        for event in history
    )

    assert (
        history[0].previous_values[
            "quantity_remaining"
        ]
        == 12
    )

    assert (
        history[1].previous_values[
            "quantity_remaining"
        ]
        == 8
    )


# ============================================================
# Test 3
# Receipt processing and duplicate protection
# ============================================================


def test_receipt_processing_non_food_filtering_and_duplicate_protection(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Verify that:

    - edible receipt products become pantry batches;
    - non-food products are skipped;
    - an ML training sample is created;
    - the processed receipt hash is stored;
    - processing the same receipt again is rejected;
    - duplicate pantry batches are not created.
    """

    household = create_household(
        db,
        "Receipt Test Household",
    )

    # Grocery-list reconciliation is separate functionality.
    # Mock it so this test focuses specifically on receipt-to-pantry logic.
    monkeypatch.setattr(
        receipt_pantry_service,
        "reconcile_receipt_changes",
        lambda **kwargs: None,
    )

    receipt = ReceiptData(
        merchant_name="Fresh Mart",
        invoice_number="INV-1001",
        purchase_date="2026-07-22",
        purchase_date_source="receipt",
        currency="PKR",
        items_subtotal=620,
        tax_amount=0,
        total_amount=620,
        items=[
            ReceiptItem(
                raw_name="Fresh Milk 1L",
                product_name="Fresh Milk 1L",
                pantry_name="Milk",
                purchased_quantity=2,
                package_size=1,
                package_unit="l",
                unit_price=250,
                line_total=500,
                category="dairy",
                location="fridge",
                is_food_item=True,
                estimated_shelf_life_days=5,
                expiry_confidence=0.9,
                expiry_reason=(
                    "Fresh refrigerated milk"
                ),
            ),
            ReceiptItem(
                raw_name="Dishwashing Liquid",
                product_name="Dishwashing Liquid",
                pantry_name="Dishwashing Liquid",
                purchased_quantity=1,
                package_unit="piece",
                unit_price=120,
                line_total=120,
                category="other",
                location="pantry",
                is_food_item=False,
            ),
        ],
    )

    file_hash = "receipt-test-hash-001"

    result = process_receipt_into_pantry(
        db=db,
        household_id=household.id,
        receipt=receipt,
        file_hash=file_hash,
        original_filename="receipt.png",
        content_type="image/png",
    )

    assert result.success is True

    assert result.summary.items_extracted == 2
    assert result.summary.items_created == 1
    assert result.summary.items_skipped == 1
    assert result.summary.items_updated == 0

    pantry_items = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id
            == household.id
        )
        .all()
    )

    assert len(pantry_items) == 1

    milk = pantry_items[0]

    assert milk.product_name == "Milk"
    assert milk.category == "dairy"
    assert milk.storage_location == "fridge"
    assert milk.quantity_initial == 2
    assert milk.quantity_remaining == 2
    assert milk.unit == "l"
    assert milk.price_amount == 500
    assert milk.status == PantryStatus.active

    processed_receipts = (
        db.query(ProcessedReceipt)
        .filter(
            ProcessedReceipt.household_id
            == household.id
        )
        .all()
    )

    assert len(processed_receipts) == 1
    assert processed_receipts[0].file_hash == file_hash

    training_samples = (
        db.query(MLTrainingSample)
        .filter(
            MLTrainingSample.household_id
            == household.id
        )
        .all()
    )

    assert len(training_samples) == 1
    assert training_samples[0].product_name == "Milk"
    assert training_samples[0].outcome == "pending"
    assert training_samples[0].label is None

    with pytest.raises(
        DuplicateReceiptError
    ) as duplicate_error:
        process_receipt_into_pantry(
            db=db,
            household_id=household.id,
            receipt=receipt,
            file_hash=file_hash,
            original_filename="receipt.png",
            content_type="image/png",
        )

    assert (
        "already been processed"
        in str(
            duplicate_error.value
        ).lower()
    )

    pantry_count_after_duplicate = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id
            == household.id
        )
        .count()
    )

    assert pantry_count_after_duplicate == 1


# ============================================================
# Test 4
# Waste-risk and Groq recipe workflow
# ============================================================


def test_waste_risk_and_recipe_recommendation_workflow(
    db: Session,
    monkeypatch: pytest.MonkeyPatch,
):
    """
    Verify that:

    - an item expiring today receives greater risk than a safe item;
    - only active items expiring in the next three days are sent to Groq;
    - expired and far-expiry items are excluded;
    - Groq is mocked and therefore no API request is made;
    - the generated recipe remains grounded in exact pantry names.
    """

    household = create_household(
        db,
        "Recipe Test Household",
    )

    fixed_today = date(
        2026,
        7,
        22,
    )

    urgent_milk = create_pantry_item(
        db,
        household_id=household.id,
        product_name="Milk",
        quantity=2,
        expiry_date=fixed_today,
        category="dairy",
        storage_location="fridge",
        unit="litre",
    )

    urgent_bread = create_pantry_item(
        db,
        household_id=household.id,
        product_name="Bread",
        quantity=1,
        expiry_date=fixed_today
        + timedelta(days=1),
        category="grain",
        storage_location="pantry",
        unit="loaf",
    )

    safe_rice = create_pantry_item(
        db,
        household_id=household.id,
        product_name="Rice",
        quantity=5,
        expiry_date=fixed_today
        + timedelta(days=180),
        category="grain",
        storage_location="pantry",
        unit="kg",
    )

    expired_yogurt = create_pantry_item(
        db,
        household_id=household.id,
        product_name="Expired Yogurt",
        quantity=1,
        expiry_date=fixed_today
        - timedelta(days=2),
        category="dairy",
        storage_location="fridge",
        unit="cup",
    )

    expired_yogurt.status = (
        PantryStatus.expired
    )

    db.commit()

    urgent_score, urgent_reasons = risk_for(
        urgent_milk,
        fixed_today,
    )

    safe_score, safe_reasons = risk_for(
        safe_rice,
        fixed_today,
    )

    assert urgent_score == 0.95
    assert safe_score == 0.10
    assert urgent_score > safe_score
    assert "Expires today" in urgent_reasons
    assert (
        "more than a week away"
        in safe_reasons[0]
    )

    urgent_items = get_urgent_recipe_items(
        db=db,
        household_id=household.id,
        today=fixed_today,
    )

    urgent_names = {
        item.product_name
        for item in urgent_items
    }

    assert urgent_names == {
        "Milk",
        "Bread",
    }

    assert "Rice" not in urgent_names
    assert "Expired Yogurt" not in urgent_names

    # Ensure the recipe generator uses the same predictable date.
    monkeypatch.setattr(
        services_module,
        "_household_today",
        lambda db, household_id: fixed_today,
    )

    fake_groq_response = GroqRecipePayload(
        recipes=[
            RecipeRead(
                title="Milk and Bread Breakfast Toast",
                description=(
                    "A quick breakfast that uses urgent "
                    "milk and bread."
                ),
                servings=2,
                prep_minutes=5,
                cook_minutes=10,
                difficulty="easy",
                used_urgent_items=[
                    "Milk",
                    "Bread",
                ],
                ingredients=[
                    RecipeIngredientRead(
                        name="Milk",
                        quantity=1,
                        unit="cup",
                        from_urgent_pantry=True,
                        pantry_item_name="Milk",
                    ),
                    RecipeIngredientRead(
                        name="Bread",
                        quantity=4,
                        unit="slices",
                        from_urgent_pantry=True,
                        pantry_item_name="Bread",
                    ),
                ],
                steps=[
                    "Warm the milk.",
                    "Toast the bread.",
                    "Serve together.",
                ],
                missing_ingredients=[],
                waste_reduction_tip=(
                    "Use the oldest milk and bread first."
                ),
            )
        ]
    )

    groq_mock_calls = []

    def fake_groq_call(
        model: str,
        prompt: str,
    ) -> GroqRecipePayload:
        groq_mock_calls.append(
            {
                "model": model,
                "prompt": prompt,
            }
        )

        return fake_groq_response

    monkeypatch.setattr(
        services_module,
        "_call_groq_for_recipes",
        fake_groq_call,
    )

    response = generate_expiry_rescue_recipes(
        db=db,
        household_id=household.id,
        request=RecipeSuggestionRequest(
            servings=2,
            recipe_count=1,
            cuisine="Pakistani",
            dietary_preferences="Halal",
        ),
    )

    assert len(groq_mock_calls) == 1

    assert len(response.urgent_items) == 2
    assert len(response.recipes) == 1

    recipe = response.recipes[0]

    assert (
        recipe.title
        == "Milk and Bread Breakfast Toast"
    )

    assert set(
        recipe.used_urgent_items
    ) == {
        "Milk",
        "Bread",
    }

    assert all(
        ingredient.from_urgent_pantry
        for ingredient in recipe.ingredients
    )

    assert {
        ingredient.pantry_item_name
        for ingredient in recipe.ingredients
    } == {
        "Milk",
        "Bread",
    }

    assert (
        response.message
        == (
            "1 recipes generated using all "
            "urgent pantry products."
        )
    )

    assert (
        response.date_window_start
        == fixed_today
    )

    assert (
        response.date_window_end
        == fixed_today
        + timedelta(days=2)
    )