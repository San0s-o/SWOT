from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============================================================
# Sets
# ============================================================
# Summoners War: Set sizes (2-set vs 4-set)
# IDs basieren auf den üblichen SW-Set-IDs im Export.
SET_SIZES: dict[int, int] = {
    # 2-set
    1: 2,   # Energy
    2: 2,   # Guard
    4: 2,   # Blade
    6: 2,   # Focus
    7: 2,   # Endure
    14: 2,  # Nemesis
    15: 2,  # Will
    16: 2,  # Shield
    17: 2,  # Revenge
    18: 2,  # Destroy
    19: 2,  # Fight
    20: 2,  # Determination
    21: 2,  # Enhance
    22: 2,  # Accuracy
    23: 2,  # Tolerance

    # 4-set
    3: 4,   # Swift
    5: 4,   # Rage
    8: 4,   # Fatal
    10: 4,  # Despair
    11: 4,  # Vampire
    13: 4,  # Violent
    24: 2,  # Seal
    25: 4,  # Intangible
}

# Für UI: Set-Name
SET_NAMES: dict[int, str] = {
    1: "Energy",
    2: "Guard",
    3: "Swift",
    4: "Blade",
    5: "Rage",
    6: "Focus",
    7: "Endure",
    8: "Fatal",
    10: "Despair",
    11: "Vampire",
    13: "Violent",
    14: "Nemesis",
    15: "Will",
    16: "Shield",
    17: "Revenge",
    18: "Destroy",
    19: "Fight",
    20: "Determination",
    21: "Enhance",
    22: "Accuracy",
    23: "Tolerance",
    24: "Seal",
    25: "Intangible",
}

SET_ID_BY_NAME: dict[str, int] = {v: k for k, v in SET_NAMES.items()}


# ============================================================
# Rune Mainstat mapping (Export pri_eff[0] -> key)
# ============================================================
# In SW-Exports sind Effect-IDs relativ stabil. Falls dein Export abweicht,
# kann man dieses Mapping später zentral anpassen.
#
# "SW Lens"-artige Keys in UI/Config:
# "HP", "ATK", "DEF", "SPD", "CR", "CD", "RES", "ACC", "HP%", "ATK%", "DEF%"
EFFECT_ID_TO_MAINSTAT_KEY: dict[int, str] = {
    # SWEX rune stat IDs
    1: "HP",
    2: "HP%",
    3: "ATK",
    4: "ATK%",
    5: "DEF",
    6: "DEF%",
    8: "SPD",
    9: "CR",
    10: "CD",
    11: "RES",
    12: "ACC",
}

MAINSTAT_KEYS: list[str] = ["HP", "ATK", "DEF", "SPD", "CR", "CD", "RES", "ACC", "HP%", "ATK%", "DEF%"]

# Übliche Slot-Whitelist (UI-Defaults)
SLOT2_DEFAULT = ["SPD", "HP%", "ATK%", "DEF%"]
SLOT4_DEFAULT = ["HP%", "ATK%", "DEF%", "CR", "CD", "ACC", "RES"]
SLOT6_DEFAULT = ["HP%", "ATK%", "DEF%", "ACC", "RES"]


# ============================================================
# "SW Lens"-style Builds
# ============================================================
@dataclass
class Build:
    """
    SWLens-Style Build Template:
    - name + priority (smaller = preferred)
    - set_options: list of alternatives, each is a list of set names
      e.g. [["Despair", "Will"], ["Swift", "Will"]]
    - mainstats: allowed mainstat keys for slots 2/4/6
      e.g. {2:["SPD"], 4:["HP%","DEF%"], 6:["HP%"]}
    """
    id: str = "default"
    name: str = "Default"
    enabled: bool = True
    priority: int = 1
    optimize_order: int = 0
    turn_order: int = 0
    set_options: List[List[str]] = field(default_factory=list)
    mainstats: Dict[int, List[str]] = field(default_factory=dict)
    min_stats: Dict[str, int] = field(default_factory=dict)

    @staticmethod
    def default_any() -> "Build":
        return Build(
            id="any",
            name="Any",
            enabled=True,
            priority=999,
            set_options=[],
            mainstats={},
        )


