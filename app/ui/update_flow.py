from __future__ import annotations

import webbrowser

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMainWindow, QMessageBox

from app.i18n import tr
from app.services.update_service import UpdateCheckResult, check_latest_release
from app.ui.async_worker import _TaskWorker


def _show_update_dialog(window: QMainWindow, result: UpdateCheckResult) -> None:
    if not result.checked or not result.update_available or not result.release:
        return

    message = QMessageBox(window)
    message.setIcon(QMessageBox.Information)
    message.setWindowTitle(tr("update.title"))
    message.setText(tr("update.text", latest=result.latest_version, current=result.current_version))
    message.setInformativeText(tr("update.open_release"))

    btn_open_release = message.addButton(tr("btn.release_page"), QMessageBox.AcceptRole)
    message.addButton(tr("btn.later"), QMessageBox.RejectRole)
    message.exec()

    if message.clickedButton() == btn_open_release:
        release_url = (result.release.html_url or "").strip()
        if release_url.startswith("https://"):
            webbrowser.open(release_url)
        else:
            webbrowser.open("https://github.com/San0s-o/Summoners-War-Team-Optimizer/releases")


def _start_update_check(window: QMainWindow) -> None:
    worker = _TaskWorker(check_latest_release)
    window._update_check_worker = worker

    def _on_finished(result_obj: object) -> None:
        window._update_check_worker = None
        if not isinstance(result_obj, UpdateCheckResult):
            return
        _show_update_dialog(window, result_obj)

    def _on_failed(detail: str) -> None:
        window._update_check_worker = None
        if window.statusBar() is not None:
            window.statusBar().showMessage(tr("svc.check_failed", detail=detail), 6000)

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)
