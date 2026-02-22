from __future__ import annotations

import sys
from pathlib import Path
from typing import Type

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.app_identity import apply_windows_app_user_model_id, resolve_app_icon
from app.ui.license_flow import _apply_license_title, _ensure_license_accepted
from app.ui.theme import apply_dark_palette as _apply_dark_palette_impl
from app.ui.update_flow import _start_update_check


def apply_dark_palette(app: QApplication) -> None:
    _apply_dark_palette_impl(app)


def _apply_physical_dpi_font_scale(app: QApplication) -> None:
    """Scale the application font so the UI appears the same physical size
    on high-resolution monitors (e.g. 2K/4K) that run at 100% OS scaling.

    Qt already handles OS display-scaling (devicePixelRatio). This function
    covers the remaining gap between the screen's physical pixel density and
    the standard ~96 DPI reference used at Full HD / 100% scaling.
    """
    screen = app.primaryScreen()
    if not screen:
        return
    phys_dpi = screen.physicalDotsPerInch()
    logic_dpi = screen.logicalDotsPerInch()
    # extra_scale = how much denser the screen is beyond what the OS already scales
    extra_scale = phys_dpi / max(logic_dpi, 96.0)
    extra_scale = max(1.0, min(2.0, extra_scale))
    if extra_scale > 1.05:
        font = app.font()
        font.setPointSizeF(font.pointSizeF() * extra_scale)
        app.setFont(font)


def acquire_single_instance():
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Global\\SWOT_SingleInstance_Mutex"
        handle = kernel32.CreateMutexW(None, True, mutex_name)
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return None
        return handle
    else:
        import fcntl
        lock_path = Path.home() / ".swot.lock"
        lock_file = open(lock_path, "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        return lock_file


def run_app(main_window_cls: Type):
    apply_windows_app_user_model_id()
    instance_lock = acquire_single_instance()
    if instance_lock is None:
        _tmp = QApplication(sys.argv)
        QMessageBox.warning(
            None,
            "SWOT",
            "Die Anwendung läuft bereits.",
        )
        sys.exit(0)

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs)
    app = QApplication(sys.argv)
    _apply_physical_dpi_font_scale(app)
    apply_dark_palette(app)
    app_icon = resolve_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)
    import app.i18n as i18n
    config_dir = Path(__file__).resolve().parents[1] / "config"
    i18n.init(config_dir)
    license_info = _ensure_license_accepted()
    if not license_info:
        sys.exit(1)
    w = main_window_cls()
    _apply_license_title(w, license_info)
    w.showMaximized()
    QTimer.singleShot(1200, lambda: _start_update_check(w))
    sys.exit(app.exec())
