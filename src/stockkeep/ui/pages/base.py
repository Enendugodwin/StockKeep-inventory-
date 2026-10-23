"""Base page with shared lifecycle and keyboard hooks."""

from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout, QWidget


class BasePage(QWidget):
    key = ""

    def __init__(self, state, main_window, parent=None):
        super().__init__(parent)
        self.state = state
        self.main = main_window
        self.setObjectName("PageRoot")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(26, 22, 26, 20)
        self.layout.setSpacing(16)
        self.build()
        self.state.data_changed.connect(self._on_data_changed)
        self.state.settings_changed.connect(self._on_settings_changed)

    # ---- lifecycle -------------------------------------------------------
    def build(self) -> None:  # pragma: no cover - overridden
        pass

    def refresh(self) -> None:
        pass

    def _on_data_changed(self) -> None:
        if self.isVisible():
            self.refresh()

    def _on_settings_changed(self) -> None:
        if self.isVisible():
            self.refresh()

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self.refresh()

    # ---- keyboard shortcuts ---------------------------------------------
    def new_action(self) -> None:
        pass

    def focus_search(self) -> None:
        pass

    def save_action(self) -> None:
        pass

    def export_action(self) -> None:
        pass
