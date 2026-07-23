"""Insert or update receipt products in the Smart Pantry."""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import date, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .grocery_service import reconcile_receipt_changes
from .models import (
    PantryItem,
    PantryStatus,
    ProcessedReceipt,
)
from .receipt_service import (
    validate_receipt_financials,
)
from .schemas import (
    PantryReceiptChange,
    ReceiptData,
    ReceiptItem,
    ReceiptProcessResponse,
    ReceiptProcessSummary,
)


logger = logging.getLogger(__name__)

class DuplicateReceiptError(ValueError):
    """Raised when the receipt has already been processed."""

    pass


MEASURED_UNITS = {
    "g",
    "kg",
    "ml",
    "l",
    "oz",
    "fl_oz",
    "lb",
    "gal",
    "pint",
    "quart",
}


GENERIC_PANTRY_NAME_RULES = (
    (
        (
            "macaroni & cheese",
            "macaroni and cheese",
            "mac & cheese",
        ),
        "Macaroni & Cheese",
    ),
    (
        (
            "greek yogurt",
        ),
        "Greek Yogurt",
    ),
    (
        (
            "yogurt",
        ),
        "Yogurt",
    ),
    (
        (
            "chicken breast",
        ),
        "Chicken Breast",
    ),
    (
        (
            "frozen chicken",
        ),
        "Frozen Chicken",
    ),
    (
        (
            "chicken",
        ),
        "Chicken",
    ),
    (
        (
            "egg",
            "eggs",
        ),
        "Eggs",
    ),
    (
        (
            "pita bread",
        ),
        "Pita Bread",
    ),
    (
        (
            "bread",
        ),
        "Bread",
    ),
    (
        (
            "banana",
            "bananas",
        ),
        "Bananas",
    ),
    (
        (
            "strawberry",
            "strawberries",
        ),
        "Strawberries",
    ),
    (
        (
            "blueberry",
            "blueberries",
        ),
        "Blueberries",
    ),
    (
        (
            "avocado",
            "avocados",
        ),
        "Avocados",
    ),
    (
        (
            "romaine",
        ),
        "Romaine Lettuce",
    ),
    (
        (
            "milk",
        ),
        "Milk",
    ),
    (
        (
            "tortilla",
            "tortillas",
        ),
        "Tortillas",
    ),
    (
        (
            "brown rice",
        ),
        "Brown Rice",
    ),
    (
        (
            "white rice",
        ),
        "White Rice",
    ),
    (
        (
            "rice",
        ),
        "Rice",
    ),
    (
        (
            "oats",
            "oatmeal",
        ),
        "Oats",
    ),
    (
        (
            "pasta sauce",
        ),
        "Pasta Sauce",
    ),
    (
        (
            "black beans",
        ),
        "Black Beans",
    ),
    (
        (
            "beans",
        ),
        "Beans",
    ),
    (
        (
            "coca-cola",
            "coca cola",
            "pepsi",
            "cola",
            "soft drink",
            "soda",
        ),
        "Soft Drink",
    ),
    (
        (
            "gatorade",
            "sports drink",
        ),
        "Sports Drink",
    ),
    (
        (
            "nutella",
            "nutelka",
            "hazelnut spread",
        ),
        "Hazelnut Spread",
    ),
    (
        (
            "biskrem",
            "cookie",
            "cookies",
            "biscuit",
            "biscuits",
        ),
        "Cookies",
    ),
    (
        (
            "flour",
            "maida",
            "medda",
            "atta",
        ),
        "Flour",
    ),
)


CATEGORY_LOCATION_DEFAULTS = {
    "beverage": "pantry",
    "dairy": "fridge",
    "fruit": "fridge",
    "grain": "pantry",
    "meat": "fridge",
    "snack": "pantry",
    "vegetable": "fridge",
    "other": "pantry",
}


CATEGORY_SHELF_LIFE_DAYS = {
    "beverage": 30,
    "dairy": 7,
    "fruit": 7,
    "grain": 180,
    "meat": 2,
    "snack": 90,
    "vegetable": 7,
    "other": 14,
}


