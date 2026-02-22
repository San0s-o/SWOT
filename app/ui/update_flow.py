from __future__ import annotations

import webbrowser

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QMainWindow, QMessageBox

from app.i18n import tr
from app.services.update_service import AutoUpdateResult, UpdateCheckResult, auto_update_from_release, check_latest_release
from app.ui.async_worker import _TaskWorker


def _show_update_dialog(window: QMainWindow, result: UpdateCheckResult) -> None:
    if not result.checked or not result.update_available or not result.release:
        return

    message = QMessageBox(window)
    message.setIcon(QMessageBox.Information)
    message.setWindowTitle(tr("update.title"))
    message.setText(tr("update.text", latest=result.latest_version, current=result.current_version))
    message.setInformativeText(tr("update.open_release"))

    btn_auto_update = message.addButton(tr("btn.install_update"), QMessageBox.AcceptRole)
    btn_open_release = message.addButton(tr("btn.release_page"), QMessageBox.AcceptRole)
    message.addButton(tr("btn.later"), QMessageBox.RejectRole)
    message.exec()

    if message.clickedButton() == btn_auto_update:
        _start_auto_update(window, result)
    elif message.clickedButton() == btn_open_release:
        release_url = (result.release.html_url or "").strip()
        if release_url.startswith("https://"):
            webbrowser.open(release_url)
        else:
            webbrowser.open("https://github.com/San0s-o/Summoners-War-Team-Optimizer/releases")


def _start_auto_update(window: QMainWindow, result: UpdateCheckResult) -> None:
    if not result.release:
        if window.statusBar() is not None:
            window.statusBar().showMessage(tr("svc.no_asset"), 6000)
        return
    if getattr(window, "_auto_update_worker", None) is not None:
        return

    worker = _TaskWorker(auto_update_from_release, result.release)
    window._auto_update_worker = worker

    def _on_finished(result_obj: object) -> None:
        window._auto_update_worker = None
        if not isinstance(result_obj, AutoUpdateResult):
            if window.statusBar() is not None:
                window.statusBar().showMessage(tr("update.auto_failed"), 6000)
            return
        if window.statusBar() is not None:
            window.statusBar().showMessage(result_obj.message, 8000)
        if result_obj.ok and result_obj.restart_required:
            QApplication.instance().quit()

    def _on_failed(detail: str) -> None:
        window._auto_update_worker = None
        if window.statusBar() is not None:
            window.statusBar().showMessage(tr("update.auto_failed"), 6000)

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)


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
