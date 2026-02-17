from __future__ import annotations

import threading
from typing import Any, Callable, Dict

from PySide6.QtCore import Qt, QTimer, QThreadPool, QEventLoop
from PySide6.QtWidgets import QApplication, QLabel, QProgressDialog

from app.i18n import tr
from app.ui.async_worker import _TaskWorker


def build_pass_progress_callback(window, label: QLabel, prefix: str) -> Callable[[int, int], None]:
    def _cb(current_pass: int, total_passes: int) -> None:
        text = tr("status.pass_progress", prefix=prefix, current=int(current_pass), total=int(total_passes))
        label.setText(text)
        window.statusBar().showMessage(text)
        QApplication.processEvents()

    return _cb


def run_with_busy_progress(
    window,
    text: str,
    work_fn: Callable[[Callable[[], bool], Callable[[Any], None], Callable[[int, int], None]], Any],
) -> Any:
    dlg = QProgressDialog(text, tr("btn.cancel"), 0, 0, window)
    dlg.setWindowTitle(tr("btn.optimize"))
    dlg.setLabelText(text)
    dlg.setWindowModality(Qt.ApplicationModal)
    dlg.setCancelButtonText(tr("btn.cancel"))
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.setRange(0, 0)
    dlg.show()
    QApplication.processEvents()

    cancel_event = threading.Event()
    solver_lock = threading.Lock()
    active_solvers: list[Any] = []
    progress_lock = threading.Lock()
    progress_state: Dict[str, int] = {"current": 0, "total": 0}

    def _is_cancelled() -> bool:
        return bool(cancel_event.is_set())

    def _register_solver(solver_obj: Any) -> None:
        with solver_lock:
            active_solvers.append(solver_obj)

    def _report_progress(current: int, total: int) -> None:
        with progress_lock:
            progress_state["current"] = max(0, int(current or 0))
            progress_state["total"] = max(0, int(total or 0))

    def _refresh_progress() -> None:
        if cancel_event.is_set():
            return
        with progress_lock:
            current = int(progress_state.get("current", 0))
            total = int(progress_state.get("total", 0))
        if total <= 0:
            return
        if dlg.maximum() == 0:
            dlg.setRange(0, 100)
            dlg.setValue(0)
        pct = max(0, min(100, int(round((float(current) / float(total)) * 100.0))))
        dlg.setValue(pct)
        label_text = f"{text} ({pct}%)"
        dlg.setLabelText(label_text)
        window.statusBar().showMessage(label_text)

    progress_timer = QTimer(dlg)
    progress_timer.timeout.connect(_refresh_progress)
    progress_timer.start(120)

    def _request_cancel() -> None:
        cancel_event.set()
        dlg.setLabelText(tr("opt.cancelled"))
        with solver_lock:
            solvers = list(active_solvers)
        for solver in solvers:
            try:
                if hasattr(solver, "StopSearch"):
                    solver.StopSearch()
                elif hasattr(solver, "stop_search"):
                    solver.stop_search()
            except Exception:
                continue

    dlg.canceled.connect(_request_cancel)

    wait_loop = QEventLoop()
    out: Dict[str, Any] = {}
    err: Dict[str, str] = {}
    worker = _TaskWorker(lambda: work_fn(_is_cancelled, _register_solver, _report_progress))

    def _on_finished(result: Any) -> None:
        out["result"] = result
        wait_loop.quit()

    def _on_failed(msg: str) -> None:
        err["msg"] = str(msg)
        wait_loop.quit()

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)
    wait_loop.exec()

    progress_timer.stop()
    dlg.close()
    dlg.deleteLater()
    QApplication.processEvents()
    if "msg" in err:
        raise RuntimeError(err["msg"])
    return out.get("result")