SPECIFIC_SHELF_LIFE_RULES = (
    (
        (
            "macaroni & cheese",
            "macaroni and cheese",
            "mac & cheese",
            "boxed macaroni",
        ),
        365,
        "boxed macaroni and cheese",
    ),
    (
        (
            "canned beverage",
            "canned soda",
        ),
        270,
        "canned beverage",
    ),
)


CATEGORY_PRODUCT_SHELF_LIFE_RULES = {
    "meat": (
        ("chicken", 2),
        ("beef", 3),
        ("mutton", 3),
        ("fish", 2),
    ),
    "dairy": (
        ("milk", 5),
        ("mozzarella", 7),
        ("cheese", 7),
        ("yogurt", 7),
        ("cream", 5),
        ("butter", 30),
        ("egg", 21),
    ),
    "fruit": (
        ("banana", 5),
        ("apple", 14),
        ("orange", 14),
    ),
    "vegetable": (
        ("tomato", 7),
        ("potato", 30),
        ("onion", 30),
    ),
    "grain": (
        ("bread", 5),
        ("flour", 180),
        ("maida", 180),
        ("medda", 180),
        ("atta", 180),
        ("rice", 365),
    ),
}


def calculate_receipt_hash(
    file_bytes: bytes,
) -> str:
    """Calculate a SHA-256 hash for duplicate detection."""

    return hashlib.sha256(
        file_bytes
    ).hexdigest()


def find_processed_receipt(
    db: Session,
    household_id: str,
    file_hash: str,
) -> ProcessedReceipt | None:
    """Find an already processed receipt for a household."""

    return (
        db.query(ProcessedReceipt)
        .filter(
            ProcessedReceipt.household_id
            == household_id,
            ProcessedReceipt.file_hash
            == file_hash,
        )
        .first()
    )


def _clean_text(
    value: str,
) -> str:
    """Remove unnecessary repeated whitespace."""

    return " ".join(
        value.strip().split()
    )


def _normalize_currency(
    value: str | None,
) -> str:
    """Return a valid three-letter currency code."""

    normalized = (
        value or "PKR"
    ).strip().upper()

    if len(normalized) != 3:
        return "PKR"

    return normalized


def _parse_purchase_date(
    purchase_date_text: str | None,
) -> date:
    """
    Convert an ISO purchase-date string into a Python date.

    The receipt service normally guarantees a valid value,
    but today's date remains the defensive fallback.
    """

    if not purchase_date_text:
        return date.today()

    try:
        return date.fromisoformat(
            purchase_date_text
        )

    except ValueError:
        return date.today()


def _infer_category(
    item: ReceiptItem,
) -> str:
    """
    Use Gemini's category first.

    If Gemini returns other, local keyword rules are applied.
    """

    if item.category != "other":
        return item.category

    searchable_name = (
        f"{item.raw_name} "
        f"{item.product_name} "
        f"{item.pantry_name or ''}"
    ).lower()

    keyword_categories = {
        "dairy": {
            "milk",
            "cheese",
            "mozzarella",
            "yogurt",
            "cream",
            "butter",
            "egg",
        },
        "grain": {
            "flour",
            "maida",
            "medda",
            "rice",
            "bread",
            "wheat",
            "atta",
            "pita",
        },
        "meat": {
            "chicken",
            "beef",
            "mutton",
            "fish",
            "meat",
        },
        "fruit": {
            "apple",
            "banana",
            "orange",
            "mango",
            "grape",
        },
        "vegetable": {
            "tomato",
            "potato",
            "onion",
            "carrot",
            "cucumber",
        },
        "beverage": {
            "juice",
            "drink",
            "water",
            "cola",
            "soda",
            "beverage",
            "gatorade",
        },
        "snack": {
            "chips",
            "biscuit",
            "cookie",
            "cookies",
            "chocolate",
            "snack",
            "nutella",
        },
    }

    for category, keywords in (
        keyword_categories.items()
    ):
        if any(
            keyword in searchable_name
            for keyword in keywords
        ):
            return category

    return "other"


def _resolve_location(
    item: ReceiptItem,
    category: str,
) -> str:
    """Resolve an unknown storage location."""

    if item.location != "unknown":
        return item.location

    return CATEGORY_LOCATION_DEFAULTS.get(
        category,
        "pantry",
    )


