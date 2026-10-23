"""Sales, refunds and reversals with atomic stock deduction."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from sqlalchemy import or_

from ..atomic import savepoint
from .. import security
from ..errors import ConflictError, NotFoundError, ValidationError
from ..models import (
    ACTIVE_SALE_STATUSES,
    PAYMENT_METHODS,
    SALE_COMPLETED,
    SALE_PARTIAL_REFUND,
    SALE_REFUNDED,
    SALE_REVERSED,
    MOVEMENT_SALE,
    Product,
    Refund,
    RefundItem,
    Sale,
    SaleItem,
    StockMovement,
)
from ..money import (
    from_milli,
    from_minor,
    line_total_minor,
    parse_decimal,
    quantize_money,
    to_milli,
    to_minor,
)
from ..timeutil import today, utc_now
from . import audit, stock
from .report_state import mark_daily_dirty


def _payment_method(value: str | None) -> str:
    text = (value or "").strip()
    for method in PAYMENT_METHODS:
        if method.lower() == text.lower():
            return method
    raise ValidationError(f"Unknown payment method: {value!r}", "payment_method")


def _normalise_items(items) -> list[dict]:
    if not items:
        raise ValidationError("A sale must contain at least one product.")
    merged: dict[int, dict] = {}
    for raw in items:
        try:
            product_id = int(raw["product_id"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError("Each sale item needs a valid product.", "items") from None
        quantity = raw.get("quantity")
        qty_milli = to_milli(quantity, field="Quantity")
        if qty_milli <= 0:
            raise ValidationError("Sale quantity must be greater than zero.", "quantity")
        if "discount_minor" in raw:
            discount_minor = int(raw.get("discount_minor") or 0)
        else:
            discount_minor = to_minor(raw.get("discount") or 0, field="Discount")
        if discount_minor < 0:
            raise ValidationError("Discount cannot be negative.", "discount")
        if product_id in merged:
            merged[product_id]["quantity_milli"] += qty_milli
            merged[product_id]["discount_minor"] += discount_minor
        else:
            merged[product_id] = {
                "product_id": product_id,
                "quantity_milli": qty_milli,
                "discount_minor": discount_minor,
            }
    return list(merged.values())


def find_sale_by_idempotency(session: Session, key: str | None) -> Sale | None:
    if not key:
        return None
    return session.query(Sale).filter(Sale.idempotency_key == key).one_or_none()


@security.requires(security.P_SALES_CREATE)
@savepoint
def create_sale(
    session: Session,
    *,
    items,
    payment_method: str,
    operator_id: int | None = None,
    business_date: date | None = None,
    created_at: datetime | None = None,
    idempotency_key: str | None = None,
    notes: str | None = None,
) -> Sale:
    """Create a sale and deduct stock in a single transaction.

    Callers must wrap this in a session transaction.  Any failure raises and the
    caller's session context rolls the whole unit of work back.
    """
    if idempotency_key:
        existing = find_sale_by_idempotency(session, idempotency_key)
        if existing is not None:
            return existing

    payment = _payment_method(payment_method)
    normalised = _normalise_items(items)
    business_day = business_date or today()
    timestamp = created_at or utc_now()

    products: dict[int, Product] = {}
    for item in normalised:
        product = session.get(Product, item["product_id"])
        if product is None:
            raise NotFoundError(f"Product {item['product_id']} not found.")
        if not product.is_active:
            raise ValidationError(f"{product.name} is archived and cannot be sold.", "product")
        products[product.id] = product

    subtotal = 0
    discount_total = 0
    prepared: list[dict] = []
    for item in normalised:
        product = products[item["product_id"]]
        qty = item["quantity_milli"]
        discount = item["discount_minor"]
        gross = line_total_minor(qty, product.selling_price_minor, 0)
        if discount > gross:
            raise ValidationError(
                f"Discount for {product.name} cannot exceed the line value.", "discount"
            )
        subtotal += gross
        discount_total += discount
        prepared.append(
            {
                "product": product,
                "quantity_milli": qty,
                "unit_price_minor": product.selling_price_minor,
                "unit_cost_minor": product.cost_price_minor,
                "discount_minor": discount,
                "line_total_minor": gross - discount,
            }
        )
    net_total = subtotal - discount_total

    sale = Sale(
        transaction_number=f"TMP-{uuid.uuid4().hex}",
        business_date=business_day,
        created_at=timestamp,
        operator_id=operator_id,
        payment_method=payment,
        subtotal_minor=subtotal,
        discount_total_minor=discount_total,
        refund_total_minor=0,
        net_total_minor=net_total,
        status=SALE_COMPLETED,
        idempotency_key=idempotency_key,
        notes=(notes or "").strip() or None,
    )
    session.add(sale)
    session.flush()
    sale.transaction_number = f"TXN-{business_day:%Y%m%d}-{sale.id:06d}"

    sale_items: list[SaleItem] = []
    for row in prepared:
        product = row["product"]
        sale_item = SaleItem(
            sale_id=sale.id,
            product_id=product.id,
            product_name_snapshot=product.name,
            quantity_milli=row["quantity_milli"],
            unit_price_minor=row["unit_price_minor"],
            unit_cost_minor=row["unit_cost_minor"],
            discount_minor=row["discount_minor"],
            line_total_minor=row["line_total_minor"],
        )
        session.add(sale_item)
        session.flush()
        sale_items.append(sale_item)

        # Conditional atomic deduction: never oversell, even under concurrency.
        result = session.execute(
            update(Product)
            .where(
                Product.id == product.id,
                Product.quantity_milli >= row["quantity_milli"],
                Product.is_active.is_(True),
            )
            .values(
                quantity_milli=Product.quantity_milli - row["quantity_milli"],
                updated_at=timestamp,
            )
            .returning(Product.quantity_milli)
        )
        after = result.scalar_one_or_none()
        if after is None:
            session.refresh(product)
            raise ConflictError(
                f"Insufficient stock for {product.name}: only "
                f"{from_milli(product.quantity_milli)} available."
            )
        after = int(after)
        before = after + row["quantity_milli"]
        product.quantity_milli = after
        session.add(
            StockMovement(
                product_id=product.id,
                movement_type=MOVEMENT_SALE,
                quantity_change_milli=-row["quantity_milli"],
                quantity_before_milli=before,
                quantity_after_milli=after,
                unit_cost_minor=row["unit_cost_minor"],
                reference_type="sale",
                reference_id=sale.id,
                reason=f"Sale {sale.transaction_number}",
                operator_id=operator_id,
                business_date=business_day,
                created_at=timestamp,
            )
        )

    audit.record(
        session,
        "sale.completed",
        "sale",
        sale.id,
        operator_id=operator_id,
        details={
            "transaction_number": sale.transaction_number,
            "payment_method": payment,
            "subtotal_minor": subtotal,
            "discount_minor": discount_total,
            "net_total_minor": net_total,
            "items": [
                {
                    "product_id": item.product_id,
                    "quantity": str(from_milli(item.quantity_milli)),
                    "unit_price_minor": item.unit_price_minor,
                    "line_total_minor": item.line_total_minor,
                }
                for item in sale_items
            ],
        },
    )
    mark_daily_dirty(session, business_day)
    session.flush()
    return sale


def get_sale(session: Session, sale_id: int) -> Sale:
    sale = session.get(Sale, sale_id)
    if sale is None:
        raise NotFoundError("Sale not found.")
    return sale


def refundable_quantities(session: Session, sale: Sale) -> dict[int, int]:
    """Remaining refundable quantity per sale-item id."""
    refunded: dict[int, int] = {}
    for refund_item in (
        session.query(RefundItem)
        .join(Refund, RefundItem.refund_id == Refund.id)
        .filter(Refund.sale_id == sale.id)
        .all()
    ):
        refunded[refund_item.sale_item_id] = (
            refunded.get(refund_item.sale_item_id, 0) + refund_item.quantity_milli
        )
    return {
        item.id: max(0, int(item.quantity_milli) - refunded.get(item.id, 0))
        for item in sale.items
    }


@security.requires(security.P_SALES_REFUND)
@savepoint
def refund_sale(
    session: Session,
    *,
    sale_id: int,
    reason: str,
    items=None,
    kind: str = "refund",
    restock: bool = True,
    operator_id: int | None = None,
    business_date: date | None = None,
) -> Refund:
    """Refund or reverse some/all of a sale.  History is never deleted."""
    if kind not in {"refund", "reversal"}:
        raise ValidationError("Refund kind must be refund or reversal.")
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("A reason is required for a refund or reversal.", "reason")
    sale = get_sale(session, sale_id)
    if sale.status not in ACTIVE_SALE_STATUSES:
        raise ConflictError("This sale has already been fully refunded or reversed.")

    remaining = refundable_quantities(session, sale)
    by_id = {item.id: item for item in sale.items}
    if not items:
        selected = [
            {"sale_item_id": item_id, "quantity_milli": qty}
            for item_id, qty in remaining.items()
            if qty > 0
        ]
    else:
        selected = []
        for raw in items:
            try:
                item_id = int(raw["sale_item_id"])
            except (KeyError, TypeError, ValueError):
                raise ValidationError("Invalid refund item.", "items") from None
            qty_milli = to_milli(raw.get("quantity"), field="Refund quantity")
            if qty_milli <= 0:
                continue
            if item_id not in by_id:
                raise ValidationError("Refund item does not belong to this sale.", "items")
            if qty_milli > remaining.get(item_id, 0):
                raise ConflictError(
                    f"Cannot refund more than the remaining quantity for "
                    f"{by_id[item_id].product_name_snapshot}."
                )
            selected.append({"sale_item_id": item_id, "quantity_milli": qty_milli})
    if not selected:
        raise ValidationError("Select at least one item and quantity to refund.")

    business_day = business_date or today()
    refund = Refund(
        refund_number=f"TMP-{uuid.uuid4().hex}",
        sale_id=sale.id,
        business_date=business_day,
        amount_minor=0,
        reason=reason,
        kind=kind,
        restocked=bool(restock),
        operator_id=operator_id,
    )
    session.add(refund)
    session.flush()
    prefix = "REV" if kind == "reversal" else "REF"
    refund.refund_number = f"{prefix}-{business_day:%Y%m%d}-{refund.id:06d}"

    total_amount = 0
    for raw in selected:
        sale_item = by_id[raw["sale_item_id"]]
        qty_milli = raw["quantity_milli"]
        gross = line_total_minor(qty_milli, sale_item.unit_price_minor, 0)
        # Proportional share of the original line discount, rounded half-up.
        discount_share = 0
        if sale_item.discount_minor:
            share = (
                from_minor(sale_item.discount_minor)
                * from_milli(qty_milli)
                / from_milli(sale_item.quantity_milli)
            )
            discount_share = int(quantize_money(share) * 100)
        amount = max(0, gross - discount_share)
        total_amount += amount
        session.add(
            RefundItem(
                refund_id=refund.id,
                sale_item_id=sale_item.id,
                product_id=sale_item.product_id,
                quantity_milli=qty_milli,
                amount_minor=amount,
            )
        )
        if restock:
            product = session.get(Product, sale_item.product_id)
            if product is not None:
                stock.return_stock(
                    session,
                    product=product,
                    quantity_milli=qty_milli,
                    reference_id=refund.id,
                    reason=f"{prefix.title()} {refund.refund_number}: {reason}",
                    operator_id=operator_id,
                    business_date=business_day,
                )

    refund.amount_minor = total_amount
    sale.refund_total_minor = int(sale.refund_total_minor) + total_amount
    session.flush()
    remaining_after = refundable_quantities(session, sale)
    if kind == "reversal":
        sale.status = SALE_REVERSED
    elif all(qty <= 0 for qty in remaining_after.values()):
        sale.status = SALE_REFUNDED
    else:
        sale.status = SALE_PARTIAL_REFUND

    audit.record(
        session,
        "sale.reversed" if kind == "reversal" else "sale.refunded",
        "sale",
        sale.id,
        operator_id=operator_id,
        reason=reason,
        details={
            "refund_number": refund.refund_number,
            "amount_minor": total_amount,
            "restocked": bool(restock),
            "items": [
                {"sale_item_id": raw["sale_item_id"], "quantity_milli": raw["quantity_milli"]}
                for raw in selected
            ],
        },
    )
    mark_daily_dirty(session, business_day)
    if sale.business_date != business_day:
        mark_daily_dirty(session, sale.business_date)
    session.flush()
    return refund


def reverse_sale(
    session: Session,
    *,
    sale_id: int,
    reason: str,
    restock: bool = True,
    operator_id: int | None = None,
    business_date: date | None = None,
) -> Refund:
    return refund_sale(
        session,
        sale_id=sale_id,
        reason=reason,
        kind="reversal",
        restock=restock,
        operator_id=operator_id,
        business_date=business_date,
    )


def list_sales(
    session: Session,
    *,
    start: date | None = None,
    end: date | None = None,
    status: str | None = None,
    payment_method: str | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 100,
) -> tuple[list[Sale], int]:
    query = session.query(Sale)
    if start:
        query = query.filter(Sale.business_date >= start)
    if end:
        query = query.filter(Sale.business_date <= end)
    if status and status not in {"all", "All"}:
        query = query.filter(Sale.status == status)
    if payment_method and payment_method not in {"all", "All"}:
        query = query.filter(Sale.payment_method == payment_method)
    term = (search or "").strip()
    if term:
        pattern = f"%{term}%"
        query = query.filter(
            or_(
                Sale.transaction_number.ilike(pattern),
                Sale.notes.ilike(pattern),
                Sale.id.in_(
                    session.query(SaleItem.sale_id).filter(
                        SaleItem.product_name_snapshot.ilike(pattern)
                    )
                ),
            )
        )
    total = query.count()
    page = max(1, int(page))
    page_size = max(1, min(500, int(page_size)))
    rows = (
        query.order_by(Sale.created_at.desc(), Sale.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return rows, total


def sale_refund_summary(session: Session, sale: Sale) -> dict:
    refunded_qty = 0
    refund_count = 0
    for refund in sale.refunds:
        refund_count += 1
        for item in refund.items:
            refunded_qty += item.quantity_milli
    sold_qty = sum(item.quantity_milli for item in sale.items)
    return {
        "refund_count": refund_count,
        "refunded_qty_milli": refunded_qty,
        "sold_qty_milli": sold_qty,
        "is_fully_refunded": refunded_qty >= sold_qty,
    }
