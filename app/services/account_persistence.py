from __future__ import annotations

import json
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

    def exists(self) -> bool:
        return self.snapshot_path.exists()

    def load(self) -> Optional[Dict[str, Any]]:
        if not self.exists():
            return None

        with self.snapshot_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def save(self, raw_json: Dict[str, Any]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)

        tmp = self.snapshot_path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(raw_json, f, ensure_ascii=False)

        tmp.replace(self.snapshot_path)

    def clear(self) -> None:
        if self.exists():
            self.snapshot_path.unlink()