@dataclass
class UnitBuildConfig:
    unit_id: int
    builds: List[Build] = field(default_factory=lambda: [Build.default_any()])


@dataclass
class ModeBuilds:
    # unit_id -> config
    by_unit_id: Dict[int, UnitBuildConfig] = field(default_factory=dict)


@dataclass
class BuildStore:
    """
    Datei: app/config/build_presets.json  (Name beibehalten für MVP)

    Schema (neu):
    {
      "version": "2026-02-07",
      "modes": {
        "siege": {"by_unit_id": {"123": {"builds": [ ... ]}}},
        "wgb": {...},
        "rta": {...}
      }
    }

    Migration (alt):
    {
      "modes": {
        "siege": {"by_unit_id": {"123": {"required_set_id": 17, "allow_broken": true}}}
      }
    }
    -> wird zu einem Build mit genau einer set_option [[SET_NAME]] und Mainstats = Any.
    """
    version: str = "2026-02-07"
    modes: Dict[str, ModeBuilds] = field(default_factory=lambda: {
        "siege": ModeBuilds(),
        "wgb": ModeBuilds(),
        "rta": ModeBuilds(),
    })

    # -----------------------------
    # I/O
    # -----------------------------
    @staticmethod
    def load(path: str | Path) -> "BuildStore":
        p = Path(path)
        if not p.exists():
            return BuildStore()

        raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        store = BuildStore()
        store.version = str(raw.get("version") or store.version)

        modes_raw = raw.get("modes") or {}
        for mode in ("siege", "wgb", "rta"):
            mr = modes_raw.get(mode) or {}
            mb = ModeBuilds()
            by = mr.get("by_unit_id") or {}

            # Detect old schema by presence of required_set_id
            is_old = False
            for _, v in by.items():
                if isinstance(v, dict) and "required_set_id" in v:
                    is_old = True
                    break

            if is_old:
                mb.by_unit_id = _migrate_old_by_unit_id(by)
            else:
                for k, v in by.items():
                    try:
                        uid = int(k)
                    except Exception:
                        continue
                    cfg = _parse_unit_build_config(uid, v)
                    if cfg is not None:
                        mb.by_unit_id[uid] = cfg

            store.modes[mode] = mb

        return store

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)

        out: Dict[str, Any] = {"version": self.version, "modes": {}}
        for mode, mb in self.modes.items():
            out["modes"][mode] = {"by_unit_id": {}}
            for uid, cfg in mb.by_unit_id.items():
                out["modes"][mode]["by_unit_id"][str(uid)] = {
                    "builds": [_build_to_json(b) for b in (cfg.builds or [])]
                }

        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # -----------------------------
    # Access
    # -----------------------------
    def get_unit_builds(self, mode: str, unit_id: int) -> List[Build]:
        mb = self.modes.get(mode)
        if not mb:
            return [Build.default_any()]
        cfg = mb.by_unit_id.get(unit_id)
        if not cfg or not cfg.builds:
            return [Build.default_any()]
        enabled = [b for b in cfg.builds if b.enabled]
        return enabled if enabled else [Build.default_any()]

    def set_unit_builds(self, mode: str, unit_id: int, builds: List[Build]) -> None:
        if mode not in self.modes:
            self.modes[mode] = ModeBuilds()
        self.modes[mode].by_unit_id[unit_id] = UnitBuildConfig(unit_id=unit_id, builds=builds)


