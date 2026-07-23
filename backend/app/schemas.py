"""Pydantic request and response schemas for WasteWise AI."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


CategoryValue = Literal[
    "beverage",
    "dairy",
    "fruit",
    "grain",
    "meat",
    "snack",
    "vegetable",
    "other",
]

StorageLocationValue = Literal[
    "fridge",
    "freezer",
    "pantry",
    "unknown",
]

PantryStatusValue = Literal[
    "active",
    "consumed",
    "wasted",
    "expired",
]

EventTypeValue = Literal[
    "consumed",
    "wasted",
    "expired",
    "adjusted",
    "updated",
]

PackageUnitValue = Literal[
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
    "piece",
    "pack",
    "unknown",
]

ExpirySourceValue = Literal[
    "local_rule",
    "gemini_estimate",
    "category_default",
]

PurchaseDateSourceValue = Literal[
    "receipt",
    "upload_date",
]


# ============================================================
# Authentication schemas
# ============================================================


class RegisterRequest(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=120,
    )

    email: str = Field(
        min_length=3,
        max_length=254,
    )

    password: str = Field(
        min_length=6,
        max_length=128,
    )

    household_name: str = Field(
        min_length=1,
        max_length=120,
        description=(
            "If this household name already exists, the user joins it "
            "as a member. Otherwise a new household is created and the "
            "user becomes its owner."
        ),
    )

    @model_validator(mode="after")
    def normalize_registration_values(self):
        self.name = self.name.strip()
        self.email = self.email.strip().lower()
        self.household_name = self.household_name.strip()

        if not self.name:
            raise ValueError("name cannot be empty")

        if not self.household_name:
            raise ValueError("household_name cannot be empty")

        return self


class LoginRequest(BaseModel):
    email: str = Field(
        min_length=3,
        max_length=254,
    )

    password: str = Field(
        min_length=1,
        max_length=128,
    )


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HouseholdInviteRead(BaseModel):
    household_id: str
    household_name: str
    invite_token: str
    expires_in_hours: int


class UserRead(BaseModel):
    id: str
    name: str
    email: str
    created_at: datetime

    household_id: str
    household_name: str
    household_role: str


# ============================================================
# Pantry schemas
# ============================================================


class PriceInput(BaseModel):
    amount: float = Field(
        ge=0,
    )

    currency: str = Field(
        default="PKR",
        min_length=3,
        max_length=3,
    )


class PantryItemCreate(BaseModel):
    product_name: str = Field(
        min_length=1,
        max_length=160,
    )

    category: CategoryValue = "other"

    quantity: float = Field(
        gt=0,
    )

    unit: str = Field(
        min_length=1,
        max_length=32,
    )

    purchase_date: date
    expiry_date: date | None = None

    storage_location: StorageLocationValue = "unknown"

    price: PriceInput | None = None

    @model_validator(mode="after")
    def validate_dates(self):
        if self.expiry_date is not None and self.expiry_date < self.purchase_date:
            raise ValueError("expiry_date must be on or after purchase_date")
        return self


class PantryItemUpdate(BaseModel):
    product_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )

    category: CategoryValue | None = None

    quantity: float | None = Field(
        default=None,
        ge=0,
    )

    unit: str | None = Field(
        default=None,
        min_length=1,
        max_length=32,
    )

    purchase_date: date | None = None
    expiry_date: date | None = None

    storage_location: StorageLocationValue | None = None

    price: PriceInput | None = None

    @model_validator(mode="after")
    def validate_dates_when_both_supplied(self):
        if (
            self.purchase_date is not None
            and self.expiry_date is not None
            and self.expiry_date < self.purchase_date
        ):
            raise ValueError("expiry_date must be on or after purchase_date")
        return self


class PantryItemRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: str
    product_name: str
    category: str | None

    quantity_initial: float
    quantity_remaining: float
    unit: str

    purchase_date: date
    expiry_date: date | None

    storage_location: str | None
    status: PantryStatusValue


# ============================================================
# Inventory event schemas
# ============================================================


class EventCreate(BaseModel):
    event_type: EventTypeValue

    quantity: float | None = Field(
        default=None,
        gt=0,
    )

    notes: str | None = Field(
        default=None,
        max_length=500,
    )

    occurred_at: datetime | None = None


class EventRead(BaseModel):
    model_config = ConfigDict(
        from_attributes=True
    )

    id: str
    pantry_item_id: str

    event_type: EventTypeValue
    quantity: float | None

    occurred_at: datetime
    notes: str | None

    previous_values: dict[str, Any] | None


# ============================================================
# Receipt extraction schemas
# ============================================================


class ReceiptItem(BaseModel):
    """One product line extracted from a receipt."""

    raw_name: str = Field(
        min_length=1,
        description=(
            "Product text as it appears on the receipt."
        ),
    )

    product_name: str = Field(
        min_length=1,
        description=(
            "Clean human-readable product name, including "
            "useful product detail when available."
        ),
    )

    pantry_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
        description=(
            "Simple generic inventory name used in the Smart "
            "Pantry. Brand names, package sizes, counts, and "
            "marketing terms should be removed."
        ),
    )

    purchased_quantity: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Number or weight purchased. This must not "
            "be confused with the package size."
        ),
    )

    package_size: float | None = Field(
        default=None,
        gt=0,
        description=(
            "Package size, such as 500 for 500g, "
            "1 for 1L, 20 for 20oz, or 0.5 for 1/2 gal."
        ),
    )

    package_unit: PackageUnitValue = "unknown"

    unit_price: float | None = Field(
        default=None,
        ge=0,
    )

    line_total: float | None = Field(
        default=None,
        ge=0,
    )

    category: CategoryValue = "other"

    location: StorageLocationValue = "unknown"

    is_food_item: bool = True

    uncertain_fields: list[str] = Field(
        default_factory=list,
        description=(
            "Fields that could not be read confidently."
        ),
    )

    estimated_shelf_life_days: int | None = Field(
        default=None,
        ge=1,
        le=730,
        description=(
            "Conservative estimated shelf life in days "
            "from the purchase date."
        ),
    )

    expiry_confidence: float | None = Field(
        default=None,
        ge=0,
        le=1,
        description=(
            "Confidence in the estimated shelf life."
        ),
    )

    expiry_reason: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "Brief explanation for the shelf-life estimate."
        ),
    )


class ReceiptData(BaseModel):
    """Complete structured data extracted from a receipt."""

    merchant_name: str | None = None
    invoice_number: str | None = None

    purchase_date: str | None = Field(
        default=None,
        description=(
            "Purchase date in YYYY-MM-DD format."
        ),
    )

    purchase_date_source: PurchaseDateSourceValue | None = Field(
        default=None,
        description=(
            "Whether the purchase date was extracted from "
            "the receipt or defaulted to the upload date."
        ),
    )

    currency: str = Field(
        default="PKR",
        min_length=3,
        max_length=3,
    )

    # Total of purchased products before tax and charges.
    items_subtotal: float | None = Field(
        default=None,
        ge=0,
    )

    tax_amount: float | None = Field(
        default=None,
        ge=0,
    )

    tax_rate: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    service_charge: float | None = Field(
        default=None,
        ge=0,
    )

    delivery_charge: float | None = Field(
        default=None,
        ge=0,
    )

    other_charges: float | None = Field(
        default=None,
        ge=0,
    )

    discount_amount: float | None = Field(
        default=None,
        ge=0,
    )

    total_amount: float | None = Field(
        default=None,
        ge=0,
    )

    payment_amount: float | None = Field(
        default=None,
        ge=0,
    )

    change_amount: float | None = Field(
        default=None,
        ge=0,
    )

    items: list[ReceiptItem] = Field(
        default_factory=list
    )


class ReceiptFinancialValidation(BaseModel):
    """Result of checking the receipt's financial totals."""

    status: Literal[
        "reconciled",
        "mismatch",
        "unavailable",
    ]

    line_items_total: float
    items_subtotal: float | None = None

    calculated_total: float | None = None
    receipt_total: float | None = None

    difference: float | None = None
    tolerance: float

    missing_line_totals: int = 0

    notes: list[str] = Field(
        default_factory=list
    )


