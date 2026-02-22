from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _copy_tree(src_dir: Path, dst_dir: Path) -> None:
    for child in src_dir.iterdir():
        target = dst_dir / child.name
        if child.is_dir():
            shutil.copytree(child, target, dirs_exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(child, target)


def _safe_rmtree(path: Path) -> None:
    try:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _copy_with_retries(src_dir: Path, dst_dir: Path, retries: int = 80, delay_s: float = 0.25) -> bool:
    for _ in range(retries):
        try:
            _copy_tree(src_dir, dst_dir)
            return True
        except Exception:
            time.sleep(delay_s)
    return False


def _relaunch_app(exe_path: Path) -> bool:
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        )
    try:
        subprocess.Popen(
            [str(exe_path)],
            creationflags=creationflags,
            close_fds=True,
        )
        return True
    except Exception:
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--apply-zip-update", action="store_true")
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--payload-dir", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--exe-path", required=True)
    return parser


def run_apply_zip_update(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.apply_zip_update:
        return 2

    staging_dir = Path(args.staging_dir)
    payload_dir = Path(args.payload_dir)
    install_dir = Path(args.install_dir)
    exe_path = Path(args.exe_path)

    # Give the main app process a short moment to exit and release files.
    time.sleep(0.8)

    copy_ok = _copy_with_retries(payload_dir, install_dir)
    _safe_rmtree(staging_dir)
    if not copy_ok:
        return 3
    if not _relaunch_app(exe_path):
        return 4
    return 0
