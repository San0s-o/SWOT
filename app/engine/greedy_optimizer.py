from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from functools import lru_cache
import json
from pathlib import Path
import threading
from typing import Dict, List, Tuple, Set, Optional, Callable, Any

from ortools.sat.python import cp_model

from app.domain.artifact_effects import artifact_effect_is_legacy, ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE
from app.domain.models import AccountData, Rune, Artifact
from app.domain.speed_ticks import min_spd_for_tick, max_spd_for_tick
from app.engine.efficiency import rune_efficiency, artifact_efficiency
from app.domain.presets import (
    BuildStore,
    Build,
    SET_ID_BY_NAME,
    SET_SIZES,
    EFFECT_ID_TO_MAINSTAT_KEY,
)
from app.i18n import tr

STAT_SCORE_WEIGHTS: Dict[int, int] = {
    1: 1,   # HP flat
    2: 8,   # HP%
    3: 1,   # ATK flat
    4: 8,   # ATK%
    5: 1,   # DEF flat
    6: 8,   # DEF%
    8: 18,  # SPD
    9: 10,  # CR
    10: 9,  # CD
    11: 4,  # RES
    12: 4,  # ACC
}

DEFENSIVE_STAT_SCORE_WEIGHTS: Dict[int, int] = {
    1: 3,    # HP flat
    2: 18,   # HP%
    3: -4,   # ATK flat
    4: -10,  # ATK%
    5: 3,    # DEF flat
    6: 18,   # DEF%
    8: 10,   # SPD
    9: -8,   # CR
    10: -8,  # CD
    11: 16,  # RES
    12: 8,   # ACC
}

SET_SCORE_BONUS: Dict[int, int] = {
    3: 160,   # Swift
    13: 140,  # Violent
    15: 90,   # Will
    10: 80,   # Despair
    17: 70,   # Revenge
    11: 70,   # Vampire
    5: 60,    # Rage
    8: 60,    # Fatal
}

# Penalty weight for excessive turn-order speed gaps during multi-pass selection.
# Applied on squared excess above the minimum legal gap (1 SPD).
TURN_ORDER_GAP_PENALTY_WEIGHT = 35
INTANGIBLE_SET_ID = 25
ARTIFACT_BONUS_FOR_SAME_UNIT = 60
ARTIFACT_BUILD_FOCUS_BONUS = 35
ARTIFACT_BUILD_MATCH_BONUS = 140
ARTIFACT_BUILD_VALUE_WEIGHT = 6
DEFAULT_BUILD_PRIORITY_PENALTY = 200
SOFT_SPEED_WEIGHT = 24
SET_OPTION_PREFERENCE_BONUS = 120
REFINE_SAME_RUNE_PENALTY = 260
REFINE_SAME_ARTIFACT_PENALTY = 180
DEFAULT_SPEED_SLACK_FOR_QUALITY = 1
RUNE_EFFICIENCY_WEIGHT_SOLVER = 6
ARTIFACT_EFFICIENCY_WEIGHT_SOLVER = 5
PASS_EFFICIENCY_WEIGHT = 10
ARENA_RUSH_ATK_EFFICIENCY_SCALE = 45
ARENA_RUSH_ATK_RUNE_EFF_WEIGHT = 2
ARENA_RUSH_ATK_ART_EFF_WEIGHT = 2
ARENA_RUSH_DEF_EFFICIENCY_SCALE = 1
ARENA_RUSH_DEF_QUALITY_WEIGHT = 4
ARENA_RUSH_DEF_RUNE_WEIGHT = 3
ARENA_RUSH_DEF_ART_WEIGHT = 3
ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT = 2
STAT_OVERCAP_LIMIT = 100
CR_OVERCAP_PENALTY_PER_POINT = 20
RES_OVERCAP_PENALTY_PER_POINT = 16
ACC_OVERCAP_PENALTY_PER_POINT = 16
SINGLE_SOLVER_OVERCAP_PENALTY_SCALE = 10
BASELINE_REGRESSION_GUARD_WEIGHT = 1200
ARTIFACT_ROLE_CONTEXT_WEIGHT = 4
ARTIFACT_HINT_BOMB_VALUE_WEIGHT = 12
ARTIFACT_HINT_SKILL_MATCH_BONUS = 180
ARTIFACT_HINT_SKILL_MISMATCH_PENALTY = 120
ARTIFACT_HINT_ACC_MATCH_BONUS = 110
ARTIFACT_HINT_RECOVERY_MATCH_BONUS = 95
ARTIFACT_HINT_SKILL_PREFERRED_BONUS = 90
ARTIFACT_HINT_ACC_PREFERRED_BONUS = 70
ARTIFACT_HINT_RECOVERY_PREFERRED_BONUS = 70
ARTIFACT_HINT_EFFECT_MATCH_BONUS = 130
ARTIFACT_HINT_EFFECT_VALUE_WEIGHT = 6
ARTIFACT_HINT_SPD_EFFECT_WITHOUT_TEAM_BUFF_PENALTY = 900
ARTIFACT_HINT_SPD_EFFECT_WITHOUT_TEAM_BUFF_VALUE_WEIGHT = 80
ARTIFACT_HINT_TOP1_MATCH_BONUS = 320
ARTIFACT_HINT_TOP2_MATCH_BONUS = 240
ARTIFACT_HINT_TOP3_MATCH_BONUS = 170
ARTIFACT_HINT_TOP4_MATCH_BONUS = 120
ARTIFACT_HINT_TOP1_VALUE_WEIGHT = 11
ARTIFACT_HINT_TOP2_VALUE_WEIGHT = 9
ARTIFACT_HINT_TOP3_VALUE_WEIGHT = 7
ARTIFACT_HINT_TOP4_VALUE_WEIGHT = 5
ARTIFACT_HINT_TOP1_MISS_PENALTY = 700
ARTIFACT_HINT_TOP2_MISS_PENALTY = 520
ARTIFACT_HINT_TOP3_MISS_PENALTY = 120
ARTIFACT_HINT_TOP4_MISS_PENALTY = 80
ARTIFACT_ATTACK_MAINSTAT_MATCH_BONUS = 180
ARTIFACT_ATTACK_MAINSTAT_MISS_PENALTY = 300
ARTIFACT_DEFENSE_MAINSTAT_MATCH_BONUS = 140
ARTIFACT_HP_MAINSTAT_MATCH_BONUS = 150
ARTIFACT_SUPPORT_MAINSTAT_MATCH_BONUS = 130
ARTIFACT_NON_ATTACK_ATK_MAINSTAT_MISS_PENALTY = 320
ARTIFACT_HINT_CRITICAL_MATCH_BONUS_BY_RANK = [1400, 950, 700, 520]
ARTIFACT_HINT_CRITICAL_MISSING_PENALTY_BY_RANK = [26000, 17000, 9000, 5000]
ARTIFACT_HINT_ADDITIONAL_DAMAGE_VALUE_FACTOR = 0.06
ARTIFACT_HINT_HIGH_ROLL_MIN = 2
ARTIFACT_HINT_HIGH_ROLL_BONUS_PER_ROLL = 160
ARTIFACT_HINT_HIGH_ROLL_BONUS_MAX = 640
ARTIFACT_HINT_TOP_EFFECT_COUNT = 4
ARTIFACT_HINT_CRITICAL_TARGET_COUNT_BY_RANK = [2, 1, 1, 1]
ARTIFACT_HINT_CRITICAL_HIT_BONUS_PER_COUNT_BY_RANK = [3200, 1400, 900, 600]
ARTIFACT_HINT_CRITICAL_SHORTFALL_PENALTY_BY_RANK = [22000, 9000, 6000, 4000]
ARTIFACT_HINT_CRITICAL_TARGET_ROLL_SUM_BY_RANK = [4, 2, 2, 2]
ARTIFACT_HINT_CRITICAL_ROLL_BONUS_PER_ROLL_BY_RANK = [1800, 1100, 700, 450]
ARTIFACT_HINT_CRITICAL_ROLL_SHORTFALL_PENALTY_BY_RANK = [12000, 7000, 4500, 2800]
RUNE_SCALING_BONUS_WEIGHT = 3
ARTIFACT_SCALING_BONUS_WEIGHT = 4

_ARTIFACT_SCORING_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "artifact_scoring.json"
_RUNE_SET_PREFERENCES_PATH = Path(__file__).resolve().parents[1] / "config" / "monster_rune_set_preferences.json"
_ARTIFACT_PROFILE_KEYS = {"attack", "defense", "hp", "support", "unknown"}
_ADDITIONAL_DAMAGE_EFFECT_IDS = {218, 219, 220, 221}
_ARTIFACT_ALLOWED_EFFECT_IDS_BY_TYPE: Dict[int, Set[int]] = {
    1: {int(x) for x in (ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE.get(1) or []) if int(x) > 0},
    2: {int(x) for x in (ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE.get(2) or []) if int(x) > 0},
}
_VALID_SET_IDS = set(int(x) for x in SET_ID_BY_NAME.values())
_RUNE_SET_HINT_PIECE_BONUS_BY_RANK = [35, 24, 16]
_RUNE_SET_HINT_FULL_BONUS_BY_RANK = [210, 150, 95]
_ROLE_DEFAULT_RUNE_SET_IDS: Dict[str, List[int]] = {
    "attack": [13, 15, 3, 5, 8, 4],       # Violent/Will/Swift/Rage/Fatal/Blade
    "defense": [13, 15, 17, 18, 10, 3],   # Violent/Will/Revenge/Destroy/Despair/Swift
    "hp": [13, 15, 17, 18, 10, 3],        # Violent/Will/Revenge/Destroy/Despair/Swift
    "support": [13, 15, 3, 10, 17, 16],   # Violent/Will/Swift/Despair/Revenge/Shield
    "unknown": [13, 15, 3, 10, 17, 8],    # balanced fallback
}
_ADDITIONAL_DAMAGE_VALUE_SCALE = 1.0
_ADDITIONAL_DAMAGE_PERCENT_REFERENCE: Dict[int, float] = {
    218: 20.0,  # Additional Damage by HP%
    219: 8.0,   # Additional Damage by ATK%
    220: 8.0,   # Additional Damage by DEF%
    221: 80.0,  # Additional Damage by SPD%
}

_DEFAULT_ARTIFACT_SCORING_CONFIG: Dict[str, Any] = {
    "legacy_multiplier": 0.72,
    "additional_damage_baseline": {
        "218": 12000.0,  # HP
        "219": 850.0,    # ATK
        "220": 700.0,    # DEF
        "221": 100.0,    # SPD
    },
    "additional_damage_factor_min": 0.70,
    "additional_damage_factor_max": 2.00,
    "profiles": {
        "attack": {
            "main_focus": {"HP": 15, "ATK": 130, "DEF": 10},
            "effects": {
                "204": 16, "210": 12, "212": 12, "222": 12, "223": 12, "224": 13, "225": 12,
                "300": 11, "301": 11, "302": 11, "303": 11, "304": 11,
                "400": 15, "401": 15, "402": 15, "403": 15, "410": 15, "411": 12,
                "218": 18, "219": 26, "220": 16, "221": 18,
                "206": 5, "407": 5, "408": 5, "409": 5,
            },
        },
        "defense": {
            "main_focus": {"HP": 95, "ATK": -110, "DEF": 140},
            "effects": {
                "201": 14, "205": 14, "226": 13,
                "213": 13, "214": 13, "305": 12, "306": 12, "307": 12, "308": 12, "309": 12,
                "404": 8, "405": 8, "406": 8,
                "206": 8, "203": 8,
                "218": 8, "219": 4, "220": 10, "221": 8,
                "407": 5, "408": 5, "409": 5,
            },
        },
        "hp": {
            "main_focus": {"HP": 145, "ATK": -110, "DEF": 90},
            "effects": {
                "201": 12, "205": 10, "226": 11,
                "213": 13, "214": 12, "305": 12, "306": 12, "307": 12, "308": 12, "309": 12,
                "404": 9, "405": 9, "406": 9,
                "206": 8, "203": 8,
                "218": 14, "219": 5, "220": 8, "221": 8,
                "407": 6, "408": 6, "409": 6,
            },
        },
        "support": {
            "main_focus": {"HP": 125, "ATK": -120, "DEF": 125},
            "effects": {
                "201": 10, "205": 10, "226": 10,
                "213": 15, "214": 15, "305": 14, "306": 14, "307": 14, "308": 14, "309": 14,
                "404": 14, "405": 14, "406": 13,
                "206": 12, "203": 10,
                "218": 10, "219": 3, "220": 8, "221": 9,
                "407": 12, "408": 12, "409": 12,
            },
        },
        "unknown": {
            "main_focus": {"HP": 25, "ATK": 25, "DEF": 25},
            "effects": {
                "201": 8, "205": 8, "226": 8,
                "203": 6, "206": 7,
                "210": 6, "212": 6, "222": 7, "223": 7, "224": 8, "225": 7,
                "300": 7, "301": 7, "302": 7, "303": 7, "304": 7,
                "305": 7, "306": 7, "307": 7, "308": 7, "309": 7,
                "400": 8, "401": 8, "402": 8, "403": 8, "410": 8, "411": 7,
                "404": 7, "405": 7, "406": 7,
                "407": 7, "408": 7, "409": 7,
                "218": 10, "219": 10, "220": 10, "221": 10,
            },
        },
    },
}

# Artifact main focus mapping (HP/ATK/DEF).
# Supports both rune-like stat IDs and commonly seen artifact main IDs.
_ARTIFACT_FOCUS_BY_EFFECT_ID: Dict[int, str] = {
    1: "HP",
    2: "HP",
    3: "ATK",
    4: "ATK",
    5: "DEF",
    6: "DEF",
    100: "HP",
    101: "ATK",
    102: "DEF",
}


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _clamp_float(value: float, lo: float, hi: float) -> float:
    return max(float(lo), min(float(hi), float(value)))


def _new_profile_template() -> Dict[str, Dict[Any, float]]:
    return {
        "main_focus": {"HP": 0.0, "ATK": 0.0, "DEF": 0.0},
        "effects": {},
    }


def _default_artifact_scoring_copy() -> Dict[str, Any]:
    src = dict(_DEFAULT_ARTIFACT_SCORING_CONFIG or {})
    profiles_src = dict(src.get("profiles") or {})
    profiles: Dict[str, Dict[str, Dict[Any, float]]] = {}
    for key in _ARTIFACT_PROFILE_KEYS:
        psrc = dict(profiles_src.get(key) or {})
        p = _new_profile_template()
        for focus, val in dict(psrc.get("main_focus") or {}).items():
            f = str(focus).upper()
            if f in ("HP", "ATK", "DEF"):
                p["main_focus"][f] = _to_float(val, p["main_focus"].get(f, 0.0))
        for eid, weight in dict(psrc.get("effects") or {}).items():
            ei = _to_int(eid, 0)
            if ei > 0:
                p["effects"][ei] = _to_float(weight, 0.0)
        profiles[key] = p
    return {
        "legacy_multiplier": _to_float(src.get("legacy_multiplier"), 1.0),
        "additional_damage_baseline": {
            int(_to_int(k, 0)): _to_float(v, 0.0)
            for k, v in dict(src.get("additional_damage_baseline") or {}).items()
            if int(_to_int(k, 0)) in _ADDITIONAL_DAMAGE_EFFECT_IDS
        },
        "additional_damage_factor_min": _to_float(src.get("additional_damage_factor_min"), 0.7),
        "additional_damage_factor_max": _to_float(src.get("additional_damage_factor_max"), 2.0),
        "profiles": profiles,
    }


@lru_cache(maxsize=1)
def _artifact_scoring_config() -> Dict[str, Any]:
    cfg = _default_artifact_scoring_copy()
    p = Path(_ARTIFACT_SCORING_CONFIG_PATH)
    if not p.exists():
        return cfg
    try:
        raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return cfg
    if not isinstance(raw, dict):
        return cfg

    cfg["legacy_multiplier"] = _to_float(raw.get("legacy_multiplier"), cfg["legacy_multiplier"])
    cfg["additional_damage_factor_min"] = _to_float(
        raw.get("additional_damage_factor_min"),
        cfg["additional_damage_factor_min"],
    )
    cfg["additional_damage_factor_max"] = _to_float(
        raw.get("additional_damage_factor_max"),
        cfg["additional_damage_factor_max"],
    )
    if float(cfg["additional_damage_factor_min"]) > float(cfg["additional_damage_factor_max"]):
        cfg["additional_damage_factor_min"], cfg["additional_damage_factor_max"] = (
            cfg["additional_damage_factor_max"],
            cfg["additional_damage_factor_min"],
        )

    baseline_raw = raw.get("additional_damage_baseline")
    if isinstance(baseline_raw, dict):
        for eid, val in baseline_raw.items():
            ei = int(_to_int(eid, 0))
            if ei in _ADDITIONAL_DAMAGE_EFFECT_IDS:
                cfg["additional_damage_baseline"][ei] = _to_float(val, cfg["additional_damage_baseline"].get(ei, 0.0))

    profiles_raw = raw.get("profiles")
    if isinstance(profiles_raw, dict):
        for role_raw, role_cfg in profiles_raw.items():
            role = _arena_role_from_archetype(str(role_raw or ""))
            if role not in _ARTIFACT_PROFILE_KEYS:
                continue
            if not isinstance(role_cfg, dict):
                continue
            dest = cfg["profiles"].setdefault(role, _new_profile_template())
            main_raw = role_cfg.get("main_focus")
            if isinstance(main_raw, dict):
                for focus, val in main_raw.items():
                    f = str(focus).upper()
                    if f in ("HP", "ATK", "DEF"):
                        dest["main_focus"][f] = _to_float(val, dest["main_focus"].get(f, 0.0))
            effects_raw = role_cfg.get("effects")
            if isinstance(effects_raw, dict):
                for eid, weight in effects_raw.items():
                    ei = int(_to_int(eid, 0))
                    if ei > 0:
                        dest["effects"][ei] = _to_float(weight, 0.0)

    return cfg


