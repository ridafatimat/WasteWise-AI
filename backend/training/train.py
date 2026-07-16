"""Train and evaluate WasteWise's offline waste-risk classifier.

The Kaggle dataset labels rows with ``used_before_expiry``. For the application,
we invert that label so the positive class is the outcome WasteWise cares about:

    1 = item was not used before expiry (waste risk)
    0 = item was used before expiry

Examples:
  python training/train.py --data "C:\\path\\to\\food_expiry_tracker.csv"
  python training/train.py --data food_expiry_tracker.csv --model xgboost
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    balanced_accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier


SOURCE_TARGET = "used_before_expiry"
FEATURE_COLUMNS = [
    "purchase_month",
    "purchase_day_of_week",
    "days_until_expiry",
    "quantity",
    "item_beverage",
    "item_dairy",
    "item_fruit",
    "item_grain",
    "item_meat",
    "item_snack",
    "item_vegetable",
    "storage_freezer",
    "storage_fridge",
    "storage_pantry",
]
BOOLEAN_COLUMNS = [column for column in FEATURE_COLUMNS if column.startswith(("item_", "storage_"))]
MODEL_VERSIONS = {
    "baseline_logistic_regression": "logistic-regression-v1",
    "xgboost": "xgboost-v1",
}


def load_training_data(data_path: Path) -> tuple[pd.DataFrame, pd.Series]:
    """Load and validate the preprocessed Kaggle training data."""
    if not data_path.exists():
        raise FileNotFoundError(f"Dataset not found: {data_path}")

    frame = pd.read_csv(data_path)
    required = FEATURE_COLUMNS + [SOURCE_TARGET]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"Dataset is missing required columns: {missing}")

    frame = frame[required].copy()

    # Accept either real booleans or CSV strings such as True/False.
    for column in BOOLEAN_COLUMNS:
        if frame[column].dtype == object:
            normalized = frame[column].astype(str).str.strip().str.lower()
            invalid = ~normalized.isin({"true", "false", "1", "0"})
            if invalid.any():
                examples = frame.loc[invalid, column].head(3).tolist()
                raise ValueError(f"Column '{column}' contains invalid boolean values: {examples}")
            frame[column] = normalized.isin({"true", "1"}).astype(int)
        else:
            frame[column] = frame[column].astype(int)

    numeric_columns = [column for column in FEATURE_COLUMNS if column not in BOOLEAN_COLUMNS]
    for column in numeric_columns + [SOURCE_TARGET]:
        frame[column] = pd.to_numeric(frame[column], errors="raise")

    if frame.isna().any().any():
        missing_counts = frame.isna().sum()
        raise ValueError(
            "Dataset contains missing values: "
            + ", ".join(f"{column}={count}" for column, count in missing_counts.items() if count)
        )

    source_labels = frame[SOURCE_TARGET].astype(int)
    if not set(source_labels.unique()).issubset({0, 1}) or source_labels.nunique() != 2:
        raise ValueError("'used_before_expiry' must contain both binary outcomes 0 and 1")

    features = frame[FEATURE_COLUMNS].astype(float)
    # Positive class is waste, so API probability can be used directly as risk.
    waste_labels = (1 - source_labels).astype(int)
    return features, waste_labels


def evaluate(model: Any, x_test: pd.DataFrame, y_test: pd.Series) -> dict[str, Any]:
    """Evaluate the positive waste class, not merely overall accuracy."""
    predictions = model.predict(x_test)
    probabilities = model.predict_proba(x_test)[:, 1]
    tn, fp, fn, tp = confusion_matrix(y_test, predictions, labels=[0, 1]).ravel()

    return {
        "accuracy": round(float(accuracy_score(y_test, predictions)), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_test, predictions)), 4),
        "waste_precision": round(float(precision_score(y_test, predictions, pos_label=1, zero_division=0)), 4),
        "waste_recall": round(float(recall_score(y_test, predictions, pos_label=1, zero_division=0)), 4),
        "waste_f1": round(float(f1_score(y_test, predictions, pos_label=1, zero_division=0)), 4),
        "roc_auc": round(float(roc_auc_score(y_test, probabilities)), 4),
        "average_precision": round(float(average_precision_score(y_test, probabilities)), 4),
        "confusion_matrix": {
            "used_predicted_used": int(tn),
            "used_predicted_waste": int(fp),
            "waste_predicted_used": int(fn),
            "waste_predicted_waste": int(tp),
        },
    }


def build_models(y_train: pd.Series) -> dict[str, Any]:
    baseline = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "model",
                LogisticRegression(
                    max_iter=2000,
                    random_state=42,
                    class_weight="balanced",
                ),
            ),
        ]
    )

    waste_rows = int((y_train == 1).sum())
    used_rows = int((y_train == 0).sum())
    scale_pos_weight = used_rows / max(waste_rows, 1)

    xgboost = XGBClassifier(
        objective="binary:logistic",
        n_estimators=150,
        max_depth=4,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.85,
        scale_pos_weight=scale_pos_weight,
        random_state=42,
        eval_metric="logloss",
        n_jobs=1,
    )
    return {
        "baseline_logistic_regression": baseline,
        "xgboost": xgboost,
    }


def select_model(reports: dict[str, dict[str, Any]], preferred_model: str) -> str:
    if preferred_model == "xgboost":
        return "xgboost"
    if preferred_model == "logistic":
        return "baseline_logistic_regression"

    # Prioritise ranking quality, then useful waste detection, then class balance.
    return max(
        reports,
        key=lambda name: (
            reports[name]["roc_auc"],
            reports[name]["waste_f1"],
            reports[name]["balanced_accuracy"],
        ),
    )


def train(
    data_path: Path,
    output_path: Path,
    preferred_model: str = "best",
) -> dict[str, Any]:
    features, labels = load_training_data(data_path)
    x_train, x_test, y_train, y_test = train_test_split(
        features,
        labels,
        test_size=0.20,
        random_state=42,
        stratify=labels,
    )

    models = build_models(y_train)
    reports: dict[str, dict[str, Any]] = {}
    for name, candidate in models.items():
        candidate.fit(x_train, y_train)
        reports[name] = evaluate(candidate, x_test, y_test)

    selected_name = select_model(reports, preferred_model)
    selected_model = models[selected_name]
    selected_version = MODEL_VERSIONS[selected_name]

    report: dict[str, Any] = {
        "dataset_rows": int(len(features)),
        "training_rows": int(len(x_train)),
        "test_rows": int(len(x_test)),
        "waste_rows": int((labels == 1).sum()),
        "used_rows": int((labels == 0).sum()),
        "positive_class": "not_used_before_expiry",
        "models": reports,
        "selected_model": selected_name,
        "selected_model_version": selected_version,
        "selection_mode": preferred_model,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    metrics_path = output_path.with_suffix(".metrics.json")
    artifact = {
        "model": selected_model,
        "feature_columns": FEATURE_COLUMNS,
        "model_version": selected_version,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "source_dataset": data_path.name,
        "source_target": SOURCE_TARGET,
        "positive_class": "not_used_before_expiry",
        "metrics": report,
    }
    joblib.dump(artifact, output_path)
    metrics_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"\nSaved model: {output_path}")
    print(f"Saved metrics: {metrics_path}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True, help="Path to food_expiry_tracker.csv")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/waste_risk_model.joblib"),
        help="Where to save the trained model artifact",
    )
    parser.add_argument(
        "--model",
        choices=["best", "xgboost", "logistic"],
        default="best",
        help="Select the best evaluated model, or force a specific model",
    )
    args = parser.parse_args()
    train(args.data, args.output, args.model)
