"""QThreadPool helpers so long-running work never blocks the UI thread."""

from __future__ import annotations

import logging
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog

log = logging.getLogger(__name__)


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(int, int)


class Worker(QRunnable):
    def __init__(self, fn, *, with_progress: bool = False):
        super().__init__()
        self.fn = fn
        self.with_progress = with_progress
        self.signals = WorkerSignals()
        self.setAutoDelete(False)

    def run(self):  # noqa: D401
        try:
            if self.with_progress:
                result = self.fn(progress=self.signals.progress.emit)
            else:
                result = self.fn()
        except Exception as exc:
            log.exception("Background task failed")
            try:
                self.signals.failed.emit(f"{exc}")
            except RuntimeError:  # window/app already torn down
                pass
        else:
            try:
                self.signals.finished.emit(result)
            except RuntimeError:  # window/app already torn down
                pass


def run_task(
    parent,
    fn,
    *,
    on_success=None,
    on_error=None,
    message: str | None = None,
    title: str = "Working",
    progress: bool = False,
) -> Worker:
    """Run `fn` in the global thread pool with an optional modal progress bar."""
    worker = Worker(fn, with_progress=progress)
    dialog = None
    if message:
        dialog = QProgressDialog(message, "", 0, 0, parent)
        dialog.setWindowTitle(title)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setCancelButton(None)
        dialog.setMinimumDuration(250)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.setMinimumWidth(380)
        if progress:
            dialog.setRange(0, 100)
        dialog.show()

    if not hasattr(parent, "_active_workers"):
        parent._active_workers = []
    parent._active_workers.append(worker)

    def cleanup():
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        if worker in getattr(parent, "_active_workers", []):
            parent._active_workers.remove(worker)

    def handle_progress(done: int, total: int):
        if dialog is None:
            return
        if total <= 0:
            dialog.setRange(0, 0)
        else:
            dialog.setRange(0, total)
            dialog.setValue(min(done, total))

    def handle_success(result):
        cleanup()
        if on_success is not None:
            on_success(result)

    def handle_failure(error: str):
        cleanup()
        if on_error is not None:
            on_error(error)
        else:
            QMessageBox.critical(parent, "Something went wrong", error)

    worker.signals.finished.connect(handle_success)
    worker.signals.failed.connect(handle_failure)
    if progress:
        worker.signals.progress.connect(handle_progress)
    QThreadPool.globalInstance().start(worker)
    return worker
