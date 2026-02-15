from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import requests

from app.i18n import tr

APP_NAME = "SWOT"
LICENSE_FILENAME = "license.json"
CONFIG_FILENAME = "license_config.json"
HTTP_TIMEOUT_S = 12
OFFLINE_CACHE_GRACE_S = 24 * 60 * 60
PLACEHOLDER_LICENSE_KEYS = {"SWTO-TEST", "SWOT-TEST", "TEST"}


@dataclass
class LicenseValidation:
    valid: bool
    message: str
    license_type: Optional[str] = None
    expires_at: Optional[int] = None
    error_kind: Optional[str] = None


def _license_base_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata)
    return Path.home() / ".config"


def _license_paths() -> list[Path]:
    # Primary path depends on runtime (SWOT for EXE, SWOT-dev for python -m app).
    app_name = os.environ.get("SWOT_LICENSE_APP_NAME", "").strip() or _runtime_app_name()
    base = _license_base_dir()
    primary = base / app_name / LICENSE_FILENAME

    paths = [primary]
    # Backward compatibility: accept the sibling path to avoid re-activation prompts
    # when switching between dev and frozen runtime.
    if app_name.endswith("-dev"):
        paths.append(base / APP_NAME / LICENSE_FILENAME)
    elif app_name == APP_NAME:
        paths.append(base / f"{APP_NAME}-dev" / LICENSE_FILENAME)
    return paths


def _license_path() -> Path:
    return _license_paths()[0]


def _runtime_app_name() -> str:
    if getattr(sys, "frozen", False):
        return APP_NAME
    return f"{APP_NAME}-dev"


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


def _normalize_key(raw: Any) -> str:
    return str(raw or "").strip()


def _is_placeholder_key(raw: Any) -> bool:
    key = _normalize_key(raw).upper()
    return bool(key and key in PLACEHOLDER_LICENSE_KEYS)


def _license_data_score(raw: dict[str, Any]) -> tuple[int, int]:
    key = _normalize_key(raw.get("key"))
    has_key = bool(key and not _is_placeholder_key(key))
    has_session = bool(str(raw.get("session_token", "")).strip())
    if has_session:
        quality = 2
    elif has_key:
        quality = 1
    else:
        quality = 0

    saved_raw = raw.get("saved_at")
    saved_at = int(saved_raw) if isinstance(saved_raw, (int, float)) else 0
    return quality, saved_at


def _load_local_license_candidates() -> list[dict[str, Any]]:
    candidates: list[tuple[tuple[int, int], dict[str, Any]]] = []

    for path in _license_paths():
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                if _is_placeholder_key(raw.get("key")):
                    continue
                candidates.append((_license_data_score(raw), raw))
        except Exception:
            continue

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [raw for _, raw in candidates]


def _load_local_license_data() -> dict[str, Any]:
    candidates = _load_local_license_candidates()
    return candidates[0] if candidates else {}


def _find_local_license_data_for_key(key: str) -> dict[str, Any]:
    key_norm = _normalize_key(key)
    if not key_norm or _is_placeholder_key(key_norm):
        return {}
    for raw in _load_local_license_candidates():
        if _normalize_key(raw.get("key")) == key_norm:
            return raw
    return {}


def _save_local_license_data(payload: dict[str, Any]) -> None:
    path = _license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _load_online_config() -> dict[str, str]:
    cfg_raw: dict[str, Any] = {}
    for cfg_path in _candidate_config_paths():
        if not cfg_path.exists():
            continue
        try:
            parsed = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                cfg_raw = parsed
                break
        except Exception:
            continue

    supabase_url = (os.environ.get("SWOT_SUPABASE_URL") or cfg_raw.get("supabase_url") or "").strip()
    supabase_anon_key = (
        os.environ.get("SWOT_SUPABASE_ANON_KEY") or cfg_raw.get("supabase_anon_key") or ""
    ).strip()
    app_id = (os.environ.get("SWOT_LICENSE_APP_ID") or cfg_raw.get("app_id") or "Summoners-War-Team-Optimizer").strip()
    app_version = (os.environ.get("SWOT_APP_VERSION") or cfg_raw.get("app_version") or "dev").strip()

    return {
        "supabase_url": supabase_url.rstrip("/"),
        "supabase_anon_key": supabase_anon_key,
        "app_id": app_id,
        "app_version": app_version,
    }


