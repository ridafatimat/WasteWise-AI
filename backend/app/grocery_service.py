"""Rule-based grocery recommendations and grocery-list lifecycle services."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from .models import (
    EventType,
    GroceryList,
    GroceryListItem,
    GroceryListStatus,
    InventoryEvent,
    MealPlan,
    PantryItem,
    PantryStatus,
)


ACTIVE_LIST_STATUSES = (GroceryListStatus.draft, GroceryListStatus.shopping)
MIN_OBSERVATION_DAYS = 7
MAX_HISTORY_DAYS = 90
LOW_STOCK_RATIO = 0.25

# Absolute lower limits stop tiny quantities being treated as "enough" when
# a normal historical batch is much larger. All values are in base units.
ABSOLUTE_LOW_STOCK_LIMITS: dict[str, float] = {
    "piece": 2.0,
    "pack": 1.0,
    "g": 100.0,
    "ml": 100.0,
}

UNIT_ALIASES: dict[str, tuple[str, float]] = {
    "g": ("g", 1.0),
    "gram": ("g", 1.0),
    "grams": ("g", 1.0),
    "kg": ("g", 1000.0),
    "kilogram": ("g", 1000.0),
    "kilograms": ("g", 1000.0),
    "oz": ("g", 28.3495),
    "ounce": ("g", 28.3495),
    "ounces": ("g", 28.3495),
    "lb": ("g", 453.592),
    "lbs": ("g", 453.592),
    "pound": ("g", 453.592),
    "pounds": ("g", 453.592),
    "ml": ("ml", 1.0),
    "millilitre": ("ml", 1.0),
    "millilitres": ("ml", 1.0),
    "milliliter": ("ml", 1.0),
    "milliliters": ("ml", 1.0),
    "l": ("ml", 1000.0),
    "litre": ("ml", 1000.0),
    "litres": ("ml", 1000.0),
    "liter": ("ml", 1000.0),
    "liters": ("ml", 1000.0),
    "fl_oz": ("ml", 29.5735),
    "fl oz": ("ml", 29.5735),
    "fluid ounce": ("ml", 29.5735),
    "fluid ounces": ("ml", 29.5735),
    "pint": ("ml", 473.176),
    "pints": ("ml", 473.176),
    "quart": ("ml", 946.353),
    "quarts": ("ml", 946.353),
    "gal": ("ml", 3785.41),
    "gallon": ("ml", 3785.41),
    "gallons": ("ml", 3785.41),
    "piece": ("piece", 1.0),
    "pieces": ("piece", 1.0),
    "item": ("piece", 1.0),
    "items": ("piece", 1.0),
    "unit": ("piece", 1.0),
    "units": ("piece", 1.0),
    "pack": ("pack", 1.0),
    "packs": ("pack", 1.0),
    "packet": ("pack", 1.0),
    "packets": ("pack", 1.0),
}

PRODUCT_ALIASES = {
    "eggs": "egg",
    "tomatoes": "tomato",
    "onions": "onion",
    "potatoes": "potato",
    "green chillies": "green chilli",
    "green chilies": "green chilli",
    "chillies": "green chilli",
    "chilies": "green chilli",
    "fresh coriander": "coriander",
    "coriander leaves": "coriander",
    "basmati rice": "rice",
    "white rice": "rice",
    "brown rice": "rice",
    "chicken breast": "chicken",
    "frozen chicken": "chicken",
    "cooking oil": "oil",
    "vegetable oil": "oil",
    "canola oil": "oil",
    "bell peppers": "bell pepper",
    "lentils": "lentil",
    "daal": "lentil",
    "dal": "lentil",
    "pita bread": "pita bread",
    "pita breads": "pita bread",
}

# Approximate weights let count-based pantry produce offset gram-based recipes.
PIECE_WEIGHT_GRAMS = {
    "tomato": 120.0,
    "onion": 150.0,
    "potato": 180.0,
    "bell pepper": 150.0,
    "green chilli": 10.0,
}


def clean_product_name(value: str) -> str:
    """Return a stable key while preserving the pantry product identity."""

    cleaned = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return " ".join(cleaned.split())


def pantry_product_key(value: str) -> str:
    """Use the exact Smart Pantry item name as the grocery-list identity."""

    return clean_product_name(value)


def normalize_product_name(value: str) -> str:
    """Create a broader key only for ingredient/receipt matching."""

    cleaned = clean_product_name(value)

    exact_alias = PRODUCT_ALIASES.get(cleaned)
    if exact_alias:
        return exact_alias

    tokens = set(cleaned.split())

    # Existing receipt data may still include brands and package details.
    # These token rules let names such as "Great Value Chicken Breast" and
    # "365 Organic Milk 2%" match their generic pantry products.
    if "chicken" in tokens and "seasoning" not in tokens:
        return "chicken"
    if "milk" in tokens and not ({"chocolate", "powder"} & tokens):
        return "milk"
    if "egg" in tokens or "eggs" in tokens:
        return "egg"
    if "pita" in tokens and "bread" in tokens:
        return "pita bread"
    if "bread" in tokens:
        return "bread"
    if "strawberry" in tokens or "strawberries" in tokens:
        return "strawberry"

    return cleaned


def canonicalize_quantity(
    product_name: str,
    quantity: float,
    unit: str,
) -> tuple[float, str]:
    """Convert a quantity to a comparable base unit."""

    normalized_unit = " ".join(unit.lower().strip().split())
    base_unit, factor = UNIT_ALIASES.get(normalized_unit, (normalized_unit, 1.0))
    base_quantity = float(quantity) * factor
    normalized_name = normalize_product_name(product_name)

    if base_unit == "piece" and normalized_name in PIECE_WEIGHT_GRAMS:
        return base_quantity * PIECE_WEIGHT_GRAMS[normalized_name], "g"

    return base_quantity, base_unit


def _display_scale(base_unit: str, largest_quantity: float) -> tuple[str, float]:
    if base_unit == "g" and largest_quantity >= 1000:
        return "kg", 1000.0
    if base_unit == "ml" and largest_quantity >= 1000:
        return "l", 1000.0
    return base_unit, 1.0


def _round_number(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    rounded = round(float(value), digits)
    return 0.0 if abs(rounded) < 10 ** (-digits) else rounded


def _round_purchase_base(quantity: float, base_unit: str) -> float:
    if quantity <= 0:
        return 0.0
    if base_unit in {"piece", "pack"}:
        return float(math.ceil(quantity - 1e-9))
    if base_unit in {"g", "ml"}:
        return float(math.ceil(quantity / 10.0) * 10.0)
    return round(quantity, 2)


def _number_from_mapping(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _consumed_quantity_from_event(event: InventoryEvent) -> float:
    """Return the amount consumed, including legacy PATCH quantity reductions."""

    if event.event_type == EventType.consumed:
        quantity = _number_from_mapping(event.quantity)
        return quantity if quantity is not None and quantity > 0 else 0.0

    if event.event_type != EventType.updated:
        return 0.0

    payload = event.previous_values or {}
    before = payload.get("before") or {}
    after = payload.get("after") or {}

    old_quantity = _number_from_mapping(before.get("quantity_remaining"))
    new_quantity = _number_from_mapping(after.get("quantity_remaining"))

    if old_quantity is None or new_quantity is None:
        return 0.0

    decrease = old_quantity - new_quantity
    return decrease if decrease > 0 else 0.0


def _query_list(db: Session, list_id: str) -> GroceryList | None:
    return (
        db.query(GroceryList)
        .options(
            selectinload(GroceryList.items),
            selectinload(GroceryList.meal_plans),
        )
        .filter(GroceryList.id == list_id)
        .first()
    )


def get_grocery_list_or_404(
    db: Session,
    list_id: str,
    household_id: str,
) -> GroceryList:
    grocery_list = _query_list(db, list_id)
    if grocery_list is None or grocery_list.household_id != household_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Grocery list not found",
        )
    return grocery_list


def get_active_grocery_list(db: Session, household_id: str) -> GroceryList | None:
    grocery_list = (
        db.query(GroceryList)
        .options(
            selectinload(GroceryList.items),
            selectinload(GroceryList.meal_plans),
        )
        .filter(
            GroceryList.household_id == household_id,
            GroceryList.status.in_(ACTIVE_LIST_STATUSES),
        )
        .order_by(GroceryList.created_at.desc())
        .first()
    )
    return grocery_list


def _stock_and_metadata(
    db: Session,
    household_id: str,
    today: date,
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    dict[tuple[str, str], date],
    dict[tuple[str, str], dict[str, Any]],
]:
    """Return usable stock, purchase metadata, and cold-start product history."""

    stock: dict[tuple[str, str], dict[str, Any]] = {}
    earliest_purchase: dict[tuple[str, str], date] = {}
    catalog: dict[tuple[str, str], dict[str, Any]] = {}

    pantry_items = (
        db.query(PantryItem)
        .filter(PantryItem.household_id == household_id)
        .all()
    )

    for item in pantry_items:
        base_initial, base_unit = canonicalize_quantity(
            item.product_name,
            item.quantity_initial,
            item.unit,
        )
        base_remaining, _ = canonicalize_quantity(
            item.product_name,
            item.quantity_remaining,
            item.unit,
        )
        key = (pantry_product_key(item.product_name), base_unit)

        if key not in earliest_purchase or item.purchase_date < earliest_purchase[key]:
            earliest_purchase[key] = item.purchase_date

        history = catalog.setdefault(
            key,
            {
                "product_name": item.product_name,
                "category": item.category or "other",
                "reference_quantity": 0.0,
                "expired_quantity": 0.0,
                "expired_batches": 0,
                "depleted_batches": 0,
                "batch_count": 0,
                "latest_purchase_date": item.purchase_date,
            },
        )
        history["batch_count"] += 1
        history["reference_quantity"] = max(
            history["reference_quantity"],
            max(base_initial, 0.0),
        )

        if item.purchase_date >= history["latest_purchase_date"]:
            history["latest_purchase_date"] = item.purchase_date
            history["product_name"] = item.product_name
            history["category"] = item.category or history["category"]

        is_past_expiry = item.expiry_date is not None and item.expiry_date < today
        is_expired = item.status == PantryStatus.expired or is_past_expiry

        if is_expired:
            history["expired_batches"] += 1
            history["expired_quantity"] += max(base_remaining, 0.0)
            continue

        if (
            item.status in {PantryStatus.consumed, PantryStatus.wasted}
            or item.quantity_remaining <= 0
        ):
            history["depleted_batches"] += 1
            continue

        if item.status != PantryStatus.active:
            continue

        record = stock.setdefault(
            key,
            {
                "quantity": 0.0,
                "product_name": item.product_name,
                "category": item.category or "other",
            },
        )
        record["quantity"] += max(base_remaining, 0.0)

        # Prefer the latest pantry-facing name/category for display.
        record["product_name"] = history["product_name"]
        record["category"] = history["category"]

    return stock, earliest_purchase, catalog

def _consumption_requirements(
    db: Session,
    household_id: str,
    coverage_days: int,
    today: date,
    stock: dict[tuple[str, str], dict[str, Any]],
    earliest_purchase: dict[tuple[str, str], date],
) -> tuple[
    dict[tuple[str, str], dict[str, Any]],
    set[tuple[str, str]],
]:
    history_start = datetime.combine(
        today - timedelta(days=MAX_HISTORY_DAYS - 1),
        datetime.min.time(),
    ).replace(tzinfo=timezone.utc)

    rows = (
        db.query(InventoryEvent, PantryItem)
        .join(PantryItem, InventoryEvent.pantry_item_id == PantryItem.id)
        .filter(
            PantryItem.household_id == household_id,
            InventoryEvent.event_type.in_(
                (EventType.consumed, EventType.updated)
            ),
            InventoryEvent.occurred_at >= history_start,
        )
        .all()
    )

    grouped: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "consumed": 0.0,
            "event_count": 0,
            "first_event_date": None,
            "product_name": None,
            "category": "other",
            "inferred_from_snapshot": False,
        }
    )

    for event, item in rows:
        consumed_quantity = _consumed_quantity_from_event(event)
        if consumed_quantity <= 0:
            continue

        base_quantity, base_unit = canonicalize_quantity(
            item.product_name,
            consumed_quantity,
            item.unit,
        )
        key = (pantry_product_key(item.product_name), base_unit)
        occurred_date = event.occurred_at.date()
        record = grouped[key]
        record["consumed"] += base_quantity
        record["event_count"] += 1
        record["product_name"] = item.product_name
        record["category"] = item.category or "other"
        if (
            record["first_event_date"] is None
            or occurred_date < record["first_event_date"]
        ):
            record["first_event_date"] = occurred_date

    # Backward-compatibility fallback: infer consumption from snapshots when
    # older clients reduced quantity without creating explicit events.
    snapshot_rows = (
        db.query(PantryItem)
        .filter(
            PantryItem.household_id == household_id,
            PantryItem.status.in_(
                (PantryStatus.active, PantryStatus.consumed)
            ),
        )
        .all()
    )

    snapshots: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "initial": 0.0,
            "remaining": 0.0,
            "purchase_date": None,
            "product_name": None,
            "category": "other",
        }
    )

    for item in snapshot_rows:
        initial_quantity, base_unit = canonicalize_quantity(
            item.product_name,
            item.quantity_initial,
            item.unit,
        )
        remaining_quantity, _ = canonicalize_quantity(
            item.product_name,
            item.quantity_remaining,
            item.unit,
        )
        key = (pantry_product_key(item.product_name), base_unit)
        snapshot = snapshots[key]
        snapshot["initial"] += max(initial_quantity, 0.0)
        snapshot["remaining"] += max(remaining_quantity, 0.0)
        snapshot["product_name"] = item.product_name
        snapshot["category"] = item.category or "other"
        if (
            snapshot["purchase_date"] is None
            or item.purchase_date < snapshot["purchase_date"]
        ):
            snapshot["purchase_date"] = item.purchase_date

    for key, snapshot in snapshots.items():
        if grouped.get(key, {}).get("consumed", 0.0) > 0:
            continue

        inferred_consumed = snapshot["initial"] - snapshot["remaining"]
        if inferred_consumed <= 1e-6:
            continue

        record = grouped[key]
        record["consumed"] = inferred_consumed
        record["event_count"] = 1
        record["first_event_date"] = snapshot["purchase_date"]
        record["product_name"] = snapshot["product_name"]
        record["category"] = snapshot["category"]
        record["inferred_from_snapshot"] = True

    evidence_keys = {
        key
        for key, data in grouped.items()
        if data["consumed"] > 1e-6
    }
    requirements: dict[tuple[str, str], dict[str, Any]] = {}

    for key, data in grouped.items():
        start_candidates = [
            candidate
            for candidate in (
                data["first_event_date"],
                earliest_purchase.get(key),
            )
            if candidate
        ]
        if not start_candidates:
            continue

        observation_start = max(
            min(start_candidates),
            today - timedelta(days=MAX_HISTORY_DAYS - 1),
        )
        observed_days = max(
            MIN_OBSERVATION_DAYS,
            (today - observation_start).days + 1,
        )
        observed_days = min(observed_days, MAX_HISTORY_DAYS)
        average_daily = data["consumed"] / observed_days
        if average_daily <= 0:
            continue

        safety_days = min(2.0, max(1.0, coverage_days * 0.10))
        required = average_daily * (coverage_days + safety_days)
        current_stock = stock.get(key, {}).get("quantity", 0.0)
        shortage = required - current_stock
        if shortage <= 1e-6:
            continue

        estimated_days = current_stock / average_daily if average_daily else None
        confidence = min(
            0.95,
            0.40
            + min(data["event_count"], 5) * 0.08
            + min(observed_days, 30) * 0.01,
        )
        requirements[key] = {
            "product_name": (
                stock.get(key, {}).get("product_name")
                or data["product_name"]
            ),
            "category": (
                stock.get(key, {}).get("category")
                or data["category"]
            ),
            "required": required,
            "average_daily": average_daily,
            "estimated_days": estimated_days,
            "event_count": data["event_count"],
            "observed_days": observed_days,
            "confidence": confidence,
            "inferred_from_snapshot": data["inferred_from_snapshot"],
        }

    return requirements, evidence_keys


def _cold_start_requirements(
    stock: dict[tuple[str, str], dict[str, Any]],
    catalog: dict[tuple[str, str], dict[str, Any]],
    consumption_evidence_keys: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Recommend expired, depleted, or unusually low items without history."""

    requirements: dict[tuple[str, str], dict[str, Any]] = {}

    for key, history in catalog.items():
        if key in consumption_evidence_keys:
            continue

        _, base_unit = key
        current_stock = float(stock.get(key, {}).get("quantity", 0.0))
        reference_quantity = max(
            float(history.get("reference_quantity", 0.0)),
            current_stock,
        )
        if reference_quantity <= 1e-6:
            continue

        absolute_limit = ABSOLUTE_LOW_STOCK_LIMITS.get(base_unit, 0.0)
        low_stock_limit = max(
            reference_quantity * LOW_STOCK_RATIO,
            absolute_limit,
        )

        reason_type: str | None = None
        if current_stock <= 1e-6 and history.get("expired_batches", 0) > 0:
            reason_type = "expired_stock"
        elif current_stock <= 1e-6 and history.get("depleted_batches", 0) > 0:
            reason_type = "depleted_stock"
        elif (
            current_stock > 1e-6
            and current_stock < reference_quantity
            and current_stock <= low_stock_limit
        ):
            reason_type = "low_stock"

        if reason_type is None:
            continue

        requirements[key] = {
            "product_name": history["product_name"],
            "category": history["category"],
            "required": reference_quantity,
            "reason_type": reason_type,
            "reference_quantity": reference_quantity,
            "low_stock_limit": low_stock_limit,
            "expired_quantity": float(history.get("expired_quantity", 0.0)),
            "expired_batches": int(history.get("expired_batches", 0)),
            "depleted_batches": int(history.get("depleted_batches", 0)),
            "confidence": 0.45,
        }

    return requirements