class ReceiptScanResponse(BaseModel):
    success: bool
    receipt: ReceiptData
    financial_validation: ReceiptFinancialValidation


# ============================================================
# Receipt-to-pantry schemas
# ============================================================


class PantryReceiptChange(BaseModel):
    product_name: str

    action: Literal[
        "created",
        "updated",
        "skipped",
    ]

    quantity_added: float | None = None
    unit: str | None = None

    pantry_item_id: str | None = None
    expiry_date: date | None = None

    expiry_source: ExpirySourceValue | None = None
    expiry_confidence: float | None = None
    expiry_reason: str | None = None

    reason: str | None = None


class ReceiptProcessSummary(BaseModel):
    items_extracted: int
    items_created: int
    items_updated: int
    items_skipped: int


class ReceiptProcessResponse(BaseModel):
    success: bool

    receipt: ReceiptData
    financial_validation: ReceiptFinancialValidation

    summary: ReceiptProcessSummary
    pantry_changes: list[PantryReceiptChange]


ReceiptJobStatusValue = Literal[
    "queued",
    "processing",
    "completed",
    "failed",
]


class ReceiptJobCreatedResponse(BaseModel):
    job_id: str
    status: ReceiptJobStatusValue
    progress: int = Field(ge=0, le=100)
    stage: str
    estimated_seconds_remaining: int | None = Field(default=None, ge=0)


class ReceiptJobStatusResponse(BaseModel):
    job_id: str
    status: ReceiptJobStatusValue
    progress: int = Field(ge=0, le=100)
    stage: str
    estimated_seconds_remaining: int | None = Field(default=None, ge=0)
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    result: ReceiptProcessResponse | None = None
    error: str | None = None

# ============================================================
# Grocery-list and meal-planning schemas
# ============================================================


GroceryListStatusValue = Literal[
    "draft",
    "shopping",
    "completed",
]

GroceryPriorityValue = Literal[
    "buy_soon",
    "running_low",
    "planned_meal",
    "manual",
]

