from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class AccountPersistence:
    """
    Handles persistence of the imported Summoners War JSON.
    Stores the raw import JSON 1:1.
    """

    def __init__(self) -> None:
        self.data_dir = Path("app/data")
        self.snapshot_path = self.data_dir / "account_snapshot.json"
        self.snapshot_meta_path = self.data_dir / "account_snapshot_meta.json"

    def exists(self) -> bool:
        return self.snapshot_path.exists()

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.exists():
            return None

        with self.snapshot_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def load_meta(self) -> Dict[str, Any]:
        if not self.snapshot_meta_path.exists():
            return {}
        try:
            raw = json.loads(self.snapshot_meta_path.read_text(encoding="utf-8"))
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
        if self.exists():
            self.snapshot_path.unlink()
        if self.snapshot_meta_path.exists():
            self.snapshot_meta_path.unlink()
