from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

APP_USER_MODEL_ID = "San0s.SWOT"


def apply_windows_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        return


def resolve_app_icon() -> QIcon:
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).resolve().parent
        candidates.extend(
            [
                base / "app_icon.ico",
                base / "_internal" / "app" / "assets" / "app_icon.ico",
                base / "_internal" / "app" / "assets" / "app_icon.png",
            ]
        )
    else:
        app_dir = Path(__file__).resolve().parents[1]
        candidates.extend(
            [
                app_dir / "assets" / "app_icon.ico",
                app_dir / "assets" / "app_icon.png",
            ]
        )

    for path in candidates:
        if not path.exists():
            continue
        icon = QIcon(str(path))
        if not icon.isNull():
            return icon

    # Fallback: use executable icon on Windows packaged runs.
    exe_path = Path(sys.executable)
    if exe_path.suffix.lower() == ".exe" and exe_path.exists():
        icon = QIcon(str(exe_path))
        if not icon.isNull():
            return icon

    return QIcon()