GrocerySourceValue = Literal[
    "consumption",
    "meal_plan",
    "combined",
    "manual",
]


class GroceryListGenerateRequest(BaseModel):
    coverage_days: int = Field(default=7, ge=1, le=30)


class MealPlanCreateRequest(BaseModel):
    message: str = Field(min_length=3, max_length=500)


class GroceryListItemCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=160)
    purchase_quantity: float = Field(gt=0)
    unit: str = Field(min_length=1, max_length=32)
    category: CategoryValue = "other"
    selected: bool = True


class GroceryListItemUpdate(BaseModel):
    product_name: str | None = Field(default=None, min_length=1, max_length=160)
    purchase_quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    category: CategoryValue | None = None
    selected: bool | None = None
    user_locked: bool | None = None


class GroceryListItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    product_name: str
    category: str | None
    required_quantity: float
    pantry_quantity: float
    purchase_quantity: float
    purchased_quantity: float
    average_daily_consumption: float | None
    estimated_days_remaining: float | None
    unit: str
    priority: GroceryPriorityValue
    source_type: GrocerySourceValue
    reason: str | None
    selected: bool
    user_locked: bool
    is_purchased: bool
    source_breakdown: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class MealPlanRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    original_request: str
    dish_name: str
    servings: int
    times: int
    recipe_source: str
    ingredients: list[dict[str, Any]]
    assumptions: list[str]
    created_at: datetime


class GroceryListRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    coverage_days: int
    start_date: date
    end_date: date
    status: GroceryListStatusValue
    generated_at: datetime
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    items: list[GroceryListItemRead] = Field(default_factory=list)
    meal_plans: list[MealPlanRead] = Field(default_factory=list)


class GroceryListHistoryItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    coverage_days: int
    start_date: date
    end_date: date
    status: GroceryListStatusValue
    created_at: datetime
    completed_at: datetime | None
    items: list[GroceryListItemRead] = Field(default_factory=list)
    meal_plans: list[MealPlanRead] = Field(default_factory=list)

# ============================================================
# Expiry-rescue recipe schemas
# ============================================================


RecipeUrgencyValue = Literal[
    "today",
    "tomorrow",
    "day_after_tomorrow",
]

RecipeDifficultyValue = Literal[
    "easy",
    "medium",
]


class RecipeSuggestionRequest(BaseModel):
    """Controls for Groq-powered expiry-rescue recipe generation."""

    servings: int = Field(
        default=4,
        ge=1,
        le=12,
    )

    recipe_count: int = Field(
        default=3,
        ge=1,
        le=4,
    )

    cuisine: str | None = Field(
        default=None,
        min_length=2,
        max_length=80,
    )

    dietary_preferences: str | None = Field(
        default=None,
        min_length=2,
        max_length=160,
    )


class UrgentPantryItemRead(BaseModel):
    """One usable pantry product expiring within the next three days."""

    pantry_item_id: str
    product_name: str
    category: str | None

    quantity: float
    unit: str

    expiry_date: date
    days_until_expiry: int
    urgency: RecipeUrgencyValue


class RecipeIngredientRead(BaseModel):
    name: str = Field(
        min_length=1,
        max_length=160,
    )

    quantity: float | None = Field(
        default=None,
        ge=0,
    )

    unit: str | None = Field(
        default=None,
        max_length=40,
    )

    from_urgent_pantry: bool = False

    pantry_item_name: str | None = Field(
        default=None,
        max_length=160,
    )


class RecipeRead(BaseModel):
    title: str = Field(
        min_length=2,
        max_length=160,
    )

    description: str = Field(
        min_length=5,
        max_length=500,
    )

    servings: int = Field(
        ge=1,
        le=12,
    )

    prep_minutes: int = Field(
        ge=0,
        le=240,
    )

    cook_minutes: int = Field(
        ge=0,
        le=360,
    )

    difficulty: RecipeDifficultyValue

    used_urgent_items: list[str] = Field(
        default_factory=list,
    )

    ingredients: list[RecipeIngredientRead] = Field(
        min_length=1,
        max_length=30,
    )

    steps: list[str] = Field(
        min_length=1,
        max_length=20,
    )

    missing_ingredients: list[str] = Field(
        default_factory=list,
        max_length=20,
    )

    waste_reduction_tip: str = Field(
        min_length=5,
        max_length=400,
    )


class RecipeSuggestionResponse(BaseModel):
    generated_at: datetime
    model: str

    date_window_start: date
    date_window_end: date

    urgent_items: list[UrgentPantryItemRead]
    recipes: list[RecipeRead]

    message: str
    safety_note: str


class GroqRecipePayload(BaseModel):
    """Internal validation model for Groq's JSON response."""

    recipes: list[RecipeRead] = Field(
        min_length=1,
        max_length=4,
    )


# ============================================================
# Household model status schemas
# ============================================================


class HouseholdModelStatusRead(BaseModel):
    household_id: str
    model_source: Literal["global", "household"]
    version: int
    total_resolved_outcomes: int
    new_outcomes_since_training: int
    last_trained_at: datetime | None
    next_trigger: str
    metrics: dict[str, Any] | None = None