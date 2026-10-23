"""SQLAlchemy models.

Money is stored as integer minor units (kobo) and quantities as integer
thousandths.  This avoids binary floating point entirely.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .money import from_milli, from_minor
from .timeutil import utc_now


class Base(DeclarativeBase):
    pass


# Sale statuses ---------------------------------------------------------------
SALE_COMPLETED = "completed"
SALE_PARTIALLY_REFUNDED = "partially_refunded"
SALE_REFUNDED = "refunded"
SALE_REVERSED = "reversed"
SALE_STATUSES = (SALE_COMPLETED, SALE_PARTIALLY_REFUNDED, SALE_REFUNDED, SALE_REVERSED)
SALE_PARTIAL_REFUND = SALE_PARTIALLY_REFUNDED
ACTIVE_SALE_STATUSES = (SALE_COMPLETED, SALE_PARTIALLY_REFUNDED)

MOVEMENT_TYPES = (
    "opening",
    "receipt",
    "sale",
    "return",
    "damage",
    "loss",
    "expiry",
    "adjustment",
    "import",
    "reversal",
)

PAYMENT_METHODS = ("Cash", "Bank Transfer", "Card", "Other")

MOVEMENT_OPENING = "opening"
MOVEMENT_RECEIPT = "receipt"
MOVEMENT_SALE = "sale"
MOVEMENT_RETURN = "return"
MOVEMENT_DAMAGE = "damage"
MOVEMENT_LOSS = "loss"
MOVEMENT_EXPIRY = "expiry"
MOVEMENT_ADJUSTMENT = "adjustment"
MOVEMENT_IMPORT = "import"
MOVEMENT_REVERSAL = "reversal"

REPORT_PENDING = "pending"
REPORT_RUNNING = "running"
REPORT_COMPLETED = "completed"
REPORT_FAILED = "failed"
REPORT_STALE = "stale"

REPORT_STATUSES = (
    REPORT_PENDING,
    REPORT_RUNNING,
    REPORT_COMPLETED,
    REPORT_FAILED,
    REPORT_STALE,
)


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    products: Mapped[list["Product"]] = relationship(back_populates="category")


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    contact: Mapped[str | None] = mapped_column(String(240))
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    username: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), default="owner", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Role(Base):
    __tablename__ = "roles"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    permissions_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("cost_price_minor >= 0", name="ck_products_cost_nonneg"),
        CheckConstraint("selling_price_minor >= 0", name="ck_products_price_nonneg"),
        CheckConstraint("quantity_milli >= 0", name="ck_products_quantity_nonneg"),
        CheckConstraint("reorder_level_milli >= 0", name="ck_products_reorder_nonneg"),
        Index("ix_products_name", "name"),
        Index("ix_products_active", "is_active", "name"),
        Index("ix_products_category", "category_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_code: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    sku: Mapped[str | None] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    cost_price_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    selling_price_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_milli: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reorder_level_milli: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit: Mapped[str] = mapped_column(String(24), default="pcs", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    category: Mapped[Category | None] = relationship(back_populates="products", lazy="joined")

    # ---- Convenience Decimal views -----------------------------------------
    @property
    def cost_price(self):
        return from_minor(self.cost_price_minor)

    @property
    def selling_price(self):
        return from_minor(self.selling_price_minor)

    @property
    def quantity(self):
        return from_milli(self.quantity_milli)

    @property
    def reorder_level(self):
        return from_milli(self.reorder_level_milli)

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else ""

    def status(self) -> str:
        if self.quantity_milli <= 0:
            return "Out of stock"
        if self.reorder_level_milli and self.quantity_milli <= self.reorder_level_milli:
            return "Low stock"
        return "In stock"


class Sale(Base):
    __tablename__ = "sales"
    __table_args__ = (
        CheckConstraint("subtotal_minor >= 0", name="ck_sales_subtotal_nonneg"),
        CheckConstraint("discount_total_minor >= 0", name="ck_sales_discount_nonneg"),
        CheckConstraint("refund_total_minor >= 0", name="ck_sales_refund_nonneg"),
        Index("ix_sales_business_date", "business_date"),
        Index("ix_sales_date_status", "business_date", "status"),
        Index("ix_sales_payment", "payment_method"),
        Index("ix_sales_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False, default="Cash")
    subtotal_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discount_total_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    refund_total_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    net_total_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default=SALE_COMPLETED)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), unique=True)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )

    operator: Mapped[User | None] = relationship(lazy="joined")
    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="sale", cascade="all, delete-orphan", lazy="selectin"
    )
    refunds: Mapped[list["Refund"]] = relationship(back_populates="sale", lazy="selectin")

    @property
    def net_total(self):
        return from_minor(self.net_total_minor)

    @property
    def refunded_total(self):
        return from_minor(self.refund_total_minor)


class SaleItem(Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        CheckConstraint("quantity_milli > 0", name="ck_saleitem_qty_positive"),
        CheckConstraint("unit_price_minor >= 0", name="ck_saleitem_price_nonneg"),
        CheckConstraint("discount_minor >= 0", name="ck_saleitem_discount_nonneg"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_name_snapshot: Mapped[str] = mapped_column(String(240), nullable=False)
    quantity_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    discount_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    line_total_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    sale: Mapped[Sale] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship()

    @property
    def quantity(self):
        return from_milli(self.quantity_milli)

    @property
    def line_total(self):
        return from_minor(self.line_total_minor)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_movements_product_date", "product_id", "business_date"),
        Index("ix_movements_type_date", "movement_type", "business_date"),
        Index("ix_movements_date", "business_date"),
        Index("ix_movements_reference", "reference_type", "reference_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False)
    quantity_change_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_before_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_after_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    reference_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    product: Mapped[Product] = relationship(lazy="joined")
    operator: Mapped[User | None] = relationship(lazy="joined")

    @property
    def quantity_change(self):
        return from_milli(self.quantity_change_milli)


class StockReceipt(Base):
    __tablename__ = "stock_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="SET NULL"))
    quantity_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    note: Mapped[str | None] = mapped_column(Text)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)

    product: Mapped[Product] = relationship(lazy="joined")
    supplier: Mapped[Supplier | None] = relationship(lazy="joined")


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (Index("ix_refunds_date", "business_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    refund_number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(20), default="refund", nullable=False)
    restocked: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    sale: Mapped[Sale] = relationship(back_populates="refunds")
    operator: Mapped[User | None] = relationship(lazy="joined")
    items: Mapped[list["RefundItem"]] = relationship(
        back_populates="refund", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def amount(self):
        return from_minor(self.amount_minor)


class RefundItem(Base):
    __tablename__ = "refund_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    refund_id: Mapped[int] = mapped_column(
        ForeignKey("refunds.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sale_item_id: Mapped[int] = mapped_column(
        ForeignKey("sale_items.id", ondelete="RESTRICT"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_milli: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_minor: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    refund: Mapped[Refund] = relationship(back_populates="items")
    sale_item: Mapped[SaleItem | None] = relationship()


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    filename: Mapped[str] = mapped_column(String(260), nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False)
    rows_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="completed", nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)


class ReportJob(Base):
    __tablename__ = "report_jobs"
    __table_args__ = (
        UniqueConstraint("report_type", "period_start", "period_end", "format", name="uq_report_job"),
        Index("ix_report_jobs_period", "period_start", "period_end"),
        Index("ix_report_jobs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[str] = mapped_column(String(40), nullable=False, default="daily")
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    format: Mapped[str] = mapped_column(String(20), nullable=False, default="bundle")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    file_path: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_created", "created_at"),
        Index("ix_audit_action", "action"),
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(60), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(80))
    reason: Mapped[str | None] = mapped_column(Text)
    details_json: Mapped[str | None] = mapped_column(Text)

    operator: Mapped[User | None] = relationship(lazy="joined")


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False
    )


class SchemaVersion(Base):
    __tablename__ = "schema_versions"

    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
