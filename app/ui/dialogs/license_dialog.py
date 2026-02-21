from __future__ import annotations

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.services.license_service import LicenseValidation, save_license_key, validate_license_key
from app.ui.async_worker import _TaskWorker


class LicenseDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial_key: str = "", auto_validate: bool = False):
        super().__init__(parent)
        self.validation_result: LicenseValidation | None = None
        self._validation_worker: _TaskWorker | None = None
        self.setWindowTitle(tr("license.title"))
        self.resize(520, 180)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("license.enter_key")))

        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("SWTO-...")
        self.edit_key.setText(initial_key)
        layout.addWidget(self.edit_key)

        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)

        buttons = QDialogButtonBox()
        self.btn_validate = buttons.addButton(tr("btn.activate"), QDialogButtonBox.AcceptRole)
        self.btn_cancel = buttons.addButton(tr("btn.quit"), QDialogButtonBox.RejectRole)
        self.btn_validate.clicked.connect(self._on_validate)
        self.btn_cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.edit_key.returnPressed.connect(self._on_validate)
        if auto_validate and self.key_text:
            QTimer.singleShot(120, self._on_validate)

    @property
    def key_text(self) -> str:
        return self.edit_key.text().strip()

    def _set_busy(self, busy: bool) -> None:
        is_busy = bool(busy)
        self.edit_key.setEnabled(not is_busy)
        self.btn_validate.setEnabled(not is_busy)
        self.btn_cancel.setEnabled(not is_busy)

    def _on_validate(self) -> None:
        if self._validation_worker is not None:
            return
        if not self.key_text:
            self.lbl_status.setText(tr("lic.no_key"))
            return
        self._set_busy(True)
        self.lbl_status.setText(tr("license.validating"))
        worker = _TaskWorker(validate_license_key, self.key_text)
        self._validation_worker = worker
        worker.signals.finished.connect(self._on_validation_result)
        worker.signals.failed.connect(self._on_validation_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_validation_result(self, result_obj: object) -> None:
        self._validation_worker = None
        self._set_busy(False)
        if not isinstance(result_obj, LicenseValidation):
            self.lbl_status.setText(tr("lic.invalid_response", status="unknown"))
            return
        result = result_obj
        if result.valid:
            save_license_key(self.key_text)
            self.validation_result = result
            self.accept()
            return
        self.lbl_status.setText(result.message)

    def _on_validation_failed(self, detail: str) -> None:
        self._validation_worker = None
        self._set_busy(False)
        self.lbl_status.setText(tr("lic.check_failed"))
        if detail:
            self.lbl_status.setToolTip(detail)

    def reject(self) -> None:
        if self._validation_worker is not None:
            return
        super().reject()
