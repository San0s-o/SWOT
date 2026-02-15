from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Set, Optional, Callable

from ortools.sat.python import cp_model

from app.domain.models import AccountData, Rune, Artifact
from app.domain.speed_ticks import min_spd_for_tick, max_spd_for_tick
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


def _is_good_even_slot_mainstat(eff_id: int, slot_no: int) -> bool:
    if slot_no not in (2, 4, 6):
        return True
    return int(eff_id or 0) in (2, 4, 6, 8, 9, 10, 11, 12)


def _rune_quality_score(r: Rune, uid: int,
                        rta_rune_ids_for_unit: Optional[Set[int]] = None) -> int:
    score = 0
    score += int(r.upgrade_curr or 0) * 8
    score += int(r.rank or 0) * 6
    score += int(r.rune_class or 0) * 10
    score += int(SET_SCORE_BONUS.get(int(r.set_id or 0), 0))

    # Main stat and prefix stat
    score += _score_stat(int(r.pri_eff[0] or 0), int(r.pri_eff[1] or 0))
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


@dataclass
class GreedyRequest:
    mode: str
    unit_ids_in_order: List[int]   # Reihenfolge = Priorität (wie SWOP)
    time_limit_per_unit_s: float = 10.0
    workers: int = 8
    multi_pass_enabled: bool = True
    multi_pass_count: int = 3
    multi_pass_time_factor: float = 0.2
    progress_callback: Optional[Callable[[int, int], None]] = None
    enforce_turn_order: bool = True
    unit_team_index: Dict[int, int] | None = None
    unit_team_turn_order: Dict[int, int] | None = None
    unit_spd_leader_bonus_flat: Dict[int, int] | None = None

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


def _allowed_runes_for_mode(account: AccountData, _selected_unit_ids: List[int]) -> List[Rune]:
    # User requested full account pool: use every rune from the JSON snapshot/import.
    return list(account.runes)


def _allowed_artifacts_for_mode(account: AccountData, _selected_unit_ids: List[int]) -> List[Artifact]:
    # User requested full account pool: use every artifact from the JSON snapshot/import.
    return [a for a in account.artifacts if int(a.type_ or 0) in (1, 2)]


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
            total += int(r.pri_eff[1] or 0)
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
    return total