@lru_cache(maxsize=1)
def _rune_set_preferences_config() -> Dict[int, List[int]]:
    out: Dict[int, List[int]] = {}
    p = Path(_RUNE_SET_PREFERENCES_PATH)
    if not p.exists():
        return out
    try:
        raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return out
    if not isinstance(raw, dict):
        return out
    by_id = raw.get("by_com2us_id", raw)
    if not isinstance(by_id, dict):
        return out

    for mid_raw, entry_raw in dict(by_id or {}).items():
        try:
            mid = int(mid_raw or 0)
        except Exception:
            continue
        if mid <= 0 or not isinstance(entry_raw, dict):
            continue
        entry = dict(entry_raw or {})
        base_stars = int(_to_int(entry.get("base_stars"), 0))
        awaken_level = int(_to_int(entry.get("awaken_level"), 1))
        if base_stars > 0 and base_stars <= 1:
            continue
        if awaken_level <= 0:
            continue

        ordered: List[int] = []
        for k in ("top_set_ids", "preferred_set_ids"):
            for x in (entry.get(k) or []):
                sid = int(_to_int(x, 0))
                if sid > 0 and sid in _VALID_SET_IDS and sid not in ordered:
                    ordered.append(int(sid))
                    if len(ordered) >= 6:
                        break
            if len(ordered) >= 6:
                break
        for x in (entry.get("top_set_names") or []):
            sid = int(_to_int(SET_ID_BY_NAME.get(str(x) or "", 0), 0))
            if sid > 0 and sid in _VALID_SET_IDS and sid not in ordered:
                ordered.append(int(sid))
                if len(ordered) >= 6:
                    break
        for x in (entry.get("preferred_set_names") or []):
            sid = int(_to_int(SET_ID_BY_NAME.get(str(x) or "", 0), 0))
            if sid > 0 and sid in _VALID_SET_IDS and sid not in ordered:
                ordered.append(int(sid))
                if len(ordered) >= 6:
                    break
        if ordered:
            out[int(mid)] = ordered[:6]
    return out


def _preferred_rune_set_ids_for_monster(com2us_id: int, role: str = "") -> List[int]:
    out: List[int] = []
    mid = int(com2us_id or 0)
    cfg = _rune_set_preferences_config()
    if mid > 0:
        out.extend(int(x) for x in (cfg.get(int(mid), []) or []) if int(x) in _VALID_SET_IDS)
    role_key = _arena_role_from_archetype(role)
    defaults = list(_ROLE_DEFAULT_RUNE_SET_IDS.get(str(role_key), _ROLE_DEFAULT_RUNE_SET_IDS["unknown"]))
    if not out:
        out = defaults
    else:
        for sid in defaults:
            if int(sid) not in out:
                out.append(int(sid))
    dedup: List[int] = []
    for sid in out:
        si = int(sid or 0)
        if si > 0 and si in _VALID_SET_IDS and si not in dedup:
            dedup.append(si)
    return dedup[:6]


def _artifact_scaled_effect_value(
    effect_id: int,
    raw_value: float,
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
    base_spd: int = 0,
) -> float:
    eid = int(effect_id or 0)
    val = max(0.0, float(raw_value or 0.0))
    if eid not in _ADDITIONAL_DAMAGE_EFFECT_IDS:
        return val

    cfg = _artifact_scoring_config()
    baseline_map: Dict[int, float] = dict(cfg.get("additional_damage_baseline") or {})
    baseline = float(baseline_map.get(eid, 0.0) or 0.0)
    factor_min = float(cfg.get("additional_damage_factor_min", 0.7))
    factor_max = float(cfg.get("additional_damage_factor_max", 2.0))
    if factor_min > factor_max:
        factor_min, factor_max = factor_max, factor_min

    stat_value = 0.0
    if eid == 218:
        stat_value = float(max(0, int(base_hp or 0)))
    elif eid == 219:
        stat_value = float(max(0, int(base_atk or 0)))
    elif eid == 220:
        stat_value = float(max(0, int(base_def or 0)))
    elif eid == 221:
        stat_value = float(max(0, int(base_spd or 0)))

    stat_factor = 1.0
    if baseline > 0.0 and stat_value > 0.0:
        stat_factor = _clamp_float(float(stat_value) / float(baseline), factor_min, factor_max)
    # Normalize additional-damage lines so different formulas are comparable:
    # SPD lines have much larger raw numbers than ATK/DEF/HP lines.
    ref = float(_ADDITIONAL_DAMAGE_PERCENT_REFERENCE.get(eid, 10.0) or 10.0)
    if ref <= 0.0:
        ref = 10.0
    normalized = (float(val) / float(ref)) * 10.0
    return float(normalized * float(_ADDITIONAL_DAMAGE_VALUE_SCALE) * stat_factor)


def _artifact_profile_score(
    art: Artifact,
    role: str = "unknown",
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
    base_spd: int = 0,
) -> int:
    cfg = _artifact_scoring_config()
    role_key = str(role or "").strip().lower()
    profiles: Dict[str, Dict[str, Dict[Any, float]]] = dict(cfg.get("profiles") or {})
    profile = profiles.get(role_key) or profiles.get("unknown") or _new_profile_template()

    score = 0.0
    focus_key = str(_artifact_focus_key(art) or "").upper()
    if focus_key:
        score += float((profile.get("main_focus") or {}).get(focus_key, 0.0))
    if role_key == "attack":
        if focus_key == "ATK":
            score += float(ARTIFACT_ATTACK_MAINSTAT_MATCH_BONUS)
        elif focus_key in ("HP", "DEF"):
            score -= float(ARTIFACT_ATTACK_MAINSTAT_MISS_PENALTY)
    elif role_key == "defense":
        if focus_key == "ATK":
            score -= float(ARTIFACT_NON_ATTACK_ATK_MAINSTAT_MISS_PENALTY)
        elif focus_key == "DEF":
            score += float(ARTIFACT_DEFENSE_MAINSTAT_MATCH_BONUS)
        elif focus_key == "HP":
            score += float(int(ARTIFACT_DEFENSE_MAINSTAT_MATCH_BONUS * 0.45))
    elif role_key == "hp":
        if focus_key == "ATK":
            score -= float(ARTIFACT_NON_ATTACK_ATK_MAINSTAT_MISS_PENALTY)
        elif focus_key == "HP":
            score += float(ARTIFACT_HP_MAINSTAT_MATCH_BONUS)
        elif focus_key == "DEF":
            score += float(int(ARTIFACT_HP_MAINSTAT_MATCH_BONUS * 0.40))
    elif role_key == "support":
        if focus_key == "ATK":
            score -= float(ARTIFACT_NON_ATTACK_ATK_MAINSTAT_MISS_PENALTY)
        elif focus_key in ("HP", "DEF"):
            score += float(ARTIFACT_SUPPORT_MAINSTAT_MATCH_BONUS)

    legacy_mult = float(cfg.get("legacy_multiplier", 1.0))
    effect_weights: Dict[int, float] = dict(profile.get("effects") or {})
    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        try:
            eid = int(sec[0] or 0)
            val = float(sec[1] or 0)
        except Exception:
            continue
        weight = float(effect_weights.get(int(eid), 0.0))
        if weight == 0.0:
            continue
        scaled_val = _artifact_scaled_effect_value(
            int(eid),
            val,
            base_hp=base_hp,
            base_atk=base_atk,
            base_def=base_def,
            base_spd=base_spd,
        )
        line = float(weight) * float(scaled_val)
        if artifact_effect_is_legacy(int(eid)):
            line *= float(legacy_mult)
        score += float(line)
    return int(round(score))


def _skill_line_effect_id_for_slot(slot: int, kind: str) -> int:
    s = int(slot or 0)
    if s < 1 or s > 4:
        return 0
    if kind == "crit":
        return 399 + s
    if kind == "acc":
        # only skill 1..3 exist for ACC lines
        return 406 + s if s <= 3 else 0
    if kind == "recovery":
        # only skill 1..3 exist for Recovery lines
        return 403 + s if s <= 3 else 0
    return 0


def _artifact_hint_score(
    art: Artifact,
    hints: Dict[str, Any] | None = None,
) -> int:
    if not hints:
        return 0

    def _effect_allowed_for_artifact_type(effect_id: int, artifact_type: int) -> bool:
        eid = int(effect_id or 0)
        t = int(artifact_type or 0)
        if eid <= 0:
            return False
        if t in (1, 2):
            allowed = _ARTIFACT_ALLOWED_EFFECT_IDS_BY_TYPE.get(int(t), set())
            if allowed:
                return int(eid) in allowed
        return True

    def _hint_effect_ids_from_key(
        data: Dict[str, Any],
        key: str,
        limit: int = ARTIFACT_HINT_TOP_EFFECT_COUNT,
    ) -> List[int]:
        vals: List[int] = []
        seen: Set[int] = set()
        for x in (data.get(str(key)) or []):
            try:
                eid = int(x or 0)
            except Exception:
                continue
            if artifact_effect_is_legacy(int(eid)):
                continue
            if eid <= 0 or eid in seen:
                continue
            seen.add(int(eid))
            vals.append(int(eid))
            if len(vals) >= int(limit):
                break
        return vals

    art_type = int(getattr(art, "type_", 0) or 0)

    bomb_slots = {
        int(x)
        for x in (hints.get("bomb_slots") or [])
        if 1 <= int(x or 0) <= 4
    }
    guaranteed_crit_slots = {
        int(x)
        for x in (hints.get("guaranteed_crit_slots") or [])
        if 1 <= int(x or 0) <= 4
    }
    recovery_slots = {
        int(x)
        for x in (hints.get("recovery_slots") or [])
        if 1 <= int(x or 0) <= 3
    }
    debuff_slots = {
        int(x)
        for x in (hints.get("debuff_slots") or [])
        if 1 <= int(x or 0) <= 3
    }
    preferred_crit_slots = {
        int(x)
        for x in (hints.get("preferred_crit_slots") or [])
        if 1 <= int(x or 0) <= 4
    }
    preferred_recovery_slots = {
        int(x)
        for x in (hints.get("preferred_recovery_slots") or [])
        if 1 <= int(x or 0) <= 3
    }
    preferred_debuff_slots = {
        int(x)
        for x in (hints.get("preferred_debuff_slots") or [])
        if 1 <= int(x or 0) <= 3
    }
    preferred_effect_ids = {
        int(x)
        for x in (hints.get("preferred_effect_ids") or [])
        if (
            int(x or 0) > 0
            and (not artifact_effect_is_legacy(int(x)))
            and _effect_allowed_for_artifact_type(int(x), int(art_type))
        )
    }
    top_key = "top_sub_effect_ids"
    if int(art_type) == 1:
        top_key = "top_attribute_effect_ids"
    elif int(art_type) == 2:
        top_key = "top_type_effect_ids"
    top_sub_effect_ids = [
        int(eid)
        for eid in _hint_effect_ids_from_key(hints, top_key, limit=ARTIFACT_HINT_TOP_EFFECT_COUNT)
        if _effect_allowed_for_artifact_type(int(eid), int(art_type))
    ]
    if not top_sub_effect_ids:
        top_sub_effect_ids = [
            int(eid)
            for eid in _hint_effect_ids_from_key(
                hints,
                "top_sub_effect_ids",
                limit=ARTIFACT_HINT_TOP_EFFECT_COUNT,
            )
            if _effect_allowed_for_artifact_type(int(eid), int(art_type))
        ]

    team_has_spd_buff: Optional[bool] = None
    raw_team_spd = (hints or {}).get("team_has_spd_buff", None)
    if raw_team_spd is not None:
        try:
            team_has_spd_buff = bool(raw_team_spd)
        except Exception:
            team_has_spd_buff = None
    if team_has_spd_buff is False:
        # SPD Increasing Effect is only meaningful if a speed buff exists in the team.
        preferred_effect_ids.discard(206)
        top_sub_effect_ids = [int(eid) for eid in top_sub_effect_ids if int(eid) != 206]

    score = 0
    present_eids: Set[int] = set()
    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        try:
            eid = int(sec[0] or 0)
            val = float(sec[1] or 0)
        except Exception:
            continue
        present_eids.add(int(eid))
        if bomb_slots and int(eid) == 210:
            score += int(round(max(0.0, float(val)) * float(ARTIFACT_HINT_BOMB_VALUE_WEIGHT) * 10.0))
        if team_has_spd_buff is False and int(eid) == 206:
            score -= int(ARTIFACT_HINT_SPD_EFFECT_WITHOUT_TEAM_BUFF_PENALTY)
            score -= int(
                round(
                    max(0.0, float(val))
                    * float(ARTIFACT_HINT_SPD_EFFECT_WITHOUT_TEAM_BUFF_VALUE_WEIGHT)
                )
            )

    if guaranteed_crit_slots:
        preferred: Set[int] = set()
        for slot in guaranteed_crit_slots:
            eff = _skill_line_effect_id_for_slot(int(slot), "crit")
            if eff > 0:
                preferred.add(int(eff))
            if int(slot) in (3, 4):
                preferred.add(410)
        all_crit_skill_lines = {400, 401, 402, 403, 410}
        non_preferred = all_crit_skill_lines.difference(preferred)
        for eff in preferred:
            if eff in present_eids:
                score += int(ARTIFACT_HINT_SKILL_MATCH_BONUS)
        for eff in non_preferred:
            if eff in present_eids:
                score -= int(ARTIFACT_HINT_SKILL_MISMATCH_PENALTY)

    if preferred_crit_slots:
        preferred: Set[int] = set()
        for slot in preferred_crit_slots:
            eff = _skill_line_effect_id_for_slot(int(slot), "crit")
            if eff > 0:
                preferred.add(int(eff))
            if int(slot) in (3, 4):
                preferred.add(410)
        for eff in preferred:
            if eff in present_eids:
                score += int(ARTIFACT_HINT_SKILL_PREFERRED_BONUS)

    if recovery_slots:
        for slot in recovery_slots:
            eff = _skill_line_effect_id_for_slot(int(slot), "recovery")
            if eff > 0 and eff in present_eids:
                score += int(ARTIFACT_HINT_RECOVERY_MATCH_BONUS)

    if preferred_recovery_slots:
        for slot in preferred_recovery_slots:
            eff = _skill_line_effect_id_for_slot(int(slot), "recovery")
            if eff > 0 and eff in present_eids:
                score += int(ARTIFACT_HINT_RECOVERY_PREFERRED_BONUS)

    if debuff_slots:
        for slot in debuff_slots:
            eff = _skill_line_effect_id_for_slot(int(slot), "acc")
            if eff > 0 and eff in present_eids:
                score += int(ARTIFACT_HINT_ACC_MATCH_BONUS)

    if preferred_debuff_slots:
        for slot in preferred_debuff_slots:
            eff = _skill_line_effect_id_for_slot(int(slot), "acc")
            if eff > 0 and eff in present_eids:
                score += int(ARTIFACT_HINT_ACC_PREFERRED_BONUS)

    if top_sub_effect_ids:
        top_bonus = [
            int(ARTIFACT_HINT_TOP1_MATCH_BONUS),
            int(ARTIFACT_HINT_TOP2_MATCH_BONUS),
            int(ARTIFACT_HINT_TOP3_MATCH_BONUS),
            int(ARTIFACT_HINT_TOP4_MATCH_BONUS),
        ]
        top_weight = [
            int(ARTIFACT_HINT_TOP1_VALUE_WEIGHT),
            int(ARTIFACT_HINT_TOP2_VALUE_WEIGHT),
            int(ARTIFACT_HINT_TOP3_VALUE_WEIGHT),
            int(ARTIFACT_HINT_TOP4_VALUE_WEIGHT),
        ]
        top_miss_penalty = [
            int(ARTIFACT_HINT_TOP1_MISS_PENALTY),
            int(ARTIFACT_HINT_TOP2_MISS_PENALTY),
            int(ARTIFACT_HINT_TOP3_MISS_PENALTY),
            int(ARTIFACT_HINT_TOP4_MISS_PENALTY),
        ]
        for idx, eff_id in enumerate(top_sub_effect_ids[: int(ARTIFACT_HINT_TOP_EFFECT_COUNT)]):
            val_scaled = int(_artifact_hint_effect_value_scaled(art, int(eff_id)))
            if val_scaled <= 0:
                score -= int(top_miss_penalty[int(idx)])
                continue
            high_roll_bonus = int(_artifact_hint_high_roll_bonus(art, int(eff_id)))
            score += int(top_bonus[int(idx)]) + int(val_scaled * int(top_weight[int(idx)])) + int(high_roll_bonus)

    if preferred_effect_ids:
        non_top_effect_ids = set(preferred_effect_ids).difference(set(top_sub_effect_ids))
        for eff_id in non_top_effect_ids:
            val_scaled = int(_artifact_hint_effect_value_scaled(art, int(eff_id)))
            if val_scaled > 0:
                high_roll_bonus = int(_artifact_hint_high_roll_bonus(art, int(eff_id)))
                score += (
                    int(ARTIFACT_HINT_EFFECT_MATCH_BONUS)
                    + int(val_scaled * int(ARTIFACT_HINT_EFFECT_VALUE_WEIGHT))
                    + int(high_roll_bonus)
                )

    return int(score)


def _sanitize_artifact_hints_for_team_context(hints: Dict[str, Any] | None = None) -> Dict[str, Any]:
    data = dict(hints or {})
    raw_team_spd = data.get("team_has_spd_buff", None)
    try:
        team_has_spd_buff = bool(raw_team_spd) if raw_team_spd is not None else None
    except Exception:
        team_has_spd_buff = None
    if team_has_spd_buff is False:
        for key in (
            "top_sub_effect_ids",
            "top_attribute_effect_ids",
            "top_type_effect_ids",
            "preferred_effect_ids",
        ):
            vals = list(data.get(str(key)) or [])
            data[str(key)] = [int(x) for x in vals if int(x or 0) > 0 and int(x or 0) != 206]
    return data


def _artifact_hint_critical_effect_ids(hints: Dict[str, Any] | None = None) -> List[int]:
    data = _sanitize_artifact_hints_for_team_context(hints)
    out: List[int] = []
    seen: Set[int] = set()

    for key in ("top_sub_effect_ids", "top_type_effect_ids", "top_attribute_effect_ids"):
        for x in (data.get(str(key)) or []):
            try:
                eid = int(x or 0)
            except Exception:
                continue
            if artifact_effect_is_legacy(int(eid)):
                continue
            if eid <= 0 or eid in seen:
                continue
            seen.add(int(eid))
            out.append(int(eid))
            if len(out) >= 2:
                break
        if len(out) >= 2:
            break

    bomb_slots = {
        int(x)
        for x in (data.get("bomb_slots") or [])
        if 1 <= int(x or 0) <= 4
    }
    if bomb_slots and 210 not in seen:
        seen.add(210)
        out.append(210)

    debuff_slots = {
        int(x)
        for x in (data.get("debuff_slots") or [])
        if 1 <= int(x or 0) <= 3
    }
    pref_debuff_slots = {
        int(x)
        for x in (data.get("preferred_debuff_slots") or [])
        if 1 <= int(x or 0) <= 3
    }
    for slot in sorted(debuff_slots.union(pref_debuff_slots)):
        eff = _skill_line_effect_id_for_slot(int(slot), "acc")
        if eff <= 0 or eff in seen:
            continue
        seen.add(int(eff))
        out.append(int(eff))
        if len(out) >= 4:
            break
    return out[:4]


