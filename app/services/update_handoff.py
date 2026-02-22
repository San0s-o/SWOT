from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.i18n import tr
from app.services.update_service import ReleaseAsset, ReleaseInfo, UpdateCheckResult


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


def _asset_to_payload(asset: ReleaseAsset | None) -> dict[str, str] | None:
    if asset is None:
        return None
    return {
        "name": str(asset.name or "").strip(),
        "download_url": str(asset.download_url or "").strip(),
    }


def _asset_from_payload(payload: Any) -> ReleaseAsset | None:
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name", "")).strip()
    url = str(payload.get("download_url", "")).strip()
    if not name or not url:
        return None
    return ReleaseAsset(name=name, download_url=url)


def _release_to_payload(release: ReleaseInfo | None) -> dict[str, Any] | None:
    if release is None:
        return None
    return {
        "version": str(release.version or "").strip(),
        "tag_name": str(release.tag_name or "").strip(),
        "name": str(release.name or "").strip(),
        "body": str(release.body or ""),
        "html_url": str(release.html_url or "").strip(),
        "published_at": str(release.published_at or "").strip(),
        "asset": _asset_to_payload(release.asset),
        "checksum_asset": _asset_to_payload(release.checksum_asset),
    }


def _release_from_payload(payload: Any) -> ReleaseInfo | None:
    if not isinstance(payload, dict):
        return None
    asset = _asset_from_payload(payload.get("asset"))
    if asset is None:
        return None
    return ReleaseInfo(
        version=str(payload.get("version", "")).strip(),
        tag_name=str(payload.get("tag_name", "")).strip(),
        name=str(payload.get("name", "")).strip(),
        body=str(payload.get("body", "")),
        html_url=str(payload.get("html_url", "")).strip(),
        published_at=str(payload.get("published_at", "")).strip(),
        asset=asset,
        checksum_asset=_asset_from_payload(payload.get("checksum_asset")),
    )


def _result_to_payload(check_result: UpdateCheckResult) -> dict[str, Any]:
    return {
        "checked": bool(check_result.checked),
        "update_available": bool(check_result.update_available),
        "current_version": str(check_result.current_version or "").strip(),
        "latest_version": str(check_result.latest_version or "").strip(),
        "message": str(check_result.message or ""),
        "release": _release_to_payload(check_result.release),
    }


def _result_from_payload(payload: Any) -> UpdateCheckResult:
    if not isinstance(payload, dict):
        raise ValueError("Updater state has invalid format.")
    release = _release_from_payload(payload.get("release"))
    if release is None:
        raise ValueError("Updater state does not contain a valid release asset.")
    return UpdateCheckResult(
        checked=bool(payload.get("checked", True)),
        update_available=bool(payload.get("update_available", True)),
        current_version=str(payload.get("current_version", "")).strip(),
        latest_version=str(payload.get("latest_version", "")).strip(),
        release=release,
        message=str(payload.get("message", "")),
    )


def write_updater_state(check_result: UpdateCheckResult, *, state_dir: Path | None = None) -> Path:
    payload = _result_to_payload(check_result)
    out_dir = state_dir or Path(tempfile.gettempdir())
    out_dir.mkdir(parents=True, exist_ok=True)
    fd, raw_path = tempfile.mkstemp(prefix="swot-updater-", suffix=".json", dir=str(out_dir))
    path = Path(raw_path)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path


def load_updater_state(state_path: Path) -> UpdateCheckResult:
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return _result_from_payload(data)


def launch_updater_process(check_result: UpdateCheckResult) -> tuple[bool, str]:
    state_path = write_updater_state(check_result)
    executable = str(Path(sys.executable))
    if bool(getattr(sys, "frozen", False)):
        cmd = [executable, "--updater-state", str(state_path)]
    else:
        cmd = [executable, "-m", "app", "--updater-state", str(state_path)]
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    try:
        subprocess.Popen(
            cmd,
            creationflags=creationflags,
            close_fds=True,
        )
        return True, ""
    except Exception as exc:
        _safe_unlink(state_path)
        return False, tr("svc.auto_updater_launch_failed", detail=str(exc))
