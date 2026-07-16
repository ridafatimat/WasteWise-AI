from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy.orm import Session

from .models import EventType, InventoryEvent, PantryItem, PantryStatus
from .schemas import EventCreate, PantryItemUpdate


def get_item_or_404(db: Session, item_id: str) -> PantryItem:
    item = db.get(PantryItem, item_id)
    if not item:
        raise HTTPException(404, "Pantry item not found")
    return item


def update_item(db: Session, item: PantryItem, changes: PantryItemUpdate) -> PantryItem:
    values = changes.model_dump(exclude_unset=True)
    if values.get("expiry_date") and values["expiry_date"] < item.purchase_date:
        raise HTTPException(422, "expiry_date must be on or after purchase_date")
    previous = {field: getattr(item, field) for field in values}
    for field, value in values.items():
        setattr(item, field, value)
    if values:
        db.add(InventoryEvent(pantry_item=item, event_type=EventType.updated, previous_values=previous))
    db.commit()
    db.refresh(item)
    return item


def record_event(db: Session, item: PantryItem, event: EventCreate) -> InventoryEvent:
    if event.event_type != "adjusted" and event.quantity > item.quantity_remaining:
        raise HTTPException(422, "Event quantity cannot exceed the remaining quantity")
    previous = {"quantity_remaining": item.quantity_remaining, "status": item.status.value}
    if event.event_type == "adjusted":
        item.quantity_remaining = event.quantity
    else:
        item.quantity_remaining -= event.quantity
    if item.quantity_remaining == 0:
        item.status = PantryStatus(event.event_type) if event.event_type != "adjusted" else PantryStatus.consumed
    db_event = InventoryEvent(
        pantry_item=item,
        event_type=EventType(event.event_type),
        quantity=event.quantity,
        occurred_at=event.occurred_at or datetime.now(timezone.utc),
        notes=event.notes,
        previous_values=previous,
    )
    db.add(db_event)
    db.commit()
    db.refresh(db_event)
    return db_event


def risk_for(item: PantryItem, today: date) -> tuple[float, list[str]]:
    if not item.expiry_date:
        return 0.15, ["No expiry date recorded"]
    days = (item.expiry_date - today).days
    if days < 0:
        return 1.0, ["Already past its expiry date"]
    if days <= 1:
        return 0.9, [f"Expires in {days} day{'s' if days != 1 else ''}"]
    if days <= 3:
        return 0.75, [f"Expires in {days} days"]
    if days <= 7:
        return 0.45, [f"Expires in {days} days"]
    return 0.1, ["Expiry date is more than a week away"]
