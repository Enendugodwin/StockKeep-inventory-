"""Render README screenshots from a seeded, throwaway database."""

from __future__ import annotations

import os
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# The offscreen platform plugin does not use the Windows font database, so
# point it at the system fonts to keep screenshots legible.
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"


def seed(database):
    from stockkeep.services import auth_service, catalog, sales, stock

    today_ = date.today()
    with database.session() as session:
        items = [
            ("Basmati Rice 5kg", "48.50", "39.00", "24", "bag", "Grains"),
            ("Sunflower Oil 1L", "12.00", "9.25", "40", "bottle", "Cooking"),
            ("Tomato Paste 400g", "3.75", "2.60", "8", "tin", "Canned"),
            ("Wheat Flour 2kg", "9.80", "7.40", "3", "bag", "Baking"),
            ("Sugar 1kg", "4.20", "3.10", "60", "pack", "Baking"),
            ("Powdered Milk 900g", "18.90", "15.00", "6", "tin", "Dairy"),
        ]
        products = []
        for name, price, cost, qty, unit, category in items:
            product = catalog.create_product(
                session,
                name=name,
                selling_price=price,
                cost_price=cost,
                quantity=qty,
                reorder_level="10",
                unit=unit,
                category=category,
                business_date=today_ - timedelta(days=6),
            )
            products.append(product)
        stock.receive_stock(
            session,
            product_id=products[0].id,
            quantity="12",
            unit_cost="39.00",
            supplier_name="Lagos Wholesale",
            business_date=today_ - timedelta(days=3),
        )
        stock.adjust_stock(
            session,
            product_id=products[2].id,
            adjustment_type="damage",
            quantity="2",
            reason="Damaged in transit",
            business_date=today_ - timedelta(days=2),
        )
        sales.create_sale(
            session,
            items=[
                {"product_id": products[0].id, "quantity": "2", "discount": "5.00"},
                {"product_id": products[4].id, "quantity": "5"},
            ],
            payment_method="Cash",
            business_date=today_ - timedelta(days=2),
        )
        sales.create_sale(
            session,
            items=[{"product_id": products[1].id, "quantity": "4"}],
            payment_method="Bank Transfer",
            business_date=today_ - timedelta(days=1),
        )
        sales.create_sale(
            session,
            items=[
                {"product_id": products[5].id, "quantity": "2"},
                {"product_id": products[3].id, "quantity": "1"},
            ],
            payment_method="Card",
            business_date=today_,
        )
        auth_service.create_user(
            session,
            username="ngozi",
            name="Ngozi Owner",
            role="owner",
            password="owner-pass-123",
        )
        auth_service.create_user(
            session,
            username="sam",
            name="Sam Cashier",
            role="staff",
            password="cashier-pass-123",
        )


def main() -> None:
    home = tempfile.mkdtemp(prefix="sk-shot-")
    os.environ["STOCKKEEP_HOME"] = home

    from PySide6.QtWidgets import QApplication

    from stockkeep.db import Database
    from stockkeep.paths import ensure_dirs
    from stockkeep.security import Actor, ROLE_ADMIN
    from stockkeep.ui.auth_dialogs import LoginDialog
    from stockkeep.ui.main_window import MainWindow
    from stockkeep.ui.state import AppState
    from stockkeep.ui.theme import apply_theme

    paths = ensure_dirs(home)
    database = Database(paths.db_path)
    seed(database)

    app = QApplication.instance() or QApplication([])
    apply_theme(app, "light")
    state = AppState(database, paths)
    state.set_current_user(
        Actor(id=1, username="admin", name="Administrator", role=ROLE_ADMIN)
    )
    window = MainWindow(state)
    window.resize(1440, 900)
    window.show()
    app.processEvents()

    deadline = time.time() + 10
    while "checking" in window.report_label.text() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
    app.processEvents()

    DOCS.mkdir(parents=True, exist_ok=True)
    for key, name in (
        ("dashboard", "dashboard"),
        ("inventory", "inventory"),
        ("sale", "record-sale"),
        ("reports", "reports"),
        ("users", "users"),
        ("roles", "roles"),
        ("settings", "settings"),
    ):
        window.go_to(key)
        app.processEvents()
        app.processEvents()
        target = DOCS / f"{name}.png"
        window.grab().save(str(target), "PNG")
        print(f"wrote {target}")

    window.close()

    login = LoginDialog(state)
    login.username.setText("admin")
    login.password.setText("portable-pass")
    login.adjustSize()
    login.show()
    app.processEvents()
    target = DOCS / "login.png"
    login.grab().save(str(target), "PNG")
    print(f"wrote {target}")
    login.close()

    state.clear_current_user()
    database.dispose()


if __name__ == "__main__":
    main()
