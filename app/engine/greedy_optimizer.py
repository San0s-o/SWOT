from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
import threading
from typing import Dict, List, Tuple, Set, Optional, Callable

from ortools.sat.python import cp_model

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
    if arch in ("attack", "atk", "angriff"):
        return "attack"
    if arch in ("defense", "def", "abwehr"):
        return "defense"
    if arch in ("hp", "leben"):
        return "hp"
    if arch in ("support", "rueckhalt", "rückhalt"):
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


def _artifact_damage_score_proxy(art: Artifact) -> int:
    score = 0
    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        try:
            eid = int(sec[0] or 0)
            val = float(sec[1] or 0)
        except Exception:
            continue
        if eid in (204, 226, 219):
            score += int(round(val * 28.0))
        elif eid in (210, 212, 222, 223, 224, 225, 400, 401, 402, 403, 410, 411):
            score += int(round(val * 18.0))
    return int(score)


def _artifact_defensive_score_proxy(art: Artifact, archetype: str = "") -> int:
    role = _arena_role_from_archetype(archetype)
    if role not in ("defense", "hp", "support"):
        return 0

    score = 0
    # Main stat is a decisive signal for defensive archetypes:
    # HP/DEF mains are strongly preferred, ATK main is penalized.
    try:
        main_eff = int((art.pri_effect or (0,))[0] or 0)
    except Exception:
        main_eff = 0
    if main_eff == 101:
        score -= 260
    elif main_eff == 100:
        score += 220 if role == "hp" else (180 if role == "support" else 160)
    elif main_eff == 102:
        score += 220 if role == "defense" else (150 if role == "support" else 120)

    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        try:
            eid = int(sec[0] or 0)
            val = float(sec[1] or 0)
        except Exception:
            continue
        if eid in (201, 205, 226):
            score += int(round(val * (14.0 if role == "defense" else 10.0)))
        elif eid in (213, 214, 305, 306, 307, 308, 309):
            score += int(round(val * (16.0 if role == "support" else 13.0)))
        elif eid in (404, 405, 406):
            score += int(round(val * (14.0 if role == "support" else 8.0)))
        elif eid in (206, 203):
            score += int(round(val * (8.0 if role == "support" else 5.0)))
        elif eid in (407, 408, 409):
            score += int(round(val * (10.0 if role == "support" else 3.0)))
    return int(score)


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
) -> int:
    score = 0
    score += int(art.level or 0) * 8
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    score += base_rank * 6

    # Defensive effect quality as the primary artifact signal.
    score += int(_artifact_defensive_score_proxy(art, archetype))
    # Penalize pure offensive artifact lines for defensive units.
    score -= int(_artifact_damage_score_proxy(art))

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
) -> int:
    if str(role) in ("defense", "hp", "support"):
        return int(
            _artifact_quality_score_defensive(art, uid, rta_artifact_ids_for_unit, archetype=role)
            + (int(ARENA_RUSH_DEF_ART_WEIGHT) * int(_artifact_defensive_score_proxy(art, role)))
            - (int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(_artifact_damage_score_proxy(art)))
        )
    if str(role) == "attack":
        return int(_artifact_quality_score(art, uid, rta_artifact_ids_for_unit) + int(_artifact_damage_score_proxy(art)))
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
    favor_damage_for_atk_type = (
        bool(arena_rush_damage_bias)
        and is_arena_rush_mode
        and str(unit_role) == "attack"
    )
    favor_defense_for_role = bool(
        is_arena_rush_mode
        and str(unit_role) in ("defense", "hp", "support")
    )
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
                        )
                    )
                    if def_q:
                        quality_terms.append((int(ARENA_RUSH_DEF_QUALITY_WEIGHT) * def_q) * av)
                if favor_damage_for_atk_type:
                    dmg_bonus = _artifact_damage_score_proxy(art)
                    if dmg_bonus:
                        quality_terms.append(dmg_bonus * av)
                if favor_defense_for_role:
                    def_bonus = _artifact_defensive_score_proxy(art, str(unit_archetype or ""))
                    if def_bonus:
                        quality_terms.append((int(ARENA_RUSH_DEF_ART_WEIGHT) * def_bonus) * av)
                    dmg_penalty = _artifact_damage_score_proxy(art)
                    if dmg_penalty:
                        quality_terms.append(
                            (-int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(dmg_penalty)) * av
                        )
            else:
                if favor_defense_for_role:
                    aw = _artifact_quality_score_defensive(
                        art,
                        uid,
                        rta_artifact_ids_for_unit,
                        archetype=str(unit_archetype or ""),
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
                    dmg_bonus = _artifact_damage_score_proxy(art)
                    if dmg_bonus:
                        quality_terms.append(dmg_bonus * av)
                if favor_defense_for_role:
                    def_bonus = _artifact_defensive_score_proxy(art, str(unit_archetype or ""))
                    if def_bonus:
                        quality_terms.append((int(ARENA_RUSH_DEF_ART_WEIGHT) * def_bonus) * av)
                    dmg_penalty = _artifact_damage_score_proxy(art)
                    if dmg_penalty:
                        quality_terms.append(
                            (-int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * int(dmg_penalty)) * av
                        )

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
            unit_quality += _artifact_quality_score(art, uid, rta_aids)
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
