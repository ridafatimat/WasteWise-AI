import enum
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Date, DateTime, Enum, Float, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def utc_now() -> datetime:
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


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    memberships: Mapped[list["HouseholdMember"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Household(Base):
    __tablename__ = "households"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Karachi")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    members: Mapped[list["HouseholdMember"]] = relationship(back_populates="household", cascade="all, delete-orphan")


class HouseholdMember(Base):
    __tablename__ = "household_members"
    __table_args__ = (UniqueConstraint("household_id", "user_id", name="uq_household_user"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    household_id: Mapped[str] = mapped_column(ForeignKey("households.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(24), default="owner")
    household: Mapped[Household] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class PantryItem(Base):
    __tablename__ = "pantry_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # Temporary local household until auth is added; all routes are scoped to this value.
    household_id: Mapped[str] = mapped_column(String(36), default="demo-household", index=True)
    product_name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    quantity_initial: Mapped[float] = mapped_column(Float)
    quantity_remaining: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(32))
    purchase_date: Mapped[date] = mapped_column(Date)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    storage_location: Mapped[str | None] = mapped_column(String(80), nullable=True)
    price_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[PantryStatus] = mapped_column(Enum(PantryStatus), default=PantryStatus.active)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    events: Mapped[list["InventoryEvent"]] = relationship(back_populates="pantry_item", cascade="all, delete-orphan")


class InventoryEvent(Base):
    __tablename__ = "inventory_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    pantry_item_id: Mapped[str] = mapped_column(ForeignKey("pantry_items.id"), index=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType))
    quantity: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    previous_values: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    pantry_item: Mapped[PantryItem] = relationship(back_populates="events")