def _rune_stat_total(r: Rune, eff_id_target: int) -> int:
    total = 0
    try:
        if int(r.pri_eff[0] or 0) == eff_id_target:
            total += int(r.pri_eff[1] or 0)
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
    return total


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
    base_spd: int,
    base_spd_bonus_flat: int,
    base_cr: int,
    base_cd: int,
    base_res: int,
    base_acc: int,
    max_final_speed: Optional[int],
    rta_rune_ids_for_unit: Optional[Set[int]] = None,
    rta_artifact_ids_for_unit: Optional[Set[int]] = None,
) -> GreedyUnitResult:
    """
    Solve for ONE unit:
    - pick exactly 1 rune per slot (1..6)
    - pick exactly 1 attribute artifact (type 1) and 1 type artifact (type 2)
    - pick exactly 1 build
    - enforce build mainstats (2/4/6) + build set_option + artifact constraints
    - objective: maximize rune weight - priority penalty
    """
    # candidates by slot
    runes_by_slot: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= r.slot_no <= 6:
            runes_by_slot[r.slot_no].append(r)

    # Hard feasibility: each slot must have >= 1 candidate
    for s in range(1, 7):
        if not runes_by_slot[s]:
            return GreedyUnitResult(uid, False, tr("opt.slot_no_runes", slot=s), runes_by_slot={})

    artifacts_by_type: Dict[int, List[Artifact]] = {1: [], 2: []}
    for art in artifact_pool:
        t = int(art.type_ or 0)
        if t in (1, 2):
            artifacts_by_type[t].append(art)

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
            for slot in range(1, 7):
                for r in runes_by_slot[slot]:
                    xv = x[(slot, r.rune_id)]
                    cr = _rune_stat_total(r, 9)
                    cd = _rune_stat_total(r, 10)
                    res = _rune_stat_total(r, 11)
                    acc = _rune_stat_total(r, 12)
                    if cr:
                        cr_terms.append(cr * xv)
                    if cd:
                        cd_terms.append(cd * xv)
                    if res:
                        res_terms.append(res * xv)
                    if acc:
                        acc_terms.append(acc * xv)

            if int(min_stats.get("CR", 0) or 0) > 0:
                model.Add(base_cr + sum(cr_terms) >= int(min_stats["CR"])).OnlyEnforceIf(vb)
            if int(min_stats.get("CD", 0) or 0) > 0:
                model.Add(base_cd + sum(cd_terms) >= int(min_stats["CD"])).OnlyEnforceIf(vb)
            if int(min_stats.get("RES", 0) or 0) > 0:
                model.Add(base_res + sum(res_terms) >= int(min_stats["RES"])).OnlyEnforceIf(vb)
            if int(min_stats.get("ACC", 0) or 0) > 0:
                model.Add(base_acc + sum(acc_terms) >= int(min_stats["ACC"])).OnlyEnforceIf(vb)

    # speed expression (for SPD-first)
    speed_terms = []
    swift_piece_vars = []
    swift_bonus_value = int(int(base_spd or 0) * 25 / 100)
    for slot in range(1, 7):
        for r in runes_by_slot[slot]:
            v = x[(slot, r.rune_id)]
            spd = _rune_flat_spd(r)
            if spd:
                speed_terms.append(spd * v)
            if int(r.set_id or 0) == 3:
                swift_piece_vars.append(v)

    swift_set_active = model.NewBoolVar(f"swift_set_u{uid}")
    swift_count = sum(swift_piece_vars) if swift_piece_vars else 0
    if swift_piece_vars:
        model.Add(swift_count >= 4).OnlyEnforceIf(swift_set_active)
        model.Add(swift_count <= 3).OnlyEnforceIf(swift_set_active.Not())
    else:
        model.Add(swift_set_active == 0)

    final_speed_expr = (
        int(base_spd or 0)
        + int(base_spd_bonus_flat or 0)
        + sum(speed_terms)
        + (swift_bonus_value * swift_set_active)
    )
    if max_final_speed is not None and max_final_speed > 0:
        model.Add(final_speed_expr <= int(max_final_speed))

    for b_idx, b in enumerate(builds):
        vb = use_build[b_idx]
        spd_tick = int(getattr(b, "spd_tick", 0) or 0)
        min_spd_cfg = int((getattr(b, "min_stats", {}) or {}).get("SPD", 0) or 0)
        min_spd_tick = int(min_spd_for_tick(spd_tick) or 0)
        min_spd_required = max(min_spd_cfg, min_spd_tick)
        if min_spd_required > 0:
            model.Add(final_speed_expr >= min_spd_required).OnlyEnforceIf(vb)
        if spd_tick > 0:
            max_spd_tick = int(max_spd_for_tick(spd_tick) or 0)
            if max_spd_tick > 0:
                model.Add(final_speed_expr <= max_spd_tick).OnlyEnforceIf(vb)

    # quality objective (2nd phase after speed is pinned)
    quality_terms = []
    for slot in range(1, 7):
        for r in runes_by_slot[slot]:
            v = x[(slot, r.rune_id)]
            w = _rune_quality_score(r, uid, rta_rune_ids_for_unit)
            quality_terms.append(w * v)
    for art_type in (1, 2):
        for art in artifacts_by_type[art_type]:
            av = xa[(art_type, int(art.artifact_id))]
            aw = _artifact_quality_score(art, uid, rta_artifact_ids_for_unit)
            quality_terms.append(aw * av)

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

    BUILD_PRIORITY_PENALTY = 200
    for b_idx, b in enumerate(builds):
        quality_terms.append((-int(b.priority) * BUILD_PRIORITY_PENALTY) * use_build[b_idx])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = int(workers)

    model.Maximize(final_speed_expr)
    status = solver.Solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        best_speed = int(solver.Value(final_speed_expr))
        model.Add(final_speed_expr == best_speed)
        model.Maximize(sum(quality_terms))
        status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        detail = _diagnose_single_unit_infeasible(pool, artifact_pool, builds)
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
        for rid in res.runes_by_slot.values():
            rune = runes_by_id.get(int(rid))
            if rune is None:
                continue
            unit_quality += _rune_quality_score(rune, uid, rta_rids)
        for aid in (res.artifacts_by_type or {}).values():
            art = artifacts_by_id.get(int(aid))
            if art is None:
                continue
            unit_quality += _artifact_quality_score(art, uid, rta_aids)
        ok_count += 1
        unit_scores.append(int(unit_quality))
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
    effective_quality = int(total_quality - (gap_excess_squared * TURN_ORDER_GAP_PENALTY_WEIGHT))
    return (
        int(ok_count),
        int(effective_quality),
        int(total_quality),
        int(avg_quality_scaled),
        int(-gap_excess_squared),
        int(min_unit_quality),
        int(speed_sum),
    )


