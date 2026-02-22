from __future__ import annotations

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QMainWindow

from app.i18n import tr
from app.services.update_service import UpdateCheckResult, check_latest_release
from app.ui.async_worker import _TaskWorker


def _launch_standalone_updater(result: UpdateCheckResult) -> tuple[bool, str]:
    from app.services.update_handoff import launch_updater_process

    return launch_updater_process(result)


def _show_update_dialog(window: QMainWindow, result: UpdateCheckResult) -> None:
    if not result.checked or not result.update_available or not result.release:
        return

    from app.ui.dialogs.update_wizard_dialog import UpdateWizardDialog

    dlg = UpdateWizardDialog(result, parent=window, launch_external_updater=_launch_standalone_updater)
    dlg.exec()


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