def _machine_fingerprint() -> str:
    raw = "|".join(
        [
            str(uuid.getnode()),
            os.environ.get("COMPUTERNAME", ""),
            platform.system(),
            platform.machine(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _headers(anon_key: str) -> dict[str, str]:
    return {
        "apikey": anon_key,
        "Authorization": f"Bearer {anon_key}",
        "Content-Type": "application/json",
    }


def _normalize_message(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback

    # Repair common UTF-8/Latin-1 mojibake sequences coming from backend text payloads.
    if any(marker in text for marker in ("\u00c3", "\u00c2", "\u00e2")):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired:
                return repaired
        except UnicodeError:
            pass
    return text


def _post_function(function_name: str, payload: dict[str, Any], cfg: dict[str, str]) -> dict[str, Any]:
    url = f"{cfg['supabase_url']}/functions/v1/{function_name}"
    try:
        response = requests.post(
            url,
            headers=_headers(cfg["supabase_anon_key"]),
            json=payload,
            timeout=HTTP_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        return {
            "ok": False,
            "message": tr("lic.network_error", detail=str(exc)),
            "error_kind": "network",
        }

    try:
        data = response.json()
    except Exception:
        data = {
            "ok": False,
            "message": tr("lic.invalid_response", status=response.status_code),
            "error_kind": "invalid_response",
        }
    if response.status_code >= 400:
        if "message" not in data:
            data["message"] = tr("lic.server_error", status=response.status_code)
        data["ok"] = False
        if "error_kind" not in data:
            data["error_kind"] = "server_transient" if response.status_code >= 500 or response.status_code == 429 else "server_rejected"
    return data


def _parse_expires_at(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        ts = int(value)
        return ts if ts > 0 else None
    raw = str(value).strip()
    if not raw:
        return None
    if raw.isdigit():
        ts = int(raw)
        return ts if ts > 0 else None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return int(parsed.timestamp())
    except ValueError:
        return None


def _activate_online(key: str, cfg: dict[str, str]) -> LicenseValidation:
    payload = {
        "key": key,
        "machine_fingerprint": _machine_fingerprint(),
        "app_id": cfg["app_id"],
        "app_version": cfg["app_version"],
    }
    data = _post_function("activate", payload, cfg)
    if not bool(data.get("ok")):
        return LicenseValidation(
            False,
            _normalize_message(data.get("message"), tr("lic.activation_failed")),
            error_kind=str(data.get("error_kind", "")).strip() or None,
        )

    _save_local_license_data(
        {
            "key": key.strip(),
            "session_token": str(data.get("session_token", "")).strip(),
            "session_expires_at": str(data.get("session_expires_at", "")).strip(),
            "license_type": str(data.get("license_type", "")).strip(),
            "license_expires_at": str(data.get("license_expires_at", "")).strip(),
            "saved_at": int(time.time()),
        }
    )
    return LicenseValidation(
        True,
        _normalize_message(data.get("message"), tr("lic.activated")),
        license_type=str(data.get("license_type", "")).strip() or None,
        expires_at=_parse_expires_at(data.get("license_expires_at")),
    )


def _validate_online(key: str, session_token: str, cfg: dict[str, str]) -> LicenseValidation:
    payload = {
        "key": key,
        "session_token": session_token,
        "machine_fingerprint": _machine_fingerprint(),
        "app_id": cfg["app_id"],
        "app_version": cfg["app_version"],
    }
    data = _post_function("validate", payload, cfg)
    if not bool(data.get("ok")):
        return LicenseValidation(
            False,
            _normalize_message(data.get("message"), tr("lic.check_failed")),
            error_kind=str(data.get("error_kind", "")).strip() or None,
        )
    current = _load_local_license_data()

    # Optional token rotation from backend
    new_token = str(data.get("session_token", "")).strip()
    new_exp = str(data.get("session_expires_at", "")).strip()
    if new_token:
        current["key"] = key.strip()
        current["session_token"] = new_token
        current["session_expires_at"] = new_exp
        current["license_type"] = str(data.get("license_type", current.get("license_type", ""))).strip()
        current["license_expires_at"] = str(data.get("license_expires_at", current.get("license_expires_at", ""))).strip()
        current["saved_at"] = int(time.time())
        _save_local_license_data(current)

    license_type = str(data.get("license_type", current.get("license_type", ""))).strip() or None
    expires_at = _parse_expires_at(data.get("license_expires_at", current.get("license_expires_at")))
    return LicenseValidation(
        True,
        _normalize_message(data.get("message"), tr("lic.valid")),
        license_type=license_type,
        expires_at=expires_at,
    )


def _offline_grace_seconds() -> int:
    raw = os.environ.get("SWOT_OFFLINE_GRACE_SECONDS", "").strip()
    if raw.isdigit():
        return max(0, int(raw))
    return OFFLINE_CACHE_GRACE_S


def _validate_from_local_cache(key: str, local_data: dict[str, Any], now_ts: int) -> Optional[LicenseValidation]:
    local_key = _normalize_key(local_data.get("key"))
    if not local_key or local_key != key:
        return None

    session_expires = _parse_expires_at(local_data.get("session_expires_at"))
    license_expires = _parse_expires_at(local_data.get("license_expires_at"))
    if session_expires is None:
        return None

    grace_until = session_expires + _offline_grace_seconds()
    if now_ts > grace_until:
        return None
    if license_expires is not None and now_ts > license_expires:
        return None

    return LicenseValidation(
        True,
        tr("lic.valid_cached"),
        license_type=str(local_data.get("license_type", "")).strip() or None,
        expires_at=license_expires,
        error_kind="cached",
    )


def validate_license_key(key: str, now_ts: Optional[int] = None) -> LicenseValidation:
    current_ts = int(time.time()) if now_ts is None else int(now_ts)
    key_norm = _normalize_key(key)
    if not key_norm:
        return LicenseValidation(False, tr("lic.no_key"))
    if _is_placeholder_key(key_norm):
        return LicenseValidation(False, tr("lic.no_key"))

    local_data = _find_local_license_data_for_key(key_norm) or _load_local_license_data()
    cached_validation = _validate_from_local_cache(key_norm, local_data, current_ts)

    cfg = _load_online_config()
    if not cfg["supabase_url"] or not cfg["supabase_anon_key"]:
        if cached_validation is not None:
            return cached_validation
        return LicenseValidation(False, tr("lic.not_configured"))

    local_key = _normalize_key(local_data.get("key"))
    session_token = str(local_data.get("session_token", "")).strip() if local_key == key_norm else ""

    if session_token:
        online_check = _validate_online(key_norm, session_token, cfg)
        if online_check.valid:
            return online_check
        if cached_validation is not None and online_check.error_kind in {"network", "invalid_response", "server_transient"}:
            return cached_validation

    # Fallback: activation endpoint is idempotent for already bound machine
    activated = _activate_online(key_norm, cfg)
    if activated.valid:
        return activated
    if cached_validation is not None and activated.error_kind in {"network", "invalid_response", "server_transient"}:
        return cached_validation
    return activated


def save_license_key(key: str) -> None:
    # Keep compatibility with existing call sites; real validation now happens online.
    key_norm = _normalize_key(key)
    if not key_norm or _is_placeholder_key(key_norm):
        return
    current = _find_local_license_data_for_key(key_norm)
    current["key"] = key_norm
    current["saved_at"] = int(time.time())
    _save_local_license_data(current)


def load_license_keys() -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for raw in _load_local_license_candidates():
        key = _normalize_key(raw.get("key"))
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys


def load_license_key() -> Optional[str]:
    keys = load_license_keys()
    return keys[0] if keys else None
