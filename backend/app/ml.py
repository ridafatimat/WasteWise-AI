"""Feature conversion and model loading for the offline waste-risk model."""

from __future__ import annotations

import os
from datetime import date
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd

from .models import PantryItem
from .services import risk_for


BASE_DIR = Path(__file__).resolve().parents[1]

MODEL_PATH = Path(
    os.getenv(
        "MODEL_PATH",
        str(BASE_DIR / "artifacts" / "waste_risk_model.joblib"),
    )
)

CATEGORY_COLUMNS = {
    "beverage",
    "dairy",
    "fruit",
    "grain",
    "meat",
    "snack",
    "vegetable",
}

STORAGE_COLUMNS = {
    "freezer",
    "fridge",
    "pantry",
}


@lru_cache(maxsize=1)
def load_model():
    """
    Load and cache the trained model artifact.

    Returns None when model training has not been completed yet.
    """
    if not MODEL_PATH.exists():
        return None

    try:
        return joblib.load(MODEL_PATH)
    except Exception as exc:
        raise RuntimeError(
            f"Could not load waste-risk model from {MODEL_PATH}"
        ) from exc


def pantry_features(
    item: PantryItem,
    today: date,
) -> pd.DataFrame:
    """
    Convert a live pantry item into the same feature space used during training.
    """
    category = (item.category or "").strip().lower()
    storage = (item.storage_location or "").strip().lower()

    if item.expiry_date:
        raw_days_until_expiry = (
            item.expiry_date - today
        ).days
        days_until_expiry = max(
            0,
            raw_days_until_expiry,
        )
    else:
        days_until_expiry = 30

    # The training dataset used quantities between 1 and 10.
    # MinMax conversion:
    # quantity 1  -> 0.0
    # quantity 10 -> 1.0
    quantity = max(
        1.0,
        min(
            float(item.quantity_remaining),
            10.0,
        ),
    )

    normalized_quantity = (
        quantity - 1.0
    ) / 9.0

    features = {
        "purchase_month": (
            item.purchase_date.month - 1
        ) / 11,
        "purchase_day_of_week": (
            item.purchase_date.weekday()
        ) / 6,
        "days_until_expiry": min(
            days_until_expiry,
            121,
        ) / 121,
        "quantity": normalized_quantity,
    }

    features.update(
        {
            f"item_{name}": int(
                name == category
            )
            for name in CATEGORY_COLUMNS
        }
    )

    features.update(
        {
            f"storage_{name}": int(
                name == storage
            )
            for name in STORAGE_COLUMNS
        }
    )

    return pd.DataFrame([features])


def apply_rescue_rules(
    model_score: float,
    item: PantryItem,
    today: date,
) -> tuple[float, list[str]]:
    """
    Adjust the raw ML score using expiry and storage safety rules.

    The Kaggle-trained model is still used as the starting point. Rules prevent
    clearly illogical cases, such as an item expiring today receiving low risk.
    """
    adjusted_score = model_score
    adjustment_reasons: list[str] = []

    if not item.expiry_date:
        return round(adjusted_score, 4), adjustment_reasons

    days_until_expiry = (
        item.expiry_date - today
    ).days

    storage = (
        item.storage_location or ""
    ).strip().lower()

    # Expired items should always be treated as extremely high risk.
    if days_until_expiry < 0:
        required_score = 0.98

        if adjusted_score < required_score:
            adjusted_score = required_score
            adjustment_reasons.append(
                "Risk increased because the item is already past expiry"
            )

    # Items expiring today should always be high risk.
    elif days_until_expiry == 0:
        required_score = 0.90

        if adjusted_score < required_score:
            adjusted_score = required_score
            adjustment_reasons.append(
                "Risk increased because the item expires today"
            )

    # One day remaining is also considered high risk.
    elif days_until_expiry == 1:
        required_score = 0.80

        if adjusted_score < required_score:
            adjusted_score = required_score
            adjustment_reasons.append(
                "Risk increased because only 1 day remains before expiry"
            )

    # Two or three days remaining should be at least medium-high risk.
    elif days_until_expiry <= 3:
        required_score = 0.70

        if adjusted_score < required_score:
            adjusted_score = required_score
            adjustment_reasons.append(
                f"Risk increased because only "
                f"{days_until_expiry} days remain before expiry"
            )

    # A properly frozen item with substantial shelf life should not normally
    # be marked medium/high risk based only on the weak global model.
    elif (
        storage == "freezer"
        and days_until_expiry > 14
        and adjusted_score > 0.35
    ):
        adjusted_score = 0.35
        adjustment_reasons.append(
            "Risk reduced because the item is frozen "
            "and has more than 14 days before expiry"
        )

    adjusted_score = max(
        0.0,
        min(
            adjusted_score,
            1.0,
        ),
    )

    return round(adjusted_score, 4), adjustment_reasons


def predict_risk(
    item: PantryItem,
    today: date,
) -> tuple[float, str, list[str]]:
    """
    Predict the probability that a pantry item will go unused before expiry.

    Returns:
        score:
            Waste-risk probability between 0 and 1.

        model_version:
            Version of the model used for the prediction.

        reasons:
            Human-readable explanation of the prediction.
    """
    artifact = load_model()

    if artifact is None:
        score, reasons = risk_for(
            item,
            today,
        )

        return (
            score,
            "rules-v1",
            reasons
            + [
                "Trained model is not available yet"
            ],
        )

    model = artifact["model"]
    columns = artifact["feature_columns"]

    features = pantry_features(
        item,
        today,
    ).reindex(
        columns=columns,
        fill_value=0,
    )

    class_one_probability = float(
        model.predict_proba(
            features
        )[0][1]
    )

    # Current artifacts use:
    # class 1 = item was NOT used before expiry.
    #
    # Older artifacts used:
    # class 1 = item WAS used before expiry.
    if (
        artifact.get("positive_class")
        == "not_used_before_expiry"
    ):
        model_score = class_one_probability
    else:
        model_score = (
            1 - class_one_probability
        )

    model_score = round(
        model_score,
        4,
    )

    final_score, adjustment_reasons = (
        apply_rescue_rules(
            model_score=model_score,
            item=item,
            today=today,
        )
    )

    reasons = [
        (
            f"ML model estimates a "
            f"{model_score:.0%} chance this item "
            f"will go unused before expiry"
        )
    ]

    if item.expiry_date:
        days = (
            item.expiry_date - today
        ).days

        if days < 0:
            reasons.append(
                "Already past expiry"
            )
        elif days == 0:
            reasons.append(
                "Expires today"
            )
        else:
            reasons.append(
                f"Expires in {days} "
                f"day{'s' if days != 1 else ''}"
            )

    reasons.extend(
        adjustment_reasons
    )

    if final_score != model_score:
        reasons.append(
            f"Final Rescue Mode risk adjusted "
            f"to {final_score:.0%}"
        )

    return (
        final_score,
        artifact["model_version"],
        reasons,
    )