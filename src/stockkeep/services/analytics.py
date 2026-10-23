"""Read models and aggregates used by the dashboard, exports and reports."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..models import (
    ACTIVE_SALE_STATUSES,
    SALE_REVERSED,
    MOVEMENT_ADJUSTMENT,
    MOVEMENT_DAMAGE,
    MOVEMENT_EXPIRY,
    MOVEMENT_IMPORT,
    MOVEMENT_LOSS,
    MOVEMENT_OPENING,
    MOVEMENT_RECEIPT,
    MOVEMENT_RETURN,
    MOVEMENT_SALE,
    Category,
    Product,
    Refund,
    RefundItem,
    Sale,
    SaleItem,
    StockMovement,
)
from ..money import from_milli, from_minor, quantize_money
from ..timeutil import month_bounds, today

ZERO = Decimal("0")

COUNTED_SALE_STATUSES = (ACTIVE_SALE_STATUSES[0], ACTIVE_SALE_STATUSES[1], "refunded")


def _int(value) -> int:
    return int(value or 0)


def _minor_from_numerator(numerator) -> int:
    """Convert sum(quantity_milli * price_minor) to minor units."""
    return int((Decimal(_int(numerator)) / Decimal(1000)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _sum_int(session: Session, column) -> int:
    return _int(session.query(func.coalesce(func.sum(column), 0)).scalar())


def sales_summary(session: Session, start: date, end: date) -> dict:
    """Revenue summary for a business-date range.

    Reversed sales are excluded (they are nullified).  Refunds (not reversals)
    are subtracted on the date the refund was recorded.
    """
    sale_rows = (
        session.query(
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.subtotal_minor), 0),
            func.coalesce(func.sum(Sale.discount_total_minor), 0),
            func.coalesce(func.sum(Sale.net_total_minor), 0),
        )
        .filter(
            Sale.business_date >= start,
            Sale.business_date <= end,
            Sale.status != SALE_REVERSED,
        )
        .one()
    )
    sales_count, gross, discounts, gross_net = (int(v or 0) for v in sale_rows)
    refund_total = int(
        session.query(func.coalesce(func.sum(Refund.amount_minor), 0))
        .join(Sale, Refund.sale_id == Sale.id)
        .filter(
            Refund.business_date >= start,
            Refund.business_date <= end,
            Refund.kind == "refund",
        )
        .scalar()
        or 0
    )
    net = gross - discounts - refund_total
    return {
        "sales_count": sales_count,
        "gross_minor": gross,
        "discount_minor": discounts,
        "refund_minor": refund_total,
        "net_minor": net,
    }


def units_sold(session: Session, start: date, end: date) -> int:
    value = (
        session.query(func.coalesce(func.sum(StockMovement.quantity_change_milli), 0))
        .filter(
            StockMovement.movement_type == MOVEMENT_SALE,
            StockMovement.business_date >= start,
            StockMovement.business_date <= end,
        )
        .scalar()
        or 0
    )
    return -int(value)


def refunds_total(session: Session, start: date, end: date, *, include_reversals: bool = False) -> int:
    query = session.query(func.coalesce(func.sum(Refund.amount_minor), 0)).filter(
        Refund.business_date >= start, Refund.business_date <= end
    )
    if not include_reversals:
        query = query.filter(Refund.kind == "refund")
    return int(query.scalar() or 0)


def payment_totals(session: Session, start: date, end: date) -> list[dict]:
    sales = (
        session.query(
            Sale.payment_method,
            func.coalesce(func.sum(Sale.subtotal_minor), 0),
            func.coalesce(func.sum(Sale.discount_total_minor), 0),
            func.coalesce(func.sum(Sale.net_total_minor), 0),
        )
        .filter(
            Sale.business_date >= start,
            Sale.business_date <= end,
            Sale.status != SALE_REVERSED,
        )
        .group_by(Sale.payment_method)
        .all()
    )
    refunds = (
        session.query(Sale.payment_method, func.coalesce(func.sum(Refund.amount_minor), 0))
        .join(Sale, Refund.sale_id == Sale.id)
        .filter(
            Refund.business_date >= start,
            Refund.business_date <= end,
            Refund.kind == "refund",
        )
        .group_by(Sale.payment_method)
        .all()
    )
    refund_map = {row[0]: int(row[1] or 0) for row in refunds}
    rows = []
    seen = set()
    for method, gross, discount, net in sales:
        refunded = refund_map.get(method, 0)
        rows.append(
            {
                "payment_method": method,
                "gross_minor": int(gross or 0),
                "discount_minor": int(discount or 0),
                "refund_minor": refunded,
                "net_minor": int(net or 0) - refunded,
            }
        )
        seen.add(method)
    for method in ("Cash", "Bank Transfer", "Card", "Other"):
        if method not in seen and refund_map.get(method):
            rows.append(
                {
                    "payment_method": method,
                    "gross_minor": 0,
                    "discount_minor": 0,
                    "refund_minor": refund_map[method],
                    "net_minor": -refund_map[method],
                }
            )
    order = {name: i for i, name in enumerate(("Cash", "Bank Transfer", "Card", "Other"))}
    rows.sort(key=lambda r: order.get(r["payment_method"], 99))
    return rows


def cost_of_goods_sold(session: Session, start: date, end: date) -> int:
    sold_numerator = (
        session.query(
            func.coalesce(func.sum(SaleItem.quantity_milli * SaleItem.unit_cost_minor), 0)
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.business_date >= start,
            Sale.business_date <= end,
            Sale.status != SALE_REVERSED,
        )
        .scalar()
        or 0
    )
    refunded_numerator = (
        session.query(
            func.coalesce(func.sum(RefundItem.quantity_milli * SaleItem.unit_cost_minor), 0)
        )
        .join(Refund, RefundItem.refund_id == Refund.id)
        .join(SaleItem, RefundItem.sale_item_id == SaleItem.id)
        .filter(
            Refund.business_date >= start,
            Refund.business_date <= end,
            Refund.kind == "refund",
        )
        .scalar()
        or 0
    )
    return _minor_from_numerator(_int(sold_numerator) - _int(refunded_numerator))


def gross_profit(session: Session, start: date, end: date) -> int:
    summary = sales_summary(session, start, end)
    return summary["net_minor"] - cost_of_goods_sold(session, start, end)


def stock_quantities(session: Session) -> dict:
    return {"opening": 0}


def movement_summary(session: Session, start: date, end: date) -> dict:
    rows = (
        session.query(
            StockMovement.movement_type,
            func.coalesce(func.sum(StockMovement.quantity_change_milli), 0),
        )
        .filter(
            StockMovement.business_date >= start,
            StockMovement.business_date <= end,
        )
        .group_by(StockMovement.movement_type)
        .all()
    )
    by_type = {row[0]: int(row[1] or 0) for row in rows}
    opening = (
        session.query(func.coalesce(func.sum(StockMovement.quantity_change_milli), 0))
        .filter(StockMovement.business_date < start)
        .scalar()
        or 0
    )
    closing = int(opening) + sum(by_type.values())
    return {
        "opening_milli": int(opening),
        "closing_milli": closing,
        "received_milli": by_type.get(MOVEMENT_RECEIPT, 0),
        "sold_milli": -by_type.get(MOVEMENT_SALE, 0),
        "returned_milli": by_type.get(MOVEMENT_RETURN, 0),
        "damaged_milli": -by_type.get(MOVEMENT_DAMAGE, 0),
        "lost_milli": -by_type.get(MOVEMENT_LOSS, 0),
        "expired_milli": -by_type.get(MOVEMENT_EXPIRY, 0),
        "adjusted_milli": by_type.get(MOVEMENT_ADJUSTMENT, 0),
        "imported_milli": by_type.get(MOVEMENT_IMPORT, 0),
        "opening_movement_milli": by_type.get(MOVEMENT_OPENING, 0),
        "movement_total_milli": sum(by_type.values()),
        "by_type": by_type,
    }


def inventory_valuation(session: Session, *, active_only: bool = True) -> dict:
    query = session.query(Product)
    if active_only:
        query = query.filter(Product.is_active.is_(True))
    products = query.all()
    cost_numerator = 0
    sell_numerator = 0
    units_milli = 0
    missing_cost = 0
    for product in products:
        units_milli += product.quantity_milli
        if product.cost_price_minor > 0:
            cost_numerator += product.quantity_milli * product.cost_price_minor
        elif product.quantity_milli > 0:
            missing_cost += 1
        sell_numerator += product.quantity_milli * product.selling_price_minor
    return {
        "cost_minor": _minor_from_numerator(cost_numerator),
        "selling_minor": _minor_from_numerator(sell_numerator),
        "units_milli": units_milli,
        "missing_cost_products": missing_cost,
        "product_count": len(products),
    }


def low_stock_products(session: Session, limit: int = 20) -> list[Product]:
    return (
        session.query(Product)
        .filter(
            Product.is_active.is_(True),
            Product.quantity_milli > 0,
            Product.reorder_level_milli > 0,
            Product.quantity_milli <= Product.reorder_level_milli,
        )
        .order_by((Product.quantity_milli - Product.reorder_level_milli).asc(), Product.name.asc())
        .limit(limit)
        .all()
    )


def out_of_stock_products(session: Session, limit: int = 20) -> list[Product]:
    return (
        session.query(Product)
        .filter(Product.is_active.is_(True), Product.quantity_milli <= 0)
        .order_by(Product.name.asc())
        .limit(limit)
        .all()
    )


def recent_sales(session: Session, limit: int = 10) -> list[Sale]:
    return session.query(Sale).order_by(Sale.created_at.desc(), Sale.id.desc()).limit(limit).all()


def best_sellers(session: Session, start: date, end: date, limit: int = 8) -> list[dict]:
    rows = (
        session.query(
            SaleItem.product_id,
            SaleItem.product_name_snapshot,
            func.coalesce(func.sum(SaleItem.quantity_milli), 0),
            func.coalesce(func.sum(SaleItem.line_total_minor), 0),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.business_date >= start,
            Sale.business_date <= end,
            Sale.status != SALE_REVERSED,
        )
        .group_by(SaleItem.product_id, SaleItem.product_name_snapshot)
        .order_by(func.sum(SaleItem.quantity_milli).desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "product_id": row[0],
            "name": row[1],
            "quantity_milli": int(row[2] or 0),
            "revenue_minor": int(row[3] or 0),
        }
        for row in rows
    ]


def sales_trend(session: Session, end: date, days: int = 14) -> list[dict]:
    start = end - timedelta(days=days - 1)
    rows = (
        session.query(
            Sale.business_date,
            func.count(Sale.id),
            func.coalesce(func.sum(Sale.subtotal_minor - Sale.discount_total_minor), 0),
        )
        .filter(
            Sale.business_date >= start,
            Sale.business_date <= end,
            Sale.status != SALE_REVERSED,
        )
        .group_by(Sale.business_date)
        .all()
    )
    by_day = {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in rows}
    result = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        count, net = by_day.get(day, (0, 0))
        result.append({"date": day, "sales_count": count, "net_minor": net})
    return result


def dashboard_stats(session: Session, tz_name: str, *, on: date | None = None) -> dict:
    day = on or today(tz_name)
    valuation = inventory_valuation(session)
    summary = sales_summary(session, day, day)
    active_products = (
        session.query(func.count(Product.id)).filter(Product.is_active.is_(True)).scalar() or 0
    )
    low_count = (
        session.query(func.count(Product.id))
        .filter(
            Product.is_active.is_(True),
            Product.quantity_milli > 0,
            Product.reorder_level_milli > 0,
            Product.quantity_milli <= Product.reorder_level_milli,
        )
        .scalar()
        or 0
    )
    out_count = (
        session.query(func.count(Product.id))
        .filter(Product.is_active.is_(True), Product.quantity_milli <= 0)
        .scalar()
        or 0
    )
    trend = sales_trend(session, day)
    month_start = day.replace(day=1)
    return {
        "business_date": day,
        "active_products": int(active_products),
        "units_milli": valuation["units_milli"],
        "inventory_cost_minor": valuation["cost_minor"],
        "inventory_selling_minor": valuation["selling_minor"],
        "missing_cost_products": valuation["missing_cost_products"],
        "today_sales_count": summary["sales_count"],
        "today_gross_minor": summary["gross_minor"],
        "today_discount_minor": summary["discount_minor"],
        "today_refund_minor": summary["refund_minor"],
        "today_net_minor": summary["net_minor"],
        "low_stock_count": int(low_count),
        "out_of_stock_count": int(out_count),
        "trend": trend,
        "recent_sales": recent_sales(session, 8),
        "low_stock": low_stock_products(session, 8),
        "out_of_stock": out_of_stock_products(session, 8),
        "best_sellers": best_sellers(session, day - timedelta(days=29), day, 6),
        "month_net_minor": sales_summary(session, month_start, day)["net_minor"],
    }


# ---------------------------------------------------------------------------
# Row builders for exports / daily reports
# ---------------------------------------------------------------------------
def transaction_rows(
    session: Session,
    start: date,
    end: date,
    *,
    product_id: int | None = None,
    payment_method: str | None = None,
    include_all_statuses: bool = True,
    search: str | None = None,
) -> list[dict]:
    query = (
        session.query(SaleItem, Sale)
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(Sale.business_date >= start, Sale.business_date <= end)
    )
    if not include_all_statuses:
        query = query.filter(Sale.status != SALE_REVERSED)
    if product_id:
        query = query.filter(SaleItem.product_id == product_id)
    if payment_method:
        query = query.filter(Sale.payment_method == payment_method)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Sale.transaction_number.ilike(pattern),
                SaleItem.product_name_snapshot.ilike(pattern),
            )
        )
    query = query.order_by(Sale.created_at.asc(), Sale.id.asc(), SaleItem.id.asc())
    rows = []
    for item, sale in query.all():
        rows.append(
            {
                "transaction_number": sale.transaction_number,
                "business_date": sale.business_date,
                "created_at": sale.created_at,
                "product_id": item.product_id,
                "product_name": item.product_name_snapshot,
                "quantity_milli": item.quantity_milli,
                "unit_price_minor": item.unit_price_minor,
                "discount_minor": item.discount_minor,
                "line_total_minor": item.line_total_minor,
                "payment_method": sale.payment_method,
                "operator": sale.operator.name if sale.operator else "",
                "status": sale.status,
                "sale_id": sale.id,
                "sale_net_minor": sale.net_total_minor,
                "sale_refund_minor": sale.refund_total_minor,
                "notes": sale.notes or "",
            }
        )
    return rows


def stock_movement_rows(
    session: Session,
    start: date,
    end: date,
    *,
    product_id: int | None = None,
) -> list[dict]:
    query = (
        session.query(StockMovement)
        .filter(
            StockMovement.business_date >= start,
            StockMovement.business_date <= end,
        )
    )
    if product_id:
        query = query.filter(StockMovement.product_id == product_id)
    query = query.order_by(StockMovement.created_at.asc(), StockMovement.id.asc())
    rows = []
    for movement in query.all():
        product = session.get(Product, movement.product_id)
        rows.append(
            {
                "business_date": movement.business_date,
                "created_at": movement.created_at,
                "product_id": movement.product_id,
                "product_name": product.name if product else "",
                "movement_type": movement.movement_type,
                "quantity_change_milli": movement.quantity_change_milli,
                "quantity_before_milli": movement.quantity_before_milli,
                "quantity_after_milli": movement.quantity_after_milli,
                "unit_cost_minor": movement.unit_cost_minor,
                "reference": f"{movement.reference_type or ''} {movement.reference_id or ''}".strip(),
                "reason": movement.reason or "",
                "operator": movement.operator.name if movement.operator else "",
            }
        )
    return rows


def refund_rows(
    session: Session,
    start: date,
    end: date,
    *,
    product_id: int | None = None,
) -> list[dict]:
    query = (
        session.query(Refund)
        .filter(Refund.business_date >= start, Refund.business_date <= end)
        .order_by(Refund.created_at.asc(), Refund.id.asc())
    )
    rows = []
    for refund in query.all():
        sale = session.get(Sale, refund.sale_id)
        if product_id:
            product_ids = {item.product_id for item in refund.items}
            if product_id not in product_ids:
                continue
        rows.append(
            {
                "refund_number": refund.refund_number,
                "business_date": refund.business_date,
                "created_at": refund.created_at,
                "transaction_number": sale.transaction_number if sale else "",
                "kind": refund.kind,
                "amount_minor": refund.amount_minor,
                "payment_method": sale.payment_method if sale else "",
                "reason": refund.reason,
                "restocked": "Yes" if refund.restocked else "No",
                "operator": refund.operator.name if refund.operator else "",
            }
        )
    return rows


def daily_summary_rows(session: Session, start: date, end: date) -> list[dict]:
    rows = []
    day = start
    while day <= end:
        summary = sales_summary(session, day, day)
        rows.append(
            {
                "business_date": day,
                **summary,
                "units_milli": units_sold(session, day, day),
                "cogs_minor": cost_of_goods_sold(session, day, day),
            }
        )
        day += timedelta(days=1)
    return rows


def inventory_rows(session: Session, *, product_id: int | None = None) -> list[dict]:
    query = session.query(Product).order_by(Product.name.asc())
    if product_id:
        query = query.filter(Product.id == product_id)
    rows = []
    for product in query.all():
        rows.append(
            {
                "product_code": product.product_code,
                "name": product.name,
                "sku": product.sku or "",
                "category": product.category_name,
                "unit": product.unit,
                "cost_price_minor": product.cost_price_minor,
                "selling_price_minor": product.selling_price_minor,
                "quantity_milli": product.quantity_milli,
                "reorder_level_milli": product.reorder_level_milli,
                "status": product.status() if product.is_active else "Archived",
                "cost_value_minor": _minor_from_numerator(
                    product.quantity_milli * product.cost_price_minor
                ),
                "selling_value_minor": _minor_from_numerator(
                    product.quantity_milli * product.selling_price_minor
                ),
                "updated_at": product.updated_at,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# Monthly report
# ---------------------------------------------------------------------------
def monthly_summary(session: Session, year: int, month: int) -> dict:
    start, end = month_bounds(year, month)
    sales = sales_summary(session, start, end)
    movements = movement_summary(session, start, end)
    cogs = cost_of_goods_sold(session, start, end)
    valuation = inventory_valuation(session)
    payment = payment_totals(session, start, end)
    daily = daily_summary_rows(session, start, end)
    products = product_performance(session, start, end)
    return {
        "year": year,
        "month": month,
        "start": start,
        "end": end,
        "opening_milli": movements["opening_milli"],
        "received_milli": movements["received_milli"],
        "sold_milli": movements["sold_milli"],
        "returned_milli": movements["returned_milli"],
        "damaged_milli": movements["damaged_milli"],
        "lost_milli": movements["lost_milli"],
        "expired_milli": movements["expired_milli"],
        "adjusted_milli": movements["adjusted_milli"],
        "closing_milli": movements["closing_milli"],
        "gross_minor": sales["gross_minor"],
        "discount_minor": sales["discount_minor"],
        "refund_minor": sales["refund_minor"],
        "net_minor": sales["net_minor"],
        "sales_count": sales["sales_count"],
        "cogs_minor": cogs,
        "gross_profit_minor": sales["net_minor"] - cogs,
        "payment_totals": payment,
        "daily": daily,
        "products": products,
        "valuation": valuation,
        "best_sellers": best_sellers(session, start, end, 10),
        "movement_by_type": movements["by_type"],
    }


def product_performance(session: Session, start: date, end: date) -> list[dict]:
    """Movement-ledger based per-product performance for the period."""
    before = dict(
        session.query(
            StockMovement.product_id,
            func.coalesce(func.sum(StockMovement.quantity_change_milli), 0),
        )
        .filter(StockMovement.business_date < start)
        .group_by(StockMovement.product_id)
        .all()
    )
    activity_rows = (
        session.query(
            StockMovement.product_id,
            StockMovement.movement_type,
            func.coalesce(func.sum(StockMovement.quantity_change_milli), 0),
        )
        .filter(
            StockMovement.business_date >= start,
            StockMovement.business_date <= end,
        )
        .group_by(StockMovement.product_id, StockMovement.movement_type)
        .all()
    )
    activity: dict[int, dict[str, int]] = {}
    product_ids = set(before)
    for product_id, movement_type, total in activity_rows:
        product_ids.add(product_id)
        activity.setdefault(product_id, {})[movement_type] = int(total or 0)

    revenue_rows = (
        session.query(
            SaleItem.product_id,
            func.coalesce(func.sum(SaleItem.quantity_milli), 0),
            func.coalesce(func.sum(SaleItem.line_total_minor), 0),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.business_date >= start,
            Sale.business_date <= end,
            Sale.status != SALE_REVERSED,
        )
        .group_by(SaleItem.product_id)
        .all()
    )
    revenue = {row[0]: (int(row[1] or 0), int(row[2] or 0)) for row in revenue_rows}

    cogs_rows = (
        session.query(
            SaleItem.product_id,
            func.coalesce(func.sum(SaleItem.quantity_milli * SaleItem.unit_cost_minor), 0),
        )
        .join(Sale, SaleItem.sale_id == Sale.id)
        .filter(
            Sale.business_date >= start,
            Sale.business_date <= end,
            Sale.status != SALE_REVERSED,
        )
        .group_by(SaleItem.product_id)
        .all()
    )
    cogs = {row[0]: _minor_from_numerator(row[1]) for row in cogs_rows}

    refund_rows_data = (
        session.query(
            RefundItem.product_id,
            func.coalesce(func.sum(RefundItem.quantity_milli), 0),
            func.coalesce(func.sum(RefundItem.amount_minor), 0),
            func.coalesce(func.sum(RefundItem.quantity_milli * SaleItem.unit_cost_minor), 0),
        )
        .join(Refund, RefundItem.refund_id == Refund.id)
        .join(SaleItem, RefundItem.sale_item_id == SaleItem.id)
        .filter(
            Refund.business_date >= start,
            Refund.business_date <= end,
            Refund.kind == "refund",
        )
        .group_by(RefundItem.product_id)
        .all()
    )
    refund_map = {
        row[0]: {
            "qty": int(row[1] or 0),
            "amount": int(row[2] or 0),
            "cogs": _minor_from_numerator(row[3]),
        }
        for row in refund_rows_data
    }

    results = []
    for product_id in sorted(product_ids):
        product = session.get(Product, product_id)
        if product is None:
            continue
        opening = int(before.get(product_id, 0))
        types = activity.get(product_id, {})
        received = types.get(MOVEMENT_RECEIPT, 0)
        sold = -types.get(MOVEMENT_SALE, 0)
        returned = types.get(MOVEMENT_RETURN, 0)
        damaged = -types.get(MOVEMENT_DAMAGE, 0)
        lost = -types.get(MOVEMENT_LOSS, 0)
        expired = -types.get(MOVEMENT_EXPIRY, 0)
        adjusted = types.get(MOVEMENT_ADJUSTMENT, 0) + types.get(MOVEMENT_IMPORT, 0)
        opening_movement = types.get(MOVEMENT_OPENING, 0)
        closing = opening + opening_movement + received + sold * -1 + returned + (damaged + lost + expired) * -1 + adjusted
        sold_qty, sold_revenue = revenue.get(product_id, (0, 0))
        refund = refund_map.get(product_id, {"qty": 0, "amount": 0, "cogs": 0})
        cogs_value = max(0, cogs.get(product_id, 0) - refund["cogs"])
        net_revenue = sold_revenue - refund["amount"]
        results.append(
            {
                "product_id": product_id,
                "product_code": product.product_code,
                "name": product.name,
                "unit": product.unit,
                "opening_milli": opening,
                "received_milli": received,
                "sold_milli": sold,
                "returned_milli": returned,
                "damaged_milli": damaged,
                "lost_milli": lost,
                "expired_milli": expired,
                "adjusted_milli": adjusted,
                "closing_milli": closing,
                "revenue_minor": net_revenue,
                "cogs_minor": cogs_value,
                "gross_profit_minor": net_revenue - cogs_value,
                "cost_price_minor": product.cost_price_minor,
            }
        )
    results.sort(key=lambda r: r["revenue_minor"], reverse=True)
    return results
