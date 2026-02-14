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


APP_NAME = "SWOT"
LICENSE_FILENAME = "license.json"
CONFIG_FILENAME = "license_config.json"
HTTP_TIMEOUT_S = 12


@dataclass
class LicenseValidation:
    valid: bool
    message: str
    license_type: Optional[str] = None
    expires_at: Optional[int] = None


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


def _load_local_license_data() -> dict[str, Any]:
    for path in _license_paths():
        if not path.exists():
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            continue
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


def _post_function(function_name: str, payload: dict[str, Any], cfg: dict[str, str]) -> dict[str, Any]:
    url = f"{cfg['supabase_url']}/functions/v1/{function_name}"
    response = requests.post(
        url,
        headers=_headers(cfg["supabase_anon_key"]),
        json=payload,
        timeout=HTTP_TIMEOUT_S,
    )
    try:
        data = response.json()
    except Exception:
        data = {"ok": False, "message": f"UngÃ¼ltige Serverantwort ({response.status_code})."}
    if response.status_code >= 400:
        if "message" not in data:
            data["message"] = f"Serverfehler ({response.status_code})."
        data["ok"] = False
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
        return LicenseValidation(False, str(data.get("message", "Aktivierung fehlgeschlagen.")))

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
        str(data.get("message", "Lizenz aktiviert.")),
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
        return LicenseValidation(False, str(data.get("message", "LizenzprÃ¼fung fehlgeschlagen.")))
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
        str(data.get("message", "Lizenz gÃ¼ltig.")),
        license_type=license_type,
        expires_at=expires_at,
    )


def validate_license_key(key: str, now_ts: Optional[int] = None) -> LicenseValidation:
    del now_ts
    key_norm = (key or "").strip()
    if not key_norm:
        return LicenseValidation(False, "Kein Key eingegeben.")

    cfg = _load_online_config()
    if not cfg["supabase_url"] or not cfg["supabase_anon_key"]:
        return LicenseValidation(False, "Lizenz-Server nicht konfiguriert (license_config.json fehlt/ist unvollstÃ¤ndig).")

    local_data = _load_local_license_data()
    local_key = str(local_data.get("key", "")).strip()
    session_token = str(local_data.get("session_token", "")).strip() if local_key == key_norm else ""

    if session_token:
        online_check = _validate_online(key_norm, session_token, cfg)
        if online_check.valid:
            return online_check

    # Fallback: activation endpoint is idempotent for already bound machine
    return _activate_online(key_norm, cfg)


def save_license_key(key: str) -> None:
    # Keep compatibility with existing call sites; real validation now happens online.
    current = _load_local_license_data()
    current["key"] = key.strip()
    current["saved_at"] = int(time.time())
    _save_local_license_data(current)


def load_license_key() -> Optional[str]:
    raw = _load_local_license_data()
    key = str(raw.get("key", "")).strip()
    return key or None