def _scaling_stat_from_hints(hints: Dict[str, Any] | None = None) -> str:
    data = dict(hints or {})
    scores: Dict[str, int] = {"HP": 0, "ATK": 0, "DEF": 0, "SPD": 0}
    add_map = {218: "HP", 219: "ATK", 220: "DEF", 221: "SPD"}

    top_weights = [70, 45, 30, 20]
    top_ids_ordered: List[int] = []
    seen_top: Set[int] = set()
    for key in ("top_sub_effect_ids", "top_attribute_effect_ids", "top_type_effect_ids"):
        for x in (data.get(str(key)) or []):
            try:
                eid = int(x or 0)
            except Exception:
                continue
            if eid <= 0 or eid in seen_top:
                continue
            seen_top.add(int(eid))
            top_ids_ordered.append(int(eid))
            if len(top_ids_ordered) >= int(ARTIFACT_HINT_TOP_EFFECT_COUNT):
                break
        if len(top_ids_ordered) >= int(ARTIFACT_HINT_TOP_EFFECT_COUNT):
            break
    for idx, eid in enumerate(top_ids_ordered[: int(ARTIFACT_HINT_TOP_EFFECT_COUNT)]):
        try:
            eid = int(eid or 0)
        except Exception:
            continue
        stat = add_map.get(int(eid))
        if not stat:
            continue
        scores[str(stat)] += int(top_weights[min(idx, len(top_weights) - 1)])

    pref_vals = [int(x or 0) for x in (data.get("preferred_effect_ids") or []) if int(x or 0) > 0]
    for idx, eid in enumerate(pref_vals[:10]):
        stat = add_map.get(int(eid))
        if not stat:
            continue
        scores[str(stat)] += int(max(6, 22 - idx))

    # Recovery lines are usually tied to HP scaling / survivability.
    if any(int(x or 0) in (404, 405, 406) for x in pref_vals):
        scores["HP"] += 12

    best_stat = max(scores.keys(), key=lambda k: int(scores[k]))
    if int(scores.get(best_stat, 0)) <= 0:
        return ""
    return str(best_stat)