def _format_package_size(
    item: ReceiptItem,
) -> str | None:
    """Format package sizes for receipt audit and responses."""

    if (
        item.package_size is None
        or item.package_unit == "unknown"
    ):
        return None

    size = float(
        item.package_size
    )

    formatted_size = (
        str(int(size))
        if size.is_integer()
        else str(size)
    )

    unit_labels = {
        "g": "g",
        "kg": "kg",
        "ml": "ml",
        "l": "L",
        "oz": "oz",
        "fl_oz": "fl oz",
        "lb": "lb",
        "gal": "gal",
        "pint": "pint",
        "quart": "quart",
        "piece": "piece",
        "pack": "pack",
    }

    unit_label = unit_labels.get(
        item.package_unit,
        item.package_unit,
    )

    return (
        f"{formatted_size} "
        f"{unit_label}"
    )

def _build_display_name(
    item: ReceiptItem,
) -> str:
    """
    Return a simple generic inventory name for Smart Pantry.

    Gemini's pantry_name is preferred. Local rules provide a
    deterministic fallback when the model omits that field.
    The branded product_name and raw_name remain preserved in
    the processed-receipt audit data.
    """

    extracted_pantry_name = _clean_text(
        item.pantry_name or ""
    )

    if extracted_pantry_name:
        return extracted_pantry_name

    searchable_name = (
        f"{item.product_name} "
        f"{item.raw_name}"
    ).lower()

    for keywords, generic_name in (
        GENERIC_PANTRY_NAME_RULES
    ):
        if any(
            keyword in searchable_name
            for keyword in keywords
        ):
            return generic_name

    clean_product_name = _clean_text(
        item.product_name
    )

    raw_name = _clean_text(
        item.raw_name
    )

    return (
        clean_product_name
        or raw_name
    )

def _resolve_quantity_and_unit(
    item: ReceiptItem,
) -> tuple[float, str]:
    """
    Convert receipt quantities into pantry quantities.

    Loose measured products retain their measured quantity.
    Countable packages such as eggs or tortillas are converted
    into total pieces. Other packaged products remain separate
    purchased items so each receipt creates its own batch.
    """

    purchased_quantity = (
        float(item.purchased_quantity)
        if item.purchased_quantity is not None
        else 1.0
    )

    package_size = (
        float(item.package_size)
        if item.package_size is not None
        else None
    )

    if (
        item.package_unit == "piece"
        and package_size is not None
    ):
        return (
            purchased_quantity
            * package_size,
            "pieces",
        )

    if (
        item.package_unit == "piece"
        and package_size is None
    ):
        return (
            purchased_quantity,
            "pieces",
        )

    if item.package_unit == "pack":
        return (
            purchased_quantity,
            "packs",
        )

    if item.package_unit in MEASURED_UNITS:
        measured_quantity = purchased_quantity
        if package_size is not None:
            measured_quantity *= package_size
        return (
            measured_quantity,
            item.package_unit,
        )

    return (
        purchased_quantity,
        "item",
    )

