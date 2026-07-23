import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
    """Return the current timezone-aware UTC datetime."""

    return datetime.now(timezone.utc)


class PantryStatus(str, enum.Enum):
    active = "active"
    consumed = "consumed"
    wasted = "wasted"
    expired = "expired"


class EventType(str, enum.Enum):
    consumed = "consumed"
    wasted = "wasted"
    expired = "expired"
    adjusted = "adjusted"
    updated = "updated"


class GroceryListStatus(str, enum.Enum):
    draft = "draft"
    shopping = "shopping"
    completed = "completed"


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    email: Mapped[str] = mapped_column(
        String(254),
        unique=True,
        nullable=False,
        index=True,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    memberships: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
    )

    timezone: Mapped[str] = mapped_column(
        String(64),
        default="Asia/Karachi",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    members: Mapped[list["HouseholdMember"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    pantry_items: Mapped[list["PantryItem"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    processed_receipts: Mapped[list["ProcessedReceipt"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    receipt_jobs: Mapped[list["ReceiptJob"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    grocery_lists: Mapped[list["GroceryList"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    ml_training_samples: Mapped[list["MLTrainingSample"]] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    household_model: Mapped["HouseholdModel | None"] = relationship(
        back_populates="household",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class HouseholdMember(Base):
    __tablename__ = "household_members"

    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "user_id",
            name="uq_household_user",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    household_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "households.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "users.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    # The account that creates a household should explicitly be assigned
    # role="owner". Accounts joining an existing household remain members.
    role: Mapped[str] = mapped_column(
        String(24),
        default="member",
        nullable=False,
    )

    household: Mapped["Household"] = relationship(
        back_populates="members",
    )

    user: Mapped["User"] = relationship(
        back_populates="memberships",
    )


class PantryItem(Base):
    __tablename__ = "pantry_items"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Every pantry item must belong to a real household.
    # There is intentionally no "demo-household" default.
    household_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "households.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    product_name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    quantity_initial: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    quantity_remaining: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )

    unit: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    purchase_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    expiry_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )

    storage_location: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    price_amount: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
    )

    status: Mapped[PantryStatus] = mapped_column(
        Enum(PantryStatus),
        default=PantryStatus.active,
        nullable=False,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    household: Mapped["Household"] = relationship(
        back_populates="pantry_items",
    )

    events: Mapped[list["InventoryEvent"]] = relationship(
        back_populates="pantry_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="InventoryEvent.occurred_at",
    )

    ml_training_sample: Mapped["MLTrainingSample | None"] = relationship(
        back_populates="pantry_item",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    pantry_item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "pantry_items.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType),
        nullable=False,
        index=True,
    )

    quantity: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
        index=True,
    )

    notes: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    previous_values: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    pantry_item: Mapped["PantryItem"] = relationship(
        back_populates="events",
    )


class ProcessedReceipt(Base):
    """Stores hashes and metadata for successfully processed receipts."""

    __tablename__ = "processed_receipts"

    __table_args__ = (
        UniqueConstraint(
            "household_id",
            "file_hash",
            name="uq_processed_receipt_household_hash",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    household_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "households.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    file_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    content_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    merchant_name: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )

    invoice_number: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
    )

    purchase_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    currency: Mapped[str | None] = mapped_column(
        String(3),
        nullable=True,
    )

    total_amount: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    extracted_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    household: Mapped["Household"] = relationship(
        back_populates="processed_receipts",
    )


class ReceiptJob(Base):
    """Tracks one asynchronous receipt-processing request."""

    __tablename__ = "receipt_jobs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    household_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "households.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    file_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    original_filename: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    content_type: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(24),
        default="queued",
        nullable=False,
        index=True,
    )

    progress: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    stage: Mapped[str] = mapped_column(
        String(160),
        default="Receipt queued",
        nullable=False,
    )

    estimated_seconds_remaining: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    result_data: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
    )

    error_message: Mapped[str | None] = mapped_column(
        String(700),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    household: Mapped["Household"] = relationship(
        back_populates="receipt_jobs",
    )


class GroceryList(Base):
    """One active or historical grocery list for a household."""

    __tablename__ = "grocery_lists"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    household_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "households.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    coverage_days: Mapped[int] = mapped_column(
        Integer,
        default=7,
        nullable=False,
    )

    start_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    end_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    status: Mapped[GroceryListStatus] = mapped_column(
        Enum(GroceryListStatus),
        default=GroceryListStatus.draft,
        nullable=False,
        index=True,
    )

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    household: Mapped["Household"] = relationship(
        back_populates="grocery_lists",
    )

    items: Mapped[list["GroceryListItem"]] = relationship(
        back_populates="grocery_list",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="GroceryListItem.created_at",
    )

    meal_plans: Mapped[list["MealPlan"]] = relationship(
        back_populates="grocery_list",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MealPlan.created_at",
    )


class GroceryListItem(Base):
    """One editable and explainable item in a grocery list."""

    __tablename__ = "grocery_list_items"

    __table_args__ = (
        UniqueConstraint(
            "grocery_list_id",
            "normalized_name",
            "unit",
            name="uq_grocery_list_item_product_unit",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    grocery_list_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "grocery_lists.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    product_name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    normalized_name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
        index=True,
    )

    category: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
    )

    required_quantity: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False,
    )

    pantry_quantity: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False,
    )

    purchase_quantity: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False,
    )

    purchased_quantity: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False,
    )

    average_daily_consumption: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    estimated_days_remaining: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    unit: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )

    priority: Mapped[str] = mapped_column(
        String(32),
        default="running_low",
        nullable=False,
    )

    source_type: Mapped[str] = mapped_column(
        String(32),
        default="consumption",
        nullable=False,
    )

    reason: Mapped[str | None] = mapped_column(
        String(700),
        nullable=True,
    )

    selected: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    user_locked: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    is_purchased: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    source_breakdown: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    grocery_list: Mapped["GroceryList"] = relationship(
        back_populates="items",
    )


class MealPlan(Base):
    """A user-requested meal whose missing ingredients feed a grocery list."""

    __tablename__ = "meal_plans"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    grocery_list_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey(
            "grocery_lists.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    original_request: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )

    dish_name: Mapped[str] = mapped_column(
        String(160),
        nullable=False,
    )

    servings: Mapped[int] = mapped_column(
        Integer,
        default=4,
        nullable=False,
    )

    times: Mapped[int] = mapped_column(
        Integer,
        default=1,
        nullable=False,
    )

    recipe_source: Mapped[str] = mapped_column(
        String(32),
        default="groq",
        nullable=False,
    )

    ingredients: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    assumptions: Mapped[list] = mapped_column(
        JSON,
        default=list,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    grocery_list: Mapped["GroceryList"] = relationship(
        back_populates="meal_plans",
    )

class MLTrainingSample(Base):
    """One pantry item outcome used to train its household-specific model."""

    __tablename__ = "ml_training_samples"

    __table_args__ = (
        UniqueConstraint(
            "pantry_item_id",
            name="uq_ml_training_sample_pantry_item",
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    household_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    pantry_item_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("pantry_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    product_name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    storage_location: Mapped[str | None] = mapped_column(String(80), nullable=True)
    purchase_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    quantity_initial: Mapped[float] = mapped_column(Float, nullable=False)
    quantity_remaining: Mapped[float] = mapped_column(Float, nullable=False)

    feature_values: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )

    outcome: Mapped[str] = mapped_column(
        String(32),
        default="pending",
        nullable=False,
        index=True,
    )

    label: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        index=True,
    )

    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    household: Mapped["Household"] = relationship(
        back_populates="ml_training_samples",
    )

    pantry_item: Mapped["PantryItem"] = relationship(
        back_populates="ml_training_sample",
    )


class HouseholdModel(Base):
    """Tracks the active personalized model for one household."""

    __tablename__ = "household_models"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    household_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("households.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    artifact_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    total_family_samples: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    samples_at_last_training: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_trained_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    household: Mapped["Household"] = relationship(
        back_populates="household_model",
    )