from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class Team:
    id: str
    name: str
    unit_ids: List[int] = field(default_factory=list)


@dataclass
class TeamStore:
    version: str = "2026-02-07"
    teams: Dict[str, Team] = field(default_factory=dict)

    @staticmethod
    def load(path: str | Path) -> "TeamStore":
        p = Path(path)
        if not p.exists():
            return TeamStore()

        raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        store = TeamStore()
        store.version = str(raw.get("version") or store.version)

        teams_raw = (raw.get("teams") or {}) if isinstance(raw, dict) else {}
        for tid, data in teams_raw.items():
            if not isinstance(data, dict):
                continue
            name = str(data.get("name") or "").strip() or f"Team {tid}"
            units_raw = data.get("unit_ids") or []
            if not isinstance(units_raw, list):
                continue
            units = []
            for uid in units_raw:
                try:
                    uid_int = int(uid)
                except Exception:
                    continue
                if uid_int != 0 and uid_int not in units:
                    units.append(uid_int)
            if not units:
                continue
            store.teams[str(tid)] = Team(id=str(tid), name=name, unit_ids=units)
        return store

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        out: Dict[str, Any] = {"version": self.version, "teams": {}}
        for tid, team in self.teams.items():
            out["teams"][tid] = {"name": team.name, "unit_ids": team.unit_ids}
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, name: str, unit_ids: List[int], tid: Optional[str] = None) -> Team:
        seen = set()
        cleaned: List[int] = []
        for raw in unit_ids:
            try:
                uid = int(raw)
            except Exception:
                continue
            if uid == 0 or uid in seen:
                continue
            seen.add(uid)
            cleaned.append(uid)
        if not cleaned:
            raise ValueError("Team needs at least one unit.")
        key = tid or str(uuid.uuid4())
        team = Team(id=key, name=name.strip() or "Unnamed Team", unit_ids=cleaned)
        self.teams[key] = team
        return team

    def remove(self, tid: str) -> None:
        if tid in self.teams:
            del self.teams[tid]
