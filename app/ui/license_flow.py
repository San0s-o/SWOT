from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QEventLoop, QThreadPool
from PySide6.QtWidgets import QDialog, QMainWindow

from app.i18n import tr
from app.services.license_service import LicenseValidation, load_license_keys, save_license_key, validate_license_key
from app.ui.async_worker import _TaskWorker
from app.ui.dialogs.license_dialog import LicenseDialog


def _format_trial_remaining(expires_at: int, now_ts: int | None = None) -> str:
    now = int(now_ts if now_ts is not None else datetime.now().timestamp())
    remaining_s = max(0, int(expires_at) - now)
    if remaining_s >= 24 * 60 * 60:
        days = max(1, remaining_s // (24 * 60 * 60))
        return tr("license.days", n=days)
    if remaining_s >= 60 * 60:
        hours = max(1, remaining_s // (60 * 60))
        return tr("license.hours", n=hours)
    minutes = max(1, remaining_s // 60)
    return tr("license.minutes", n=minutes)


def _apply_license_title(window: QMainWindow, result: LicenseValidation) -> None:
    base_title = "SW Team Optimizer"
    license_type = (result.license_type or "").strip().lower()
    if "trial" not in license_type:
        window.setWindowTitle(base_title)
        return
    if result.expires_at:
        remaining = _format_trial_remaining(result.expires_at)
        window.setWindowTitle(f"{base_title} - {tr('license.trial_remaining', remaining=remaining)}")
        return
    window.setWindowTitle(f"{base_title} - {tr('license.trial')}")


def _validate_license_key_threaded_sync(key: str) -> LicenseValidation:
    wait_loop = QEventLoop()
    result_box: dict[str, LicenseValidation] = {"result": LicenseValidation(False, tr("lic.check_failed"))}
    worker = _TaskWorker(validate_license_key, key)

    def _on_finished(result_obj: object) -> None:
        if isinstance(result_obj, LicenseValidation):
            result_box["result"] = result_obj
        wait_loop.quit()

    def _on_failed(_detail: str) -> None:
        wait_loop.quit()

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)
    wait_loop.exec()
    return result_box["result"]


def _ensure_license_accepted() -> LicenseValidation | None:
    known_keys = load_license_keys()
    existing = known_keys[0] if known_keys else None
    cached_candidate: tuple[str, LicenseValidation] | None = None
    for key in known_keys:
        check = _validate_license_key_threaded_sync(key)
        if check.valid and check.error_kind != "cached":
            save_license_key(key)
            return check
        if check.valid:
            if cached_candidate is None:
                cached_candidate = (key, check)
            else:
                current_exp = check.expires_at or -1
                best_exp = cached_candidate[1].expires_at or -1
                if current_exp > best_exp:
                    cached_candidate = (key, check)

    if cached_candidate is not None:
        save_license_key(cached_candidate[0])
        return cached_candidate[1]

    dlg = LicenseDialog(initial_key=existing or "")
    if dlg.exec() == QDialog.Accepted:
        return dlg.validation_result
    return None
