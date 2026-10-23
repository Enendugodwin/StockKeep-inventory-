"""Reports & exports page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

from ... import security
from ...services import reports, scheduler
from ..common import DateRangeBar, export_path, show_error
from ..models import TableColumn
from ..theme import status_color
from ..widgets import (
    DataTable,
    KpiCard,
    PageHeader,
    SectionCard,
    make_button,
    open_path,
)
from ..workers import run_task
from .base import BasePage


class ReportsPage(BasePage):
    def build(self) -> None:
        self.header = PageHeader(
            "Reports & Exports",
            "Automatic daily CSV/Excel bundles plus ad-hoc exports for any date range.",
        )
        self.header.add_action("Refresh", "secondary", "refresh", self.refresh)
        self.generate_button = self.header.add_action(
            "Generate missing", "primary", "reports", self._generate_missing
        )
        self.generate_button.setVisible(self.state.can(security.P_REPORTS_MANAGE))
        self.header.add_action("Open reports folder", "secondary", "folder", self._open_root)
        self.layout.addWidget(self.header)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(12)
        self.kpi_missing = KpiCard("Reports missing", "alert", "#B45309")
        self.kpi_last = KpiCard("Last successful report", "check", "#16803C")
        self.kpi_closed = KpiCard("Last closed business date", "clock", "#0E7C86")
        for card in (self.kpi_missing, self.kpi_last, self.kpi_closed):
            kpi_row.addWidget(card)
        self.layout.addLayout(kpi_row)

        jobs_card = SectionCard(
            "Daily report jobs",
            "A four-file bundle (transactions CSV/XLSX, movements CSV, summary XLSX) per business date.",
        )
        self.regenerate_button = make_button(
            "Regenerate selected", "secondary", "refresh", self._regenerate
        )
        self.regenerate_button.setVisible(self.state.can(security.P_REPORTS_MANAGE))
        jobs_card.add_action(self.regenerate_button)
        jobs_card.add_action(make_button("Open selected", "secondary", "folder", self._open_selected))
        self.jobs_table = DataTable()
        self.jobs_table.setMinimumHeight(220)
        self.jobs_table.doubleClicked.connect(self._open_selected)
        jobs_card.content.addWidget(self.jobs_table, 1)
        self.jobs_hint = QLabel("")
        self.jobs_hint.setObjectName("Muted")
        jobs_card.content.addWidget(self.jobs_hint)
        self.layout.addWidget(jobs_card, 3)

        export_card = SectionCard(
            "Export a date range", "Every export is written atomically to the destination you choose."
        )
        controls = QWidget()
        row = QHBoxLayout(controls)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        self.kind_combo = QComboBox()
        for key, label in reports.EXPORT_TYPES.items():
            self.kind_combo.addItem(label, key)
        row.addWidget(self.kind_combo, 2)
        self.range = DateRangeBar("month")
        row.addWidget(self.range)
        self.format_combo = QComboBox()
        self.format_combo.addItem("Excel (.xlsx)", "xlsx")
        self.format_combo.addItem("CSV (.csv)", "csv")
        row.addWidget(self.format_combo)
        row.addWidget(make_button("Export", "primary", "download", self.export_action))
        export_card.content.addWidget(controls)
        self.export_hint = QLabel("")
        self.export_hint.setObjectName("Muted")
        self.export_hint.setWordWrap(True)
        export_card.content.addWidget(self.export_hint)
        self.layout.addWidget(export_card, 2)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        try:
            snapshot = scheduler.status_snapshot(self.state.database, self.state.report_config)
        except Exception as exc:
            show_error(self, exc, "Could not read report status")
            return
        rows = []
        for job in snapshot["jobs"]:
            files = 0
            if job.status == "completed" and job.file_path:
                files = 4
            rows.append(
                {
                    "id": job.id,
                    "date": job.period_start,
                    "status": job.status,
                    "files": files,
                    "generated_at": job.generated_at,
                    "attempts": job.attempts,
                    "error": job.last_error or "",
                    "path": job.file_path or "",
                }
            )
        self.jobs_table.set_data(
            rows,
            [
                TableColumn(
                    "date",
                    "Business date",
                    120,
                    formatter=lambda row: self.state.date(row.get("date")),
                    bold=True,
                ),
                TableColumn(
                    "status",
                    "Status",
                    100,
                    formatter=lambda row: str(row.get("status", "")).title(),
                    color=lambda row: status_color(row.get("status"), self.state.theme),
                ),
                TableColumn(
                    "files",
                    "Files",
                    56,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                ),
                TableColumn(
                    "generated_at",
                    "Generated",
                    150,
                    formatter=lambda row: self.state.datetime(row.get("generated_at")),
                ),
                TableColumn(
                    "attempts",
                    "Attempts",
                    72,
                    align=int(Qt.AlignRight | Qt.AlignVCenter),
                ),
                TableColumn("error", "Last error", 360),
            ],
        )
        self.jobs_table.connect_selection(self._selection_changed)
        last = snapshot["last"]
        self.kpi_missing.set_value(
            f"{snapshot['total_missing']:,}",
            "Generate missing to catch up" if snapshot["total_missing"] else "All closed dates covered",
        )
        self.kpi_last.set_value(
            self.state.date(last.period_start) if last else "—",
            f"{len(rows):,} job(s) recorded" if rows else "No reports yet",
        )
        self.kpi_closed.set_value(self.state.date(snapshot["last_closed"]), "Daily bundles are due after closing time")
        self.jobs_hint.setText(
            f"Reports folder: {self.state.report_config.report_root}    ·    "
            "Catch-up runs at startup and every five minutes while StockKeep is open."
        )
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        self.regenerate_button.setEnabled(self.jobs_table.selected_record() is not None)

    def _selected(self) -> dict | None:
        return self.jobs_table.selected_record()

    # ------------------------------------------------------------------
    def _generate_missing(self) -> None:
        if not self.state.can(security.P_REPORTS_MANAGE):
            return
        def job():
            return scheduler.generate_missing(
                self.state.database, self.state.report_config
            )

        def done(summary):
            if summary.locked:
                self.main.show_status("A report run is already in progress.")
            else:
                self.main.show_status(summary.message())
                if summary.generated:
                    self.state.notify_data_changed()
            self.refresh()

        run_task(
            self,
            job,
            on_success=done,
            message="Generating missing daily reports…",
            title="Daily reports",
            progress=True,
        )

    def _regenerate(self) -> None:
        if not self.state.can(security.P_REPORTS_MANAGE):
            return
        record = self._selected()
        if record is None:
            return
        day = record["date"]

        def job():
            return scheduler.run_for_date(
                self.state.database, self.state.report_config, day, force=True
            )

        def done(outcome):
            if outcome.ok:
                self.main.show_status(f"Report for {self.state.date(day)} regenerated.")
                self.state.notify_data_changed()
            else:
                show_error(self, Exception(outcome.error or "Report failed"), "Report generation failed")
            self.refresh()

        run_task(
            self,
            job,
            on_success=done,
            message=f"Regenerating the report for {self.state.date(day)}…",
            title="Daily report",
        )

    def _open_root(self) -> None:
        open_path(self.state.report_config.report_root)

    def _open_selected(self, *_args) -> None:
        record = self._selected()
        if record is None:
            return
        directory = reports.daily_directory(self.state.report_config.report_root, record["date"])
        open_path(directory)

    # ------------------------------------------------------------------
    def export_action(self) -> None:
        start, end = self.range.range()
        kind = self.kind_combo.currentData()
        fmt = self.format_combo.currentData()
        if end < start:
            show_error(self, ValueError("The end date cannot be before the start date."))
            return
        target = export_path(
            self, self.state, f"{kind}_{start}_{end}", formats="Excel workbook (*.xlsx);;CSV file (*.csv)"
        )
        if target is None:
            return
        if target.suffix.lower() != f".{fmt}":
            target = target.with_suffix(f".{fmt}")

        def job():
            with self.state.database.session() as session:
                return reports.export_report(
                    session,
                    kind,
                    start,
                    end,
                    target,
                    fmt=fmt,
                    tz=self.state.settings.timezone,
                    currency_symbol=self.state.settings.currency_symbol,
                    business_name=self.state.settings.business_name,
                )

        def done(path):
            self.main.show_status(f"Export saved to {path}.")
            open_path(path)

        run_task(
            self,
            job,
            on_success=done,
            message="Building the export…",
            title="Export",
        )

    def export_action_shortcut(self) -> None:
        self.export_action()
