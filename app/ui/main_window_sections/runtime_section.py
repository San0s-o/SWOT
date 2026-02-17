from __future__ import annotations

import sys
from pathlib import Path
from typing import Type

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.ui.license_flow import _apply_license_title, _ensure_license_accepted
from app.ui.theme import apply_dark_palette as _apply_dark_palette_impl
from app.ui.update_flow import _start_update_check


def apply_dark_palette(app: QApplication) -> None:
    _apply_dark_palette_impl(app)


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
    instance_lock = acquire_single_instance()
    if instance_lock is None:
        _tmp = QApplication(sys.argv)
        QMessageBox.warning(
            None,
            "SWOT",
            "Die Anwendung läuft bereits.",
        )
        sys.exit(0)

    app = QApplication(sys.argv)
    apply_dark_palette(app)
    icon_path = Path(__file__).resolve().parents[1] / "assets" / "app_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    import app.i18n as i18n
    config_dir = Path(__file__).resolve().parents[1] / "config"
    i18n.init(config_dir)
    license_info = _ensure_license_accepted()
    if not license_info:
        sys.exit(1)
    w = main_window_cls()
    _apply_license_title(w, license_info)
    w.show()
    QTimer.singleShot(1200, lambda: _start_update_check(w))
    sys.exit(app.exec())