def _estimate_shelf_life_days(
    item: ReceiptItem,
    product_name: str,
    category: str,
    location: str,
) -> tuple[int, str, float, str]:
    """
    Estimate shelf life using this priority:

    1. Storage-sensitive local rules
    2. Specific packaged-product rules
    3. Category-specific local rules
    4. Gemini estimate
    5. Category default
    """

    searchable_name = (
        f"{product_name} "
        f"{item.pantry_name or ''} "
        f"{item.product_name} "
        f"{item.raw_name}"
    ).lower()

    padded_name = (
        f" {searchable_name} "
    )

    if (
        category == "meat"
        and location == "freezer"
    ):
        return (
            180,
            "local_rule",
            0.90,
            "Frozen meat local storage rule.",
        )

    # A pantry product containing the word "cheese" should
    # not automatically receive fresh-cheese shelf life.
    if location == "pantry":
        for (
            keywords,
            shelf_life_days,
            rule_name,
        ) in SPECIFIC_SHELF_LIFE_RULES:
            if any(
                keyword in searchable_name
                for keyword in keywords
            ):
                return (
                    shelf_life_days,
                    "local_rule",
                    0.90,
                    (
                        "Matched shelf-stable local rule "
                        f"for {rule_name}."
                    ),
                )

    # Detect beverage cans using a complete word match. This
    # avoids accidentally matching unrelated words.
    if (
        category == "beverage"
        and location == "pantry"
        and (
            " canned " in padded_name
            or " can " in padded_name
            or searchable_name.endswith(
                " can"
            )
        )
    ):
        return (
            270,
            "local_rule",
            0.90,
            "Matched shelf-stable local rule for a canned beverage.",
        )

    category_rules = (
        CATEGORY_PRODUCT_SHELF_LIFE_RULES.get(
            category,
            (),
        )
    )

    for keyword, shelf_life_days in category_rules:
        if keyword in searchable_name:
            return (
                shelf_life_days,
                "local_rule",
                0.85,
                (
                    "Matched local shelf-life rule "
                    f"for {keyword}."
                ),
            )

    if (
        item.estimated_shelf_life_days
        is not None
    ):
        estimated_days = max(
            1,
            min(
                int(
                    item.estimated_shelf_life_days
                ),
                730,
            ),
        )

        confidence = (
            float(item.expiry_confidence)
            if item.expiry_confidence is not None
            else 0.50
        )

        confidence = max(
            0.0,
            min(
                confidence,
                1.0,
            ),
        )

        reason = (
            item.expiry_reason
            or (
                "Gemini estimated shelf life using "
                "the product type and storage location."
            )
        )

        return (
            estimated_days,
            "gemini_estimate",
            confidence,
            reason,
        )

    default_days = (
        CATEGORY_SHELF_LIFE_DAYS.get(
            category,
            14,
        )
    )

    return (
        default_days,
        "category_default",
        0.40,
        (
            "No product-specific shelf-life estimate "
            f"was available, so the {category} category "
            "default was used."
        ),
    )


def _calculate_price_amount(
    item: ReceiptItem,
) -> float | None:
    """
    Calculate the amount paid for the receipt line.

    unit_price is multiplied by the number of purchased
    packages or receipt units, not by the converted pantry
    quantity. This prevents a 12-piece egg carton from being
    priced as twelve separate cartons.
    """

    if item.line_total is not None:
        return round(
            float(item.line_total),
            2,
        )

    if item.unit_price is not None:
        purchased_units = (
            float(item.purchased_quantity)
            if item.purchased_quantity is not None
            else 1.0
        )

        return round(
            float(item.unit_price)
            * purchased_units,
            2,
        )

    return None


