from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class AccountPersistence:
    """
    Handles persistence of the imported Summoners War JSON.
    Stores the raw import JSON 1:1.
    """

    def __init__(self) -> None:
        self.data_dir = self._primary_data_dir()
        self.snapshot_path = self.data_dir / "account_snapshot.json"
        self.snapshot_meta_path = self.data_dir / "account_snapshot_meta.json"
        self.legacy_data_dir = Path("app/data")
        self.legacy_snapshot_path = self.legacy_data_dir / "account_snapshot.json"
        self.legacy_snapshot_meta_path = self.legacy_data_dir / "account_snapshot_meta.json"

    def _runtime_app_name(self) -> str:
        if getattr(sys, "frozen", False):
            return "SWOT"
        return "SWOT-dev"

    def _primary_data_dir(self) -> Path:
        override_dir = (os.environ.get("SWOT_DATA_DIR") or "").strip()
        if override_dir:
            return Path(override_dir)

        app_name = (os.environ.get("SWOT_DATA_APP_NAME") or "").strip() or self._runtime_app_name()
        base_dir = (
            (os.environ.get("LOCALAPPDATA") or "").strip()
            or (os.environ.get("APPDATA") or "").strip()
        )
        if base_dir:
            return Path(base_dir) / app_name
        return Path.home() / ".config" / app_name

    def active_snapshot_path(self) -> Path:
        if self.snapshot_path.exists():
            return self.snapshot_path
        if self.legacy_snapshot_path.exists():
            return self.legacy_snapshot_path
        return self.snapshot_path

    def active_snapshot_meta_path(self) -> Path:
        if self.snapshot_meta_path.exists():
            return self.snapshot_meta_path
        if self.legacy_snapshot_meta_path.exists():
            return self.legacy_snapshot_meta_path
        return self.snapshot_meta_path

    def exists(self) -> bool:
        return self.snapshot_path.exists() or self.legacy_snapshot_path.exists()

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.exists():
            return None

        with self.active_snapshot_path().open("r", encoding="utf-8") as f:
            return json.load(f)

    def load_meta(self) -> Dict[str, Any]:
        meta_path = self.active_snapshot_meta_path()
        if not meta_path.exists():
            return {}
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
        except Exception:
            pass
        return {}

    def save(self, raw_json: Dict[str, Any], source_name: Optional[str] = None) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

        tmp = self.snapshot_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(raw_json, f, ensure_ascii=False)

        tmp.replace(self.snapshot_path)
        meta = {
            "source_name": (source_name or "").strip(),
            "imported_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.snapshot_meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self) -> None:
        for p in {
            self.snapshot_path,
            self.snapshot_meta_path,
            self.legacy_snapshot_path,
            self.legacy_snapshot_meta_path,
        }:
            try:
                if p.exists():
                    p.unlink()
            except OSError:
                continue
