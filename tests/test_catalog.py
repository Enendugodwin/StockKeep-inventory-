"""Unit catalogue tests, including yard-based stock."""

from __future__ import annotations

from stockkeep.services import catalog


def test_yard_is_an_available_unit():
    assert "yard" in catalog.UNITS
    assert "metre" in catalog.UNITS


def test_fabric_can_be_stocked_in_fractional_yards(db):
    with db.session() as session:
        product = catalog.create_product(
            session,
            name="Ankara fabric",
            selling_price="1500",
            cost_price="900",
            quantity="2.5",
            unit="yard",
        )
        assert product.unit == "yard"
        assert product.quantity_milli == 2500