def _rune_scaling_score_proxy(
    r: Rune,
    scaling_stat: str = "",
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
) -> int:
    stat = str(scaling_stat or "").upper().strip()
    if not stat:
        return 0
    hp_pct = int(_rune_stat_total(r, 2) or 0)
    hp_flat = int(_rune_stat_total(r, 1) or 0)
    atk_pct = int(_rune_stat_total(r, 4) or 0)
    atk_flat = int(_rune_stat_total(r, 3) or 0)
    def_pct = int(_rune_stat_total(r, 6) or 0)
    def_flat = int(_rune_stat_total(r, 5) or 0)
    spd = int(_rune_flat_spd(r) or 0)
    hp_flat_as_pct = int((hp_flat * 100) / max(1, int(base_hp or 1)))
    atk_flat_as_pct = int((atk_flat * 100) / max(1, int(base_atk or 1)))
    def_flat_as_pct = int((def_flat * 100) / max(1, int(base_def or 1)))

    if stat == "HP":
        return int((hp_pct * 24) + (hp_flat_as_pct * 16) + (spd * 4) + (def_pct * 6) - (atk_pct * 4))
    if stat == "DEF":
        return int((def_pct * 24) + (def_flat_as_pct * 16) + (spd * 4) + (hp_pct * 6) - (atk_pct * 4))
    if stat == "ATK":
        return int((atk_pct * 24) + (atk_flat_as_pct * 16) + (spd * 4) + (_rune_damage_score_proxy(r, int(base_atk or 0)) // 4))
    if stat == "SPD":
        return int((spd * 28) + (hp_pct * 8) + (def_pct * 6) + (atk_pct * 4))
    return 0


def _artifact_scaling_score_proxy(art: Artifact, scaling_stat: str = "") -> int:
    stat = str(scaling_stat or "").upper().strip()
    if not stat:
        return 0
    focus = str(_artifact_focus_key(art) or "").upper().strip()
    score = 0
    if stat == "HP":
        if focus == "HP":
            score += 420
        elif focus == "ATK":
            score -= 260
        elif focus == "DEF":
            score -= 320
        hp_line = int(_artifact_hint_effect_value_scaled(art, 218))
        def_line = int(_artifact_hint_effect_value_scaled(art, 220))
        atk_line = int(_artifact_hint_effect_value_scaled(art, 219))
        score += int(hp_line * 24) - int(def_line * 7) - int(atk_line * 5)
    elif stat == "DEF":
        if focus == "DEF":
            score += 420
        elif focus == "ATK":
            score -= 260
        elif focus == "HP":
            score -= 150
        def_line = int(_artifact_hint_effect_value_scaled(art, 220))
        hp_line = int(_artifact_hint_effect_value_scaled(art, 218))
        atk_line = int(_artifact_hint_effect_value_scaled(art, 219))
        score += int(def_line * 20) - int(hp_line * 5) - int(atk_line * 4)
    elif stat == "ATK":
        if focus == "ATK":
            score += 360
        elif focus in ("HP", "DEF"):
            score -= 180
        atk_line = int(_artifact_hint_effect_value_scaled(art, 219))
        score += int(atk_line * 16)
    elif stat == "SPD":
        if focus in ("HP", "DEF"):
            score += 110
        elif focus == "ATK":
            score -= 90
        spd_line = int(_artifact_hint_effect_value_scaled(art, 221))
        score += int(spd_line * 14)
    return int(score)


def _score_stat(eff_id: int, value: int) -> int:
    eff = int(eff_id or 0)
    return int(STAT_SCORE_WEIGHTS.get(eff, 0) * int(value or 0))


def _score_stat_defensive(eff_id: int, value: int) -> int:
    eff = int(eff_id or 0)
    return int(DEFENSIVE_STAT_SCORE_WEIGHTS.get(eff, 0) * int(value or 0))


def _is_attack_type_unit(base_hp: int, base_atk: int, base_def: int, archetype: str = "") -> bool:
    # Prefer explicit archetype when available; fall back to base-stat heuristic.
    arch = str(archetype or "").strip().lower()
    if arch:
        if arch in ("attack", "atk"):
            return True
        if arch in ("defense", "def", "hp", "support"):
            return False
    # Heuristic: ATK-type monsters usually have clearly higher base ATK than CON/DEF.
    atk = int(base_atk or 0)
    defense = int(base_def or 0)
    con = int((int(base_hp or 0)) / 15) if int(base_hp or 0) > 0 else 0
    if atk <= 0:
        return False
    return bool(atk >= defense + 60 and atk >= con + 40)


def _arena_role_from_archetype(archetype: str = "") -> str:
    arch = str(archetype or "").strip().lower()
    if not arch:
        return "unknown"
    if arch in (
        "attack", "atk", "angriff", "offense", "offensive",
        "dd", "dps", "nuker", "sniper", "damage",
    ):
        return "attack"
    if arch in ("defense", "def", "abwehr", "bruiser"):
        return "defense"
    if arch in ("hp", "leben", "tank"):
        return "hp"
    if arch in (
        "support", "rueckhalt", "rückhalt",
        "cc", "stripper", "control", "healer", "buffer", "debuffer",
    ):
        return "support"
    if arch == "unknown":
        return "unknown"
    return "unknown"


def _is_attack_archetype(archetype: str = "") -> bool:
    return str(_arena_role_from_archetype(archetype)) == "attack"


def _is_defensive_archetype(archetype: str = "") -> bool:
    return str(_arena_role_from_archetype(archetype)) in ("defense", "hp", "support")


def _rune_damage_score_proxy(r: Rune, base_atk: int) -> int:
    atk_pct = int(_rune_stat_total(r, 4) or 0)
    atk_flat = int(_rune_stat_total(r, 3) or 0)
    cr = int(_rune_stat_total(r, 9) or 0)
    cd = int(_rune_stat_total(r, 10) or 0)
    spd = int(_rune_flat_spd(r) or 0)
    flat_as_pct = int((atk_flat * 100) / max(1, int(base_atk or 1)))
    return int((atk_pct * 18) + (flat_as_pct * 12) + (cr * 14) + (cd * 16) + (spd * 2))


def _rune_defensive_score_proxy(r: Rune, base_hp: int, base_def: int, archetype: str = "") -> int:
    role = _arena_role_from_archetype(archetype)
    hp_pct = int(_rune_stat_total(r, 2) or 0)
    hp_flat = int(_rune_stat_total(r, 1) or 0)
    def_pct = int(_rune_stat_total(r, 6) or 0)
    def_flat = int(_rune_stat_total(r, 5) or 0)
    res = int(_rune_stat_total(r, 11) or 0)
    acc = int(_rune_stat_total(r, 12) or 0)
    spd = int(_rune_flat_spd(r) or 0)

    hp_flat_as_pct = int((hp_flat * 100) / max(1, int(base_hp or 1)))
    def_flat_as_pct = int((def_flat * 100) / max(1, int(base_def or 1)))

    if role == "defense":
        return int(
            (hp_pct * 9)
            + (hp_flat_as_pct * 6)
            + (def_pct * 18)
            + (def_flat_as_pct * 12)
            + (res * 8)
            + (spd * 4)
            + (acc * 2)
        )
    if role == "hp":
        return int(
            (hp_pct * 18)
            + (hp_flat_as_pct * 12)
            + (def_pct * 8)
            + (def_flat_as_pct * 6)
            + (res * 8)
            + (spd * 4)
            + (acc * 2)
        )
    if role == "support":
        return int(
            (hp_pct * 12)
            + (hp_flat_as_pct * 9)
            + (def_pct * 10)
            + (def_flat_as_pct * 7)
            + (res * 11)
            + (spd * 7)
            + (acc * 8)
        )
    return 0


def _artifact_damage_score_proxy(
    art: Artifact,
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
    base_spd: int = 0,
) -> int:
    # Offensive profile for damage dealers.
    return int(
        _artifact_profile_score(
            art,
            role="attack",
            base_hp=base_hp,
            base_atk=base_atk,
            base_def=base_def,
            base_spd=base_spd,
        )
    )


def _artifact_defensive_score_proxy(
    art: Artifact,
    archetype: str = "",
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
    base_spd: int = 0,
) -> int:
    role = _arena_role_from_archetype(archetype)
    if role not in ("defense", "hp", "support"):
        return 0
    return int(
        _artifact_profile_score(
            art,
            role=role,
            base_hp=base_hp,
            base_atk=base_atk,
            base_def=base_def,
            base_spd=base_spd,
        )
    )


def _artifact_context_score_proxy(
    art: Artifact,
    role: str = "",
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
    base_spd: int = 0,
) -> int:
    role_key = _arena_role_from_archetype(role)
    if role_key == "unknown":
        role_key = "unknown"
    return int(
        _artifact_profile_score(
            art,
            role=role_key,
            base_hp=base_hp,
            base_atk=base_atk,
            base_def=base_def,
            base_spd=base_spd,
        )
    )


def _is_good_even_slot_mainstat(eff_id: int, slot_no: int) -> bool:
    if slot_no not in (2, 4, 6):
        return True
    return int(eff_id or 0) in (2, 4, 6, 8, 9, 10, 11, 12)


def _projected_rune_mainstat_value(r: Rune) -> int:
    try:
        raw = int((r.pri_eff or (0, 0))[1] or 0)
    except Exception:
        return 0
    if raw <= 0:
        return 0
    upgrade = int(getattr(r, "upgrade_curr", 0) or 0)
    # Requested behavior: allow +12 runes and project their main stat to +15.
    # Keep lower upgrades untouched to avoid over-projecting unfinished runes.
    if upgrade < 12 or upgrade >= 15:
        return int(raw)
    factor = float(15.0 / max(1.0, float(upgrade)))
    return int(round(float(raw) * factor))


def _rune_quality_score(r: Rune, uid: int,
                        rta_rune_ids_for_unit: Optional[Set[int]] = None) -> int:
    score = 0
    score += int(r.upgrade_curr or 0) * 8
    score += int(r.rank or 0) * 6
    score += int(r.rune_class or 0) * 10
    score += int(SET_SCORE_BONUS.get(int(r.set_id or 0), 0))

    # Main stat and prefix stat
    score += _score_stat(int(r.pri_eff[0] or 0), int(_projected_rune_mainstat_value(r)))
    score += _score_stat(int(r.prefix_eff[0] or 0), int(r.prefix_eff[1] or 0))

    # Penalize flat mains on even slots when no build mainstat forces it
    if not _is_good_even_slot_mainstat(int(r.pri_eff[0] or 0), int(r.slot_no or 0)):
        score -= 140

    # Substats incl. grind
    for sec in (r.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0)
        val = int(sec[1] or 0)
        grind = int(sec[3] or 0) if len(sec) >= 4 else 0
        score += _score_stat(eff_id, val + grind)

    # Keep currently equipped rune on same unit slightly preferred
    if rta_rune_ids_for_unit is not None:
        # RTA mode: prefer runes that are RTA-equipped on this unit
        if r.rune_id in rta_rune_ids_for_unit:
            score += 45
    elif r.occupied_type == 1 and r.occupied_id == uid:
        score += 45

    return score


def _rune_quality_score_defensive(
    r: Rune,
    uid: int,
    rta_rune_ids_for_unit: Optional[Set[int]] = None,
) -> int:
    score = 0
    score += int(r.upgrade_curr or 0) * 8
    score += int(r.rank or 0) * 6
    score += int(r.rune_class or 0) * 10

    score += _score_stat_defensive(int(r.pri_eff[0] or 0), int(_projected_rune_mainstat_value(r)))
    score += _score_stat_defensive(int(r.prefix_eff[0] or 0), int(r.prefix_eff[1] or 0))

    for sec in (r.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0)
        val = int(sec[1] or 0)
        grind = int(sec[3] or 0) if len(sec) >= 4 else 0
        score += _score_stat_defensive(eff_id, val + grind)

    if not _is_good_even_slot_mainstat(int(r.pri_eff[0] or 0), int(r.slot_no or 0)):
        score -= 140

    if rta_rune_ids_for_unit is not None:
        if r.rune_id in rta_rune_ids_for_unit:
            score += 45
    elif r.occupied_type == 1 and r.occupied_id == uid:
        score += 45

    return int(score)


def _artifact_focus_key(art: Artifact) -> str:
    if not art.pri_effect:
        return ""
    try:
        eff_id = int(art.pri_effect[0] or 0)
    except Exception:
        return ""
    return str(_ARTIFACT_FOCUS_BY_EFFECT_ID.get(eff_id, ""))


def _artifact_substat_ids(art: Artifact) -> Set[int]:
    out: Set[int] = set()
    for sec in (art.sec_effects or []):
        if not sec:
            continue
        try:
            out.add(int(sec[0] or 0))
        except Exception:
            continue
    out.discard(0)
    return out


def _artifact_effect_value_scaled(art: Artifact, effect_id: int) -> int:
    target = int(effect_id or 0)
    if target <= 0:
        return 0
    total = 0
    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        try:
            if int(sec[0] or 0) != target:
                continue
            total += int(round(float(sec[1] or 0) * 10.0))
        except Exception:
            continue
    return int(total)


def _artifact_hint_effect_value_scaled(art: Artifact, effect_id: int) -> int:
    eid = int(effect_id or 0)
    raw = int(_artifact_effect_value_scaled(art, eid))
    if raw <= 0:
        return 0
    if eid in _ADDITIONAL_DAMAGE_EFFECT_IDS:
        # raw is value*10; convert back to percentage and normalize by effect family.
        val_pct = float(raw) / 10.0
        ref = float(_ADDITIONAL_DAMAGE_PERCENT_REFERENCE.get(eid, 10.0) or 10.0)
        if ref <= 0.0:
            ref = 10.0
        normalized = (val_pct / ref) * 10.0
        return int(round(float(normalized) * 10.0 * float(ARTIFACT_HINT_ADDITIONAL_DAMAGE_VALUE_FACTOR)))
    return int(raw)


def _artifact_effect_roll_count(art: Artifact, effect_id: int) -> int:
    target = int(effect_id or 0)
    if target <= 0:
        return 0
    best = 0
    for sec in (art.sec_effects or []):
        if not sec:
            continue
        try:
            eid = int(sec[0] or 0)
        except Exception:
            continue
        if eid != target:
            continue
        upgrades = 0
        try:
            upgrades = int(sec[2] or 0) if len(sec) > 2 else 0
        except Exception:
            upgrades = 0
        if upgrades > best:
            best = int(upgrades)
    return int(best)


def _artifact_hint_high_roll_bonus(art: Artifact, effect_id: int) -> int:
    rolls = int(_artifact_effect_roll_count(art, int(effect_id)))
    if rolls < int(ARTIFACT_HINT_HIGH_ROLL_MIN):
        return 0
    extra_rolls = int(rolls - int(ARTIFACT_HINT_HIGH_ROLL_MIN) + 1)
    if extra_rolls <= 0:
        return 0
    bonus = int(extra_rolls * int(ARTIFACT_HINT_HIGH_ROLL_BONUS_PER_ROLL))
    return int(min(int(ARTIFACT_HINT_HIGH_ROLL_BONUS_MAX), int(bonus)))


def _artifact_quality_score(
    art: Artifact,
    uid: int,
    rta_artifact_ids_for_unit: Optional[Set[int]] = None,
) -> int:
    score = 0
    score += int(art.level or 0) * 8
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    score += base_rank * 6

    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        try:
            val = float(sec[1] or 0)
        except Exception:
            continue
        score += int(round(val * 4))

    if rta_artifact_ids_for_unit is not None:
        if int(art.artifact_id or 0) in rta_artifact_ids_for_unit:
            score += ARTIFACT_BONUS_FOR_SAME_UNIT
    elif int(art.occupied_id or 0) == int(uid):
        score += ARTIFACT_BONUS_FOR_SAME_UNIT

    return int(score)


def _artifact_quality_score_defensive(
    art: Artifact,
    uid: int,
    rta_artifact_ids_for_unit: Optional[Set[int]] = None,
    archetype: str = "",
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
    base_spd: int = 0,
) -> int:
    score = 0
    score += int(art.level or 0) * 8
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    score += base_rank * 6

    # Defensive effect quality as the primary artifact signal.
    score += int(
        _artifact_defensive_score_proxy(
            art,
            archetype,
            base_hp=base_hp,
            base_atk=base_atk,
            base_def=base_def,
            base_spd=base_spd,
        )
    )
    # Penalize pure offensive artifact lines for defensive units.
    score -= int(
        _artifact_damage_score_proxy(
            art,
            base_hp=base_hp,
            base_atk=base_atk,
            base_def=base_def,
            base_spd=base_spd,
        )
    )

    if rta_artifact_ids_for_unit is not None:
        if int(art.artifact_id or 0) in rta_artifact_ids_for_unit:
            score += ARTIFACT_BONUS_FOR_SAME_UNIT
    elif int(art.occupied_id or 0) == int(uid):
        score += ARTIFACT_BONUS_FOR_SAME_UNIT

    return int(score)


def _baseline_guard_rune_coef(
    r: Rune,
    uid: int,
    base_hp: int,
    base_atk: int,
    base_def: int,
    role: str,
    rta_rune_ids_for_unit: Optional[Set[int]] = None,
) -> int:
    if str(role) in ("defense", "hp", "support"):
        return int(
            _rune_quality_score_defensive(r, uid, rta_rune_ids_for_unit)
            + (int(ARENA_RUSH_DEF_RUNE_WEIGHT) * int(_rune_defensive_score_proxy(r, base_hp, base_def, role)))
            - (int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(_rune_damage_score_proxy(r, base_atk)))
        )
    if str(role) == "attack":
        return int(_rune_quality_score(r, uid, rta_rune_ids_for_unit) + int(_rune_damage_score_proxy(r, base_atk)))
    return int(_rune_quality_score(r, uid, rta_rune_ids_for_unit))


def _baseline_guard_artifact_coef(
    art: Artifact,
    uid: int,
    role: str,
    rta_artifact_ids_for_unit: Optional[Set[int]] = None,
    base_hp: int = 0,
    base_atk: int = 0,
    base_def: int = 0,
    base_spd: int = 0,
) -> int:
    if str(role) in ("defense", "hp", "support"):
        return int(
            _artifact_quality_score_defensive(
                art,
                uid,
                rta_artifact_ids_for_unit,
                archetype=role,
                base_hp=base_hp,
                base_atk=base_atk,
                base_def=base_def,
                base_spd=base_spd,
            )
            + (
                int(ARENA_RUSH_DEF_ART_WEIGHT)
                * int(
                    _artifact_defensive_score_proxy(
                        art,
                        role,
                        base_hp=base_hp,
                        base_atk=base_atk,
                        base_def=base_def,
                        base_spd=base_spd,
                    )
                )
            )
            - (
                int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT)
                * int(
                    _artifact_damage_score_proxy(
                        art,
                        base_hp=base_hp,
                        base_atk=base_atk,
                        base_def=base_def,
                        base_spd=base_spd,
                    )
                )
            )
        )
    if str(role) == "attack":
        return int(
            _artifact_quality_score(art, uid, rta_artifact_ids_for_unit)
            + int(
                _artifact_damage_score_proxy(
                    art,
                    base_hp=base_hp,
                    base_atk=base_atk,
                    base_def=base_def,
                    base_spd=base_spd,
                )
            )
        )
    return int(_artifact_quality_score(art, uid, rta_artifact_ids_for_unit))


@dataclass
class GreedyRequest:
    mode: str
    unit_ids_in_order: List[int]   # Reihenfolge = Priorität (wie SWOP)
    time_limit_per_unit_s: float = 10.0
    workers: int = 8
    multi_pass_enabled: bool = True
    multi_pass_count: int = 3
    multi_pass_time_factor: float = 0.2
    multi_pass_strategy: str = "greedy_refine"  # greedy_only | greedy_refine
    rune_top_per_set: int = 200
    quality_profile: str = "balanced"  # fast | balanced | max_quality | gpu_search_fast | gpu_search_balanced | gpu_search_max
    speed_slack_for_quality: int = DEFAULT_SPEED_SLACK_FOR_QUALITY
    progress_callback: Optional[Callable[[int, int], None]] = None
    is_cancelled: Optional[Callable[[], bool]] = None
    register_solver: Optional[Callable[[object], None]] = None
    enforce_turn_order: bool = True
    unit_team_index: Dict[int, int] | None = None
    unit_team_turn_order: Dict[int, int] | None = None
    unit_spd_leader_bonus_flat: Dict[int, int] | None = None
    unit_min_final_speed: Dict[int, int] | None = None
    unit_max_final_speed: Dict[int, int] | None = None
    unit_speed_tiebreak_weight: Dict[int, int] | None = None
    excluded_rune_ids: Set[int] | None = None
    excluded_artifact_ids: Set[int] | None = None
    unit_fixed_runes_by_slot: Dict[int, Dict[int, int]] | None = None
    unit_fixed_artifacts_by_type: Dict[int, Dict[int, int]] | None = None
    unit_baseline_runes_by_slot: Dict[int, Dict[int, int]] | None = None
    unit_baseline_artifacts_by_type: Dict[int, Dict[int, int]] | None = None
    baseline_regression_guard_weight: int = 0
    global_seed_offset: int = 0
    unit_archetype_by_uid: Dict[int, str] | None = None
    unit_artifact_hints_by_uid: Dict[int, Dict[str, Any]] | None = None
    unit_team_has_spd_buff_by_uid: Dict[int, bool] | None = None
    arena_rush_context: str = ""  # "", "defense", "offense"

@dataclass
class GreedyUnitResult:
    unit_id: int
    ok: bool
    message: str
    chosen_build_id: str = ""
    chosen_build_name: str = ""
    runes_by_slot: Dict[int, int] = None  # slot -> rune_id
    artifacts_by_type: Dict[int, int] = None  # artifact_type (1/2) -> artifact_id
    final_speed: int = 0


@dataclass
class GreedyResult:
    ok: bool
    message: str
    results: List[GreedyUnitResult]


@dataclass
class _PassOutcome:
    pass_idx: int
    order: List[int]
    results: List[GreedyUnitResult]
    score: Tuple[int, int, int, int, int, int, int]


def _rune_pool_rank_score(r: Rune) -> int:
    # Unit-agnostic pre-ranking for pool pruning (fast and stable enough).
    base = 0
    base += int(round(float(rune_efficiency(r)) * 100.0))
    base += int(r.upgrade_curr or 0) * 40
    base += int(r.rank or 0) * 30
    base += int(r.rune_class or 0) * 25
    return int(base)


def _allowed_runes_for_mode(
    account: AccountData,
    req: GreedyRequest,
    _selected_unit_ids: List[int],
    rune_top_per_set_override: Optional[int] = None,
) -> List[Rune]:
    # Full account pool optionally pruned to top-N per set to keep search tractable.
    all_runes = list(account.runes)
    excluded_rune_ids = {
        int(rid)
        for rid in (req.excluded_rune_ids or set())
        if int(rid or 0) > 0
    }
    if excluded_rune_ids:
        all_runes = [r for r in all_runes if int(r.rune_id or 0) not in excluded_rune_ids]
    top_n_raw = rune_top_per_set_override if rune_top_per_set_override is not None else getattr(req, "rune_top_per_set", 0)
    top_n = int(top_n_raw or 0)
    if top_n <= 0:
        return all_runes

    mode_key = str(getattr(req, "mode", "") or "").strip().lower()
    arena_rush_pool_by_set_size = mode_key == "arena_rush"

    by_set: Dict[int, List[Rune]] = {}
    for r in all_runes:
        sid = int(r.set_id or 0)
        by_set.setdefault(sid, []).append(r)

    pruned: List[Rune] = []
    for sid, runes in by_set.items():
        per_set_cap = int(top_n)
        if arena_rush_pool_by_set_size:
            set_size = int(SET_SIZES.get(int(sid), 2) or 2)
            if int(set_size) == 4:
                per_set_cap = 500
            elif int(set_size) == 2:
                per_set_cap = 300
        ranked = sorted(
            runes,
            key=lambda rr: (_rune_pool_rank_score(rr), int(rr.slot_no or 0), -int(rr.rune_id or 0)),
            reverse=True,
        )
        pruned.extend(ranked[:max(0, int(per_set_cap))])
    return pruned


def _allowed_artifacts_for_mode(
    account: AccountData,
    _selected_unit_ids: List[int],
    req: GreedyRequest | None = None,
) -> List[Artifact]:
    # User requested full account pool: use every artifact from the JSON snapshot/import.
    artifacts = [a for a in account.artifacts if int(a.type_ or 0) in (1, 2)]
    excluded_artifact_ids = {
        int(aid)
        for aid in ((req.excluded_artifact_ids or set()) if req is not None else set())
        if int(aid or 0) > 0
    }
    if excluded_artifact_ids:
        artifacts = [a for a in artifacts if int(a.artifact_id or 0) not in excluded_artifact_ids]
    return artifacts


def _count_required_set_pieces(set_names: List[str]) -> Dict[int, int]:
    needed: Dict[int, int] = {}
    for name in set_names:
        sid = SET_ID_BY_NAME.get(name)
        if not sid:
            continue
        needed[sid] = needed.get(sid, 0) + int(SET_SIZES.get(sid, 2))
    return needed


def _rune_flat_spd(r: Rune) -> int:
    total = 0
    try:
        if int(r.pri_eff[0] or 0) == 8:
            total += int(_projected_rune_mainstat_value(r))
    except Exception:
        pass
    try:
        if int(r.prefix_eff[0] or 0) == 8:
            total += int(r.prefix_eff[1] or 0)
    except Exception:
        pass
    for sec in (r.sec_eff or []):
        if not sec:
            continue
        try:
            if int(sec[0] or 0) != 8:
                continue
            total += int(sec[1] or 0)
            if len(sec) >= 4:
                total += int(sec[3] or 0)
        except Exception:
            continue
    return int(total)


def _rune_stat_total(r: Rune, eff_id_target: int) -> int:
    total = 0
    try:
        if int(r.pri_eff[0] or 0) == eff_id_target:
            total += int(_projected_rune_mainstat_value(r))
    except Exception:
        pass
    try:
        if int(r.prefix_eff[0] or 0) == eff_id_target:
            total += int(r.prefix_eff[1] or 0)
    except Exception:
        pass
    for sec in (r.sec_eff or []):
        if not sec:
            continue
        try:
            if int(sec[0] or 0) != eff_id_target:
                continue
            total += int(sec[1] or 0)
            if len(sec) >= 4:
                total += int(sec[3] or 0)
        except Exception:
            continue
    return int(total)


def _build_allows_swift(b: Build) -> bool:
    for opt in (getattr(b, "set_options", []) or []):
        for name in (opt or []):
            if str(name).strip().lower() == "swift":
                return True
    return False


def _unit_is_turn_or_position_one(req: GreedyRequest, uid: int) -> bool:
    turn_map = dict(req.unit_team_turn_order or {})
    team_map = dict(req.unit_team_index or {})
    turn = int(turn_map.get(int(uid), 0) or 0)
    if turn > 0:
        return turn == 1
    team = team_map.get(int(uid), None)
    if team is None:
        # No team map: first in overall order counts as position 1 fallback.
        ordered = [int(x) for x in (req.unit_ids_in_order or [])]
        return bool(ordered and int(ordered[0]) == int(uid))
    ordered = [int(x) for x in (req.unit_ids_in_order or [])]
    for cand in ordered:
        if team_map.get(int(cand), None) == team:
            return int(cand) == int(uid)
    return False


def _force_swift_speed_priority(req: GreedyRequest, uid: int, builds: List[Build]) -> bool:
    if not _unit_is_turn_or_position_one(req, uid):
        return False
    if not builds:
        return False
    # "Nothing further in min stats": allow SPD min, but no other min-stat requirements.
    has_swift = any(_build_allows_swift(b) for b in builds)
    if not has_swift:
        return False
    if any(int(getattr(b, "spd_tick", 0) or 0) != 0 for b in builds):
        return False
    for b in builds:
        mins = dict(getattr(b, "min_stats", {}) or {})
        for k, v in mins.items():
            key = str(k).strip().upper()
            val = int(v or 0)
            if val <= 0:
                continue
            if key not in ("SPD", "SPD_NO_BASE"):
                return False
    return True


def _diagnose_single_unit_infeasible(
    pool: List[Rune],
    artifact_pool: List[Artifact],
    builds: List[Build],
) -> str:
    runes_by_slot: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= r.slot_no <= 6:
            runes_by_slot[r.slot_no].append(r)

    for s in range(1, 7):
        if not runes_by_slot[s]:
            return tr("opt.slot_no_runes", slot=s)

    art_by_type: Dict[int, List[Artifact]] = {1: [], 2: []}
    for art in artifact_pool:
        t = int(art.type_ or 0)
        if t in (1, 2):
            art_by_type[t].append(art)

    if not art_by_type[1]:
        return tr("opt.no_attr_artifact")
    if not art_by_type[2]:
        return tr("opt.no_type_artifact")

    if not builds:
        return tr("opt.no_builds")

    reasons: List[str] = []
    for b in builds:
        # Mainstat feasibility
        ok_main = True
        for slot in (2, 4, 6):
            allowed = (b.mainstats or {}).get(slot) or []
            if not allowed:
                continue
            cnt = 0
            for r in runes_by_slot[slot]:
                key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(r.pri_eff[0] or 0), "")
                if key in allowed:
                    cnt += 1
            if cnt == 0:
                ok_main = False
                reasons.append(tr("opt.mainstat_missing", name=b.name, slot=slot, allowed=allowed))
                break

        if not ok_main:
            continue

        # Artifact feasibility (focus/substats)
        artifact_ok = True
        focus_cfg = dict(getattr(b, "artifact_focus", {}) or {})
        subs_cfg = dict(getattr(b, "artifact_substats", {}) or {})
        for type_id, key in ((1, "attribute"), (2, "type")):
            candidates = list(art_by_type.get(type_id, []))
            allowed_focus = [str(x).upper() for x in (focus_cfg.get(key) or []) if str(x)]
            needed_subs = [int(x) for x in (subs_cfg.get(key) or []) if int(x) > 0][:2]
            if not allowed_focus and not needed_subs:
                continue

            feasible = 0
            for art in candidates:
                fkey = _artifact_focus_key(art)
                if allowed_focus and fkey not in allowed_focus:
                    continue
                sec_ids = _artifact_substat_ids(art)
                if needed_subs and any(req_id not in sec_ids for req_id in needed_subs):
                    continue
                feasible += 1

            if feasible == 0:
                artifact_ok = False
                kind = tr("artifact.attribute") if type_id == 1 else tr("artifact.type")
                reasons.append(
                    tr("opt.no_artifact_match", name=b.name, kind=kind,
                       focus=allowed_focus or "Any", subs=needed_subs or "Any")
                )
                break

        if not artifact_ok:
            continue

        # Set feasibility
        if not b.set_options:
            return tr("opt.feasible")

        feasible_any_option = False
        for opt in b.set_options:
            needed = _count_required_set_pieces([str(s) for s in opt])
            total_pieces = sum(int(v) for v in needed.values())
            if total_pieces > 6:
                reasons.append(tr("opt.set_too_many", name=b.name, opt=opt, pieces=total_pieces))
                continue
            ok_opt = True
            intangible_avail = 0
            for slot in range(1, 7):
                intangible_avail += sum(
                    1 for r in runes_by_slot[slot] if int(r.set_id or 0) == int(INTANGIBLE_SET_ID)
                )
            intangible_budget = 1 if intangible_avail > 0 else 0
            for set_id, pieces in needed.items():
                avail = 0
                for slot in range(1, 7):
                    avail += sum(1 for r in runes_by_slot[slot] if int(r.set_id or 0) == int(set_id))
                if int(set_id) == int(INTANGIBLE_SET_ID):
                    if avail < pieces:
                        ok_opt = False
                        reasons.append(
                            tr("opt.set_not_enough", name=b.name, set_id=set_id, pieces=pieces, avail=avail)
                        )
                        break
                    continue

                deficit = max(0, int(pieces) - int(avail))
                if deficit <= 0:
                    continue
                if deficit == 1 and intangible_budget > 0:
                    intangible_budget -= 1
                    continue

                if avail < pieces:
                    ok_opt = False
                    reasons.append(
                        tr("opt.set_not_enough", name=b.name, set_id=set_id, pieces=pieces, avail=avail)
                    )
                    break
            if ok_opt:
                feasible_any_option = True
                break

        if feasible_any_option:
            return tr("opt.feasible")

    if reasons:
        return " | ".join(reasons[:3])
    return tr("opt.infeasible")