def process_receipt_into_pantry(
    db: Session,
    household_id: str,
    receipt: ReceiptData,
    file_hash: str,
    original_filename: str | None,
    content_type: str | None,
) -> ReceiptProcessResponse:
    """
    Create one new pantry batch for every extracted food line.

    Items from different receipts are never merged because
    each purchase can have a different purchase date, expiry
    date, price, and remaining quantity. The frontend can
    group batches by their generic product_name for display.

    Pantry batches and the processed-receipt record are saved
    in one database transaction.
    """

    existing_receipt = find_processed_receipt(
        db=db,
        household_id=household_id,
        file_hash=file_hash,
    )

    if existing_receipt:
        raise DuplicateReceiptError(
            "This receipt has already been processed."
        )

    financial_validation = (
        validate_receipt_financials(
            receipt
        )
    )

    purchase_date = _parse_purchase_date(
        receipt.purchase_date
    )

    currency = _normalize_currency(
        receipt.currency
    )

    created_count = 0
    updated_count = 0
    skipped_count = 0

    changes: list[
        PantryReceiptChange
    ] = []

    try:
        for extracted_item in receipt.items:
            display_name = _build_display_name(
                extracted_item
            )

            if not extracted_item.is_food_item:
                skipped_count += 1

                changes.append(
                    PantryReceiptChange(
                        product_name=(
                            display_name
                            or "Unknown item"
                        ),
                        action="skipped",
                        reason=(
                            "The receipt item is not "
                            "a food product."
                        ),
                    )
                )

                continue

            if not display_name:
                skipped_count += 1

                changes.append(
                    PantryReceiptChange(
                        product_name="Unknown item",
                        action="skipped",
                        reason=(
                            "No product name could "
                            "be extracted."
                        ),
                    )
                )

                continue

            category = _infer_category(
                extracted_item
            )

            location = _resolve_location(
                extracted_item,
                category,
            )

            quantity, unit = (
                _resolve_quantity_and_unit(
                    extracted_item
                )
            )

            if quantity <= 0:
                skipped_count += 1

                changes.append(
                    PantryReceiptChange(
                        product_name=display_name,
                        action="skipped",
                        reason=(
                            "The extracted quantity "
                            "was not valid."
                        ),
                    )
                )

                continue

            (
                shelf_life_days,
                expiry_source,
                expiry_confidence,
                expiry_reason,
            ) = _estimate_shelf_life_days(
                item=extracted_item,
                product_name=display_name,
                category=category,
                location=location,
            )

            expiry_date = (
                purchase_date
                + timedelta(
                    days=shelf_life_days
                )
            )

            price_amount = (
                _calculate_price_amount(
                    extracted_item
                )
            )

            pantry_item = PantryItem(
                product_name=display_name,
                category=category,
                quantity_initial=quantity,
                quantity_remaining=quantity,
                unit=unit,
                purchase_date=purchase_date,
                expiry_date=expiry_date,
                storage_location=location,
                price_amount=price_amount,
                currency=currency,
                household_id=household_id,
                status=PantryStatus.active,
            )

            db.add(
                pantry_item
            )

            db.flush()

            # Every receipt-created pantry batch starts a pending,
            # household-specific ML training sample.
            from .ml import ensure_training_sample

            ensure_training_sample(
                db,
                pantry_item,
            )

            created_count += 1

            # Temporary production-readiness test:
            # When enabled, fail after the second food item has been added
            # to the current transaction. The outer exception handler must
            # roll back every pantry item, ML training sample, and receipt
            # record created during this request.
            if (
                os.getenv(
                    "SIMULATE_RECEIPT_DB_FAILURE",
                    "false",
                ).lower()
                == "true"
                and created_count == 2
            ):
                raise RuntimeError(
                    "Simulated receipt database failure."
                )

            changes.append(
                PantryReceiptChange(
                    product_name=display_name,
                    action="created",
                    quantity_added=quantity,
                    unit=unit,
                    pantry_item_id=str(
                        pantry_item.id
                    ),
                    expiry_date=expiry_date,
                    expiry_source=expiry_source,
                    expiry_confidence=(
                        expiry_confidence
                    ),
                    expiry_reason=expiry_reason,
                    reason=(
                        "Created as a separate pantry batch "
                        "for this receipt purchase."
                    ),
                )
            )

        processed_receipt = ProcessedReceipt(
            household_id=household_id,
            file_hash=file_hash,
            original_filename=original_filename,
            content_type=content_type,
            merchant_name=receipt.merchant_name,
            invoice_number=receipt.invoice_number,
            purchase_date=purchase_date,
            currency=currency,
            total_amount=receipt.total_amount,
            extracted_data={
                "receipt": receipt.model_dump(
                    mode="json"
                ),
                "financial_validation": (
                    financial_validation.model_dump(
                        mode="json"
                    )
                ),
            },
        )

        db.add(
            processed_receipt
        )

        db.commit()

        # Match purchased receipt items against the active grocery list.
        # A partial receipt keeps the list active; when every selected row
        # is satisfied, reconciliation completes the list automatically.
        try:
            reconcile_receipt_changes(
                db=db,
                household_id=household_id,
                pantry_changes=changes,
            )
        except Exception:
            db.rollback()
            logger.exception(
                "Receipt was processed, but grocery-list reconciliation failed"
            )

    except IntegrityError as exc:
        db.rollback()

        duplicate = find_processed_receipt(
            db=db,
            household_id=household_id,
            file_hash=file_hash,
        )

        if duplicate:
            raise DuplicateReceiptError(
                "This receipt has already been processed."
            ) from exc

        raise

    except Exception:
        db.rollback()
        raise

    return ReceiptProcessResponse(
        success=True,
        receipt=receipt,
        financial_validation=financial_validation,
        summary=ReceiptProcessSummary(
            items_extracted=len(
                receipt.items
            ),
            items_created=created_count,
            items_updated=updated_count,
            items_skipped=skipped_count,
        ),
        pantry_changes=changes,
    )