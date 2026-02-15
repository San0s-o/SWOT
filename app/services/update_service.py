from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import requests

from app.i18n import tr

APP_NAME = "SWOT"
CONFIG_FILENAME = "license_config.json"
HTTP_TIMEOUT_S = 8


@dataclass
class ReleaseAsset:
    name: str
    download_url: str


@dataclass
class ReleaseInfo:
    version: str
    tag_name: str
    name: str
    body: str
    html_url: str
    published_at: str
    asset: Optional[ReleaseAsset]


@dataclass
class DownloadResult:
    ok: bool
    message: str
    file_path: Optional[Path] = None


@dataclass
class UpdateCheckResult:
    checked: bool
    update_available: bool
    current_version: str
    latest_version: str
    release: Optional[ReleaseInfo] = None
    message: str = ""


def _runtime_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def _candidate_config_paths() -> list[Path]:
    base = _runtime_base_dir()
    candidates = [base / CONFIG_FILENAME]
    if getattr(sys, "frozen", False):
        candidates.append(base / "_internal" / CONFIG_FILENAME)
    return candidates


def _load_update_config() -> dict[str, str]:
    cfg_raw: dict[str, Any] = {}
    for cfg_path in _candidate_config_paths():
        if not cfg_path.exists():
            continue
        try:
            parsed = json_load(cfg_path)
            if isinstance(parsed, dict):
                cfg_raw = parsed
                break
        except Exception:
            continue

    app_version = (os.environ.get("SWOT_APP_VERSION") or cfg_raw.get("app_version") or "dev").strip()
    github_repo = (os.environ.get("SWOT_GITHUB_REPO") or cfg_raw.get("github_repo") or "").strip()
    asset_pattern = (os.environ.get("SWOT_UPDATE_ASSET_PATTERN") or cfg_raw.get("update_asset_pattern") or "").strip()

    return {
        "app_version": app_version,
        "github_repo": github_repo,
        "asset_pattern": asset_pattern,
    }


def json_load(path: Path) -> Any:
    import json

    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_version(raw: str) -> str:
    v = (raw or "").strip()
    if v.lower().startswith("v."):
        return v[2:]
    if v.lower().startswith("v"):
        return v[1:]
    return v


def _version_tuple(raw: str) -> Optional[tuple[int, int, int, int, str]]:
    v = _normalize_version(raw)
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+]([A-Za-z0-9._-]+))?$", v)
    if not m:
        return None
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    suffix = (m.group(4) or "").lower()
    # Stable release should sort after prerelease for same version.
    stable_rank = 1 if not suffix else 0
    return (major, minor, patch, stable_rank, suffix)


def is_newer_version(current_version: str, latest_version: str) -> bool:
    cur = _normalize_version(current_version)
    lat = _normalize_version(latest_version)
    if not lat or cur == lat:
        return False

    cur_t = _version_tuple(cur)
    lat_t = _version_tuple(lat)
    if cur_t and lat_t:
        return lat_t > cur_t
    if not cur_t and lat_t:
        return True
    if cur_t and not lat_t:
        return False
    return lat.lower() != cur.lower()


def _pick_asset(assets: list[dict[str, Any]], pattern: str = "") -> Optional[ReleaseAsset]:
    if not assets:
        return None

    if pattern:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
            for asset in assets:
                name = str(asset.get("name", ""))
                url = str(asset.get("browser_download_url", ""))
                if name and url and rx.search(name):
                    return ReleaseAsset(name=name, download_url=url)
        except re.error:
            pass

    candidates: list[tuple[int, ReleaseAsset]] = []
    for asset in assets:
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if not name or not url:
            continue

        lowered = name.lower()
        score = 0
        if lowered.endswith(".exe"):
            score += 5
        elif lowered.endswith(".msi"):
            score += 4
        elif lowered.endswith(".zip"):
            score += 3
        if "win" in lowered or "windows" in lowered:
            score += 2
        if "x64" in lowered or "amd64" in lowered:
            score += 1
        candidates.append((score, ReleaseAsset(name=name, download_url=url)))

    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    return candidates[0][1]


def check_latest_release() -> UpdateCheckResult:
    cfg = _load_update_config()
    current_version = cfg["app_version"]
    repo = cfg["github_repo"]

    if not repo:
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            latest_version="",
            message=tr("svc.no_repo"),
        )

    if not current_version or current_version.lower() == "dev":
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            latest_version="",
            message=tr("svc.no_version"),
        )

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": f"{APP_NAME}-updater"}

    try:
        response = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_S)
        data = response.json() if response.content else {}
    except requests.RequestException as exc:
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            latest_version="",
            message=tr("svc.check_failed", detail=str(exc)),
        )
    except Exception:
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            latest_version="",
            message=tr("svc.invalid_response"),
        )

    if response.status_code >= 400:
        msg = str(data.get("message", f"HTTP {response.status_code}")) if isinstance(data, dict) else f"HTTP {response.status_code}"
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            latest_version="",
            message=tr("svc.check_failed", detail=msg),
        )

    if not isinstance(data, dict):
        return UpdateCheckResult(
            checked=False,
            update_available=False,
            current_version=current_version,
            latest_version="",
            message=tr("svc.unexpected_format"),
        )

    tag_name = str(data.get("tag_name", "")).strip()
    latest_version = _normalize_version(tag_name)
    update_available = is_newer_version(current_version, latest_version)

    release = ReleaseInfo(
        version=latest_version,
        tag_name=tag_name,
        name=str(data.get("name", "")).strip(),
        body=str(data.get("body", "")).strip(),
        html_url=str(data.get("html_url", "")).strip(),
        published_at=str(data.get("published_at", "")).strip(),
        asset=_pick_asset(list(data.get("assets") or []), cfg["asset_pattern"]),
    )

    return UpdateCheckResult(
        checked=True,
        update_available=update_available,
        current_version=current_version,
        latest_version=latest_version,
        release=release,
        message="",
    )


def download_release_asset(release: ReleaseInfo, target_dir: Path | None = None) -> DownloadResult:
    if not release.asset:
        return DownloadResult(False, tr("svc.no_asset"))

    out_dir = target_dir or (Path.home() / "Downloads" / "SWOT-updates")
    out_dir.mkdir(parents=True, exist_ok=True)

    file_path = out_dir / release.asset.name

    try:
        with requests.get(release.asset.download_url, timeout=30, stream=True) as response:
            if response.status_code >= 400:
                return DownloadResult(False, tr("svc.download_http_fail", status=response.status_code))
            with file_path.open("wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    if chunk:
                        f.write(chunk)
    except requests.RequestException as exc:
        return DownloadResult(False, tr("svc.download_failed", detail=str(exc)))

    return DownloadResult(True, tr("svc.download_ok"), file_path=file_path)