def _solve_single_unit_best(
    uid: int,
    pool: List[Rune],
    artifact_pool: List[Artifact],
    builds: List[Build],
    time_limit_s: float,
    workers: int,
    base_hp: int,
    base_atk: int,
    base_def: int,
    base_spd: int,
    base_spd_bonus_flat: int,
    base_cr: int,
    base_cd: int,
    base_res: int,
    base_acc: int,
    max_final_speed: Optional[int],
    min_final_speed: Optional[int] = None,
    rta_rune_ids_for_unit: Optional[Set[int]] = None,
    rta_artifact_ids_for_unit: Optional[Set[int]] = None,
    speed_hard_priority: bool = True,
    speed_weight_soft: int = SOFT_SPEED_WEIGHT,
    speed_tiebreak_weight: int = 1,
    build_priority_penalty: int = DEFAULT_BUILD_PRIORITY_PENALTY,
    set_option_preference_offset: int = 0,
    set_option_preference_bonus: int = SET_OPTION_PREFERENCE_BONUS,
    fixed_runes_by_slot: Optional[Dict[int, int]] = None,
    fixed_artifacts_by_type: Optional[Dict[int, int]] = None,
    baseline_runes_by_slot: Optional[Dict[int, int]] = None,
    baseline_artifacts_by_type: Optional[Dict[int, int]] = None,
    baseline_regression_guard_weight: int = 0,
    avoid_runes_by_slot: Optional[Dict[int, int]] = None,
    avoid_artifacts_by_type: Optional[Dict[int, int]] = None,
    avoid_same_rune_penalty: int = 0,
    avoid_same_artifact_penalty: int = 0,
    speed_slack_for_quality: int = 0,
    objective_mode: str = "balanced",  # balanced | efficiency
    force_speed_priority: bool = False,
    arena_rush_damage_bias: bool = False,
    unit_archetype: str = "",
    artifact_hints: Optional[Dict[str, Any]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
    register_solver: Optional[Callable[[object], None]] = None,
    mode: str = "normal",
) -> GreedyUnitResult:
    """
    Solve for ONE unit:
    - pick exactly 1 rune per slot (1..6)
    - pick exactly 1 attribute artifact (type 1) and 1 type artifact (type 2)
    - pick exactly 1 build
    - enforce build mainstats (2/4/6) + build set_option + artifact constraints
    - objective: maximize rune weight - priority penalty
    """
    if is_cancelled and is_cancelled():
        return GreedyUnitResult(uid, False, tr("opt.cancelled"), runes_by_slot={})

    # candidates by slot
    runes_by_slot: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= r.slot_no <= 6:
            runes_by_slot[r.slot_no].append(r)

    locked_runes = {
        int(slot): int(rid)
        for slot, rid in (fixed_runes_by_slot or {}).items()
        if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
    }
    for slot, rune_id in locked_runes.items():
        matches = [r for r in runes_by_slot.get(int(slot), []) if int(r.rune_id or 0) == int(rune_id)]
        if not matches:
            return GreedyUnitResult(
                uid,
                False,
                f"Locked rune {int(rune_id)} not available for slot {int(slot)}.",
                runes_by_slot={},
            )
        runes_by_slot[int(slot)] = matches

    # Hard feasibility: each slot must have >= 1 candidate
    for s in range(1, 7):
        if not runes_by_slot[s]:
            return GreedyUnitResult(uid, False, tr("opt.slot_no_runes", slot=s), runes_by_slot={})

    artifacts_by_type: Dict[int, List[Artifact]] = {1: [], 2: []}
    for art in artifact_pool:
        t = int(art.type_ or 0)
        if t in (1, 2):
            artifacts_by_type[t].append(art)

    locked_artifacts = {
        int(art_type): int(aid)
        for art_type, aid in (fixed_artifacts_by_type or {}).items()
        if int(art_type or 0) in (1, 2) and int(aid or 0) > 0
    }
    for art_type, art_id in locked_artifacts.items():
        matches = [
            a for a in artifacts_by_type.get(int(art_type), [])
            if int(a.artifact_id or 0) == int(art_id)
        ]
        if not matches:
            return GreedyUnitResult(
                uid,
                False,
                f"Locked artifact {int(art_id)} not available for type {int(art_type)}.",
                runes_by_slot={},
            )
        artifacts_by_type[int(art_type)] = matches

    if not artifacts_by_type[1]:
        return GreedyUnitResult(uid, False, tr("opt.no_attr_artifact"), runes_by_slot={})
    if not artifacts_by_type[2]:
        return GreedyUnitResult(uid, False, tr("opt.no_type_artifact"), runes_by_slot={})

    model = cp_model.CpModel()

    # x[slot, rune_id]
    x: Dict[Tuple[int, int], cp_model.IntVar] = {}
    for slot in range(1, 7):
        vs = []
        for r in runes_by_slot[slot]:
            v = model.NewBoolVar(f"x_u{uid}_s{slot}_r{r.rune_id}")
            x[(slot, r.rune_id)] = v
            vs.append(v)
        model.Add(sum(vs) == 1)

    # rune unique within this unit is automatically true because each rune has fixed slot,
    # but keep it safe anyway (in case slot_no mismatch exists)
    for r in pool:
        uses = []
        for slot in range(1, 7):
            key = (slot, r.rune_id)
            if key in x:
                uses.append(x[key])
        if uses:
            model.Add(sum(uses) <= 1)

    # artifact selection: exactly one per artifact type (1=attribute, 2=type)
    xa: Dict[Tuple[int, int], cp_model.IntVar] = {}
    for art_type in (1, 2):
        vars_for_type: List[cp_model.IntVar] = []
        for art in artifacts_by_type[art_type]:
            v = model.NewBoolVar(f"xa_u{uid}_t{art_type}_a{int(art.artifact_id)}")
            xa[(art_type, int(art.artifact_id))] = v
            vars_for_type.append(v)
        model.Add(sum(vars_for_type) == 1)

    # build selection
    if not builds:
        builds = [Build.default_any()]

    use_build: Dict[int, cp_model.IntVar] = {}
    for b_idx, b in enumerate(builds):
        use_build[b_idx] = model.NewBoolVar(f"use_build_u{uid}_b{b_idx}")
    model.Add(sum(use_build.values()) == 1)

    set_choice_vars: Dict[int, List[cp_model.IntVar]] = {}
    for slot in range(1, 7):
        for r in runes_by_slot[slot]:
            sid = int(r.set_id or 0)
            set_choice_vars.setdefault(sid, []).append(x[(slot, r.rune_id)])
    intangible_piece_vars = set_choice_vars.get(int(INTANGIBLE_SET_ID), [])
    intangible_piece_count_expr = sum(intangible_piece_vars) if intangible_piece_vars else 0

    # for each build, add constraints only if chosen
    # set options: if present => choose one option if build chosen
    option_bias_terms = []
    apply_rune_set_fallback = not any(bool(getattr(bb, "set_options", []) or []) for bb in (builds or []))
    fallback_rune_set_ids: List[int] = []
    if apply_rune_set_fallback:
        unit_obj = account.units_by_id.get(int(uid))
        master_id = int((unit_obj.unit_master_id if unit_obj else 0) or 0)
        fallback_rune_set_ids = _preferred_rune_set_ids_for_monster(master_id, role=str(unit_archetype or ""))
    for b_idx, b in enumerate(builds):
        vb = use_build[b_idx]

        # mainstats
        for slot in (2, 4, 6):
            allowed = (b.mainstats or {}).get(slot) or []
            if not allowed:
                continue
            for r in runes_by_slot[slot]:
                key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(r.pri_eff[0] or 0), "")
                if key and (key not in allowed):
                    model.Add(x[(slot, r.rune_id)] == 0).OnlyEnforceIf(vb)

        # artifact constraints (separate for attribute/type artifact)
        artifact_focus_cfg = dict(getattr(b, "artifact_focus", {}) or {})
        artifact_sub_cfg = dict(getattr(b, "artifact_substats", {}) or {})
        for art_type, cfg_key in ((1, "attribute"), (2, "type")):
            allowed_focus = [str(x).upper() for x in (artifact_focus_cfg.get(cfg_key) or []) if str(x)]
            required_subs = [int(x) for x in (artifact_sub_cfg.get(cfg_key) or []) if int(x) > 0][:2]
            if not allowed_focus and not required_subs:
                continue
            for art in artifacts_by_type[art_type]:
                av = xa[(art_type, int(art.artifact_id))]
                if allowed_focus:
                    if _artifact_focus_key(art) not in allowed_focus:
                        model.Add(av == 0).OnlyEnforceIf(vb)
                        continue
                if required_subs:
                    sec_ids = _artifact_substat_ids(art)
                    if any(req_id not in sec_ids for req_id in required_subs):
                        model.Add(av == 0).OnlyEnforceIf(vb)

        # sets
        if b.set_options:
            opt_vars = []
            for o_idx, _ in enumerate(b.set_options):
                opt_vars.append(model.NewBoolVar(f"use_opt_u{uid}_b{b_idx}_o{o_idx}"))

            model.Add(sum(opt_vars) == 1).OnlyEnforceIf(vb)
            model.Add(sum(opt_vars) == 0).OnlyEnforceIf(vb.Not())

            for o_idx, opt in enumerate(b.set_options):
                vo = opt_vars[o_idx]
                if len(opt_vars) > 1 and int(set_option_preference_bonus) > 0:
                    pref_idx = int(set_option_preference_offset) % len(opt_vars)
                    distance = (o_idx - pref_idx) % len(opt_vars)
                    bias = max(0, int(set_option_preference_bonus) - (distance * 12))
                    if bias > 0:
                        option_bias_terms.append(bias * vo)
                needed = _count_required_set_pieces([str(s) for s in opt])
                replacement_vars: List[cp_model.IntVar] = []

                for set_id, pieces in needed.items():
                    sid = int(set_id)
                    needed_pieces = int(pieces)
                    chosen_set_vars = set_choice_vars.get(sid, [])
                    set_count_expr = sum(chosen_set_vars) if chosen_set_vars else 0

                    # Intangible set requirement itself cannot be fulfilled via replacement.
                    if sid == int(INTANGIBLE_SET_ID):
                        if not chosen_set_vars:
                            model.Add(vo == 0)
                            continue
                        model.Add(set_count_expr >= needed_pieces).OnlyEnforceIf(vo)
                        continue

                    rep = model.NewIntVar(0, 1, f"rep_u{uid}_b{b_idx}_o{o_idx}_s{sid}")
                    replacement_vars.append(rep)
                    model.Add(set_count_expr + rep >= needed_pieces).OnlyEnforceIf(vo)

                if replacement_vars:
                    model.Add(sum(replacement_vars) <= 1).OnlyEnforceIf(vo)
                    if intangible_piece_vars:
                        model.Add(sum(replacement_vars) <= intangible_piece_count_expr).OnlyEnforceIf(vo)
                    else:
                        model.Add(sum(replacement_vars) == 0).OnlyEnforceIf(vo)

        # min stat thresholds
        min_stats = dict(getattr(b, "min_stats", {}) or {})
        if min_stats:
            cr_terms = []
            cd_terms = []
            res_terms = []
            acc_terms = []
            hp_flat_terms = []
            hp_pct_terms = []
            atk_flat_terms = []
            atk_pct_terms = []
            def_flat_terms = []
            def_pct_terms = []
            for slot in range(1, 7):
                for r in runes_by_slot[slot]:
                    xv = x[(slot, r.rune_id)]
                    cr = _rune_stat_total(r, 9)
                    cd = _rune_stat_total(r, 10)
                    res = _rune_stat_total(r, 11)
                    acc = _rune_stat_total(r, 12)
                    hp_flat = _rune_stat_total(r, 1)
                    hp_pct = _rune_stat_total(r, 2)
                    atk_flat = _rune_stat_total(r, 3)
                    atk_pct = _rune_stat_total(r, 4)
                    def_flat = _rune_stat_total(r, 5)
                    def_pct = _rune_stat_total(r, 6)
                    if cr:
                        cr_terms.append(cr * xv)
                    if cd:
                        cd_terms.append(cd * xv)
                    if res:
                        res_terms.append(res * xv)
                    if acc:
                        acc_terms.append(acc * xv)
                    if hp_flat:
                        hp_flat_terms.append(hp_flat * xv)
                    if hp_pct:
                        hp_pct_terms.append(hp_pct * xv)
                    if atk_flat:
                        atk_flat_terms.append(atk_flat * xv)
                    if atk_pct:
                        atk_pct_terms.append(atk_pct * xv)
                    if def_flat:
                        def_flat_terms.append(def_flat * xv)
                    if def_pct:
                        def_pct_terms.append(def_pct * xv)

            if int(min_stats.get("CR", 0) or 0) > 0:
                model.Add(base_cr + sum(cr_terms) >= int(min_stats["CR"])).OnlyEnforceIf(vb)
            if int(min_stats.get("CD", 0) or 0) > 0:
                model.Add(base_cd + sum(cd_terms) >= int(min_stats["CD"])).OnlyEnforceIf(vb)
            if int(min_stats.get("RES", 0) or 0) > 0:
                model.Add(base_res + sum(res_terms) >= int(min_stats["RES"])).OnlyEnforceIf(vb)
            if int(min_stats.get("ACC", 0) or 0) > 0:
                model.Add(base_acc + sum(acc_terms) >= int(min_stats["ACC"])).OnlyEnforceIf(vb)

            def _add_primary_min_constraints(
                stat_key: str,
                stat_no_base_key: str,
                base_value: int,
                flat_terms: List[cp_model.LinearExpr],
                pct_terms: List[cp_model.LinearExpr],
            ) -> None:
                min_with_base = int(min_stats.get(stat_key, 0) or 0)
                min_without_base = int(min_stats.get(stat_no_base_key, 0) or 0)
                if min_with_base <= 0 and min_without_base <= 0:
                    return
                flat_total_expr = sum(flat_terms) if flat_terms else 0
                pct_total_expr = sum(pct_terms) if pct_terms else 0
                pct_bonus_expr: cp_model.LinearExpr = 0
                if int(base_value) > 0 and pct_terms:
                    pct_total_var = model.NewIntVar(0, 3000, f"mns_{stat_key}_pct_u{uid}_b{b_idx}")
                    model.Add(pct_total_var == pct_total_expr)
                    pct_scaled_var = model.NewIntVar(0, int(base_value) * 3000, f"mns_{stat_key}_pct_scaled_u{uid}_b{b_idx}")
                    model.Add(pct_scaled_var == int(base_value) * pct_total_var)
                    pct_bonus_var = model.NewIntVar(0, int(base_value) * 30, f"mns_{stat_key}_pct_bonus_u{uid}_b{b_idx}")
                    model.AddDivisionEquality(pct_bonus_var, pct_scaled_var, 100)
                    pct_bonus_expr = pct_bonus_var
                final_with_base_expr = int(base_value) + flat_total_expr + pct_bonus_expr
                final_without_base_expr = flat_total_expr + pct_bonus_expr
                if min_with_base > 0:
                    model.Add(final_with_base_expr >= min_with_base).OnlyEnforceIf(vb)
                if min_without_base > 0:
                    model.Add(final_without_base_expr >= min_without_base).OnlyEnforceIf(vb)

            _add_primary_min_constraints("HP", "HP_NO_BASE", int(base_hp or 0), hp_flat_terms, hp_pct_terms)
            _add_primary_min_constraints("ATK", "ATK_NO_BASE", int(base_atk or 0), atk_flat_terms, atk_pct_terms)
            _add_primary_min_constraints("DEF", "DEF_NO_BASE", int(base_def or 0), def_flat_terms, def_pct_terms)

    # speed expression (for SPD-first)
    speed_terms = []
    swift_piece_vars = []
    cr_terms_all: List[cp_model.LinearExpr] = []
    res_terms_all: List[cp_model.LinearExpr] = []
    acc_terms_all: List[cp_model.LinearExpr] = []
    swift_bonus_value = int(int(base_spd or 0) * 25 / 100)
    for slot in range(1, 7):
        for r in runes_by_slot[slot]:
            v = x[(slot, r.rune_id)]
            spd = _rune_flat_spd(r)
            if spd:
                speed_terms.append(spd * v)
            cr = _rune_stat_total(r, 9)
            if cr:
                cr_terms_all.append(cr * v)
            res = _rune_stat_total(r, 11)
            if res:
                res_terms_all.append(res * v)
            acc = _rune_stat_total(r, 12)
            if acc:
                acc_terms_all.append(acc * v)
            if int(r.set_id or 0) == 3:
                swift_piece_vars.append(v)

    swift_set_active = model.NewBoolVar(f"swift_set_u{uid}")
    swift_count = sum(swift_piece_vars) if swift_piece_vars else 0
    if swift_piece_vars:
        model.Add(swift_count >= 4).OnlyEnforceIf(swift_set_active)
        model.Add(swift_count <= 3).OnlyEnforceIf(swift_set_active.Not())
    else:
        model.Add(swift_set_active == 0)

    # Raw SPD for min-SPD constraints: base + runes (+swift), no tower, no leader.
    final_speed_raw_expr = (
        int(base_spd or 0)
        + sum(speed_terms)
        + (swift_bonus_value * swift_set_active)
    )
    # Combat SPD for turn-order/tick/caps: includes tower and leader.
    final_speed_expr = final_speed_raw_expr + int(base_spd_bonus_flat or 0)
    if min_final_speed is not None and int(min_final_speed) > 0:
        model.Add(final_speed_expr >= int(min_final_speed))
    if max_final_speed is not None and max_final_speed > 0:
        model.Add(final_speed_expr <= int(max_final_speed))

    for b_idx, b in enumerate(builds):
        vb = use_build[b_idx]
        spd_tick = int(getattr(b, "spd_tick", 0) or 0)
        min_spd_cfg = int((getattr(b, "min_stats", {}) or {}).get("SPD", 0) or 0)
        min_spd_no_base_cfg = int((getattr(b, "min_stats", {}) or {}).get("SPD_NO_BASE", 0) or 0)
        apply_native_spd_tick = str(mode or "").strip().lower() != "arena_rush"
        min_spd_tick = int(min_spd_for_tick(spd_tick, mode) or 0) if apply_native_spd_tick else 0
        if min_spd_cfg > 0:
            model.Add(final_speed_raw_expr >= min_spd_cfg).OnlyEnforceIf(vb)
        if min_spd_no_base_cfg > 0:
            model.Add(final_speed_raw_expr - int(base_spd or 0) >= min_spd_no_base_cfg).OnlyEnforceIf(vb)
        if min_spd_tick > 0:
            model.Add(final_speed_expr >= min_spd_tick).OnlyEnforceIf(vb)
        if apply_native_spd_tick and spd_tick != 0:
            max_spd_tick = int(max_spd_for_tick(spd_tick, mode) or 0)
            if max_spd_tick > 0:
                model.Add(final_speed_expr <= max_spd_tick).OnlyEnforceIf(vb)

    # Soft-penalty for wasted capped stats (CR/RES/ACC above 100).
    # Use slack vars with lower bounds only; objective minimizes them via negative weight.
    cr_total_var = model.NewIntVar(0, 500, f"stat_cr_total_u{uid}")
    model.Add(cr_total_var == int(base_cr or 0) + (sum(cr_terms_all) if cr_terms_all else 0))
    cr_over_var = model.NewIntVar(0, 400, f"stat_cr_overcap_u{uid}")
    model.Add(cr_over_var >= cr_total_var - int(STAT_OVERCAP_LIMIT))

    res_total_var = model.NewIntVar(0, 500, f"stat_res_total_u{uid}")
    model.Add(res_total_var == int(base_res or 0) + (sum(res_terms_all) if res_terms_all else 0))
    res_over_var = model.NewIntVar(0, 400, f"stat_res_overcap_u{uid}")
    model.Add(res_over_var >= res_total_var - int(STAT_OVERCAP_LIMIT))

    acc_total_var = model.NewIntVar(0, 500, f"stat_acc_total_u{uid}")
    model.Add(acc_total_var == int(base_acc or 0) + (sum(acc_terms_all) if acc_terms_all else 0))
    acc_over_var = model.NewIntVar(0, 400, f"stat_acc_overcap_u{uid}")
    model.Add(acc_over_var >= acc_total_var - int(STAT_OVERCAP_LIMIT))

    overcap_penalty_expr: cp_model.LinearExpr = (
        (int(CR_OVERCAP_PENALTY_PER_POINT) * cr_over_var)
        + (int(RES_OVERCAP_PENALTY_PER_POINT) * res_over_var)
        + (int(ACC_OVERCAP_PENALTY_PER_POINT) * acc_over_var)
    )

    # quality objective (2nd phase after speed is pinned)
    is_arena_rush_mode = str(mode or "").strip().lower() == "arena_rush"
    unit_role = _arena_role_from_archetype(str(unit_archetype or ""))
    artifact_role_for_scoring = str(unit_role)
    if artifact_role_for_scoring == "unknown":
        artifact_role_for_scoring = (
            "attack"
            if _is_attack_type_unit(base_hp, base_atk, base_def, archetype=str(unit_archetype or ""))
            else "support"
        )
    favor_damage_for_atk_type = (
        bool(arena_rush_damage_bias)
        and is_arena_rush_mode
        and str(unit_role) == "attack"
    )
    favor_defense_for_role = bool(
        is_arena_rush_mode
        and str(unit_role) in ("defense", "hp", "support")
    )
    scaling_stat = _scaling_stat_from_hints(artifact_hints)
    quality_terms = []
    for slot in range(1, 7):
        for r in runes_by_slot[slot]:
            v = x[(slot, r.rune_id)]
            if str(objective_mode) == "efficiency":
                if favor_damage_for_atk_type:
                    eff_scale = int(ARENA_RUSH_ATK_EFFICIENCY_SCALE)
                elif favor_defense_for_role:
                    eff_scale = int(ARENA_RUSH_DEF_EFFICIENCY_SCALE)
                else:
                    eff_scale = 100
                eff_bonus = int(round(float(rune_efficiency(r)) * float(eff_scale)))
                if eff_bonus:
                    quality_terms.append(eff_bonus * v)
                if favor_defense_for_role:
                    def_q = int(_rune_quality_score_defensive(r, uid, rta_rune_ids_for_unit))
                    if def_q:
                        quality_terms.append((int(ARENA_RUSH_DEF_QUALITY_WEIGHT) * def_q) * v)
                if favor_damage_for_atk_type:
                    dmg_bonus = _rune_damage_score_proxy(r, int(base_atk or 0))
                    if dmg_bonus:
                        quality_terms.append(dmg_bonus * v)
                if favor_defense_for_role:
                    def_bonus = _rune_defensive_score_proxy(
                        r,
                        int(base_hp or 0),
                        int(base_def or 0),
                        str(unit_archetype or ""),
                    )
                    if def_bonus:
                        quality_terms.append((int(ARENA_RUSH_DEF_RUNE_WEIGHT) * def_bonus) * v)
                    dmg_penalty = _rune_damage_score_proxy(r, int(base_atk or 0))
                    if dmg_penalty:
                        quality_terms.append(
                            (-int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(dmg_penalty)) * v
                        )
                scaling_bonus = int(
                    _rune_scaling_score_proxy(
                        r,
                        scaling_stat=str(scaling_stat),
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                    )
                )
                if scaling_bonus:
                    quality_terms.append((int(RUNE_SCALING_BONUS_WEIGHT) * scaling_bonus) * v)
            else:
                if favor_defense_for_role:
                    w = _rune_quality_score_defensive(r, uid, rta_rune_ids_for_unit)
                else:
                    w = _rune_quality_score(r, uid, rta_rune_ids_for_unit)
                quality_terms.append(w * v)
                if favor_damage_for_atk_type:
                    eff_weight = int(ARENA_RUSH_ATK_RUNE_EFF_WEIGHT)
                elif favor_defense_for_role:
                    eff_weight = int(ARENA_RUSH_DEF_EFFICIENCY_SCALE)
                else:
                    eff_weight = int(RUNE_EFFICIENCY_WEIGHT_SOLVER)
                eff_bonus = int(round(float(rune_efficiency(r)) * float(eff_weight)))
                if eff_bonus:
                    quality_terms.append(eff_bonus * v)
                if favor_damage_for_atk_type:
                    dmg_bonus = _rune_damage_score_proxy(r, int(base_atk or 0))
                    if dmg_bonus:
                        quality_terms.append(dmg_bonus * v)
                if favor_defense_for_role:
                    def_bonus = _rune_defensive_score_proxy(
                        r,
                        int(base_hp or 0),
                        int(base_def or 0),
                        str(unit_archetype or ""),
                    )
                    if def_bonus:
                        quality_terms.append((int(ARENA_RUSH_DEF_RUNE_WEIGHT) * def_bonus) * v)
                    dmg_penalty = _rune_damage_score_proxy(r, int(base_atk or 0))
                    if dmg_penalty:
                        quality_terms.append(
                            (-int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(dmg_penalty)) * v
                        )
                scaling_bonus = int(
                    _rune_scaling_score_proxy(
                        r,
                        scaling_stat=str(scaling_stat),
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                    )
                )
                if scaling_bonus:
                    quality_terms.append((int(RUNE_SCALING_BONUS_WEIGHT) * scaling_bonus) * v)
    for art_type in (1, 2):
        for art in artifacts_by_type[art_type]:
            av = xa[(art_type, int(art.artifact_id))]
            if str(objective_mode) == "efficiency":
                if favor_damage_for_atk_type:
                    eff_scale = int(ARENA_RUSH_ATK_EFFICIENCY_SCALE)
                elif favor_defense_for_role:
                    eff_scale = int(ARENA_RUSH_DEF_EFFICIENCY_SCALE)
                else:
                    eff_scale = 100
                art_eff_bonus = int(round(float(artifact_efficiency(art)) * float(eff_scale)))
                if art_eff_bonus:
                    quality_terms.append(art_eff_bonus * av)
                if favor_defense_for_role:
                    def_q = int(
                        _artifact_quality_score_defensive(
                            art,
                            uid,
                            rta_artifact_ids_for_unit,
                            archetype=str(unit_archetype or ""),
                            base_hp=int(base_hp or 0),
                            base_atk=int(base_atk or 0),
                            base_def=int(base_def or 0),
                            base_spd=int(base_spd or 0),
                        )
                    )
                    if def_q:
                        quality_terms.append((int(ARENA_RUSH_DEF_QUALITY_WEIGHT) * def_q) * av)
                if favor_damage_for_atk_type:
                    dmg_bonus = _artifact_damage_score_proxy(
                        art,
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                        base_spd=int(base_spd or 0),
                    )
                    if dmg_bonus:
                        quality_terms.append(dmg_bonus * av)
                if favor_defense_for_role:
                    def_bonus = _artifact_defensive_score_proxy(
                        art,
                        str(unit_archetype or ""),
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                        base_spd=int(base_spd or 0),
                    )
                    if def_bonus:
                        quality_terms.append((int(ARENA_RUSH_DEF_ART_WEIGHT) * def_bonus) * av)
                    dmg_penalty = _artifact_damage_score_proxy(
                        art,
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                        base_spd=int(base_spd or 0),
                    )
                    if dmg_penalty:
                        quality_terms.append(
                            (-int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(dmg_penalty)) * av
                        )
                if not favor_damage_for_atk_type and not favor_defense_for_role:
                    context_bonus = int(
                        _artifact_context_score_proxy(
                            art,
                            role=str(artifact_role_for_scoring),
                            base_hp=int(base_hp or 0),
                            base_atk=int(base_atk or 0),
                            base_def=int(base_def or 0),
                            base_spd=int(base_spd or 0),
                        )
                    )
                    if context_bonus:
                        quality_terms.append((int(ARTIFACT_ROLE_CONTEXT_WEIGHT) * context_bonus) * av)
            else:
                if favor_defense_for_role:
                    aw = _artifact_quality_score_defensive(
                        art,
                        uid,
                        rta_artifact_ids_for_unit,
                        archetype=str(unit_archetype or ""),
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                        base_spd=int(base_spd or 0),
                    )
                else:
                    aw = _artifact_quality_score(art, uid, rta_artifact_ids_for_unit)
                quality_terms.append(aw * av)
                if favor_damage_for_atk_type:
                    eff_weight = int(ARENA_RUSH_ATK_ART_EFF_WEIGHT)
                elif favor_defense_for_role:
                    eff_weight = int(ARENA_RUSH_DEF_EFFICIENCY_SCALE)
                else:
                    eff_weight = int(ARTIFACT_EFFICIENCY_WEIGHT_SOLVER)
                art_eff_bonus = int(round(float(artifact_efficiency(art)) * float(eff_weight)))
                if art_eff_bonus:
                    quality_terms.append(art_eff_bonus * av)
                if favor_damage_for_atk_type:
                    dmg_bonus = _artifact_damage_score_proxy(
                        art,
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                        base_spd=int(base_spd or 0),
                    )
                    if dmg_bonus:
                        quality_terms.append(dmg_bonus * av)
                if favor_defense_for_role:
                    def_bonus = _artifact_defensive_score_proxy(
                        art,
                        str(unit_archetype or ""),
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                        base_spd=int(base_spd or 0),
                    )
                    if def_bonus:
                        quality_terms.append((int(ARENA_RUSH_DEF_ART_WEIGHT) * def_bonus) * av)
                    dmg_penalty = _artifact_damage_score_proxy(
                        art,
                        base_hp=int(base_hp or 0),
                        base_atk=int(base_atk or 0),
                        base_def=int(base_def or 0),
                        base_spd=int(base_spd or 0),
                    )
                    if dmg_penalty:
                        quality_terms.append(
                            (-int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(dmg_penalty)) * av
                        )
                if not favor_damage_for_atk_type and not favor_defense_for_role:
                    context_bonus = int(
                        _artifact_context_score_proxy(
                            art,
                            role=str(artifact_role_for_scoring),
                            base_hp=int(base_hp or 0),
                            base_atk=int(base_atk or 0),
                            base_def=int(base_def or 0),
                            base_spd=int(base_spd or 0),
                        )
                    )
                    if context_bonus:
                        quality_terms.append((int(ARTIFACT_ROLE_CONTEXT_WEIGHT) * context_bonus) * av)
            hint_bonus = int(_artifact_hint_score(art, artifact_hints))
            if hint_bonus:
                quality_terms.append(hint_bonus * av)
            scaling_bonus = int(_artifact_scaling_score_proxy(art, scaling_stat=str(scaling_stat)))
            if scaling_bonus:
                quality_terms.append((int(ARTIFACT_SCALING_BONUS_WEIGHT) * scaling_bonus) * av)

    if apply_rune_set_fallback and fallback_rune_set_ids:
        for rank, sid in enumerate(fallback_rune_set_ids[:3]):
            set_vars = list(set_choice_vars.get(int(sid), []) or [])
            if not set_vars:
                continue
            piece_bonus = int(_RUNE_SET_HINT_PIECE_BONUS_BY_RANK[min(rank, len(_RUNE_SET_HINT_PIECE_BONUS_BY_RANK) - 1)])
            full_bonus = int(_RUNE_SET_HINT_FULL_BONUS_BY_RANK[min(rank, len(_RUNE_SET_HINT_FULL_BONUS_BY_RANK) - 1)])
            if piece_bonus > 0:
                quality_terms.append(int(piece_bonus) * sum(set_vars))
            needed = int(SET_SIZES.get(int(sid), 2) or 2)
            if full_bonus > 0 and needed > 0:
                count_expr = sum(set_vars)
                full_var = model.NewBoolVar(f"hint_set_full_u{uid}_s{int(sid)}_r{int(rank)}")
                model.Add(count_expr >= int(needed)).OnlyEnforceIf(full_var)
                model.Add(count_expr <= int(max(0, int(needed) - 1))).OnlyEnforceIf(full_var.Not())
                quality_terms.append(int(full_bonus) * full_var)

    # Unit-level critical hint satisfaction:
    # reward selecting at least one artifact carrying each critical effect
    # (e.g. Bomb DMG, Skill 2 Accuracy) when available in candidate pool.
    critical_hint_eids = _artifact_hint_critical_effect_ids(artifact_hints)
    if critical_hint_eids:
        for rank, eff_id in enumerate(critical_hint_eids[:4]):
            idx = min(rank, len(ARTIFACT_HINT_CRITICAL_HIT_BONUS_PER_COUNT_BY_RANK) - 1)
            per_hit_bonus = int(ARTIFACT_HINT_CRITICAL_HIT_BONUS_PER_COUNT_BY_RANK[idx])
            target_hits = int(ARTIFACT_HINT_CRITICAL_TARGET_COUNT_BY_RANK[idx])
            shortfall_penalty = int(ARTIFACT_HINT_CRITICAL_SHORTFALL_PENALTY_BY_RANK[idx])
            per_roll_bonus = int(ARTIFACT_HINT_CRITICAL_ROLL_BONUS_PER_ROLL_BY_RANK[idx])
            target_roll_sum = int(ARTIFACT_HINT_CRITICAL_TARGET_ROLL_SUM_BY_RANK[idx])
            roll_shortfall_penalty = int(ARTIFACT_HINT_CRITICAL_ROLL_SHORTFALL_PENALTY_BY_RANK[idx])
            hit_vars: List[cp_model.IntVar] = []
            roll_terms: List[cp_model.LinearExpr] = []
            for art_type in (1, 2):
                for art in artifacts_by_type[art_type]:
                    if int(_artifact_effect_value_scaled(art, int(eff_id))) <= 0:
                        continue
                    av = xa[(art_type, int(art.artifact_id))]
                    hit_vars.append(av)
                    rolls = int(_artifact_effect_roll_count(art, int(eff_id)))
                    if rolls > 0:
                        roll_terms.append(int(rolls) * av)
            if not hit_vars:
                continue
            hit_count = model.NewIntVar(0, 2, f"hint_cnt_u{uid}_e{int(eff_id)}_r{int(rank)}")
            model.Add(hit_count == sum(hit_vars))
            if per_hit_bonus > 0:
                quality_terms.append(int(per_hit_bonus) * hit_count)
            if target_hits > 0 and shortfall_penalty > 0:
                shortfall = model.NewIntVar(0, int(target_hits), f"hint_short_u{uid}_e{int(eff_id)}_r{int(rank)}")
                model.Add(shortfall >= int(target_hits) - hit_count)
                quality_terms.append((-int(shortfall_penalty)) * shortfall)
            if roll_terms:
                roll_sum = model.NewIntVar(0, 20, f"hint_roll_u{uid}_e{int(eff_id)}_r{int(rank)}")
                model.Add(roll_sum == sum(roll_terms))
                if per_roll_bonus > 0:
                    quality_terms.append(int(per_roll_bonus) * roll_sum)
                if target_roll_sum > 0 and roll_shortfall_penalty > 0:
                    roll_shortfall = model.NewIntVar(0, int(target_roll_sum), f"hint_roll_short_u{uid}_e{int(eff_id)}_r{int(rank)}")
                    model.Add(roll_shortfall >= int(target_roll_sum) - roll_sum)
                    quality_terms.append((-int(roll_shortfall_penalty)) * roll_shortfall)

    # Build-aware artifact quality:
    # if artifact filters are selected, prefer higher rolls in those selected effects.
    for b_idx, b in enumerate(builds):
        vb = use_build[b_idx]
        artifact_focus_cfg = dict(getattr(b, "artifact_focus", {}) or {})
        artifact_sub_cfg = dict(getattr(b, "artifact_substats", {}) or {})
        for art_type, cfg_key in ((1, "attribute"), (2, "type")):
            allowed_focus = [str(x).upper() for x in (artifact_focus_cfg.get(cfg_key) or []) if str(x)]
            preferred_subs = [int(x) for x in (artifact_sub_cfg.get(cfg_key) or []) if int(x) > 0][:2]
            if not allowed_focus and not preferred_subs:
                continue

            for art in artifacts_by_type[art_type]:
                aid = int(art.artifact_id)
                av = xa[(art_type, aid)]
                bonus = 0

                if allowed_focus and _artifact_focus_key(art) in allowed_focus:
                    bonus += ARTIFACT_BUILD_FOCUS_BONUS

                for req_id in preferred_subs:
                    val_scaled = _artifact_effect_value_scaled(art, req_id)
                    if val_scaled > 0:
                        bonus += ARTIFACT_BUILD_MATCH_BONUS + (val_scaled * ARTIFACT_BUILD_VALUE_WEIGHT)

                if bonus <= 0:
                    continue

                z = model.NewBoolVar(f"qab_u{uid}_b{b_idx}_t{art_type}_a{aid}")
                model.Add(z <= av)
                model.Add(z <= vb)
                model.Add(z >= av + vb - 1)
                quality_terms.append(bonus * z)

    for b_idx, b in enumerate(builds):
        if str(objective_mode) == "efficiency":
            quality_terms.append((-int(b.priority) * int(max(20, build_priority_penalty // 3))) * use_build[b_idx])
        else:
            quality_terms.append((-int(b.priority) * int(build_priority_penalty)) * use_build[b_idx])
    quality_terms.extend(option_bias_terms)
    if avoid_runes_by_slot and int(avoid_same_rune_penalty) > 0:
        for slot, rid in avoid_runes_by_slot.items():
            key = (int(slot), int(rid))
            if key in x:
                quality_terms.append((-int(avoid_same_rune_penalty)) * x[key])
    if avoid_artifacts_by_type and int(avoid_same_artifact_penalty) > 0:
        for art_type, aid in avoid_artifacts_by_type.items():
            akey = (int(art_type), int(aid))
            if akey in xa:
                quality_terms.append((-int(avoid_same_artifact_penalty)) * xa[akey])
    quality_terms.append((-int(SINGLE_SOLVER_OVERCAP_PENALTY_SCALE)) * overcap_penalty_expr)

    guard_weight = int(max(0, int(baseline_regression_guard_weight or 0)))
    if guard_weight > 0:
        baseline_slots = {
            int(slot): int(rid)
            for slot, rid in dict(baseline_runes_by_slot or {}).items()
            if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
        }
        baseline_arts = {
            int(t): int(aid)
            for t, aid in dict(baseline_artifacts_by_type or {}).items()
            if int(t or 0) in (1, 2) and int(aid or 0) > 0
        }
        if len(baseline_slots) == 6 and len(baseline_arts) == 2:
            guard_role = str(unit_role)
            if guard_role == "unknown":
                guard_role = (
                    "attack"
                    if _is_attack_type_unit(base_hp, base_atk, base_def, archetype=str(unit_archetype or ""))
                    else "support"
                )
            baseline_runes: List[Rune] = []
            baseline_ok = True
            for slot in range(1, 7):
                rid = int(baseline_slots.get(int(slot), 0) or 0)
                key = (int(slot), int(rid))
                if rid <= 0 or key not in x:
                    baseline_ok = False
                    break
                ref = next((rr for rr in runes_by_slot[int(slot)] if int(rr.rune_id or 0) == int(rid)), None)
                if ref is None:
                    baseline_ok = False
                    break
                baseline_runes.append(ref)
            baseline_artifacts: List[Artifact] = []
            if baseline_ok:
                for art_type in (1, 2):
                    aid = int(baseline_arts.get(int(art_type), 0) or 0)
                    akey = (int(art_type), int(aid))
                    if aid <= 0 or akey not in xa:
                        baseline_ok = False
                        break
                    aref = next(
                        (aa for aa in artifacts_by_type[int(art_type)] if int(aa.artifact_id or 0) == int(aid)),
                        None,
                    )
                    if aref is None:
                        baseline_ok = False
                        break
                    baseline_artifacts.append(aref)
            if baseline_ok:
                guard_terms: List[cp_model.LinearExpr] = []
                for slot in range(1, 7):
                    for r in runes_by_slot[slot]:
                        coef = int(
                            _baseline_guard_rune_coef(
                                r,
                                uid=uid,
                                base_hp=int(base_hp or 0),
                                base_atk=int(base_atk or 0),
                                base_def=int(base_def or 0),
                                role=str(guard_role),
                                rta_rune_ids_for_unit=rta_rune_ids_for_unit,
                            )
                        )
                        if coef != 0:
                            guard_terms.append(coef * x[(slot, int(r.rune_id))])
                for art_type in (1, 2):
                    for art in artifacts_by_type[art_type]:
                        coef = int(
                            _baseline_guard_artifact_coef(
                                art,
                                uid=uid,
                                role=str(guard_role),
                                rta_artifact_ids_for_unit=rta_artifact_ids_for_unit,
                                base_hp=int(base_hp or 0),
                                base_atk=int(base_atk or 0),
                                base_def=int(base_def or 0),
                                base_spd=int(base_spd or 0),
                            )
                        )
                        if coef != 0:
                            guard_terms.append(coef * xa[(int(art_type), int(art.artifact_id))])
                guard_expr = (sum(guard_terms) if guard_terms else 0) - (
                    int(SINGLE_SOLVER_OVERCAP_PENALTY_SCALE) * overcap_penalty_expr
                )
                baseline_guard_score = 0
                baseline_cr_total = int(base_cr or 0)
                baseline_res_total = int(base_res or 0)
                baseline_acc_total = int(base_acc or 0)
                for r in baseline_runes:
                    baseline_guard_score += int(
                        _baseline_guard_rune_coef(
                            r,
                            uid=uid,
                            base_hp=int(base_hp or 0),
                            base_atk=int(base_atk or 0),
                            base_def=int(base_def or 0),
                            role=str(guard_role),
                            rta_rune_ids_for_unit=rta_rune_ids_for_unit,
                        )
                    )
                    baseline_cr_total += int(_rune_stat_total(r, 9) or 0)
                    baseline_res_total += int(_rune_stat_total(r, 11) or 0)
                    baseline_acc_total += int(_rune_stat_total(r, 12) or 0)
                for art in baseline_artifacts:
                    baseline_guard_score += int(
                        _baseline_guard_artifact_coef(
                            art,
                            uid=uid,
                            role=str(guard_role),
                            rta_artifact_ids_for_unit=rta_artifact_ids_for_unit,
                            base_hp=int(base_hp or 0),
                            base_atk=int(base_atk or 0),
                            base_def=int(base_def or 0),
                            base_spd=int(base_spd or 0),
                        )
                    )
                baseline_over = (
                    (int(CR_OVERCAP_PENALTY_PER_POINT) * max(0, int(baseline_cr_total) - int(STAT_OVERCAP_LIMIT)))
                    + (int(RES_OVERCAP_PENALTY_PER_POINT) * max(0, int(baseline_res_total) - int(STAT_OVERCAP_LIMIT)))
                    + (int(ACC_OVERCAP_PENALTY_PER_POINT) * max(0, int(baseline_acc_total) - int(STAT_OVERCAP_LIMIT)))
                )
                baseline_guard_score -= int(SINGLE_SOLVER_OVERCAP_PENALTY_SCALE) * int(baseline_over)
                shortfall_cap = max(200000, abs(int(baseline_guard_score)) + 200000)
                guard_shortfall = model.NewIntVar(0, int(shortfall_cap), f"baseline_guard_shortfall_u{uid}")
                model.Add(guard_shortfall >= int(baseline_guard_score) - guard_expr)
                quality_terms.append((-int(guard_weight)) * guard_shortfall)

    solver = cp_model.CpSolver()
    if register_solver:
        try:
            register_solver(solver)
        except Exception:
            pass
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = int(workers)

    if is_cancelled and is_cancelled():
        return GreedyUnitResult(uid, False, tr("opt.cancelled"), runes_by_slot={})

    if speed_hard_priority or bool(force_speed_priority):
        model.Maximize(final_speed_expr)
        status = solver.Solve(model)
        if is_cancelled and is_cancelled():
            return GreedyUnitResult(uid, False, tr("opt.cancelled"), runes_by_slot={})
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            best_speed = int(solver.Value(final_speed_expr))
            keep_speed_min = int(best_speed)
            if not bool(force_speed_priority):
                keep_speed_min = max(0, int(best_speed) - max(0, int(speed_slack_for_quality)))
            # Keep speed near optimum but allow small slack so quality can win.
            model.Add(final_speed_expr >= keep_speed_min)
            model.Maximize(sum(quality_terms) + (int(speed_tiebreak_weight) * final_speed_expr))
            status = solver.Solve(model)
            if is_cancelled and is_cancelled():
                return GreedyUnitResult(uid, False, tr("opt.cancelled"), runes_by_slot={})
    else:
        if str(objective_mode) == "efficiency":
            # In refinement we prioritize efficiency; speed only breaks ties.
            model.Maximize((sum(quality_terms) * 1000) + (int(speed_tiebreak_weight) * final_speed_expr))
        else:
            model.Maximize(sum(quality_terms) + (int(speed_weight_soft) * final_speed_expr))
        status = solver.Solve(model)
        if is_cancelled and is_cancelled():
            return GreedyUnitResult(uid, False, tr("opt.cancelled"), runes_by_slot={})

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        detail = _diagnose_single_unit_infeasible(pool, artifact_pool, builds)
        if str(detail) == str(tr("opt.feasible")):
            detail = (
                f"{detail}; harte Constraints nicht erfuellbar "
                f"(z. B. Min-Stats/SPD-Tick/Turnorder-Speed-Caps/Locks)"
            )
        return GreedyUnitResult(uid, False, f"infeasible ({detail})", runes_by_slot={})

    # extract build
    chosen_build = builds[0]
    for b_idx, b in enumerate(builds):
        if solver.Value(use_build[b_idx]) == 1:
            chosen_build = b
            break

    chosen: Dict[int, int] = {}
    for slot in range(1, 7):
        rid = None
        for r in runes_by_slot[slot]:
            if solver.Value(x[(slot, r.rune_id)]) == 1:
                rid = r.rune_id
                break
        if rid is None:
            return GreedyUnitResult(uid, False, tr("opt.internal_no_rune", slot=slot), runes_by_slot={})
        chosen[slot] = rid

    chosen_artifacts: Dict[int, int] = {}
    for art_type in (1, 2):
        aid = None
        for art in artifacts_by_type[art_type]:
            if solver.Value(xa[(art_type, int(art.artifact_id))]) == 1:
                aid = int(art.artifact_id)
                break
        if aid is None:
            return GreedyUnitResult(uid, False, tr("opt.internal_no_artifact", art_type=art_type), runes_by_slot={})
        chosen_artifacts[art_type] = aid

    return GreedyUnitResult(
        unit_id=uid,
        ok=True,
        message="OK",
        chosen_build_id=chosen_build.id,
        chosen_build_name=chosen_build.name,
        runes_by_slot=chosen,
        artifacts_by_type=chosen_artifacts,
        final_speed=int(solver.Value(final_speed_expr)),
    )


def _reorder_for_turn_order(req: GreedyRequest, unit_ids: List[int]) -> List[int]:
    # When enforce_turn_order is active, reorder units within each team
    # so that lower turn_order values are optimized first.  This ensures
    # the speed cap mechanism works correctly (unit with turn_order=1 is
    # optimized first -> gets fastest runes -> turn_order=2 is capped below it).
    if req.enforce_turn_order and req.unit_team_index and req.unit_team_turn_order:
        team_queues: Dict[int, List[int]] = {}
        for uid in unit_ids:
            team = req.unit_team_index.get(int(uid))
            if team is not None:
                team_queues.setdefault(int(team), []).append(int(uid))
        for team in team_queues:
            orig = list(team_queues[team])
            orig_pos: Dict[int, int] = {int(u): idx for idx, u in enumerate(orig)}
            team_queues[team].sort(
                key=lambda u, _pos=orig_pos: (
                    int(req.unit_team_turn_order.get(u, 0) or 0) or 999,
                    int(_pos.get(int(u), 10**9)),
                )
            )
        team_iters: Dict[int, int] = {t: 0 for t in team_queues}
        reordered: List[int] = []
        for uid in unit_ids:
            team = req.unit_team_index.get(int(uid))
            if team is not None and int(team) in team_queues:
                t = int(team)
                reordered.append(team_queues[t][team_iters[t]])
                team_iters[t] += 1
            else:
                reordered.append(int(uid))
        return reordered
    return list(unit_ids)


def _build_pass_orders(base_unit_ids: List[int], pass_count: int) -> List[List[int]]:
    out: List[List[int]] = []
    seen: Set[Tuple[int, ...]] = set()
    n = len(base_unit_ids)
    if n == 0:
        return out

    def _push(order: List[int]) -> None:
        key = tuple(int(x) for x in order)
        if key in seen:
            return
        seen.add(key)
        out.append(list(order))

    _push(base_unit_ids)
    if n > 1:
        _push(list(reversed(base_unit_ids)))

    shift = 1
    while len(out) < max(1, int(pass_count)) and shift < n:
        rotated = base_unit_ids[shift:] + base_unit_ids[:shift]
        _push(rotated)
        if len(out) < max(1, int(pass_count)):
            _push(list(reversed(rotated)))
        shift += 1

    return out[:max(1, int(pass_count))]


def _evaluate_pass_score(
    account: AccountData,
    req: GreedyRequest,
    results: List[GreedyUnitResult],
) -> Tuple[int, int, int, int, int, int, int]:
    runes_by_id = account.runes_by_id()
    artifacts_by_id: Dict[int, Artifact] = {int(a.artifact_id): a for a in account.artifacts}
    rta_equip = account.rta_rune_equip if req.mode == "rta" else {}
    rta_art_equip = account.rta_artifact_equip if req.mode == "rta" else {}

    ok_count = 0
    unit_scores: List[int] = []
    total_eff_scaled = 0
    speed_sum = 0
    unit_speed_by_uid: Dict[int, int] = {}
    for res in results:
        if not res.ok or not res.runes_by_slot:
            continue
        uid = int(res.unit_id)
        unit = account.units_by_id.get(int(uid))
        base_hp = int((unit.base_con or 0) * 15) if unit else 0
        base_atk = int(unit.base_atk or 0) if unit else 0
        base_def = int(unit.base_def or 0) if unit else 0
        base_spd = int(unit.base_spd or 0) if unit else 0
        unit_arch = str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
        role_for_art = _arena_role_from_archetype(unit_arch)
        if role_for_art == "unknown":
            role_for_art = (
                "attack"
                if _is_attack_type_unit(base_hp, base_atk, base_def, archetype=unit_arch)
                else "support"
            )
        rta_rids: Optional[Set[int]] = None
        if rta_equip:
            rta_rids = set(int(rid) for rid in rta_equip.get(uid, []))
        rta_aids: Optional[Set[int]] = None
        if rta_art_equip:
            rta_aids = set(int(aid) for aid in rta_art_equip.get(uid, []))
        unit_quality = 0
        unit_eff_scaled = 0
        for rid in res.runes_by_slot.values():
            rune = runes_by_id.get(int(rid))
            if rune is None:
                continue
            unit_quality += _rune_quality_score(rune, uid, rta_rids)
            unit_eff_scaled += int(round(float(rune_efficiency(rune)) * 10.0))
        for aid in (res.artifacts_by_type or {}).values():
            art = artifacts_by_id.get(int(aid))
            if art is None:
                continue
            eval_hints = dict((req.unit_artifact_hints_by_uid or {}).get(int(uid), {}) or {})
            team_spd_map = dict(req.unit_team_has_spd_buff_by_uid or {})
            if int(uid) in team_spd_map:
                eval_hints["team_has_spd_buff"] = bool(team_spd_map.get(int(uid), False))
            eval_hints = _sanitize_artifact_hints_for_team_context(eval_hints)
            unit_quality += _artifact_quality_score(art, uid, rta_aids)
            unit_quality += int(
                ARTIFACT_ROLE_CONTEXT_WEIGHT
                * _artifact_context_score_proxy(
                    art,
                    role=str(role_for_art),
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    base_spd=int(base_spd or 0),
                )
            )
            unit_quality += int(
                _artifact_hint_score(
                    art,
                    dict(eval_hints),
                )
            )
            unit_eff_scaled += int(round(float(artifact_efficiency(art)) * 10.0))
        ok_count += 1
        unit_scores.append(int(unit_quality))
        total_eff_scaled += int(unit_eff_scaled)
        speed_sum += int(res.final_speed or 0)
        unit_speed_by_uid[uid] = int(res.final_speed or 0)

    gap_excess_squared = 0
    if req.enforce_turn_order and req.unit_team_index and req.unit_team_turn_order and unit_speed_by_uid:
        team_rows: Dict[int, List[Tuple[int, int]]] = {}
        for uid, spd in unit_speed_by_uid.items():
            team = req.unit_team_index.get(int(uid))
            turn = int(req.unit_team_turn_order.get(int(uid), 0) or 0)
            if team is None or turn <= 0:
                continue
            team_rows.setdefault(int(team), []).append((turn, int(spd)))
        for rows in team_rows.values():
            rows.sort(key=lambda x: int(x[0]))
            for i in range(1, len(rows)):
                prev_spd = int(rows[i - 1][1])
                cur_spd = int(rows[i][1])
                # Legal minimum is 1 SPD gap; penalize anything beyond that.
                excess = max(0, (prev_spd - cur_spd) - 1)
                gap_excess_squared += int(excess * excess)

    # Score ordering:
    # 1) as many successful units as possible
    # 2) maximize effective quality (total quality minus turn-gap penalty)
    # 3) maximize total quality
    # 4) maximize average quality (scaled int) for stability if success count differs
    # 5) minimize excessive turn gaps (direct tie-break)
    # 6) maximize weakest successful unit (fairness tie-break)
    # 7) maximize total speed (final tie-break)
    min_unit_quality = min(unit_scores) if unit_scores else -10**9
    total_quality = sum(unit_scores)
    avg_quality_scaled = int((total_quality * 1000) / max(1, ok_count))
    effective_quality = int(
        total_quality
        + (int(total_eff_scaled) * int(PASS_EFFICIENCY_WEIGHT))
        - (gap_excess_squared * TURN_ORDER_GAP_PENALTY_WEIGHT)
    )
    return (
        int(ok_count),
        int(effective_quality),
        int(total_quality),
        int(avg_quality_scaled),
        int(-gap_excess_squared),
        int(min_unit_quality),
        int(speed_sum),
    )


def _run_pass_with_profile(
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
    unit_ids: List[int],
    time_limit_per_unit_s: float,
    speed_hard_priority: bool,
    build_priority_penalty: int,
    set_option_preference_offset_base: int = 0,
    set_option_preference_bonus: int = 0,
    avoid_solution_by_unit: Optional[Dict[int, GreedyUnitResult]] = None,
    avoid_same_rune_penalty: int = 0,
    avoid_same_artifact_penalty: int = 0,
    speed_slack_for_quality: int = 0,
    objective_mode: str = "balanced",
    rune_top_per_set_override: Optional[int] = None,
) -> List[GreedyUnitResult]:
    unit_ids = _reorder_for_turn_order(req, unit_ids)

    # initial pool
    pool = _allowed_runes_for_mode(account, req, unit_ids, rune_top_per_set_override=rune_top_per_set_override)
    artifact_pool = _allowed_artifacts_for_mode(account, unit_ids, req=req)
    # Reserve fixed assignments for their owner unit so no other unit can consume them.
    reserved_rune_owner: Dict[int, int] = {}
    for owner_uid, by_slot in dict(req.unit_fixed_runes_by_slot or {}).items():
        ou = int(owner_uid or 0)
        if ou <= 0:
            continue
        for rid in (dict(by_slot or {})).values():
            ri = int(rid or 0)
            if ri > 0:
                reserved_rune_owner[ri] = ou
    reserved_artifact_owner: Dict[int, int] = {}
    for owner_uid, by_type in dict(req.unit_fixed_artifacts_by_type or {}).items():
        ou = int(owner_uid or 0)
        if ou <= 0:
            continue
        for aid in (dict(by_type or {})).values():
            ai = int(aid or 0)
            if ai > 0:
                reserved_artifact_owner[ai] = ou
    blocked: Set[int] = set(reserved_rune_owner.keys())  # rune_id
    blocked_artifacts: Set[int] = set(reserved_artifact_owner.keys())  # artifact_id

    # For RTA mode, build lookup of RTA-equipped rune IDs per unit
    rta_equip = account.rta_rune_equip if req.mode == "rta" else {}
    rta_art_equip = account.rta_artifact_equip if req.mode == "rta" else {}

    results: List[GreedyUnitResult] = []

    for unit_pos, uid in enumerate(unit_ids):
        if req.is_cancelled and req.is_cancelled():
            break
        cur_pool = [
            r for r in pool
            if (r.rune_id not in blocked) or (int(reserved_rune_owner.get(int(r.rune_id), 0)) == int(uid))
        ]
        cur_art_pool = [
            a for a in artifact_pool
            if (int(a.artifact_id or 0) not in blocked_artifacts)
            or (int(reserved_artifact_owner.get(int(a.artifact_id or 0), 0)) == int(uid))
        ]
        unit = account.units_by_id.get(uid)
        base_hp = int((unit.base_con or 0) * 15) if unit else 0
        base_atk = int(unit.base_atk or 0) if unit else 0
        base_def = int(unit.base_def or 0) if unit else 0
        base_spd = int(unit.base_spd or 0) if unit else 0
        totem_spd_bonus_flat = int(base_spd * int(account.sky_tribe_totem_spd_pct or 0) / 100)
        leader_spd_bonus_flat = int((req.unit_spd_leader_bonus_flat or {}).get(int(uid), 0) or 0)
        base_spd_bonus_flat = int(totem_spd_bonus_flat + leader_spd_bonus_flat)
        base_cr = int(unit.crit_rate or 15) if unit else 15
        base_cd = int(unit.crit_dmg or 50) if unit else 50
        base_res = int(unit.base_res or 15) if unit else 15
        base_acc = int(unit.base_acc or 0) if unit else 0
        max_speed_cap: Optional[int] = None
        min_speed_floor: Optional[int] = None
        if req.enforce_turn_order:
            team_idx_map = req.unit_team_index or {}
            team_turn_map = req.unit_team_turn_order or {}
            my_team = team_idx_map.get(int(uid))
            my_turn = int(team_turn_map.get(int(uid), 0) or 0)
            if my_team is not None and my_turn > 1:
                prev_caps: List[int] = []
                for prev in results:
                    if not prev.ok:
                        continue
                    puid = int(prev.unit_id)
                    if team_idx_map.get(puid) != my_team:
                        continue
                    pturn = int(team_turn_map.get(puid, 0) or 0)
                    if pturn > 0 and pturn < my_turn and int(prev.final_speed or 0) > 1:
                        prev_caps.append(int(prev.final_speed) - 1)
                if prev_caps:
                    max_speed_cap = min(prev_caps)
        min_floor_map = dict(req.unit_min_final_speed or {})
        min_speed_value = int(min_floor_map.get(int(uid), 0) or 0)
        if min_speed_value > 0:
            min_speed_floor = int(min_speed_value)
        max_cap_map = dict(req.unit_max_final_speed or {})
        max_speed_value = int(max_cap_map.get(int(uid), 0) or 0)
        if max_speed_value > 0:
            if max_speed_cap is None:
                max_speed_cap = int(max_speed_value)
            else:
                max_speed_cap = min(int(max_speed_cap), int(max_speed_value))

        # RTA mode: pass RTA-equipped rune IDs for scoring preference
        rta_rids: Optional[Set[int]] = None
        if rta_equip:
            rta_rids = set(int(rid) for rid in rta_equip.get(uid, []))
        rta_aids: Optional[Set[int]] = None
        if rta_art_equip:
            rta_aids = set(int(aid) for aid in rta_art_equip.get(uid, []))

        builds = presets.get_unit_builds(req.mode, uid)
        # IMPORTANT: greedy feels more SWOP-like if we sort builds by priority ascending
        builds = sorted(builds, key=lambda b: int(b.priority))
        avoid_ref = (avoid_solution_by_unit or {}).get(int(uid))
        force_speed_priority = _force_swift_speed_priority(req, uid, builds)
        speed_tie_raw = (req.unit_speed_tiebreak_weight or {}).get(int(uid), None)
        speed_tiebreak_weight = 1 if speed_tie_raw is None else int(speed_tie_raw)
        unit_speed_hard_priority = bool(speed_hard_priority) and int(speed_tiebreak_weight) > 0
        fixed_runes_by_slot = dict(((req.unit_fixed_runes_by_slot or {}).get(int(uid), {}) or {}))
        fixed_artifacts_by_type = dict(((req.unit_fixed_artifacts_by_type or {}).get(int(uid), {}) or {}))
        baseline_runes_by_slot = dict(((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {}))
        baseline_artifacts_by_type = dict(((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {}))
        artifact_hints_for_unit = dict((req.unit_artifact_hints_by_uid or {}).get(int(uid), {}) or {})
        team_spd_map = dict(req.unit_team_has_spd_buff_by_uid or {})
        if int(uid) in team_spd_map:
            artifact_hints_for_unit["team_has_spd_buff"] = bool(team_spd_map.get(int(uid), False))
        artifact_hints_for_unit = _sanitize_artifact_hints_for_team_context(artifact_hints_for_unit)

        r = _solve_single_unit_best(
            uid=uid,
            pool=cur_pool,
            artifact_pool=cur_art_pool,
            builds=builds,
            time_limit_s=float(time_limit_per_unit_s),
            workers=req.workers,
            base_hp=base_hp,
            base_atk=base_atk,
            base_def=base_def,
            base_spd=base_spd,
            base_spd_bonus_flat=base_spd_bonus_flat,
            base_cr=base_cr,
            base_cd=base_cd,
            base_res=base_res,
            base_acc=base_acc,
            max_final_speed=max_speed_cap,
            min_final_speed=min_speed_floor,
            rta_rune_ids_for_unit=rta_rids,
            rta_artifact_ids_for_unit=rta_aids,
            speed_hard_priority=unit_speed_hard_priority,
            speed_weight_soft=(int(SOFT_SPEED_WEIGHT) * int(speed_tiebreak_weight)),
            speed_tiebreak_weight=int(speed_tiebreak_weight),
            build_priority_penalty=build_priority_penalty,
            set_option_preference_offset=int(set_option_preference_offset_base) + int(unit_pos),
            set_option_preference_bonus=int(set_option_preference_bonus),
            fixed_runes_by_slot=fixed_runes_by_slot,
            fixed_artifacts_by_type=fixed_artifacts_by_type,
            baseline_runes_by_slot=baseline_runes_by_slot,
            baseline_artifacts_by_type=baseline_artifacts_by_type,
            baseline_regression_guard_weight=int(
                getattr(req, "baseline_regression_guard_weight", BASELINE_REGRESSION_GUARD_WEIGHT)
                or 0
            ),
            avoid_runes_by_slot=dict((avoid_ref.runes_by_slot or {})) if avoid_ref else None,
            avoid_artifacts_by_type=dict((avoid_ref.artifacts_by_type or {})) if avoid_ref else None,
            avoid_same_rune_penalty=int(avoid_same_rune_penalty),
            avoid_same_artifact_penalty=int(avoid_same_artifact_penalty),
            speed_slack_for_quality=int(speed_slack_for_quality),
            objective_mode=str(objective_mode),
            force_speed_priority=bool(force_speed_priority),
            arena_rush_damage_bias=(
                str(getattr(req, "arena_rush_context", "") or "").strip().lower() == "offense"
            ),
            unit_archetype=str((req.unit_archetype_by_uid or {}).get(int(uid), "") or ""),
            artifact_hints=dict(artifact_hints_for_unit),
            is_cancelled=req.is_cancelled,
            register_solver=req.register_solver,
            mode=str(req.mode),
        )
        if str(r.message or "") == tr("opt.cancelled"):
            break
        results.append(r)

        if r.ok and r.runes_by_slot:
            for rid in r.runes_by_slot.values():
                blocked.add(int(rid))
            for aid in (r.artifacts_by_type or {}).values():
                blocked_artifacts.add(int(aid))
        else:
            # SWOP-like: keep going, but mark as failed
            # (alternativ: break; wenn du "alles muss klappen" willst)
            pass
    return results


def _run_greedy_pass(
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
    unit_ids: List[int],
    time_limit_per_unit_s: float,
    speed_slack_for_quality: int = 0,
    rune_top_per_set_override: Optional[int] = None,
) -> List[GreedyUnitResult]:
    return _run_pass_with_profile(
        account=account,
        presets=presets,
        req=req,
        unit_ids=unit_ids,
        time_limit_per_unit_s=time_limit_per_unit_s,
        speed_hard_priority=True,
        build_priority_penalty=DEFAULT_BUILD_PRIORITY_PENALTY,
        set_option_preference_offset_base=0,
        set_option_preference_bonus=0,
        speed_slack_for_quality=max(0, int(speed_slack_for_quality)),
        objective_mode="balanced",
        rune_top_per_set_override=rune_top_per_set_override,
    )


def _results_signature(
    results: List[GreedyUnitResult],
) -> Tuple[Tuple[int, bool, Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...], int, str], ...]:
    sig: List[Tuple[int, bool, Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...], int, str]] = []
    for r in results:
        runes = tuple(
            (int(slot), int(rid))
            for slot, rid in sorted((r.runes_by_slot or {}).items(), key=lambda x: int(x[0]))
        )
        arts = tuple(
            (int(kind), int(aid))
            for kind, aid in sorted((r.artifacts_by_type or {}).items(), key=lambda x: int(x[0]))
        )
        sig.append(
            (
                int(r.unit_id),
                bool(r.ok),
                runes,
                arts,
                int(r.final_speed or 0),
                str(r.chosen_build_id or ""),
            )
        )
    sig.sort(key=lambda x: x[0])
    return tuple(sig)


def optimize_greedy(account: AccountData, presets: BuildStore, req: GreedyRequest) -> GreedyResult:
    """
    Extended SWOP-like greedy:
    - runs one or multiple passes with different optimization orders
    - pass 1 uses greedy seed; optional later passes can use refine strategy
    - keeps the best full-account outcome (units built + fair quality distribution)
    """
    base_unit_ids = list(req.unit_ids_in_order)
    if not base_unit_ids:
        return GreedyResult(False, tr("opt.no_units"), [])

    pass_orders = [base_unit_ids]
    if bool(req.multi_pass_enabled) and len(base_unit_ids) > 1:
        pass_orders = _build_pass_orders(base_unit_ids, int(req.multi_pass_count or 1))
    profile = str(getattr(req, "quality_profile", "balanced") or "balanced").strip().lower()
    if profile not in (
        "fast",
        "balanced",
        "max_quality",
        "gpu_search",
        "gpu_search_fast",
        "gpu_search_balanced",
        "gpu_search_max",
    ):
        profile = "balanced"
    if profile == "max_quality":
        from app.engine.global_optimizer import optimize_global
        run_count = int(max(1, int(req.multi_pass_count or 1))) if bool(req.multi_pass_enabled) else 1
        if run_count <= 1:
            return optimize_global(account, presets, req)

        max_parallel = int(max(1, int(req.workers or 1)))
        parallel_runs = int(max(1, min(int(run_count), int(max_parallel))))
        workers_per_run = int(max(1, int(max_parallel // parallel_runs)))

        def _run_global_once(run_idx: int) -> tuple[int, GreedyResult]:
            if req.is_cancelled and req.is_cancelled():
                return int(run_idx), GreedyResult(False, tr("opt.cancelled"), [])
            sub_req = replace(
                req,
                workers=int(workers_per_run),
                multi_pass_enabled=False,
                multi_pass_count=1,
                progress_callback=None,
                register_solver=None,
                global_seed_offset=int(run_idx * 100003),
            )
            return int(run_idx), optimize_global(account, presets, sub_req)

        completed = 0
        run_results: List[tuple[int, GreedyResult]] = []
        heartbeat_stop = threading.Event()
        heartbeat_lock = threading.Lock()
        heartbeat_state: Dict[str, int] = {"completed": 0}

        def _heartbeat() -> None:
            if not req.progress_callback:
                return
            while not heartbeat_stop.wait(1.0):
                try:
                    with heartbeat_lock:
                        current = int(heartbeat_state.get("completed", 0))
                    req.progress_callback(int(current), int(run_count))
                except Exception:
                    continue

        hb_thread = threading.Thread(target=_heartbeat, daemon=True)
        hb_thread.start()
        try:
            with ThreadPoolExecutor(max_workers=int(parallel_runs)) as ex:
                futures = [ex.submit(_run_global_once, int(i)) for i in range(int(run_count))]
                for fut in as_completed(futures):
                    if req.is_cancelled and req.is_cancelled():
                        for ff in futures:
                            ff.cancel()
                        break
                    try:
                        run_results.append(fut.result())
                    except Exception:
                        continue
                    completed += 1
                    with heartbeat_lock:
                        heartbeat_state["completed"] = int(completed)
                    if req.progress_callback:
                        try:
                            req.progress_callback(int(completed), int(run_count))
                        except Exception:
                            pass
        finally:
            heartbeat_stop.set()
            hb_thread.join(timeout=0.5)

        if not run_results:
            return GreedyResult(False, tr("opt.cancelled"), [])

        best_idx = -1
        best_result: Optional[GreedyResult] = None
        best_score: Optional[Tuple[int, int, int, int, int, int, int]] = None
        seen_signatures: Set[
            Tuple[Tuple[int, bool, Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...], int, str], ...]
        ] = set()
        for ridx, rres in run_results:
            sig = _results_signature(list(rres.results or []))
            seen_signatures.add(sig)
            score = _evaluate_pass_score(account, req, list(rres.results or []))
            if best_score is None or score > best_score:
                best_score = score
                best_result = rres
                best_idx = int(ridx)

        if best_result is None:
            return GreedyResult(False, "Global optimization failed.", [])
        msg = (
            f"{str(best_result.message or 'Global optimization finished.')} "
            f"parallel_runs={int(parallel_runs)}, launches={int(run_count)}, "
            f"workers_per_run={int(workers_per_run)}, unique={int(max(1, len(seen_signatures)))}, "
            f"best_run={int(best_idx + 1)}."
        )
        return GreedyResult(bool(best_result.ok), msg, list(best_result.results or []))
    if profile.startswith("gpu_search"):
        from app.engine.gpu_search_optimizer import optimize_gpu_search

        return optimize_gpu_search(account, presets, req)
    strategy = str(getattr(req, "multi_pass_strategy", "greedy_refine") or "greedy_refine").strip().lower()
    if strategy not in ("greedy_only", "greedy_refine"):
        strategy = "greedy_refine"
    requested_top_n_raw = int(getattr(req, "rune_top_per_set", 200) or 200)
    use_full_rune_pool = int(requested_top_n_raw) <= 0
    if profile == "fast":
        strategy = "greedy_only"
        no_improve_patience = 2
        rune_top_per_set_effective = 0 if use_full_rune_pool else min(int(requested_top_n_raw), 120)
        speed_slack_effective = 0
    elif profile == "max_quality":
        no_improve_patience = 6 if strategy == "greedy_refine" else 3
        rune_top_per_set_effective = 0
        speed_slack_effective = max(2, int(getattr(req, "speed_slack_for_quality", DEFAULT_SPEED_SLACK_FOR_QUALITY) or 2))
    else:
        no_improve_patience = 4 if strategy == "greedy_refine" else 2
        rune_top_per_set_effective = 0 if use_full_rune_pool else max(int(requested_top_n_raw), 300)
        speed_slack_effective = int(getattr(req, "speed_slack_for_quality", DEFAULT_SPEED_SLACK_FOR_QUALITY) or DEFAULT_SPEED_SLACK_FOR_QUALITY)

    outcomes: List[_PassOutcome] = []
    seen_signatures: Set[
        Tuple[Tuple[int, bool, Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...], int, str], ...]
    ] = set()
    best_score: Optional[Tuple[int, int, int, int, int, int, int]] = None
    no_improve_streak = 0
    early_stop_reason = ""
    best_outcome: Optional[_PassOutcome] = None
    total_passes = len(pass_orders)
    for idx, unit_ids in enumerate(pass_orders):
        if req.is_cancelled and req.is_cancelled():
            break
        if req.progress_callback:
            try:
                req.progress_callback(idx + 1, total_passes)
            except Exception:
                pass
        pass_time = float(req.time_limit_per_unit_s)
        if idx > 0:
            if profile == "max_quality":
                pass_time = max(1.5, float(req.time_limit_per_unit_s) * max(1.2, float(req.multi_pass_time_factor)))
            elif strategy == "greedy_refine":
                # Refinement needs real search time; tiny budgets collapse to pass-1 clones.
                pass_time = max(1.0, float(req.time_limit_per_unit_s) * max(0.8, float(req.multi_pass_time_factor)))
            else:
                pass_time = max(0.5, float(req.time_limit_per_unit_s) * float(req.multi_pass_time_factor))
        use_refine = idx > 0 and strategy == "greedy_refine"
        if use_refine:
            from app.engine.refine_optimizer import run_refine_pass

            pass_results = run_refine_pass(
                account=account,
                presets=presets,
                req=req,
                unit_ids=unit_ids,
                time_limit_per_unit_s=pass_time,
                pass_idx=idx,
                avoid_solution_by_unit=(
                    {int(r.unit_id): r for r in (best_outcome.results if best_outcome else [])}
                ),
                speed_slack_for_quality=max(0, int(speed_slack_effective)),
                rune_top_per_set_override=max(0, int(rune_top_per_set_effective)),
            )
        else:
            pass_results = _run_greedy_pass(
                account=account,
                presets=presets,
                req=req,
                unit_ids=unit_ids,
                time_limit_per_unit_s=pass_time,
                speed_slack_for_quality=(
                    0 if idx == 0 else max(0, int(speed_slack_effective))
                ),
                rune_top_per_set_override=max(0, int(rune_top_per_set_effective)),
            )
        outcome = _PassOutcome(
            pass_idx=idx,
            order=list(unit_ids),
            results=pass_results,
            score=_evaluate_pass_score(account, req, pass_results),
        )
        outcomes.append(outcome)

        sig = _results_signature(pass_results)
        repeated_solution = sig in seen_signatures
        seen_signatures.add(sig)

        improved = best_score is None or outcome.score > best_score
        if improved:
            best_score = outcome.score
            best_outcome = outcome
            no_improve_streak = 0
        else:
            no_improve_streak += 1

        if idx > 0:
            if repeated_solution and not improved and strategy != "greedy_refine":
                early_stop_reason = tr("opt.stable_solution")
                break
            if no_improve_streak >= int(no_improve_patience):
                early_stop_reason = tr("opt.no_improvement")
                break

    if not outcomes:
        return GreedyResult(False, tr("opt.cancelled"), [])

    if req.is_cancelled and req.is_cancelled():
        best_cancel = max(outcomes, key=lambda o: o.score)
        return GreedyResult(False, tr("opt.cancelled"), best_cancel.results)

    best = max(outcomes, key=lambda o: o.score)
    ok_all = all(r.ok for r in best.results)

    if len(outcomes) <= 1:
        msg = tr("opt.ok") if ok_all else tr("opt.partial_fail")
        return GreedyResult(ok_all, msg, best.results)

    msg_prefix = tr("opt.ok") if ok_all else tr("opt.partial_fail")
    planned = len(pass_orders)
    used = len(outcomes)
    msg = tr("opt.multi_pass", prefix=msg_prefix, used=used, pass_idx=best.pass_idx + 1)
    if early_stop_reason and used < planned:
        msg = tr("opt.multi_pass_early", prefix=msg_prefix, used=used, planned=planned,
                 pass_idx=best.pass_idx + 1, reason=early_stop_reason)
    return GreedyResult(ok_all, msg, best.results)
