"""Stock file import: preview, validate and apply."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from ...services import imports as import_service
from ..common import confirm, confirm_typed, show_error, show_info
from ..models import TableColumn
from ..theme import status_color
from ..widgets import (
    DataTable,
    PageHeader,
    SearchBox,
    SectionCard,
    make_button,
    open_path,
)
from ..workers import run_task
from .base import BasePage


MODES = [
    ("Add new only", "add_new", "Rows that match existing stock are skipped."),
    ("Update matching only", "update_existing", "Rows without a match are skipped."),
    ("Add new and update matching", "upsert", "New rows are created and matches are updated."),
    (
        "Replace inventory (privileged)",
        "replace",
        "Applies the file as the full inventory and archives anything missing. "
        "Requires explicit confirmation and a file with no invalid rows.",
    ),
]


class ImportStockPage(BasePage):
    def build(self) -> None:
        self.preview = None
        self.preview_path: Path | None = None

        self.header = PageHeader(
            "Import Stock",
            "Bring in a CSV or Excel file, review every row, then apply it atomically.",
        )
        self.header.add_action("CSV template", "secondary", "download", self._template_csv)
        self.header.add_action("Excel template", "secondary", "download", self._template_xlsx)
        self.header.add_action("Reset", "secondary", "refresh", self._reset)
        self.layout.addWidget(self.header)

        select_card = SectionCard(
            "1. Choose a file",
            "Required columns: Stock Name, Price, Amount in Inventory. "
            "Optional: Product ID, SKU, Category, Cost Price, Reorder Level, Unit.",
        )
        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        self.path_edit = QLineEdit()
        self.path_edit.setReadOnly(True)
        self.path_edit.setPlaceholderText("No file selected")
        file_row.addWidget(self.path_edit, 1)
        browse = make_button("Browse…", "secondary", "folder", self._browse)
        file_row.addWidget(browse)
        self.preview_button = make_button("Preview file", "primary", "search", self._preview_file)
        file_row.addWidget(self.preview_button)
        select_card.content.addLayout(file_row)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        mode_label = QLabel("Import mode")
        mode_label.setObjectName("FieldLabel")
        mode_row.addWidget(mode_label)
        self.mode_combo = QComboBox()
        for label, value, description in MODES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        mode_row.addWidget(self.mode_combo, 1)
        self.mode_hint = QLabel(MODES[0][2])
        self.mode_hint.setObjectName("Muted")
        self.mode_hint.setWordWrap(True)
        mode_row.addWidget(self.mode_hint, 2)
        select_card.content.addLayout(mode_row)
        self.layout.addWidget(select_card)

        summary_card = SectionCard("2. Review the preview", "Nothing is written until you apply.")
        self.summary = QLabel("Select a file and preview it to see validation results.")
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        summary_card.content.addWidget(self.summary)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.apply_button = make_button("Apply import", "primary", "import", self._apply)
        self.apply_button.setEnabled(False)
        actions.addWidget(self.apply_button)
        self.rejected_button = make_button(
            "Export rejected rows", "secondary", "download", self._export_rejected
        )
        self.rejected_button.setEnabled(False)
        actions.addWidget(self.rejected_button)
        self.clear_button = make_button("Clear preview", "ghost", None, self._reset)
        actions.addWidget(self.clear_button)
        actions.addStretch(1)
        self.import_hint = QLabel("")
        self.import_hint.setObjectName("Muted")
        actions.addWidget(self.import_hint)
        summary_card.content.addLayout(actions)

        self.table = DataTable()
        self.table.setMinimumHeight(220)
        summary_card.content.addWidget(self.table, 1)
        self.layout.addWidget(summary_card, 3)

        recent_card = SectionCard("Recent imports", "Your last stock file imports")
        self.recent_table = DataTable()
        self.recent_table.setMinimumHeight(140)
        recent_card.content.addWidget(self.recent_table, 1)
        self.layout.addWidget(recent_card, 2)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self._load_recent()

    def _load_recent(self) -> None:
        with self.state.database.session() as session:
            rows = [
                {
                    "filename": batch.filename,
                    "mode": batch.mode.replace("_", " ").title(),
                    "total": batch.rows_total,
                    "added": batch.rows_added,
                    "updated": batch.rows_updated,
                    "skipped": batch.rows_skipped,
                    "rejected": batch.rows_rejected,
                    "status": batch.status,
                    "created_at": batch.created_at,
                }
                for batch in import_service.recent_imports(session, 15)
            ]
        self.recent_table.set_data(
            rows,
            [
                TableColumn("filename", "File", 220),
                TableColumn(
                    "created_at",
                    "Imported",
                    150,
                    formatter=lambda row: self.state.datetime(row.get("created_at")),
                ),
                TableColumn("mode", "Mode", 160),
                TableColumn("total", "Rows", 66, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn("added", "Added", 66, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn("updated", "Updated", 76, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn("skipped", "Skipped", 76, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn("rejected", "Rejected", 76, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn(
                    "status",
                    "Status",
                    92,
                    color=lambda row: status_color(row.get("status"), self.state.theme),
                ),
            ],
        )

    # ------------------------------------------------------------------
    def _browse(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self, "Choose a stock file", "", "Stock files (*.csv *.xlsx)"
        )
        if not selected:
            return
        self.preview_path = Path(selected)
        self.path_edit.setText(selected)
        self._preview_file()

    def _preview_file(self) -> None:
        if self.preview_path is None:
            show_info(self, "Choose a CSV or Excel file first.", "No file selected")
            return
        path = self.preview_path

        def job():
            with self.state.database.session() as session:
                return import_service.preview_file(path, session)

        run_task(
            self,
            job,
            on_success=self._preview_ready,
            message="Reading and validating the file…",
            title="Preview import",
        )

    def _preview_ready(self, preview) -> None:
        self.preview = preview
        if preview.fatal_error:
            self.summary.setText(f"<b>This file cannot be imported:</b> {preview.fatal_error}")
            self.table.set_data([], self._columns())
            self.apply_button.setEnabled(False)
            self.rejected_button.setEnabled(False)
            self.import_hint.setText("")
            return

        counts = preview.counts()
        self.summary.setText(
            f"Rows: {counts['total']:,}  ·  New: {counts['new']:,}  ·  "
            f"Updates: {counts['update']:,}  ·  Invalid: {counts['invalid']:,}  ·  "
            f"Duplicates: {counts['duplicates']:,}  ·  Ready to apply: {counts['valid']:,}"
        )
        rows = [
            {
                "row": row.row_number,
                "status": row.status,
                "name": row.values.get("name", ""),
                "price": row.values.get("price", ""),
                "quantity": row.values.get("quantity", ""),
                "code": row.values.get("code", ""),
                "sku": row.values.get("sku", ""),
                "category": row.values.get("category", ""),
                "errors": row.error_text(),
            }
            for row in preview.rows
        ]
        self.table.set_data(
            rows,
            [
                TableColumn("row", "Row", 54, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn(
                    "status",
                    "Status",
                    86,
                    formatter=lambda row: str(row.get("status", "")).title(),
                    color=lambda row: status_color(row.get("status"), self.state.theme),
                ),
                TableColumn("name", "Stock name", 220, bold=True),
                TableColumn("price", "Price", 92, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn("quantity", "Quantity", 88, align=int(Qt.AlignRight | Qt.AlignVCenter)),
                TableColumn("code", "Product ID", 104),
                TableColumn("sku", "SKU", 120),
                TableColumn("category", "Category", 110),
                TableColumn("errors", "Validation messages", 320),
            ],
        )
        self.apply_button.setEnabled(bool(preview.valid_count))
        self.rejected_button.setEnabled(bool(preview.rejected_count))
        self.import_hint.setText(
            f"{preview.rejected_count:,} row(s) will be rejected and left untouched."
            if preview.rejected_count
            else "All rows passed validation."
        )

    def _columns(self) -> list[TableColumn]:
        return [TableColumn("name", "Stock name", 300)]

    # ------------------------------------------------------------------
    def _mode_changed(self, _index: int) -> None:
        mode = self.mode_combo.currentData()
        for label, value, description in MODES:
            if value == mode:
                self.mode_hint.setText(description)
                break

    def _replace_blocker(self) -> bool:
        if self.preview is None:
            return True
        if self.preview.rejected_count:
            show_info(
                self,
                "Replacement is blocked while the file contains invalid or duplicate rows. "
                "Fix or remove those rows, then preview again.",
                "Replace inventory",
            )
            return True
        return False

    def _apply(self) -> None:
        if self.preview is None:
            return
        if self.preview.fatal_error:
            show_info(self, self.preview.fatal_error, "Cannot import")
            return
        mode = self.mode_combo.currentData()
        if mode == "replace" and self._replace_blocker():
            return
        if self.preview.rejected_count and not confirm(
            self,
            "Apply valid rows",
            f"{self.preview.rejected_count:,} invalid or duplicate row(s) will be skipped. "
            "Only the valid rows are applied, in a single transaction. Continue?",
            confirm_text="Apply valid rows",
        ):
            return
        if mode == "replace":
            if not confirm_typed(
                self,
                "Replace inventory",
                "This will treat the file as the complete inventory, archive active products "
                "that are missing, and reset quantities for the products it contains. "
                "This is a privileged action and cannot be undone without a backup.",
                "REPLACE",
            ):
                return

        preview = self.preview

        def job(progress=None):
            with self.state.database.session() as session:
                return import_service.apply_import(
                    session,
                    preview,
                    mode=mode,
                    operator_id=self.state.operator_id,
                    business_date=self.state.business_date,
                    confirm_replace=True,
                    progress=progress,
                )

        self.apply_button.setEnabled(False)
        run_task(
            self,
            job,
            on_success=self._applied,
            on_error=self._apply_failed,
            message="Importing stock rows…",
            title="Import stock",
            progress=True,
        )

    def _apply_failed(self, message: str) -> None:
        self.apply_button.setEnabled(bool(self.preview and self.preview.valid_count))
        show_error(self, Exception(message), "Import failed")

    def _applied(self, result) -> None:
        rejected = result.rejected
        self.state.notify_data_changed()
        self.main.request_report_refresh()
        self.main.show_status(result.summary())
        show_info(
            self,
            f"{result.summary()}\n\nBatch #{result.batch_id} was recorded in the audit log.",
            "Import complete",
        )
        if rejected:
            self._export_rejected()
        self._reset()
        self._load_recent()

    # ------------------------------------------------------------------
    def _template_csv(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self, "Save CSV template", str(self.state.paths.exports_dir / "stock_import_template.csv"),
            "CSV file (*.csv)",
        )
        if not selected:
            return
        try:
            path = import_service.write_template_csv(selected)
        except Exception as exc:
            show_error(self, exc)
            return
        self.main.show_status(f"Template saved to {path}.")
        open_path(path)

    def _template_xlsx(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self, "Save Excel template", str(self.state.paths.exports_dir / "stock_import_template.xlsx"),
            "Excel workbook (*.xlsx)",
        )
        if not selected:
            return
        try:
            path = import_service.write_template_xlsx(selected)
        except Exception as exc:
            show_error(self, exc)
            return
        self.main.show_status(f"Template saved to {path}.")
        open_path(path)

    def _export_rejected(self) -> None:
        if self.preview is None or not self.preview.rejected_count:
            return
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Save rejected rows",
            str(self.state.paths.exports_dir / "rejected_import_rows.xlsx"),
            "Excel workbook (*.xlsx);;CSV file (*.csv)",
        )
        if not selected:
            return
        try:
            path = import_service.write_rejected(self.preview, selected)
        except Exception as exc:
            show_error(self, exc)
            return
        self.main.show_status(f"Rejected rows saved to {path}.")
        open_path(path)

    def _reset(self) -> None:
        self.preview = None
        self.preview_path = None
        self.path_edit.clear()
        self.summary.setText("Select a file and preview it to see validation results.")
        self.table.set_data([], self._columns())
        self.apply_button.setEnabled(False)
        self.rejected_button.setEnabled(False)
        self.import_hint.setText("")