# ============================================================
# Parsing helpers
# ============================================================
def _build_to_json(b: Build) -> Dict[str, Any]:
    return {
        "id": b.id,
        "name": b.name,
        "enabled": bool(b.enabled),
        "priority": int(b.priority),
        "optimize_order": int(b.optimize_order),
        "turn_order": int(b.turn_order),
        "set_options": b.set_options or [],
        "mainstats": {str(k): (v or []) for k, v in (b.mainstats or {}).items()},
        "min_stats": {str(k): int(v) for k, v in (b.min_stats or {}).items()},
    }


def _parse_build(raw: Any) -> Optional[Build]:
    if not isinstance(raw, dict):
        return None
    bid = str(raw.get("id") or "build")
    name = str(raw.get("name") or bid)
    enabled = bool(raw.get("enabled", True))
    try:
        priority = int(raw.get("priority") or 1)
    except Exception:
        priority = 1
    try:
        optimize_order = int(raw.get("optimize_order") or 0)
    except Exception:
        optimize_order = 0
    try:
        turn_order = int(raw.get("turn_order") or 0)
    except Exception:
        turn_order = 0

    set_options_raw = raw.get("set_options") or []
    set_options: List[List[str]] = []
    if isinstance(set_options_raw, list):
        for opt in set_options_raw:
            if isinstance(opt, list):
                names = [str(x) for x in opt if str(x)]
                if names:
                    set_options.append(names)

    mainstats_raw = raw.get("mainstats") or {}
    mainstats: Dict[int, List[str]] = {}
    if isinstance(mainstats_raw, dict):
        for k, v in mainstats_raw.items():
            try:
                slot = int(k)
            except Exception:
                continue
            if slot not in (2, 4, 6):
                continue
            if isinstance(v, list):
                keys = [str(x) for x in v if str(x)]
                if keys:
                    mainstats[slot] = keys

    min_stats_raw = raw.get("min_stats") or {}
    min_stats: Dict[str, int] = {}
    if isinstance(min_stats_raw, dict):
        for k, v in min_stats_raw.items():
            key = str(k).strip().upper()
            if key not in ("SPD", "CR", "CD", "RES", "ACC"):
                continue
            try:
                val = int(v)
            except Exception:
                continue
            if val > 0:
                min_stats[key] = val

    return Build(
        id=bid,
        name=name,
        enabled=enabled,
        priority=priority,
        optimize_order=optimize_order,
        turn_order=turn_order,
        set_options=set_options,
        mainstats=mainstats,
        min_stats=min_stats,
    )


def _parse_unit_build_config(unit_id: int, raw: Any) -> Optional[UnitBuildConfig]:
    if not isinstance(raw, dict):
        return None
    builds_raw = raw.get("builds") or []
    builds: List[Build] = []
    if isinstance(builds_raw, list):
        for b in builds_raw:
            bb = _parse_build(b)
            if bb is not None:
                builds.append(bb)
    if not builds:
        builds = [Build.default_any()]
    return UnitBuildConfig(unit_id=unit_id, builds=builds)


def _migrate_old_by_unit_id(old_by: Dict[str, Any]) -> Dict[int, UnitBuildConfig]:
    """
    Alt: {"123": {"required_set_id": 17, "allow_broken": true}}
    Neu: 1 Build mit set_option auf [<SetName>] (bzw. leer bei 0)
    """
    out: Dict[int, UnitBuildConfig] = {}
    for k, v in (old_by or {}).items():
        try:
            uid = int(k)
        except Exception:
            continue
        if not isinstance(v, dict):
            continue
        req_set_id = int(v.get("required_set_id") or 0)

        set_options: List[List[str]] = []
        if req_set_id != 0 and req_set_id in SET_NAMES:
            # "Pflichtset" im alten Sinne: mindestens set_size dieses Sets, rest egal.
            set_options = [[SET_NAMES[req_set_id]]]

        b = Build(
            id="migrated",
            name="Migrated",
            enabled=True,
            priority=1,
            set_options=set_options,
            mainstats={},  # Any
        )
        out[uid] = UnitBuildConfig(unit_id=uid, builds=[b])
    return out