def _find_matching_pantry_key(
    product_name: str,
    base_unit: str,
    catalog: dict[tuple[str, str], dict[str, Any]],
) -> tuple[str, str]:
    """Prefer an exact pantry name, then a unique broader pantry match."""

    exact_key = (pantry_product_key(product_name), base_unit)
    if exact_key in catalog:
        return exact_key

    broader_key = normalize_product_name(product_name)
    matches = [
        key
        for key, row in catalog.items()
        if key[1] == base_unit
        and normalize_product_name(str(row.get("product_name", ""))) == broader_key
    ]

    if len(matches) == 1:
        return matches[0]

    return exact_key


def _meal_requirements(
    grocery_list: GroceryList,
    catalog: dict[tuple[str, str], dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    requirements: dict[tuple[str, str], dict[str, Any]] = {}

    for meal in grocery_list.meal_plans:
        for ingredient in meal.ingredients or []:
            try:
                name = str(ingredient["product_name"])
                quantity = float(ingredient["quantity"])
                unit = str(ingredient["unit"])
            except (KeyError, TypeError, ValueError):
                continue
            if quantity <= 0:
                continue

            base_quantity, base_unit = canonicalize_quantity(name, quantity, unit)
            key = _find_matching_pantry_key(name, base_unit, catalog)
            record = requirements.setdefault(
                key,
                {
                    "product_name": name,
                    "category": ingredient.get("category", "other"),
                    "required": 0.0,
                    "meals": [],
                },
            )
            record["required"] += base_quantity
            record["meals"].append(
                {
                    "meal_plan_id": meal.id,
                    "dish_name": meal.dish_name,
                    "quantity_base": base_quantity,
                }
            )

    return requirements


def _make_recommendations(
    db: Session,
    household_id: str,
    grocery_list: GroceryList,
    today: date,
) -> dict[tuple[str, str], dict[str, Any]]:
    stock, earliest_purchase, catalog = _stock_and_metadata(
        db,
        household_id,
        today,
    )
    consumption, consumption_evidence_keys = _consumption_requirements(
        db,
        household_id,
        grocery_list.coverage_days,
        today,
        stock,
        earliest_purchase,
    )
    fallback = _cold_start_requirements(
        stock,
        catalog,
        consumption_evidence_keys,
    )
    meals = _meal_requirements(grocery_list, catalog)
    keys = set(consumption) | set(fallback) | set(meals)
    recommendations: dict[tuple[str, str], dict[str, Any]] = {}

    for key in keys:
        normalized_name, base_unit = key
        consumption_data = consumption.get(key)
        fallback_data = fallback.get(key)
        meal_data = meals.get(key)
        current_stock = stock.get(key, {}).get("quantity", 0.0)
        consumption_required = (
            consumption_data["required"] if consumption_data else 0.0
        )
        fallback_required = fallback_data["required"] if fallback_data else 0.0
        meal_required = meal_data["required"] if meal_data else 0.0

        if consumption_data:
            total_required = consumption_required + meal_required
        elif fallback_data and meal_data:
            # A normal fallback restock may already cover the planned meal.
            total_required = max(fallback_required, meal_required)
        else:
            total_required = fallback_required + meal_required

        purchase_base = _round_purchase_base(
            total_required - current_stock,
            base_unit,
        )
        if purchase_base <= 0:
            continue

        catalog_data = catalog.get(key, {})
        product_name = (
            stock.get(key, {}).get("product_name")
            or (consumption_data or {}).get("product_name")
            or (fallback_data or {}).get("product_name")
            or catalog_data.get("product_name")
            or (meal_data or {}).get("product_name")
            or normalized_name.title()
        )
        category = (
            stock.get(key, {}).get("category")
            or (meal_data or {}).get("category")
            or (consumption_data or {}).get("category")
            or (fallback_data or {}).get("category")
            or catalog_data.get("category")
            or "other"
        )
        largest = max(total_required, current_stock, purchase_base, 1.0)
        display_unit, divisor = _display_scale(base_unit, largest)
        purchase_quantity = purchase_base / divisor
        required_quantity = total_required / divisor
        pantry_quantity = current_stock / divisor
        average_daily = (
            consumption_data["average_daily"] / divisor
            if consumption_data
            else None
        )
        estimated_days = (
            consumption_data["estimated_days"] if consumption_data else None
        )

        has_automatic_need = bool(consumption_data or fallback_data)
        if meal_data and has_automatic_need:
            source_type = "combined"
        elif meal_data:
            source_type = "meal_plan"
        else:
            # Keep schema compatibility: fallback recommendations are automatic
            # pantry-based recommendations, so they use the consumption source.
            source_type = "consumption"

        fallback_reason_type = (
            fallback_data.get("reason_type") if fallback_data else None
        )
        if fallback_reason_type in {"expired_stock", "depleted_stock"}:
            priority = "buy_soon"
        elif (
            consumption_data
            and estimated_days is not None
            and estimated_days <= 3
        ):
            priority = "buy_soon"
        elif meal_data and not has_automatic_need:
            priority = "planned_meal"
        else:
            priority = "running_low"

        source_breakdown: dict[str, Any] = {}
        reason_parts: list[str] = []

        if consumption_data:
            consumption_display = consumption_required / divisor
            source_breakdown["consumption"] = {
                "required_quantity": _round_number(consumption_display),
                "unit": display_unit,
                "coverage_days": grocery_list.coverage_days,
                "average_daily_consumption": _round_number(average_daily, 3),
                "event_count": consumption_data["event_count"],
                "observed_days": consumption_data["observed_days"],
                "confidence": _round_number(consumption_data["confidence"], 2),
                "calculation_basis": (
                    "pantry_quantity_change"
                    if consumption_data["inferred_from_snapshot"]
                    else "consumption_events"
                ),
            }
            if consumption_data["inferred_from_snapshot"]:
                reason_parts.append(
                    "Estimated household use from pantry quantity changes is "
                    f"about {_round_number(average_daily, 2)} {display_unit}/day."
                )
            else:
                reason_parts.append(
                    f"Household use is about {_round_number(average_daily, 2)} "
                    f"{display_unit}/day."
                )

        if fallback_data:
            source_breakdown["fallback"] = {
                "calculation_basis": fallback_reason_type,
                "target_quantity": _round_number(
                    fallback_data["required"] / divisor
                ),
                "usable_pantry_quantity": _round_number(pantry_quantity),
                "excluded_expired_quantity": _round_number(
                    fallback_data["expired_quantity"] / divisor
                ),
                "low_stock_threshold": _round_number(
                    fallback_data["low_stock_limit"] / divisor
                ),
                "unit": display_unit,
                "confidence": _round_number(fallback_data["confidence"], 2),
            }

            if fallback_reason_type == "expired_stock":
                reason_parts.append(
                    "Recorded stock is expired, so it is excluded from usable "
                    "pantry quantity."
                )
            elif fallback_reason_type == "depleted_stock":
                reason_parts.append(
                    "This product has no usable quantity remaining."
                )
            else:
                reason_parts.append(
                    "Usable stock is below 25% of the household's usual batch size."
                )

        if meal_data:
            meal_rows = []
            dish_names = []
            for meal_row in meal_data["meals"]:
                meal_rows.append(
                    {
                        "meal_plan_id": meal_row["meal_plan_id"],
                        "dish_name": meal_row["dish_name"],
                        "required_quantity": _round_number(
                            meal_row["quantity_base"] / divisor
                        ),
                        "unit": display_unit,
                    }
                )
                dish_names.append(meal_row["dish_name"])
            source_breakdown["meals"] = meal_rows
            reason_parts.append(
                f"Planned meal requirement: {', '.join(dict.fromkeys(dish_names))}."
            )

        reason_parts.append(
            f"Pantry currently has {_round_number(pantry_quantity)} {display_unit} "
            "of usable stock."
        )

        recommendations[key] = {
            "product_name": product_name,
            "normalized_name": normalized_name,
            "category": category,
            "required_quantity": _round_number(required_quantity),
            "pantry_quantity": _round_number(pantry_quantity),
            "purchase_quantity": _round_number(purchase_quantity),
            "average_daily_consumption": _round_number(average_daily, 3),
            "estimated_days_remaining": _round_number(estimated_days, 1),
            "unit": display_unit,
            "priority": priority,
            "source_type": source_type,
            "reason": " ".join(reason_parts),
            "source_breakdown": source_breakdown,
        }

    return recommendations

def regenerate_grocery_list(
    db: Session,
    household_id: str,
    coverage_days: int,
) -> GroceryList:
    """Create or refresh the household's single active grocery list."""

    today = date.today()
    grocery_list = get_active_grocery_list(db, household_id)

    if grocery_list is None:
        grocery_list = GroceryList(
            household_id=household_id,
            coverage_days=coverage_days,
            start_date=today,
            end_date=today + timedelta(days=coverage_days - 1),
            status=GroceryListStatus.draft,
        )
        db.add(grocery_list)
        db.flush()
        # New relationship collections are available immediately.
        grocery_list.items = []
        grocery_list.meal_plans = []
    else:
        grocery_list.coverage_days = coverage_days
        grocery_list.start_date = today
        grocery_list.end_date = today + timedelta(days=coverage_days - 1)

    grocery_list.generated_at = datetime.now(timezone.utc)
    recommendations = _make_recommendations(
        db, household_id, grocery_list, today
    )

    existing_by_key: dict[tuple[str, str], GroceryListItem] = {}
    for item in list(grocery_list.items):
        _, base_unit = canonicalize_quantity(item.product_name, 1, item.unit)
        existing_by_key[(pantry_product_key(item.product_name), base_unit)] = item

    for key, recommendation in recommendations.items():
        item = existing_by_key.get(key)
        if item is not None and item.user_locked:
            continue

        if item is None:
            item = GroceryListItem(
                grocery_list=grocery_list,
                product_name=recommendation["product_name"],
                normalized_name=recommendation["normalized_name"],
                unit=recommendation["unit"],
                purchased_quantity=0,
                selected=True,
                user_locked=False,
                is_purchased=False,
            )
            db.add(item)

        for field, value in recommendation.items():
            setattr(item, field, value)

        item.is_purchased = (
            item.purchase_quantity > 0
            and (item.purchased_quantity or 0) + 1e-6 >= item.purchase_quantity
        )

    recommendation_keys = set(recommendations)
    for key, item in existing_by_key.items():
        if key in recommendation_keys:
            continue
        if item.user_locked or item.source_type == "manual":
            continue
        db.delete(item)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return get_grocery_list_or_404(db, grocery_list.id, household_id)


def add_meal_plan(
    db: Session,
    grocery_list: GroceryList,
    original_request: str,
    parsed: dict,
) -> GroceryList:
    """Replace the current planned recipe with the newly requested recipe.

    WasteWise keeps one active AI meal plan per active grocery list. Without
    replacing older meal plans, ingredients from previous dishes continue to
    accumulate and appear inside the next recipe's grocery recommendations.
    Manual grocery items and rule-based consumption recommendations are not
    affected.
    """

    if grocery_list.status == GroceryListStatus.completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A completed grocery list cannot be changed",
        )

    cleaned_request = " ".join(original_request.strip().split())
    if len(cleaned_request) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please enter a meal or recipe to plan",
        )

    ingredients = parsed.get("ingredients") or []
    if not isinstance(ingredients, list) or not ingredients:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The generated recipe did not contain any ingredients",
        )

    # Keep only the newest requested recipe. This prevents ingredients from
    # older dishes being merged into a later request such as noodles.
    (
        db.query(MealPlan)
        .filter(MealPlan.grocery_list_id == grocery_list.id)
        .delete(synchronize_session=False)
    )
    db.flush()

    meal = MealPlan(
        grocery_list_id=grocery_list.id,
        original_request=cleaned_request,
        dish_name=str(parsed["dish_name"]).strip(),
        servings=int(parsed["servings"]),
        times=int(parsed["times"]),
        recipe_source=str(parsed["recipe_source"]),
        ingredients=ingredients,
        assumptions=parsed.get("assumptions", []),
    )
    db.add(meal)

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    return regenerate_grocery_list(
        db,
        grocery_list.household_id,
        grocery_list.coverage_days,
    )


