"""Sales, refunds, oversell protection and idempotency tests."""

from __future__ import annotations

from datetime import date

import pytest

from stockkeep.errors import ConflictError, ValidationError
from stockkeep.models import Product, Sale, StockMovement
from stockkeep.services import analytics, catalog, sales, stock

DAY = date(2026, 3, 1)


def _product(session, name="Rice", price="10.00", cost="6.00", qty="10"):
    product = catalog.create_product(
        session,
        name=name,
        selling_price=price,
        cost_price=cost,
        quantity=qty,
        business_date=DAY,
    )
    session.flush()
    return product


def test_sale_deducts_stock_and_records_totals(db):
    with db.session() as session:
        rice = _product(session, qty="10")
        sale = sales.create_sale(
            session,
            items=[{"product_id": rice.id, "quantity": "2.5", "discount": "1.00"}],
            payment_method="Cash",
            business_date=DAY,
        )
        assert sale.transaction_number == f"TXN-{DAY:%Y%m%d}-{sale.id:06d}"
        assert sale.subtotal_minor == 2500
        assert sale.discount_total_minor == 100
        assert sale.net_total_minor == 2400
        assert session.get(Product, rice.id).quantity_milli == 7500

        movement = (
            session.query(StockMovement)
            .filter(StockMovement.reference_id == sale.id, StockMovement.movement_type == "sale")
            .one()
        )
        assert movement.quantity_change_milli == -2500
        assert movement.quantity_after_milli == 7500

        summary = analytics.sales_summary(session, DAY, DAY)
        assert summary["sales_count"] == 1
        assert summary["net_minor"] == 2400
        assert analytics.units_sold(session, DAY, DAY) == 2500


def test_oversell_is_rejected_and_leaves_no_trace(db):
    with db.session() as session:
        rice = _product(session, qty="2")
        with pytest.raises(ConflictError):
            sales.create_sale(
                session,
                items=[{"product_id": rice.id, "quantity": "3"}],
                payment_method="Cash",
                business_date=DAY,
            )
    with db.session() as session:
        assert session.query(Sale).count() == 0
        assert session.get(Product, rice.id).quantity_milli == 2000


def test_multi_item_sale_is_atomic(db):
    with db.session() as session:
        rice = _product(session, name="Rice", qty="10")
        beans = _product(session, name="Beans", qty="1")
        rice_id, beans_id = rice.id, beans.id
        with pytest.raises(ConflictError):
            sales.create_sale(
                session,
                items=[
                    {"product_id": rice_id, "quantity": "2"},
                    {"product_id": beans_id, "quantity": "5"},
                ],
                payment_method="Cash",
                business_date=DAY,
            )
    with db.session() as session:
        assert session.get(Product, rice_id).quantity_milli == 10000
        assert session.get(Product, beans_id).quantity_milli == 1000
        assert session.query(Sale).count() == 0


def test_idempotency_returns_existing_sale(db):
    with db.session() as session:
        rice = _product(session, qty="10")
        first = sales.create_sale(
            session,
            items=[{"product_id": rice.id, "quantity": "1"}],
            payment_method="Card",
            business_date=DAY,
            idempotency_key="client-123",
        )
        second = sales.create_sale(
            session,
            items=[{"product_id": rice.id, "quantity": "1"}],
            payment_method="Card",
            business_date=DAY,
            idempotency_key="client-123",
        )
        assert first.id == second.id
        assert session.get(Product, rice.id).quantity_milli == 9000


def test_discount_cannot_exceed_line_value(db):
    with db.session() as session:
        rice = _product(session, price="5.00", qty="10")
        with pytest.raises(ValidationError):
            sales.create_sale(
                session,
                items=[{"product_id": rice.id, "quantity": "1", "discount": "6.00"}],
                payment_method="Cash",
                business_date=DAY,
            )


def test_partial_then_full_refund_restores_stock(db):
    with db.session() as session:
        rice = _product(session, qty="10")
        sale = sales.create_sale(
            session,
            items=[{"product_id": rice.id, "quantity": "4"}],
            payment_method="Cash",
            business_date=DAY,
        )
        item = sale.items[0]
        refund = sales.refund_sale(
            session,
            sale_id=sale.id,
            items=[{"sale_item_id": item.id, "quantity": "1.5"}],
            reason="Customer returned part",
            business_date=DAY,
        )
        assert refund.amount_minor == 1500
        assert sale.status == "partially_refunded"
        assert session.get(Product, rice.id).quantity_milli == 7500

        sales.refund_sale(
            session, sale_id=sale.id, reason="Return the rest", business_date=DAY
        )
        assert sale.status == "refunded"
        assert sale.refund_total_minor == 4000
        assert session.get(Product, rice.id).quantity_milli == 10000
        with pytest.raises(ConflictError):
            sales.refund_sale(session, sale_id=sale.id, reason="again", business_date=DAY)


def test_reversal_excludes_sale_from_revenue(db):
    with db.session() as session:
        rice = _product(session, qty="10")
        sale = sales.create_sale(
            session,
            items=[{"product_id": rice.id, "quantity": "2"}],
            payment_method="Cash",
            business_date=DAY,
        )
        sales.reverse_sale(session, sale_id=sale.id, reason="Wrong entry", business_date=DAY)
        assert sale.status == "reversed"
        summary = analytics.sales_summary(session, DAY, DAY)
        assert summary["sales_count"] == 0
        assert summary["net_minor"] == 0
        assert session.get(Product, rice.id).quantity_milli == 10000


def test_refund_requires_reason_and_valid_quantity(db):
    with db.session() as session:
        rice = _product(session, qty="5")
        sale = sales.create_sale(
            session,
            items=[{"product_id": rice.id, "quantity": "1"}],
            payment_method="Cash",
            business_date=DAY,
        )
        with pytest.raises(ValidationError):
            sales.refund_sale(session, sale_id=sale.id, reason="  ")
        with pytest.raises(ConflictError):
            sales.refund_sale(
                session,
                sale_id=sale.id,
                items=[{"sale_item_id": sale.items[0].id, "quantity": "2"}],
                reason="Too many",
            )


def test_stock_adjustments_and_receipts(db):
    with db.session() as session:
        rice = _product(session, qty="0")
        stock.receive_stock(
            session,
            product_id=rice.id,
            quantity="6",
            unit_cost="5.50",
            supplier_name="Acme",
            business_date=DAY,
        )
        assert session.get(Product, rice.id).quantity_milli == 6000
        assert session.get(Product, rice.id).cost_price_minor == 550

        stock.adjust_stock(
            session,
            product_id=rice.id,
            adjustment_type="damage",
            quantity="1",
            reason="Broken bag",
            business_date=DAY,
        )
        assert session.get(Product, rice.id).quantity_milli == 5000

        stock.adjust_stock(
            session,
            product_id=rice.id,
            adjustment_type="count",
            new_quantity="3",
            reason="Stock count",
            business_date=DAY,
        )
        assert session.get(Product, rice.id).quantity_milli == 3000
