"""Qt application bootstrap."""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from .. import APP_NAME, __version__
from ..logging_util import configure_logging
from ..services import auth_service
from .auth_dialogs import LoginDialog, SetupAdminDialog
from .icons import icon
from .main_window import MainWindow
from .state import AppState
from .theme import apply_theme

log = logging.getLogger(__name__)


def _initial_sign_in(state) -> bool:
    with state.database.session() as session:
        first_run = auth_service.needs_setup(session)
    if first_run:
        dialog = SetupAdminDialog(state)
        if dialog.exec() != QDialog.Accepted or dialog.user is None:
            return False
        state.set_current_user(dialog.user)
        return True

    dialog = LoginDialog(state)
    if dialog.exec() != QDialog.Accepted or dialog.user is None:
        return False
    state.set_current_user(dialog.user)
    return True


def run_app(database, paths) -> int:
    configure_logging(paths)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("StockKeep")
    app.setApplicationVersion(__version__)

    state = AppState(database, paths)
    apply_theme(app, state.theme)
    app.setWindowIcon(icon("package", "#0E7C86", 64))

    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("StockKeep.Desktop.1")
        except Exception:
            pass

    def excepthook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        log.error("Unhandled exception:\n%s", text)
        QMessageBox.critical(
            None,
            "StockKeep encountered an error",
            f"{exc_value}\n\nThe details were written to the application log:\n{paths.log_path}",
        )

    sys.excepthook = excepthook

    exit_code = 0
    try:
        if not _initial_sign_in(state):
            return 0

        while True:
            window = MainWindow(state)
            window.show()
            exit_code = app.exec()

            if not state.sign_out_requested:
                break

            # Sign-out returns to the login screen and rebuilds the window so
            # navigation and permissions match the next user.
            state.clear_current_user()
            state.sign_out_requested = False
            window.deleteLater()
            app.processEvents()

            dialog = LoginDialog(state)
            if dialog.exec() != QDialog.Accepted or dialog.user is None:
                break
            state.set_current_user(dialog.user)
        return exit_code
    finally:
        database.dispose()
