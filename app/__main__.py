from __future__ import annotations

import sys


def _is_apply_zip_mode(argv: list[str]) -> bool:
    for arg in argv:
        if arg == "--apply-zip-update":
            return True
    return False


def _is_updater_mode(argv: list[str]) -> bool:
    for arg in argv:
        if arg == "--updater-state" or arg.startswith("--updater-state="):
            return True
    return False


if __name__ == "__main__":
    if _is_apply_zip_mode(sys.argv[1:]):
        from app.update_apply import run_apply_zip_update

        raise SystemExit(run_apply_zip_update(sys.argv[1:]))

    if _is_updater_mode(sys.argv[1:]):
        from app.updater_main import run_updater

        raise SystemExit(run_updater(sys.argv[1:]))

    from app.ui.main_window import run_app

    run_app()
