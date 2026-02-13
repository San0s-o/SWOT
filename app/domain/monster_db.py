from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Any


@dataclass(frozen=True)
class LeaderSkill:
    stat: str       # "HP%", "ATK%", "DEF%", "SPD%", "CR%", "CD%", "RES%", "ACC%"
    amount: int     # percentage value
    area: str       # "General", "Arena", "Guild", "Dungeon", "Element"
    element: str    # only for area=="Element", e.g. "Fire"; otherwise ""


@dataclass(frozen=True)
class MonsterInfo:
    com2us_id: int
    name: str
    element: str            # Fire/Wind/Water/Light/Dark/Unknown
    icon: str               # relative path like "icons/13403.png" or ""
    leader_skill: Optional[LeaderSkill] = None


class MonsterDB:
    """
    Offline Monster DB:
      app/assets/monsters.json

    Schema:
    {
      "version": "2026-02-08",
      "monsters": [
        {
          "com2us_id": 13403, "name": "Lushen", "element": "Wind",
          "icon": "icons/13403.png",
          "leader_skill": {"stat": "ATK%", "amount": 33, "area": "Arena"}
        },
        ...
      ]
    }
    """
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self._by_id: Dict[int, MonsterInfo] = {}

    def load(self) -> None:
        self._by_id = {}
        if not self.db_path.exists():
            return
        raw = json.loads(self.db_path.read_text(encoding="utf-8", errors="replace"))
        for m in raw.get("monsters", []) or []:
            try:
                mid = int(m.get("com2us_id") or 0)
                if mid <= 0:
                    continue
                ls = self._parse_leader_skill(m)
                info = MonsterInfo(
                    com2us_id=mid,
                    name=str(m.get("name") or "").strip() or f"#{mid}",
                    element=str(m.get("element") or "Unknown").strip() or "Unknown",
                    icon=str(m.get("icon") or "").strip(),
                    leader_skill=ls,
                )
                self._by_id[mid] = info
            except Exception:
                continue

    def get(self, com2us_id: int) -> Optional[MonsterInfo]:
        return self._by_id.get(int(com2us_id))

    def name_for(self, com2us_id: int) -> str:
        info = self.get(com2us_id)
        return info.name if info else f"#{com2us_id}"

    def element_for(self, com2us_id: int) -> str:
        info = self.get(com2us_id)
        return info.element if info else "Unknown"

    def icon_path_for(self, com2us_id: int) -> str:
        info = self.get(com2us_id)
        return info.icon if info else ""

    def leader_skill_for(self, com2us_id: int) -> Optional[LeaderSkill]:
        info = self.get(com2us_id)
        return info.leader_skill if info else None

    def speed_lead_percent_for(self, com2us_id: int) -> int:
        ls = self.leader_skill_for(com2us_id)
        if ls and ls.stat == "SPD%":
            return ls.amount
        return 0

    def rta_speed_lead_percent_for(self, com2us_id: int) -> int:
        """SPD lead % that applies in RTA (General or Arena area only)."""
        ls = self.leader_skill_for(com2us_id)
        if ls and ls.stat == "SPD%" and ls.area in ("General", "Arena"):
            return ls.amount
        return 0

    @staticmethod
    def _parse_leader_skill(raw: Dict[str, Any]) -> Optional[LeaderSkill]:
        ls = raw.get("leader_skill")
        if not ls or not isinstance(ls, dict):
            return None
        stat = str(ls.get("stat") or "").strip()
        amount = 0
        try:
            amount = max(0, int(ls.get("amount") or 0))
        except Exception:
            pass
        if not stat or amount <= 0:
            return None
        area = str(ls.get("area") or "General").strip()
        element = str(ls.get("element") or "").strip()
        return LeaderSkill(stat=stat, amount=amount, area=area, element=element)