def remove_meal_plan(
    db: Session,
    grocery_list: GroceryList,
    meal_id: str,
) -> GroceryList:
    meal = next((row for row in grocery_list.meal_plans if row.id == meal_id), None)
    if meal is None:
        raise HTTPException(status_code=404, detail="Meal plan not found")
    db.delete(meal)
    db.commit()
    return regenerate_grocery_list(
        db, grocery_list.household_id, grocery_list.coverage_days
    )


def complete_grocery_list(db: Session, grocery_list: GroceryList) -> GroceryList:
    grocery_list.status = GroceryListStatus.completed
    grocery_list.completed_at = datetime.now(timezone.utc)
    db.commit()
    return get_grocery_list_or_404(db, grocery_list.id, grocery_list.household_id)


def start_shopping(db: Session, grocery_list: GroceryList) -> GroceryList:
    if grocery_list.status == GroceryListStatus.completed:
        raise HTTPException(status_code=409, detail="Grocery list is already completed")
    grocery_list.status = GroceryListStatus.shopping
    db.commit()
    return get_grocery_list_or_404(db, grocery_list.id, grocery_list.household_id)


def reconcile_receipt_changes(
    db: Session,
    household_id: str,
    pantry_changes: list[Any],
) -> None:
    """Mark active grocery items as purchased using processed receipt changes."""

    grocery_list = get_active_grocery_list(db, household_id)
    if grocery_list is None:
        return

    items_by_key: dict[tuple[str, str], GroceryListItem] = {}
    for item in grocery_list.items:
        _, base_unit = canonicalize_quantity(item.product_name, 1, item.unit)
        items_by_key[(pantry_product_key(item.product_name), base_unit)] = item

    changed = False
    for change in pantry_changes:
        action = getattr(change, "action", None)
        quantity_added = getattr(change, "quantity_added", None)
        unit = getattr(change, "unit", None)
        product_name = getattr(change, "product_name", None)
        if action not in {"created", "updated"} or not quantity_added or not unit or not product_name:
            continue

        base_quantity, base_unit = canonicalize_quantity(product_name, quantity_added, unit)
        key = (pantry_product_key(product_name), base_unit)
        list_item = items_by_key.get(key)
        if list_item is None:
            continue

        _, item_factor = UNIT_ALIASES.get(list_item.unit.lower(), (list_item.unit.lower(), 1.0))
        # Produce count conversion may have changed piece to grams.
        if base_unit == "g" and list_item.unit.lower() in {"piece", "pieces", "item", "items"}:
            piece_weight = PIECE_WEIGHT_GRAMS.get(normalize_product_name(list_item.product_name))
            item_factor = piece_weight or item_factor
        purchased_in_item_unit = base_quantity / item_factor
        list_item.purchased_quantity = round(
            list_item.purchased_quantity + purchased_in_item_unit, 4
        )
        list_item.is_purchased = (
            list_item.purchased_quantity + 1e-6 >= list_item.purchase_quantity
        )
        changed = True

    if not changed:
        return

    selected_items = [
        item for item in grocery_list.items if item.selected and item.purchase_quantity > 0
    ]
    if selected_items and all(item.is_purchased for item in selected_items):
        grocery_list.status = GroceryListStatus.completed
        grocery_list.completed_at = datetime.now(timezone.utc)

    db.commit()