def _run_greedy_pass(
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
    unit_ids: List[int],
    time_limit_per_unit_s: float,
) -> List[GreedyUnitResult]:
    unit_ids = _reorder_for_turn_order(req, unit_ids)

    # initial pool
    pool = _allowed_runes_for_mode(account, unit_ids)
    blocked: Set[int] = set()  # rune_id
    artifact_pool = _allowed_artifacts_for_mode(account, unit_ids)
    blocked_artifacts: Set[int] = set()  # artifact_id

    # For RTA mode, build lookup of RTA-equipped rune IDs per unit
    rta_equip = account.rta_rune_equip if req.mode == "rta" else {}
    rta_art_equip = account.rta_artifact_equip if req.mode == "rta" else {}

    results: List[GreedyUnitResult] = []

    for uid in unit_ids:
        cur_pool = [r for r in pool if r.rune_id not in blocked]
        cur_art_pool = [a for a in artifact_pool if int(a.artifact_id or 0) not in blocked_artifacts]
        unit = account.units_by_id.get(uid)
        base_spd = int(unit.base_spd or 0) if unit else 0
        totem_spd_bonus_flat = int(base_spd * int(account.sky_tribe_totem_spd_pct or 0) / 100)
        leader_spd_bonus_flat = int((req.unit_spd_leader_bonus_flat or {}).get(int(uid), 0) or 0)
        base_spd_bonus_flat = int(totem_spd_bonus_flat + leader_spd_bonus_flat)
        base_cr = int(unit.crit_rate or 15) if unit else 15
        base_cd = int(unit.crit_dmg or 50) if unit else 50
        base_res = int(unit.base_res or 15) if unit else 15
        base_acc = int(unit.base_acc or 0) if unit else 0
        max_speed_cap: Optional[int] = None
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

        r = _solve_single_unit_best(
            uid=uid,
            pool=cur_pool,
            artifact_pool=cur_art_pool,
            builds=builds,
            time_limit_s=float(time_limit_per_unit_s),
            workers=req.workers,
            base_spd=base_spd,
            base_spd_bonus_flat=base_spd_bonus_flat,
            base_cr=base_cr,
            base_cd=base_cd,
            base_res=base_res,
            base_acc=base_acc,
            max_final_speed=max_speed_cap,
            rta_rune_ids_for_unit=rta_rids,
            rta_artifact_ids_for_unit=rta_aids,
        )
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
    - runs one or multiple greedy passes with different optimization orders
    - keeps the best full-account outcome (units built + fair quality distribution)
    """
    base_unit_ids = list(req.unit_ids_in_order)
    if not base_unit_ids:
        return GreedyResult(False, tr("opt.no_units"), [])

    pass_orders = [base_unit_ids]
    if bool(req.multi_pass_enabled) and len(base_unit_ids) > 1:
        pass_orders = _build_pass_orders(base_unit_ids, int(req.multi_pass_count or 1))

    outcomes: List[_PassOutcome] = []
    seen_signatures: Set[
        Tuple[Tuple[int, bool, Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...], int, str], ...]
    ] = set()
    best_score: Optional[Tuple[int, int, int, int, int, int, int]] = None
    no_improve_streak = 0
    early_stop_reason = ""
    total_passes = len(pass_orders)
    for idx, unit_ids in enumerate(pass_orders):
        if req.progress_callback:
            try:
                req.progress_callback(idx + 1, total_passes)
            except Exception:
                pass
        pass_time = float(req.time_limit_per_unit_s)
        if idx > 0:
            pass_time = max(0.5, float(req.time_limit_per_unit_s) * float(req.multi_pass_time_factor))
        pass_results = _run_greedy_pass(
            account=account,
            presets=presets,
            req=req,
            unit_ids=unit_ids,
            time_limit_per_unit_s=pass_time,
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
            no_improve_streak = 0
        else:
            no_improve_streak += 1

        if idx > 0:
            if repeated_solution and not improved:
                early_stop_reason = tr("opt.stable_solution")
                break
            if no_improve_streak >= 2:
                early_stop_reason = tr("opt.no_improvement")
                break

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
