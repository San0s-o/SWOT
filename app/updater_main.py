from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

import app.i18n as i18n
from app.i18n import tr
from app.services.update_handoff import load_updater_state
from app.ui.app_identity import apply_windows_app_user_model_id, resolve_app_icon
from app.ui.dialogs.update_wizard_dialog import UpdateWizardDialog
from app.ui.theme import apply_dark_palette


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--updater-state", required=True)
    return parser


def _init_gui(argv: list[str]) -> QApplication:
    apply_windows_app_user_model_id()
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_DontUseNativeDialogs)
    app = QApplication(argv)
    apply_dark_palette(app)

    app_icon = resolve_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    app_dir = Path(__file__).resolve().parent
    config_dir = app_dir / "config"
    i18n.init(config_dir)
    return app


def run_updater(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    app = _init_gui(sys.argv)

    state_path = Path(args.updater_state).resolve()
    try:
        check_result = load_updater_state(state_path)
    except Exception as exc:
        QMessageBox.critical(
            None,
            "SWOT",
            tr("svc.auto_updater_state_invalid", detail=str(exc)),
        )
        return 2
    finally:
        _safe_unlink(state_path)

    dialog = UpdateWizardDialog(check_result=check_result, parent=None, auto_start_download=True)
    dialog.exec()
    return 0
