"""Stock receiving and authorised adjustments.

Every quantity change writes an immutable StockMovement row; products are never
edited directly by the UI.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from ..errors import ConflictError, NotFoundError, ValidationError
from .. import security
from ..models import (
    MOVEMENT_ADJUSTMENT,
    MOVEMENT_DAMAGE,
    MOVEMENT_EXPIRY,
    MOVEMENT_LOSS,
    MOVEMENT_RECEIPT,
    MOVEMENT_RETURN,
    Product,
    StockMovement,
    StockReceipt,
    Supplier,
)
from ..money import from_milli, to_milli, to_minor
from ..timeutil import today, utc_now
from . import audit
from .report_state import mark_daily_dirty

ADJUSTMENT_TYPES = {
    "damage": MOVEMENT_DAMAGE,
    "loss": MOVEMENT_LOSS,
    "expiry": MOVEMENT_EXPIRY,
    "adjustment": MOVEMENT_ADJUSTMENT,
    "count": MOVEMENT_ADJUSTMENT,
}

TYPE_LABELS = {
    "damage": "Damaged stock",
    "loss": "Missing / lost stock",
    "expiry": "Expired stock",
    "count": "Stock-count correction",
    "adjustment": "Other authorised adjustment",
}


def _get_product(session: Session, product_id: int) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    return product


def apply_movement(
    session: Session,
    product: Product,
    quantity_change_milli: int,
    movement_type: str,
    *,
    unit_cost_minor: int = 0,
    reference_type: str | None = None,
    reference_id: int | None = None,
    reason: str | None = None,
    note: str | None = None,
    operator_id: int | None = None,
    business_date: date | None = None,
) -> StockMovement:
    """Apply a stock delta and append the matching movement in one unit of work."""
    if quantity_change_milli == 0:
        raise ValidationError("The stock movement has no quantity change.")
    before = int(product.quantity_milli)
    after = before + int(quantity_change_milli)
    if after < 0:
        raise ConflictError(
            f"Cannot reduce {product.name} below zero (available {from_milli(before)})."
        )
    product.quantity_milli = after
    product.updated_at = utc_now()
    movement = StockMovement(
        product_id=product.id,
        movement_type=movement_type,
        quantity_change_milli=int(quantity_change_milli),
        quantity_before_milli=before,
        quantity_after_milli=after,
        unit_cost_minor=max(0, int(unit_cost_minor or 0)),
        reference_type=reference_type,
        reference_id=reference_id,
        reason=reason,
        note=note,
        operator_id=operator_id,
        business_date=business_date or today(),
    )
    session.add(movement)
    return movement


def find_or_create_supplier(session: Session, name: str | None) -> Supplier | None:
    name = (name or "").strip()
    if not name:
        return None
    supplier = session.query(Supplier).filter(Supplier.name.ilike(name)).one_or_none()
    if supplier is None:
        supplier = Supplier(name=name, is_active=True)
        session.add(supplier)
        session.flush()
    return supplier


@security.requires(security.P_STOCK_RECEIVE)
def receive_stock(
    session: Session,
    *,
    product_id: int,
    quantity,
    unit_cost=None,
    supplier_name: str | None = None,
    reference: str | None = None,
    note: str | None = None,
    operator_id: int | None = None,
    business_date: date | None = None,
    update_cost_price: bool = True,
) -> StockReceipt:
    product = _get_product(session, product_id)
    qty_milli = to_milli(quantity, field="Quantity received")
    if qty_milli <= 0:
        raise ValidationError("Quantity received must be greater than zero.", "quantity")
    if unit_cost in (None, ""):
        cost_minor = int(product.cost_price_minor)
    else:
        cost_decimal = to_minor(unit_cost, field="Unit cost")
        if cost_decimal < 0:
            raise ValidationError("Unit cost cannot be negative.", "unit_cost")
        cost_minor = cost_decimal

    supplier = find_or_create_supplier(session, supplier_name)
    receipt = StockReceipt(
        product_id=product.id,
        quantity_milli=qty_milli,
        unit_cost_minor=cost_minor,
        supplier_id=supplier.id if supplier else None,
        reference=(reference or "").strip() or None,
        note=(note or "").strip() or None,
        operator_id=operator_id,
        business_date=business_date or today(),
    )
    session.add(receipt)
    session.flush()

    movement = apply_movement(
        session,
        product,
        qty_milli,
        MOVEMENT_RECEIPT,
        unit_cost_minor=cost_minor,
        reference_type="stock_receipt",
        reference_id=receipt.id,
        reason="Stock received",
        note=reference,
        operator_id=operator_id,
        business_date=receipt.business_date,
    )
    if update_cost_price and cost_minor > 0:
        product.cost_price_minor = cost_minor
        product.updated_at = utc_now()

    audit.record(
        session,
        "stock.received",
        "product",
        product.id,
        operator_id=operator_id,
        reason="Stock received",
        details={
            "quantity": str(from_milli(qty_milli)),
            "unit_cost_minor": cost_minor,
            "reference": receipt.reference,
            "supplier": supplier.name if supplier else None,
            "movement_id": movement.id,
        },
    )
    mark_daily_dirty(session, receipt.business_date)
    session.flush()
    return receipt


@security.requires(security.P_STOCK_ADJUST)
def adjust_stock(
    session: Session,
    *,
    product_id: int,
    adjustment_type: str,
    quantity=None,
    new_quantity=None,
    reason: str,
    note: str | None = None,
    operator_id: int | None = None,
    business_date: date | None = None,
) -> StockMovement:
    """Record damage/loss/expiry, a count correction, or another adjustment.

    `count` uses `new_quantity` (the physically counted stock) and derives the
    delta.  Other types use a positive `quantity` magnitude that is removed.
    """
    if adjustment_type not in ADJUSTMENT_TYPES:
        raise ValidationError("Unknown adjustment type.", "adjustment_type")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required for stock adjustments.", "reason")

    product = _get_product(session, product_id)
    if adjustment_type == "count":
        if new_quantity is None:
            raise ValidationError("Enter the counted quantity.", "new_quantity")
        counted = to_milli(new_quantity, field="Counted quantity")
        if counted < 0:
            raise ValidationError("Counted quantity cannot be negative.", "new_quantity")
        delta = counted - int(product.quantity_milli)
        if delta == 0:
            raise ValidationError("The counted quantity matches current stock; no adjustment needed.")
        movement_type = MOVEMENT_ADJUSTMENT
    else:
        if quantity is None:
            raise ValidationError("Enter a quantity.", "quantity")
        amount = to_milli(quantity, field="Quantity")
        if amount <= 0:
            raise ValidationError("Adjustment quantity must be greater than zero.", "quantity")
        delta = -amount
        movement_type = ADJUSTMENT_TYPES[adjustment_type]

    movement = apply_movement(
        session,
        product,
        delta,
        movement_type,
        unit_cost_minor=product.cost_price_minor,
        reference_type="adjustment",
        reason=reason,
        note=note,
        operator_id=operator_id,
        business_date=business_date or today(),
    )
    audit.record(
        session,
        "stock.adjusted",
        "product",
        product.id,
        operator_id=operator_id,
        reason=reason,
        details={
            "type": adjustment_type,
            "delta": str(from_milli(delta)),
            "before": str(from_milli(movement.quantity_before_milli)),
            "after": str(from_milli(movement.quantity_after_milli)),
            "movement_id": movement.id,
        },
    )
    mark_daily_dirty(session, movement.business_date)
    session.flush()
    return movement


def return_stock(
    session: Session,
    *,
    product: Product,
    quantity_milli: int,
    reference_id: int,
    reason: str,
    operator_id: int | None = None,
    business_date: date | None = None,
) -> StockMovement:
    """Restock returned goods (used by refunds/reversals)."""
    if quantity_milli <= 0:
        raise ValidationError("Returned quantity must be positive.")
    movement = apply_movement(
        session,
        product,
        quantity_milli,
        MOVEMENT_RETURN,
        unit_cost_minor=product.cost_price_minor,
        reference_type="refund",
        reference_id=reference_id,
        reason=reason,
        operator_id=operator_id,
        business_date=business_date or today(),
    )
    mark_daily_dirty(session, movement.business_date)
    return movement


def movement_history(session: Session, product_id: int, limit: int = 200) -> list[StockMovement]:
    return (
        session.query(StockMovement)
        .filter(StockMovement.product_id == product_id)
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .limit(limit)
        .all()
    )


def recent_receipts(session: Session, limit: int = 100) -> list[StockReceipt]:
    return (
        session.query(StockReceipt)
        .order_by(StockReceipt.created_at.desc(), StockReceipt.id.desc())
        .limit(limit)
        .all()
    )


def recent_adjustments(session: Session, limit: int = 100) -> list[StockMovement]:
    return (
        session.query(StockMovement)
        .filter(
            StockMovement.movement_type.in_(
                [MOVEMENT_DAMAGE, MOVEMENT_LOSS, MOVEMENT_EXPIRY, MOVEMENT_ADJUSTMENT]
            ),
            StockMovement.reference_type != "import",
        )
        .order_by(StockMovement.created_at.desc(), StockMovement.id.desc())
        .limit(limit)
        .all()
    )
