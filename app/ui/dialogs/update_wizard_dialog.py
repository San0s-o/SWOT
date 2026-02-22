from __future__ import annotations

import webbrowser
from typing import Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)

from app.i18n import tr
from app.services.update_service import (
    AutoUpdateResult,
    DownloadResult,
    ReleaseInfo,
    UpdateCheckResult,
    apply_update,
    download_release_asset,
)
from app.ui.async_worker import _TaskWorker

STEP_INFO = 0
STEP_DOWNLOAD = 1
STEP_DONE = 2

_GITHUB_RELEASES_URL = "https://github.com/San0s-o/Summoners-War-Team-Optimizer/releases"


class _DownloadSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)


class _DownloadWorker(QRunnable):
    def __init__(self, release: ReleaseInfo, cancel_flag: list) -> None:
        super().__init__()
        self.signals = _DownloadSignals()
        self._release = release
        self._cancel_flag = cancel_flag

    def run(self) -> None:
        try:
            result = download_release_asset(
                self._release,
                progress_cb=lambda done, total: self.signals.progress.emit(done, total),
                cancel_flag=self._cancel_flag,
            )
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class UpdateWizardDialog(QDialog):
    def __init__(
        self,
        check_result: UpdateCheckResult,
        parent=None,
        launch_external_updater: Optional[Callable[[UpdateCheckResult], tuple[bool, str]]] = None,
        auto_start_download: bool = False,
    ) -> None:
        super().__init__(parent)
        self._check_result = check_result
        self._launch_external_updater = launch_external_updater
        self._auto_start_download = auto_start_download
        self._download_worker: Optional[_DownloadWorker] = None
        self._install_worker: Optional[_TaskWorker] = None
        self._cancel_flag: list = [False]
        self._downloaded_path = None

        self.setWindowTitle(tr("update.title"))
        self.setMinimumWidth(500)
        self.setMinimumHeight(340)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        app = QApplication.instance()
        if app is not None and not app.windowIcon().isNull():
            self.setWindowIcon(app.windowIcon())

        self._setup_ui()
        self._go_to_step(STEP_INFO)
        if self._auto_start_download:
            QTimer.singleShot(0, self._start_download)

    # ── UI Setup ─────────────────────────────────────────────────

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        root.addWidget(self._make_step_indicator())

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #555;")
        root.addWidget(sep)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._make_info_page())
        self._stack.addWidget(self._make_download_page())
        self._stack.addWidget(self._make_done_page())
        root.addWidget(self._stack, 1)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #555;")
        root.addWidget(sep2)

        root.addLayout(self._make_button_row())

    def _make_step_indicator(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)

        self._step_bubbles: list[QLabel] = []
        self._step_labels: list[QLabel] = []
        steps = [
            tr("update.wizard.step_info"),
            tr("update.wizard.step_download"),
            tr("update.wizard.step_done"),
        ]
        for i, name in enumerate(steps):
            bubble = QLabel(str(i + 1))
            bubble.setFixedSize(24, 24)
            bubble.setAlignment(Qt.AlignCenter)
            self._step_bubbles.append(bubble)

            lbl = QLabel(name)
            self._step_labels.append(lbl)

            layout.addWidget(bubble)
            layout.addWidget(lbl)

            if i < len(steps) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                layout.addWidget(line, 1)

        return widget

    def _make_info_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(6)

        release = self._check_result.release
        latest = self._check_result.latest_version
        current = self._check_result.current_version

        lbl_version = QLabel(tr("update.wizard.new_version", latest=latest, current=current))
        lbl_version.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(lbl_version)

        if release and release.name:
            lbl_name = QLabel(release.name)
            lbl_name.setStyleSheet("color: #aaa; font-size: 11px;")
            layout.addWidget(lbl_name)

        if release and release.body:
            layout.addSpacing(6)
            lbl_notes_header = QLabel(tr("update.wizard.release_notes"))
            lbl_notes_header.setStyleSheet("color: #ccc; font-size: 11px;")
            layout.addWidget(lbl_notes_header)

            notes = QTextEdit()
            notes.setReadOnly(True)
            notes.setPlainText(release.body)
            notes.setMaximumHeight(140)
            notes.setStyleSheet("background: #2a2a2a; border: 1px solid #444; color: #ccc; font-size: 11px;")
            layout.addWidget(notes)

        layout.addStretch(1)
        return page

    def _make_download_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        self._lbl_download_status = QLabel(tr("update.wizard.downloading"))
        self._lbl_download_status.setAlignment(Qt.AlignCenter)
        self._lbl_download_status.setStyleSheet("font-size: 12px;")
        layout.addWidget(self._lbl_download_status)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFixedHeight(22)
        layout.addWidget(self._progress_bar)

        self._lbl_download_bytes = QLabel("")
        self._lbl_download_bytes.setAlignment(Qt.AlignCenter)
        self._lbl_download_bytes.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(self._lbl_download_bytes)

        layout.addStretch(1)
        return page

    def _make_done_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setAlignment(Qt.AlignCenter)

        self._lbl_done = QLabel("")
        self._lbl_done.setAlignment(Qt.AlignCenter)
        self._lbl_done.setWordWrap(True)
        self._lbl_done.setStyleSheet("font-size: 13px;")
        layout.addWidget(self._lbl_done)

        layout.addStretch(1)
        return page

    def _make_button_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)

        self._btn_later = QPushButton(tr("btn.later"))
        self._btn_release = QPushButton(tr("btn.release_page"))
        self._btn_install = QPushButton(tr("btn.install_update"))
        self._btn_install.setDefault(True)
        self._btn_cancel = QPushButton(tr("btn.cancel"))
        self._btn_close = QPushButton(tr("btn.close"))

        for btn in (self._btn_later, self._btn_release, self._btn_install, self._btn_cancel, self._btn_close):
            row.addWidget(btn)

        self._btn_later.clicked.connect(self.reject)
        self._btn_release.clicked.connect(self._open_release_page)
        self._btn_install.clicked.connect(self._start_download)
        self._btn_cancel.clicked.connect(self._cancel_download)
        self._btn_close.clicked.connect(self.accept)

        return row

    # ── Step navigation ───────────────────────────────────────────

    def _go_to_step(self, step: int) -> None:
        self._stack.setCurrentIndex(step)
        self._update_step_styles(step)
        self._btn_later.setVisible(step == STEP_INFO)
        self._btn_release.setVisible(step == STEP_INFO)
        self._btn_install.setVisible(step == STEP_INFO)
        self._btn_cancel.setVisible(step == STEP_DOWNLOAD)
        self._btn_close.setVisible(step == STEP_DONE)

    def _update_step_styles(self, current: int) -> None:
        for i, (bubble, lbl) in enumerate(zip(self._step_bubbles, self._step_labels)):
            if i < current:
                bubble.setStyleSheet(
                    "background: #3a7a3a; color: #fff; border-radius: 12px; font-weight: bold;"
                )
                bubble.setText("✓")
                lbl.setStyleSheet("color: #888;")
            elif i == current:
                bubble.setStyleSheet(
                    "background: #2979ff; color: #fff; border-radius: 12px; font-weight: bold;"
                )
                bubble.setText(str(i + 1))
                lbl.setStyleSheet("color: #fff; font-weight: bold;")
            else:
                bubble.setStyleSheet(
                    "background: #444; color: #888; border-radius: 12px;"
                )
                bubble.setText(str(i + 1))
                lbl.setStyleSheet("color: #888;")

    # ── Actions ───────────────────────────────────────────────────

    def _open_release_page(self) -> None:
        release = self._check_result.release
        url = (release.html_url or "").strip() if release else ""
        webbrowser.open(url if url.startswith("https://") else _GITHUB_RELEASES_URL)
        self.reject()

    def _start_download(self) -> None:
        if self._launch_external_updater is not None:
            ok, detail = self._launch_external_updater(self._check_result)
            if not ok:
                self._show_done(False, detail or tr("update.auto_failed"))
                return

            self.accept()
            app = QApplication.instance()
            if app is not None:
                app.quit()
            return
        if not self._check_result.release:
            return
        self._cancel_flag[0] = False
        self._progress_bar.setRange(0, 0)
        self._lbl_download_bytes.setText("")
        self._lbl_download_status.setText(tr("update.wizard.downloading"))
        self._go_to_step(STEP_DOWNLOAD)

        worker = _DownloadWorker(self._check_result.release, self._cancel_flag)
        self._download_worker = worker
        worker.signals.progress.connect(self._on_download_progress)
        worker.signals.finished.connect(self._on_download_finished)
        worker.signals.failed.connect(self._on_download_failed)
        QThreadPool.globalInstance().start(worker)

    def _cancel_download(self) -> None:
        self._cancel_flag[0] = True
        self._go_to_step(STEP_INFO)

    def _on_download_progress(self, done: int, total: int) -> None:
        if total > 0:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(int(done * 100 / total))
            self._lbl_download_bytes.setText(
                f"{done / 1_048_576:.1f} MB / {total / 1_048_576:.1f} MB"
            )
        else:
            self._progress_bar.setRange(0, 0)
            self._lbl_download_bytes.setText(f"{done / 1_048_576:.1f} MB")

    def _on_download_finished(self, result_obj: object) -> None:
        self._download_worker = None
        if not isinstance(result_obj, DownloadResult):
            self._show_done(False, tr("update.auto_failed"))
            return
        if not result_obj.ok:
            self._show_done(False, result_obj.message)
            return
        self._downloaded_path = result_obj.file_path
        self._start_install()

    def _on_download_failed(self, detail: str) -> None:
        self._download_worker = None
        self._show_done(False, tr("svc.check_failed", detail=detail))

    def _start_install(self) -> None:
        if not self._downloaded_path:
            self._show_done(False, tr("svc.no_asset"))
            return
        self._lbl_download_status.setText(tr("update.wizard.installing"))
        self._progress_bar.setRange(0, 0)

        worker = _TaskWorker(apply_update, self._downloaded_path)
        self._install_worker = worker
        worker.signals.finished.connect(self._on_install_finished)
        worker.signals.failed.connect(lambda detail: self._show_done(False, detail))
        QThreadPool.globalInstance().start(worker)

    def _on_install_finished(self, result_obj: object) -> None:
        self._install_worker = None
        if not isinstance(result_obj, AutoUpdateResult):
            self._show_done(False, tr("update.auto_failed"))
            return
        self._show_done(result_obj.ok, result_obj.message)
        if result_obj.ok and result_obj.restart_required:
            self.accept()
            app = QApplication.instance()
            if app is not None:
                app.quit()

    def _show_done(self, success: bool, message: str) -> None:
        if success:
            self._lbl_done.setStyleSheet("color: #6abf69; font-size: 13px;")
            self._lbl_done.setText(f"✓  {message}")
        else:
            self._lbl_done.setStyleSheet("color: #e57373; font-size: 13px;")
            self._lbl_done.setText(f"✗  {message}")
        self._go_to_step(STEP_DONE)

    def reject(self) -> None:
        if self._download_worker is not None or self._install_worker is not None:
            return
        super().reject()
