"""Monthly business summary with reconciliation to the database."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QSpinBox,
    QTabWidget,
    QWidget,
)

from ...services import analytics, reports
from ..common import export_path, show_error
from ..models import TableColumn
from ..widgets import DataTable, KpiCard, PageHeader, SectionCard, open_path
from ..workers import run_task
from .base import BasePage


MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


class MonthlyPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader(
            "Monthly Summary",
            "Month-to-date financials, stock reconciliation and product performance.",
        )
        self.header.add_action("Export Excel", "primary", "download", lambda: self._export("xlsx"))
        self.header.add_action("Export CSV", "secondary", "download", lambda: self._export("csv"))
        self.layout.addWidget(self.header)

        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.month_combo = QComboBox()
        for index, name in enumerate(MONTHS, start=1):
            self.month_combo.addItem(name, index)
        today = date.today()
        self.month_combo.setCurrentIndex(today.month - 1)
        row.addWidget(self.month_combo)
        self.year_spin = QSpinBox()
        self.year_spin.setRange(2000, 2100)
        self.year_spin.setValue(today.year)
        self.year_spin.setFixedWidth(96)
        row.addWidget(self.year_spin)
        row.addStretch(1)
        self.month_combo.currentIndexChanged.connect(self._reload)
        self.year_spin.valueChanged.connect(self._reload)
        self.layout.addWidget(controls)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.kpi_net = KpiCard("Net sales", "receipt", "#0E7C86")
        self.kpi_profit = KpiCard("Gross profit", "reports", "#16803C")
        self.kpi_sales = KpiCard("Completed sales", "transactions", "#2F80ED")
        self.kpi_closing = KpiCard("Closing stock", "inventory", "#7A5AF8")
        for card in (self.kpi_net, self.kpi_profit, self.kpi_sales, self.kpi_closing):
            kpi_row.addWidget(card)
        self.layout.addLayout(kpi_row)

        card = SectionCard("Monthly detail", "Figures are computed directly from sales and stock movements.")
        self.tabs = QTabWidget()
        self.summary_table = DataTable()
        self.daily_table = DataTable()
        self.product_table = DataTable()
        self.payment_table = DataTable()
        for table in (self.summary_table, self.daily_table, self.product_table, self.payment_table):
            table.setMinimumHeight(250)
        self.tabs.addTab(self.summary_table, "Executive summary")
        self.tabs.addTab(self.daily_table, "Daily sales")
        self.tabs.addTab(self.product_table, "Product performance")
        self.tabs.addTab(self.payment_table, "Payments")
        card.content.addWidget(self.tabs, 1)
        self.layout.addWidget(card, 1)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._reload()

    def _reload(self, *_args) -> None:
        year = self.year_spin.value()
        month = int(self.month_combo.currentData() or 1)
        try:
            with self.state.database.session() as session:
                summary = analytics.monthly_summary(session, year, month)
        except Exception as exc:
            show_error(self, exc, "Could not build the monthly summary")
            return

        self.header.subtitle_label.setText(
            f"{MONTHS[month - 1]} {year}  ·  {self.state.date(summary['start'])} to "
            f"{self.state.date(summary['end'])}"
        )
        self.kpi_net.set_value(
            self.state.money(summary["net_minor"]),
            f"Gross {self.state.money(summary['gross_minor'])}  ·  "
            f"Refunds {self.state.money(summary['refund_minor'])}",
        )
        self.kpi_profit.set_value(
            self.state.money(summary["gross_profit_minor"]),
            f"COGS {self.state.money(summary['cogs_minor'])}",
        )
        self.kpi_sales.set_value(
            f"{summary['sales_count']:,}",
            f"Units sold {self.state.quantity(summary['sold_milli'])}",
        )
        self.kpi_closing.set_value(
            self.state.quantity(summary["closing_milli"]),
            f"Opened {self.state.quantity(summary['opening_milli'])}",
        )

        summary_rows = [
            {"metric": "Opening stock (units)", "value": self.state.quantity(summary["opening_milli"])},
            {"metric": "Stock received", "value": self.state.quantity(summary["received_milli"])},
            {"metric": "Units sold", "value": self.state.quantity(summary["sold_milli"])},
            {"metric": "Customer returns", "value": self.state.quantity(summary["returned_milli"])},
            {"metric": "Damaged", "value": self.state.quantity(summary["damaged_milli"])},
            {"metric": "Lost", "value": self.state.quantity(summary["lost_milli"])},
            {"metric": "Expired", "value": self.state.quantity(summary["expired_milli"])},
            {"metric": "Other adjustments", "value": self.state.quantity(summary["adjusted_milli"])},
            {"metric": "Closing stock (units)", "value": self.state.quantity(summary["closing_milli"])},
            {"metric": "Gross sales", "value": self.state.money(summary["gross_minor"])},
            {"metric": "Discounts", "value": self.state.money(summary["discount_minor"])},
            {"metric": "Refunds", "value": self.state.money(summary["refund_minor"])},
            {"metric": "Net sales", "value": self.state.money(summary["net_minor"])},
            {"metric": "Estimated COGS", "value": self.state.money(summary["cogs_minor"])},
            {"metric": "Estimated gross profit", "value": self.state.money(summary["gross_profit_minor"])},
            {
                "metric": "Current inventory value (cost)",
                "value": self.state.money(summary["valuation"]["cost_minor"]),
            },
            {
                "metric": "Current inventory value (selling)",
                "value": self.state.money(summary["valuation"]["selling_minor"]),
            },
            {
                "metric": "Products missing cost price",
                "value": f"{summary['valuation']['missing_cost_products']:,}",
            },
        ]
        self.summary_table.set_data(
            summary_rows,
            [
                TableColumn("metric", "Metric", 320, bold=True),
                TableColumn("value", "Value", 240, align=int(Qt.AlignRight | Qt.AlignVCenter)),
            ],
        )

        daily = summary["daily"]
        self.daily_table.set_data(
            daily,
            [
                TableColumn(
                    "business_date",
                    "Date",
                    120,
                    formatter=lambda row: self.state.date(row.get("business_date")),
                ),
                TableColumn("sales_count", "Sales", 70, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn(
                    "units_milli",
                    "Units",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("units_milli")),
                ),
                TableColumn(
                    "gross_minor",
                    "Gross",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("gross_minor")),
                ),
                TableColumn(
                    "discount_minor",
                    "Discounts",
                    100,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("discount_minor")),
                ),
                TableColumn(
                    "refund_minor",
                    "Refunds",
                    100,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("refund_minor")),
                ),
                TableColumn(
                    "net_minor",
                    "Net",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("net_minor")),
                    bold=True,
                ),
                TableColumn(
                    "cogs_minor",
                    "Est. COGS",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("cogs_minor")),
                ),
            ],
        )

        products = summary["products"]
        self.product_table.set_data(
            products,
            [
                TableColumn("product_code", "Product ID", 104),
                TableColumn("name", "Product", 210, bold=True),
                TableColumn("unit", "Unit", 62),
                TableColumn(
                    "opening_milli",
                    "Opening",
                    88,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("opening_milli")),
                ),
                TableColumn(
                    "received_milli",
                    "Received",
                    88,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("received_milli")),
                ),
                TableColumn(
                    "sold_milli",
                    "Sold",
                    80,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("sold_milli")),
                ),
                TableColumn(
                    "returned_milli",
                    "Returns",
                    84,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("returned_milli")),
                ),
                TableColumn(
                    "closing_milli",
                    "Closing",
                    88,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.quantity(row.get("closing_milli")),
                ),
                TableColumn(
                    "revenue_minor",
                    "Revenue",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("revenue_minor")),
                ),
                TableColumn(
                    "gross_profit_minor",
                    "Gross profit",
                    112,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("gross_profit_minor")),
                    bold=True,
                ),
            ],
        )

        self.payment_table.set_data(
            summary["payment_totals"],
            [
                TableColumn("payment_method", "Payment method", 180, bold=True),
                TableColumn(
                    "gross_minor",
                    "Gross",
                    120,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("gross_minor")),
                ),
                TableColumn(
                    "discount_minor",
                    "Discounts",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("discount_minor")),
                ),
                TableColumn(
                    "refund_minor",
                    "Refunds",
                    110,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("refund_minor")),
                ),
                TableColumn(
                    "net_minor",
                    "Net",
                    120,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                    formatter=lambda row: self.state.money(row.get("net_minor")),
                    bold=True,
                ),
            ],
        )

    # ------------------------------------------------------------------
    def _export(self, fmt: str) -> None:
        year = self.year_spin.value()
        month = int(self.month_combo.currentData() or 1)
        default_ext = "xlsx" if fmt == "xlsx" else "csv"
        target = export_path(
            self,
            self.state,
            f"monthly_{year}_{month:02d}",
            formats="Excel workbook (*.xlsx)" if fmt == "xlsx" else "Package of CSV files (*.csv)",
        )
        if target is None:
            return
        if target.suffix.lower() != f".{default_ext}":
            target = target.with_suffix(f".{default_ext}")

        def job():
            with self.state.database.session() as session:
                return reports.export_monthly(
                    session,
                    year,
                    month,
                    target,
                    fmt=fmt,
                    tz=self.state.settings.timezone,
                    currency_symbol=self.state.settings.currency_symbol,
                    business_name=self.state.settings.business_name,
                )

        def done(path):
            self.main.show_status(f"Monthly report saved to {path}.")
            open_path(path)

        run_task(
            self,
            job,
            on_success=done,
            message="Building the monthly report…",
            title="Monthly report",
        )

    def export_action(self) -> None:
        self._export("xlsx")
