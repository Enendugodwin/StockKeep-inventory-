"""Dashboard: live business overview."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel

from ... import security
from ...services import analytics
from ..models import TableColumn
from ..theme import status_color
from ..widgets import BarChart, DataTable, KpiCard, PageHeader, SectionCard, make_button
from .base import BasePage


class DashboardPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader(
            "Dashboard",
            "Today at a glance — sales, stock health and recent activity.",
        )
        self.header.add_action("Refresh", "secondary", "refresh", self.refresh)
        if self.state.can(security.P_SALES_CREATE):
            self.header.add_action("Record sale", "primary", "sale", lambda: self.main.go_to("sale"))
        self.layout.addWidget(self.header)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.kpi_net = KpiCard("Today's net sales", "receipt", "#0E7C86")
        self.kpi_sales = KpiCard("Transactions today", "transactions", "#2F80ED")
        self.kpi_stock_value = KpiCard("Inventory value (cost)", "inventory", "#7A5AF8")
        self.kpi_alerts = KpiCard("Stock alerts", "alert", "#B45309")
        for card in (self.kpi_net, self.kpi_sales, self.kpi_stock_value, self.kpi_alerts):
            kpi_row.addWidget(card)
        self.layout.addLayout(kpi_row)

        middle = QHBoxLayout()
        middle.setSpacing(12)
        trend_card = SectionCard("Sales trend", "Net sales per business day (last 14 days)")
        self.chart = BarChart()
        self.chart.setMinimumHeight(170)
        trend_card.content.addWidget(self.chart)
        middle.addWidget(trend_card, 2)

        alerts_card = SectionCard("Needs attention", "Low and out-of-stock items")
        self.alerts_table = DataTable()
        self.alerts_table.setMinimumHeight(170)
        alerts_card.content.addWidget(self.alerts_table, 1)
        middle.addWidget(alerts_card, 2)
        self.layout.addLayout(middle, 2)

        bottom = QHBoxLayout()
        bottom.setSpacing(12)
        recent_card = SectionCard("Recent transactions", "Latest sales activity")
        self.recent_table = DataTable()
        self.recent_table.setMinimumHeight(170)
        recent_card.content.addWidget(self.recent_table, 1)
        bottom.addWidget(recent_card, 3)

        actions_card = SectionCard("Quick actions", "Common tasks")
        grid = QGridLayout()
        grid.setSpacing(8)
        actions = []
        if self.state.can(security.P_INVENTORY_EDIT):
            actions.append(("Add stock item", "plus", self._add_product))
        if self.state.can(security.P_STOCK_RECEIVE):
            actions.append(("Receive stock", "receiving", lambda: self.main.go_to("receiving")))
        if self.state.can(security.P_INVENTORY_IMPORT):
            actions.append(("Import stock file", "import", lambda: self.main.go_to("import")))
        if self.state.can(security.P_STOCK_ADJUST):
            actions.append(("Stock adjustment", "adjustments", lambda: self.main.go_to("adjustments")))
        if self.state.can(security.P_SALES_VIEW):
            actions.append(("View transactions", "transactions", lambda: self.main.go_to("transactions")))
        if self.state.can(security.P_REPORTS_VIEW):
            actions.append(("Reports & exports", "reports", lambda: self.main.go_to("reports")))
        for index, (text, icon, handler) in enumerate(actions):
            grid.addWidget(make_button(text, "quick", icon, handler), index // 2, index % 2)
        actions_card.content.addLayout(grid)
        if not actions:
            empty = QLabel("No quick actions are enabled for your role.")
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            actions_card.content.addWidget(empty)
        actions_card.content.addStretch(1)
        hint = QLabel(
            "Shortcuts: Ctrl+N new item, Ctrl+F search, Ctrl+S save, Ctrl+E export, F5 refresh."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        actions_card.content.addWidget(hint)
        bottom.addWidget(actions_card, 2)
        self.layout.addLayout(bottom, 3)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            with self.state.database.session() as session:
                stats = analytics.dashboard_stats(session, self.state.settings.timezone)
                units_today = analytics.units_sold(
                    session, stats["business_date"], stats["business_date"]
                )
                recent = [
                    {
                        "id": sale.id,
                        "number": sale.transaction_number,
                        "created_at": sale.created_at,
                        "items": len(sale.items),
                        "net": sale.net_total_minor,
                        "payment": sale.payment_method,
                        "status": sale.status,
                    }
                    for sale in stats["recent_sales"]
                ]
                alerts = [
                    {
                        "name": product.name,
                        "code": product.product_code,
                        "quantity": product.quantity_milli,
                        "reorder": product.reorder_level_milli,
                        "status": product.status(),
                    }
                    for product in stats["low_stock"] + stats["out_of_stock"]
                ]
        except Exception:
            self.main.show_status("Could not load dashboard data.")
            raise

        self.header.subtitle_label.setText(
            f"Business date {self.state.date(stats['business_date'])}  ·  "
            f"{stats['active_products']:,} active stock item(s)"
        )
        self.kpi_net.set_value(
            self.state.money(stats["today_net_minor"]),
            f"Gross {self.state.money(stats['today_gross_minor'])}"
            + (
                f"  ·  Refunds {self.state.money(stats['today_refund_minor'])}"
                if stats["today_refund_minor"]
                else ""
            ),
        )
        self.kpi_sales.set_value(
            f"{stats['today_sales_count']:,}",
            f"Units sold {self.state.quantity(units_today)}",
        )
        self.kpi_stock_value.set_value(
            self.state.money(stats["inventory_cost_minor"]),
            f"Retail value {self.state.money(stats['inventory_selling_minor'])}",
        )
        alert_hint = f"{stats['low_stock_count']} low  ·  {stats['out_of_stock_count']} out"
        self.kpi_alerts.set_value(f"{stats['low_stock_count'] + stats['out_of_stock_count']:,}", alert_hint)

        self.chart.set_values(
            [(row["date"].strftime("%d"), row["net_minor"]) for row in stats["trend"]]
        )

        self.alerts_table.set_data(
            alerts,
            [
                TableColumn("name", "Stock item", 190),
                TableColumn("code", "Product ID", 100),
                TableColumn(
                    "quantity",
                    "Qty",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("quantity")),
                ),
                TableColumn(
                    "reorder",
                    "Reorder",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("reorder")),
                ),
                TableColumn(
                    "status",
                    "Status",
                    100,
                    color=lambda row: status_color(row.get("status"), self.state.theme),
                    formatter=lambda row: row.get("status", ""),
                ),
            ],
        )

        self.recent_table.set_data(
            recent,
            [
                TableColumn("number", "Transaction", 178, bold=True),
                TableColumn(
                    "created_at",
                    "Time",
                    112,
                    formatter=lambda row: self.state.datetime_short(row.get("created_at")),
                ),
                TableColumn(
                    "items",
                    "Items",
                    46,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                ),
                TableColumn(
                    "net",
                    "Net",
                    88,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("net")),
                    bold=True,
                ),
                TableColumn("payment", "Payment", 104),
                TableColumn(
                    "status",
                    "Status",
                    90,
                    formatter=lambda row: str(row.get("status", "")).replace("_", " ").title(),
                    color=lambda row: status_color(row.get("status"), self.state.theme),
                ),
            ],
        )

    def _add_product(self) -> None:
        from ..dialogs import ProductEditorDialog

        dialog = ProductEditorDialog(self.state, parent=self)
        if dialog.exec() and dialog.saved_id:
            self.state.notify_data_changed()
            self.main.show_status("Stock item created.")
            self.main.request_report_refresh()
