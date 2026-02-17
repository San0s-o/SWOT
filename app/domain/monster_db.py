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
    turn_effect_capabilities: Dict[str, int | bool] | None = None


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
          "leader_skill": {"stat": "ATK%", "amount": 33, "area": "Arena"},
          "turn_effect_capabilities": {"has_spd_buff": false, "has_atb_boost": true, "max_atb_boost_pct": 30}
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
                    turn_effect_capabilities=self._parse_turn_effect_capabilities(m),
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

    def turn_effect_capability_for(self, com2us_id: int) -> Dict[str, int | bool]:
        info = self.get(com2us_id)
        if not info:
            return {"has_spd_buff": False, "has_atb_boost": False, "max_atb_boost_pct": 0}
        raw = dict(info.turn_effect_capabilities or {})
        return {
            "has_spd_buff": bool(raw.get("has_spd_buff", False)),
            "has_atb_boost": bool(raw.get("has_atb_boost", False)),
            "max_atb_boost_pct": int(raw.get("max_atb_boost_pct", 0) or 0),
        }

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
        if not stat:
            attr = str(ls.get("attribute") or "").strip().lower()
            attr_to_stat = {
                "attack speed": "SPD%",
                "attack power": "ATK%",
                "attack": "ATK%",
                "defense": "DEF%",
                "def": "DEF%",
                "hp": "HP%",
                "critical rate": "CR%",
                "critical damage": "CD%",
                "resistance": "RES%",
                "accuracy": "ACC%",
            }
            stat = str(attr_to_stat.get(attr, "") or "")
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

    @staticmethod
    def _parse_turn_effect_capabilities(raw: Dict[str, Any]) -> Dict[str, int | bool]:
        data = raw.get("turn_effect_capabilities")
        if not isinstance(data, dict):
            data = raw.get("turn_effects")
        if not isinstance(data, dict):
            data = raw
        has_spd_buff = bool(data.get("has_spd_buff", False))
        has_atb_boost = bool(data.get("has_atb_boost", False))
        max_atb = int(data.get("max_atb_boost_pct", 0) or 0)
        if has_atb_boost and max_atb <= 0:
            max_atb = 100
        return {
            "has_spd_buff": has_spd_buff,
            "has_atb_boost": has_atb_boost,
            "max_atb_boost_pct": max(0, int(max_atb)),
        }
