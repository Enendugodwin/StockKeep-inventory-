"""Product catalogue: validation, creation, editing and archiving."""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..errors import ConflictError, NotFoundError, ValidationError
from .. import security
from ..models import (
    MOVEMENT_OPENING,
    Category,
    Product,
    SaleItem,
    StockMovement,
)
from ..money import from_milli, from_minor, parse_decimal, to_milli, to_minor
from ..timeutil import today
from . import audit, stock
from .report_state import mark_daily_dirty

CODE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,39}$")
UNITS = [
    "pcs",
    "kg",
    "g",
    "litre",
    "ml",
    "pack",
    "box",
    "carton",
    "bag",
    "dozen",
    "metre",
    "yard",
]


def ensure_category(session: Session, name: str | None) -> Category | None:
    name = (name or "").strip()
    if not name:
        return None
    existing = session.query(Category).filter(func.lower(Category.name) == name.lower()).one_or_none()
    if existing:
        return existing
    category = Category(name=name)
    session.add(category)
    session.flush()
    return category


def list_categories(session: Session) -> list[Category]:
    return session.query(Category).order_by(Category.name.asc()).all()


def next_product_code(session: Session) -> str:
    codes = [
        row[0]
        for row in session.query(Product.product_code)
        .filter(Product.product_code.like("PRD-%"))
        .all()
    ]
    highest = 0
    for code in codes:
        try:
            highest = max(highest, int(code.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    candidate = highest + 1
    while session.query(Product.id).filter(Product.product_code == f"PRD-{candidate:05d}").first():
        candidate += 1
    return f"PRD-{candidate:05d}"


def _clean_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValidationError("Stock name is required.", "name")
    if len(name) > 240:
        raise ValidationError("Stock name must be 240 characters or fewer.", "name")
    return name


def _clean_sku(session: Session, value, *, exclude_id: int | None = None) -> str | None:
    sku = str(value or "").strip()
    if not sku:
        return None
    if len(sku) > 80:
        raise ValidationError("SKU / barcode must be 80 characters or fewer.", "sku")
    query = session.query(Product).filter(func.lower(Product.sku) == sku.lower())
    if exclude_id is not None:
        query = query.filter(Product.id != exclude_id)
    if query.first():
        raise ConflictError(f"SKU / barcode {sku!r} is already used by another product.")
    return sku


def _clean_code(session: Session, value, *, exclude_id: int | None = None) -> str:
    code = str(value or "").strip()
    if not code:
        code = next_product_code(session)
    if not CODE_RE.match(code):
        raise ValidationError(
            "Product ID may contain letters, numbers, dots, dashes and underscores (max 40).",
            "product_code",
        )
    query = session.query(Product).filter(func.lower(Product.product_code) == code.lower())
    if exclude_id is not None:
        query = query.filter(Product.id != exclude_id)
    if query.first():
        raise ConflictError(f"Product ID {code!r} already exists.")
    return code


def _clean_prices(selling_price, cost_price) -> tuple[int, int]:
    selling = parse_decimal(selling_price, field="Selling price")
    cost = parse_decimal(cost_price if cost_price not in (None, "") else 0, field="Cost price")
    if selling < 0:
        raise ValidationError("Selling price cannot be negative.", "selling_price")
    if cost < 0:
        raise ValidationError("Cost price cannot be negative.", "cost_price")
    return to_minor(selling, field="Selling price"), to_minor(cost, field="Cost price")


def _clean_quantities(quantity, reorder_level) -> tuple[int, int]:
    qty = parse_decimal(quantity if quantity not in (None, "") else 0, field="Quantity")
    reorder = parse_decimal(
        reorder_level if reorder_level not in (None, "") else 0, field="Reorder level"
    )
    if qty < 0:
        raise ValidationError("Quantity cannot be negative.", "quantity")
    if reorder < 0:
        raise ValidationError("Reorder level cannot be negative.", "reorder_level")
    return to_milli(qty, field="Quantity"), to_milli(reorder, field="Reorder level")


@security.requires(security.P_INVENTORY_EDIT)
def create_product(
    session: Session,
    *,
    name,
    selling_price,
    cost_price=0,
    quantity=0,
    reorder_level=0,
    unit: str = "pcs",
    sku=None,
    category: str | None = None,
    description: str | None = None,
    product_code: str | None = None,
    is_active: bool = True,
    operator_id: int | None = None,
    business_date: date | None = None,
) -> Product:
    clean_name = _clean_name(name)
    selling_minor, cost_minor = _clean_prices(selling_price, cost_price)
    qty_milli, reorder_milli = _clean_quantities(quantity, reorder_level)
    code = _clean_code(session, product_code)
    clean_sku = _clean_sku(session, sku)
    unit = (unit or "pcs").strip() or "pcs"
    if len(unit) > 24:
        raise ValidationError("Unit must be 24 characters or fewer.", "unit")
    category_obj = ensure_category(session, category)

    product = Product(
        product_code=code,
        sku=clean_sku,
        name=clean_name,
        category_id=category_obj.id if category_obj else None,
        description=(description or "").strip() or None,
        cost_price_minor=cost_minor,
        selling_price_minor=selling_minor,
        quantity_milli=0,
        reorder_level_milli=reorder_milli,
        unit=unit,
        is_active=bool(is_active),
    )
    session.add(product)
    session.flush()

    if qty_milli > 0:
        business_day = business_date or today()
        stock.apply_movement(
            session,
            product,
            qty_milli,
            MOVEMENT_OPENING,
            unit_cost_minor=cost_minor,
            reference_type="opening",
            reason="Opening stock",
            operator_id=operator_id,
            business_date=business_day,
        )
        mark_daily_dirty(session, business_day)
    elif business_date:
        mark_daily_dirty(session, business_date)

    audit.record(
        session,
        "product.created",
        "product",
        product.id,
        operator_id=operator_id,
        details={
            "code": product.product_code,
            "name": product.name,
            "selling_price_minor": product.selling_price_minor,
            "cost_price_minor": product.cost_price_minor,
            "quantity": str(from_milli(qty_milli)),
            "unit": product.unit,
        },
    )
    session.flush()
    return product


@security.requires(security.P_INVENTORY_EDIT)
def update_product(
    session: Session,
    product_id: int,
    *,
    name=None,
    selling_price=None,
    cost_price=None,
    reorder_level=None,
    unit=None,
    sku=None,
    category=None,
    description=None,
    is_active=None,
    operator_id: int | None = None,
    business_date: date | None = None,
) -> Product:
    """Update catalogue fields.  Quantity is never editable here."""
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    changes: dict[str, object] = {}

    if name is not None:
        clean_name = _clean_name(name)
        if clean_name != product.name:
            changes["name"] = (product.name, clean_name)
            product.name = clean_name
    if selling_price is not None:
        selling_minor, _ = _clean_prices(selling_price, from_minor(product.cost_price_minor))
        if selling_minor != product.selling_price_minor:
            changes["selling_price_minor"] = (product.selling_price_minor, selling_minor)
            product.selling_price_minor = selling_minor
    if cost_price is not None:
        _, cost_minor = _clean_prices(from_minor(product.selling_price_minor), cost_price)
        if cost_minor != product.cost_price_minor:
            changes["cost_price_minor"] = (product.cost_price_minor, cost_minor)
            product.cost_price_minor = cost_minor
    if reorder_level is not None:
        _, reorder_milli = _clean_quantities(0, reorder_level)
        if reorder_milli != product.reorder_level_milli:
            changes["reorder_level_milli"] = (product.reorder_level_milli, reorder_milli)
            product.reorder_level_milli = reorder_milli
    if unit is not None:
        clean_unit = (unit or "").strip()
        if not clean_unit:
            raise ValidationError("Unit is required.", "unit")
        if len(clean_unit) > 24:
            raise ValidationError("Unit must be 24 characters or fewer.", "unit")
        if clean_unit != product.unit:
            changes["unit"] = (product.unit, clean_unit)
            product.unit = clean_unit
    if sku is not None:
        clean_sku = _clean_sku(session, sku, exclude_id=product.id)
        if clean_sku != product.sku:
            changes["sku"] = (product.sku, clean_sku)
            product.sku = clean_sku
    if category is not None:
        category_obj = ensure_category(session, category)
        new_id = category_obj.id if category_obj else None
        if new_id != product.category_id:
            changes["category_id"] = (product.category_id, new_id)
            product.category_id = new_id
    if description is not None:
        clean_description = str(description).strip() or None
        if clean_description != product.description:
            changes["description"] = (product.description, clean_description)
            product.description = clean_description
    if is_active is not None and bool(is_active) != product.is_active:
        changes["is_active"] = (product.is_active, bool(is_active))
        product.is_active = bool(is_active)

    if changes:
        audit.record(
            session,
            "product.updated",
            "product",
            product.id,
            operator_id=operator_id,
            details={"changes": changes},
        )
        if business_date:
            mark_daily_dirty(session, business_date)
    session.flush()
    return product


@security.requires(security.P_INVENTORY_EDIT)
def archive_product(
    session: Session, product_id: int, *, operator_id: int | None = None, reason: str | None = None
) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    if not product.is_active:
        return product
    product.is_active = False
    audit.record(
        session,
        "product.archived",
        "product",
        product.id,
        operator_id=operator_id,
        reason=reason,
        details={"name": product.name, "quantity": str(product.quantity)},
    )
    session.flush()
    return product


@security.requires(security.P_INVENTORY_EDIT)
def restore_product(session: Session, product_id: int, *, operator_id: int | None = None) -> Product:
    product = session.get(Product, product_id)
    if product is None:
        raise NotFoundError("Product not found.")
    product.is_active = True
    audit.record(
        session,
        "product.restored",
        "product",
        product.id,
        operator_id=operator_id,
        details={"name": product.name},
    )
    session.flush()
    return product


SORT_COLUMNS = {
    "product_code": Product.product_code,
    "name": Product.name,
    "sku": Product.sku,
    "category": Category.name,
    "cost_price": Product.cost_price_minor,
    "selling_price": Product.selling_price_minor,
    "quantity": Product.quantity_milli,
    "reorder": Product.reorder_level_milli,
    "updated": Product.updated_at,
}


def inventory_page(
    session: Session,
    *,
    search: str = "",
    category_id: int | None = None,
    status: str = "all",
    sort_key: str = "name",
    descending: bool = False,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[Product], int]:
    query = session.query(Product).outerjoin(Category, Product.category_id == Category.id)
    if status == "archived":
        query = query.filter(Product.is_active.is_(False))
    else:
        query = query.filter(Product.is_active.is_(True))
        if status == "out":
            query = query.filter(Product.quantity_milli <= 0)
        elif status == "low":
            query = query.filter(
                Product.quantity_milli > 0,
                Product.reorder_level_milli > 0,
                Product.quantity_milli <= Product.reorder_level_milli,
            )
        elif status == "in":
            query = query.filter(
                or_(
                    Product.quantity_milli <= 0,
                    Product.reorder_level_milli <= 0,
                    Product.quantity_milli > Product.reorder_level_milli,
                )
            )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    term = (search or "").strip()
    if term:
        pattern = f"%{term}%"
        query = query.filter(
            or_(
                Product.name.ilike(pattern),
                Product.product_code.ilike(pattern),
                Product.sku.ilike(pattern),
                Product.description.ilike(pattern),
            )
        )
    total = query.count()
    column = SORT_COLUMNS.get(sort_key, Product.name)
    query = query.order_by(column.desc() if descending else column.asc(), Product.id.asc())
    page = max(1, int(page))
    page_size = max(1, min(500, int(page_size)))
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total


def all_active_products(session: Session) -> list[Product]:
    return (
        session.query(Product)
        .filter(Product.is_active.is_(True))
        .order_by(Product.name.asc())
        .all()
    )


def product_choices(session: Session, search: str = "", limit: int = 500) -> list[Product]:
    query = session.query(Product).filter(Product.is_active.is_(True))
    term = (search or "").strip()
    if term:
        pattern = f"%{term}%"
        query = query.filter(
            or_(
                Product.name.ilike(pattern),
                Product.product_code.ilike(pattern),
                Product.sku.ilike(pattern),
            )
        )
    return query.order_by(Product.name.asc()).limit(limit).all()


def product_sales_history(session: Session, product_id: int, limit: int = 100) -> list[SaleItem]:
    return (
        session.query(SaleItem)
        .filter(SaleItem.product_id == product_id)
        .order_by(SaleItem.id.desc())
        .limit(limit)
        .all()
    )


def product_history(session: Session, product_id: int, limit: int = 200) -> list[StockMovement]:
    return stock.movement_history(session, product_id, limit=limit)
