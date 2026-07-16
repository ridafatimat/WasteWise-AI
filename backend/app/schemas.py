from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Money(BaseModel):
    amount: float = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)


class PantryItemCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=160)
    category: str | None = Field(default=None, max_length=80)
    quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    purchase_date: date
    expiry_date: date | None = None
    storage_location: str | None = Field(default=None, max_length=80)
    price: Money | None = None

    @model_validator(mode="after")
    def expiry_after_purchase(self):
        if self.expiry_date and self.expiry_date < self.purchase_date:
            raise ValueError("expiry_date must be on or after purchase_date")
        return self


class PantryItemUpdate(BaseModel):
    category: str | None = Field(default=None, max_length=80)
    quantity_remaining: float | None = Field(default=None, ge=0)
    expiry_date: date | None = None
    storage_location: str | None = Field(default=None, max_length=80)


class PantryItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    product_name: str
    category: str | None
    quantity_initial: float
    quantity_remaining: float
    unit: str
    purchase_date: date
    expiry_date: date | None
    storage_location: str | None
    status: str


class EventCreate(BaseModel):
    event_type: Literal["consumed", "wasted", "expired", "adjusted"]
    quantity: float = Field(gt=0)
    occurred_at: datetime | None = None
    notes: str | None = Field(default=None, max_length=500)


class EventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    event_type: str
    quantity: float | None
    occurred_at: datetime
    notes: str | None
    previous_values: dict | None
