from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from ortools.sat.python import cp_model

from app.domain.models import AccountData, Rune, Artifact
from app.domain.presets import BuildStore, Build, EFFECT_ID_TO_MAINSTAT_KEY
from app.domain.speed_ticks import min_spd_for_tick, max_spd_for_tick
from app.engine.efficiency import rune_efficiency, artifact_efficiency
from app.engine.greedy_optimizer import (
    ACC_OVERCAP_PENALTY_PER_POINT,
    ARENA_RUSH_DEF_ART_WEIGHT,
    ARENA_RUSH_DEF_EFFICIENCY_SCALE,
    ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT,
    ARENA_RUSH_DEF_QUALITY_WEIGHT,
    ARENA_RUSH_DEF_RUNE_WEIGHT,
    ARENA_RUSH_ATK_EFFICIENCY_SCALE,
    ARTIFACT_ROLE_CONTEXT_WEIGHT,
    BASELINE_REGRESSION_GUARD_WEIGHT,
    CR_OVERCAP_PENALTY_PER_POINT,
    RES_OVERCAP_PENALTY_PER_POINT,
    STAT_OVERCAP_LIMIT,
    INTANGIBLE_SET_ID,
    GreedyRequest,
    GreedyResult,
    GreedyUnitResult,
    _allowed_artifacts_for_mode,
    _allowed_runes_for_mode,
    _artifact_focus_key,
    _artifact_substat_ids,
    _artifact_context_score_proxy,
    _artifact_hint_score,
    _count_required_set_pieces,
    _rune_flat_spd,
    _rune_stat_total,
    _rune_quality_score,
    _artifact_quality_score,
    _artifact_damage_score_proxy,
    _artifact_defensive_score_proxy,
    _artifact_quality_score_defensive,
    _baseline_guard_artifact_coef,
    _baseline_guard_rune_coef,
    _force_swift_speed_priority,
    _arena_role_from_archetype,
    _is_attack_type_unit,
    _is_attack_archetype,
    _is_defensive_archetype,
    _rune_damage_score_proxy,
    _rune_quality_score_defensive,
    _rune_defensive_score_proxy,
    _run_greedy_pass,
)
from app.i18n import tr

GLOBAL_SOLVER_OVERCAP_PENALTY_SCALE = 100
GLOBAL_BASELINE_REGRESSION_GUARD_WEIGHT = 1500


def optimize_global(account: AccountData, presets: BuildStore, req: GreedyRequest) -> GreedyResult:
    unit_ids = [int(u) for u in (req.unit_ids_in_order or [])]
    if not unit_ids:
        return GreedyResult(False, tr("opt.no_units"), [])
    if req.is_cancelled and req.is_cancelled():
        return GreedyResult(False, tr("opt.cancelled"), [])

    pool = _allowed_runes_for_mode(account, req, unit_ids)
    artifact_pool = _allowed_artifacts_for_mode(account, unit_ids, req=req)
    runes_by_slot_global: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= int(r.slot_no or 0) <= 6:
            runes_by_slot_global[int(r.slot_no)].append(r)

    artifacts_by_type_global: Dict[int, List[Artifact]] = {1: [], 2: []}
    for a in artifact_pool:
        t = int(a.type_ or 0)
        if t in (1, 2):
            artifacts_by_type_global[t].append(a)

    model = cp_model.CpModel()

    # x[(uid, slot, rid)] = 1 if rune rid is assigned to uid in slot
    x: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
    # xa[(uid, type, aid)] = 1 if artifact aid is assigned
    xa: Dict[Tuple[int, int, int], cp_model.IntVar] = {}
    use_build: Dict[Tuple[int, int], cp_model.IntVar] = {}
    final_speed_expr: Dict[int, cp_model.LinearExpr] = {}
    final_speed_raw_expr: Dict[int, cp_model.LinearExpr] = {}
    force_speed_uids: Set[int] = set()
    swift_active_by_uid: Dict[int, cp_model.IntVar] = {}
    speed_tiebreak_weight_by_uid: Dict[int, int] = {}
    favor_damage_by_uid: Dict[int, bool] = {}
    favor_defense_by_uid: Dict[int, bool] = {}
    archetype_by_uid: Dict[int, str] = {}
    artifact_role_by_uid: Dict[int, str] = {}
    unit_base_stats_by_uid: Dict[int, Tuple[int, int, int, int]] = {}
    overcap_penalty_expr_by_uid: Dict[int, cp_model.LinearExpr] = {}
    baseline_guard_shortfall_by_uid: Dict[int, cp_model.IntVar] = {}

    # Keep deterministic build order
    builds_by_uid: Dict[int, List[Build]] = {}
    for uid in unit_ids:
        bu = sorted(presets.get_unit_builds(req.mode, uid), key=lambda b: int(b.priority))
        if not bu:
            bu = [Build.default_any()]
        builds_by_uid[uid] = bu

    # per-unit constraints
    for uid in unit_ids:
        unit = account.units_by_id.get(uid)
        base_hp = int((unit.base_con or 0) * 15) if unit else 0
        base_atk = int(unit.base_atk or 0) if unit else 0
        base_def = int(unit.base_def or 0) if unit else 0
        base_spd = int(unit.base_spd or 0) if unit else 0
        unit_base_stats_by_uid[int(uid)] = (
            int(base_hp or 0),
            int(base_atk or 0),
            int(base_def or 0),
            int(base_spd or 0),
        )
        totem_spd_bonus_flat = int(base_spd * int(account.sky_tribe_totem_spd_pct or 0) / 100)
        leader_spd_bonus_flat = int((req.unit_spd_leader_bonus_flat or {}).get(int(uid), 0) or 0)
        base_spd_bonus_flat = int(totem_spd_bonus_flat + leader_spd_bonus_flat)
        base_cr = int(unit.crit_rate or 15) if unit else 15
        base_cd = int(unit.crit_dmg or 50) if unit else 50
        base_res = int(unit.base_res or 15) if unit else 15
        base_acc = int(unit.base_acc or 0) if unit else 0
        unit_arch = str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
        archetype_by_uid[int(uid)] = str(unit_arch)
        role_for_art = _arena_role_from_archetype(unit_arch)
        if role_for_art == "unknown":
            role_for_art = (
                "attack"
                if _is_attack_type_unit(base_hp, base_atk, base_def, archetype=unit_arch)
                else "support"
            )
        artifact_role_by_uid[int(uid)] = str(role_for_art)
        is_arena_offense = bool(
            str(req.mode or "").strip().lower() == "arena_rush"
            and str(getattr(req, "arena_rush_context", "") or "").strip().lower() == "offense"
        )
        favor_damage_by_uid[int(uid)] = bool(
            is_arena_offense
            and _is_attack_archetype(unit_arch)
        )
        favor_defense_by_uid[int(uid)] = bool(
            is_arena_offense
            and _is_defensive_archetype(unit_arch)
        )
        fixed_runes_by_slot = {
            int(slot): int(rid)
            for slot, rid in ((req.unit_fixed_runes_by_slot or {}).get(int(uid), {}) or {}).items()
            if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
        }
        fixed_artifacts_by_type = {
            int(art_type): int(aid)
            for art_type, aid in ((req.unit_fixed_artifacts_by_type or {}).get(int(uid), {}) or {}).items()
            if int(art_type or 0) in (1, 2) and int(aid or 0) > 0
        }

        # rune pick: exactly one per slot
        rune_candidates_by_slot: Dict[int, List[Rune]] = {}
        for slot in range(1, 7):
            cands = list(runes_by_slot_global.get(slot, []))
            locked_rune_id = int(fixed_runes_by_slot.get(int(slot), 0) or 0)
            if locked_rune_id > 0:
                cands = [r for r in cands if int(r.rune_id or 0) == int(locked_rune_id)]
            rune_candidates_by_slot[slot] = cands
            if not cands:
                fallback = _run_greedy_pass(
                    account=account,
                    presets=presets,
                    req=req,
                    unit_ids=unit_ids,
                    time_limit_per_unit_s=float(req.time_limit_per_unit_s),
                    speed_slack_for_quality=0,
                    rune_top_per_set_override=0,
                )
                return GreedyResult(False, "Global fallback: slot has no candidates.", fallback)
            vars_for_slot: List[cp_model.IntVar] = []
            for r in cands:
                v = model.NewBoolVar(f"x_u{uid}_s{slot}_r{int(r.rune_id)}")
                x[(uid, slot, int(r.rune_id))] = v
                vars_for_slot.append(v)
            model.Add(sum(vars_for_slot) == 1)

        # artifact pick: exactly one per type
        for art_type in (1, 2):
            cands = list(artifacts_by_type_global[art_type])
            locked_artifact_id = int(fixed_artifacts_by_type.get(int(art_type), 0) or 0)
            if locked_artifact_id > 0:
                cands = [a for a in cands if int(a.artifact_id or 0) == int(locked_artifact_id)]
            if not cands:
                fallback = _run_greedy_pass(
                    account=account,
                    presets=presets,
                    req=req,
                    unit_ids=unit_ids,
                    time_limit_per_unit_s=float(req.time_limit_per_unit_s),
                    speed_slack_for_quality=0,
                    rune_top_per_set_override=0,
                )
                return GreedyResult(False, "Global fallback: artifact pool incomplete.", fallback)
            vars_for_type: List[cp_model.IntVar] = []
            for a in cands:
                av = model.NewBoolVar(f"xa_u{uid}_t{art_type}_a{int(a.artifact_id)}")
                xa[(uid, art_type, int(a.artifact_id))] = av
                vars_for_type.append(av)
            model.Add(sum(vars_for_type) == 1)

        # build select
        builds = builds_by_uid[uid]
        # Global mode: treat a unit as Swift-opener if at least one viable build
        # qualifies for Swift speed priority. This avoids losing opener-priority
        # just because other alternative builds have extra constraints.
        if any(_force_swift_speed_priority(req, uid, [b]) for b in builds):
            force_speed_uids.add(int(uid))
        use_vars: List[cp_model.IntVar] = []
        for b_idx, _b in enumerate(builds):
            bv = model.NewBoolVar(f"use_build_u{uid}_b{b_idx}")
            use_build[(uid, b_idx)] = bv
            use_vars.append(bv)
        model.Add(sum(use_vars) == 1)

        # set counting vars
        set_choice_vars: Dict[int, List[cp_model.IntVar]] = {}
        for slot in range(1, 7):
            for r in rune_candidates_by_slot[slot]:
                sid = int(r.set_id or 0)
                set_choice_vars.setdefault(sid, []).append(x[(uid, slot, int(r.rune_id))])
        intangible_piece_vars = set_choice_vars.get(int(INTANGIBLE_SET_ID), [])
        intangible_piece_count_expr = sum(intangible_piece_vars) if intangible_piece_vars else 0

        # speed expression
        speed_terms: List[cp_model.LinearExpr] = []
        swift_piece_vars: List[cp_model.IntVar] = []
        cr_terms_all: List[cp_model.LinearExpr] = []
        res_terms_all: List[cp_model.LinearExpr] = []
        acc_terms_all: List[cp_model.LinearExpr] = []
        swift_bonus_value = int(int(base_spd or 0) * 25 / 100)
        for slot in range(1, 7):
            for r in rune_candidates_by_slot[slot]:
                xv = x[(uid, slot, int(r.rune_id))]
                spd = _rune_flat_spd(r)
                if spd:
                    speed_terms.append(spd * xv)
                cr = int(_rune_stat_total(r, 9) or 0)
                if cr:
                    cr_terms_all.append(cr * xv)
                rs = int(_rune_stat_total(r, 11) or 0)
                if rs:
                    res_terms_all.append(rs * xv)
                ac = int(_rune_stat_total(r, 12) or 0)
                if ac:
                    acc_terms_all.append(ac * xv)
                if int(r.set_id or 0) == 3:
                    swift_piece_vars.append(xv)
        swift_set_active = model.NewBoolVar(f"swift_set_u{uid}")
        swift_count = sum(swift_piece_vars) if swift_piece_vars else 0
        if swift_piece_vars:
            model.Add(swift_count >= 4).OnlyEnforceIf(swift_set_active)
            model.Add(swift_count <= 3).OnlyEnforceIf(swift_set_active.Not())
        else:
            model.Add(swift_set_active == 0)
        swift_active_by_uid[int(uid)] = swift_set_active
        # Raw SPD for min-SPD constraints: base + runes (+swift), no tower, no leader.
        final_spd_raw = (
            int(base_spd or 0)
            + sum(speed_terms)
            + (swift_bonus_value * swift_set_active)
        )
        # Combat SPD for turn-order/tick: includes tower and leader.
        final_spd = final_spd_raw + int(base_spd_bonus_flat or 0)
        final_speed_raw_expr[uid] = final_spd_raw
        final_speed_expr[uid] = final_spd
        speed_tie_raw = (req.unit_speed_tiebreak_weight or {}).get(int(uid), None)
        speed_tiebreak_weight_by_uid[int(uid)] = 1 if speed_tie_raw is None else int(speed_tie_raw)

        # Request-level final combat speed bounds (used by Arena Rush coordination
        # between defense and offense contexts, e.g. shared-unit tick guarantees).
        req_min_final = int((dict(req.unit_min_final_speed or {})).get(int(uid), 0) or 0)
        req_max_final = int((dict(req.unit_max_final_speed or {})).get(int(uid), 0) or 0)
        if req_min_final > 0:
            model.Add(final_spd >= int(req_min_final))
        if req_max_final > 0:
            model.Add(final_spd <= int(req_max_final))

        # Safety floor (global mode):
        # - min SPD is raw SPD (without tower/leader)
        # - tick floor is combat SPD (with tower/leader)
        unit_min_spd_floor_raw = 0
        unit_min_spd_floor_no_base = 0
        unit_min_tick_floor = 0
        for bb in builds:
            cfg_min = int((getattr(bb, "min_stats", {}) or {}).get("SPD", 0) or 0)
            cfg_min_no_base = int((getattr(bb, "min_stats", {}) or {}).get("SPD_NO_BASE", 0) or 0)
            tick_min = int(min_spd_for_tick(int(getattr(bb, "spd_tick", 0) or 0), req.mode) or 0)
            unit_min_spd_floor_raw = max(unit_min_spd_floor_raw, cfg_min)
            unit_min_spd_floor_no_base = max(unit_min_spd_floor_no_base, cfg_min_no_base)
            unit_min_tick_floor = max(unit_min_tick_floor, tick_min)
        if unit_min_spd_floor_raw > 0:
            model.Add(final_spd_raw >= int(unit_min_spd_floor_raw))
        if unit_min_spd_floor_no_base > 0:
            model.Add(final_spd_raw - int(base_spd or 0) >= int(unit_min_spd_floor_no_base))
        if unit_min_tick_floor > 0:
            model.Add(final_spd >= int(unit_min_tick_floor))

        # Soft-penalty for wasted capped stats (CR/RES/ACC above 100).
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

        overcap_penalty_expr_by_uid[int(uid)] = (
            (int(CR_OVERCAP_PENALTY_PER_POINT) * cr_over_var)
            + (int(RES_OVERCAP_PENALTY_PER_POINT) * res_over_var)
            + (int(ACC_OVERCAP_PENALTY_PER_POINT) * acc_over_var)
        )

        baseline_guard_weight = int(
            getattr(req, "baseline_regression_guard_weight", BASELINE_REGRESSION_GUARD_WEIGHT) or 0
        )
        if baseline_guard_weight > 0:
            baseline_slots = {
                int(slot): int(rid)
                for slot, rid in (((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {}).items())
                if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
            }
            baseline_arts = {
                int(t): int(aid)
                for t, aid in (((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {}).items())
                if int(t or 0) in (1, 2) and int(aid or 0) > 0
            }
            if len(baseline_slots) == 6 and len(baseline_arts) == 2:
                guard_role = str(archetype_by_uid.get(int(uid), "") or "").strip().lower()
                if guard_role in ("rueckhalt", "rückhalt"):
                    guard_role = "support"
                if guard_role == "":
                    guard_role = "attack" if _is_attack_type_unit(base_hp, base_atk, base_def, archetype="") else "support"
                if guard_role not in ("attack", "defense", "hp", "support"):
                    guard_role = "attack" if _is_attack_type_unit(base_hp, base_atk, base_def, archetype=guard_role) else "support"

                baseline_rune_refs: List[Rune] = []
                baseline_ok = True
                for slot in range(1, 7):
                    rid = int(baseline_slots.get(int(slot), 0) or 0)
                    if rid <= 0 or (uid, slot, rid) not in x:
                        baseline_ok = False
                        break
                    rr = next(
                        (r for r in rune_candidates_by_slot[int(slot)] if int(r.rune_id or 0) == int(rid)),
                        None,
                    )
                    if rr is None:
                        baseline_ok = False
                        break
                    baseline_rune_refs.append(rr)
                baseline_art_refs: List[Artifact] = []
                if baseline_ok:
                    for art_type in (1, 2):
                        aid = int(baseline_arts.get(int(art_type), 0) or 0)
                        if aid <= 0 or (uid, art_type, aid) not in xa:
                            baseline_ok = False
                            break
                        aa = next(
                            (a for a in artifacts_by_type_global[int(art_type)] if int(a.artifact_id or 0) == int(aid)),
                            None,
                        )
                        if aa is None:
                            baseline_ok = False
                            break
                        baseline_art_refs.append(aa)
                if baseline_ok:
                    guard_terms: List[cp_model.LinearExpr] = []
                    for slot in range(1, 7):
                        for r in rune_candidates_by_slot[slot]:
                            coef = int(
                                _baseline_guard_rune_coef(
                                    r,
                                    uid=int(uid),
                                    base_hp=int(base_hp or 0),
                                    base_atk=int(base_atk or 0),
                                    base_def=int(base_def or 0),
                                    role=str(guard_role),
                                    rta_rune_ids_for_unit=None,
                                )
                            )
                            if coef != 0:
                                guard_terms.append(coef * x[(uid, slot, int(r.rune_id))])
                    for art_type in (1, 2):
                        for a in artifacts_by_type_global[art_type]:
                            coef = int(
                                _baseline_guard_artifact_coef(
                                    a,
                                    uid=int(uid),
                                    role=str(guard_role),
                                    rta_artifact_ids_for_unit=None,
                                    base_hp=int(base_hp or 0),
                                    base_atk=int(base_atk or 0),
                                    base_def=int(base_def or 0),
                                    base_spd=int(base_spd or 0),
                                )
                            )
                            if coef != 0:
                                guard_terms.append(coef * xa[(uid, art_type, int(a.artifact_id))])
                    guard_expr = (sum(guard_terms) if guard_terms else 0) - (
                        int(GLOBAL_SOLVER_OVERCAP_PENALTY_SCALE) * overcap_penalty_expr_by_uid[int(uid)]
                    )
                    baseline_score = 0
                    baseline_cr = int(base_cr or 0)
                    baseline_res = int(base_res or 0)
                    baseline_acc = int(base_acc or 0)
                    for r in baseline_rune_refs:
                        baseline_score += int(
                            _baseline_guard_rune_coef(
                                r,
                                uid=int(uid),
                                base_hp=int(base_hp or 0),
                                base_atk=int(base_atk or 0),
                                base_def=int(base_def or 0),
                                role=str(guard_role),
                                rta_rune_ids_for_unit=None,
                            )
                        )
                        baseline_cr += int(_rune_stat_total(r, 9) or 0)
                        baseline_res += int(_rune_stat_total(r, 11) or 0)
                        baseline_acc += int(_rune_stat_total(r, 12) or 0)
                    for a in baseline_art_refs:
                        baseline_score += int(
                            _baseline_guard_artifact_coef(
                                a,
                                uid=int(uid),
                                role=str(guard_role),
                                rta_artifact_ids_for_unit=None,
                                base_hp=int(base_hp or 0),
                                base_atk=int(base_atk or 0),
                                base_def=int(base_def or 0),
                                base_spd=int(base_spd or 0),
                            )
                        )
                    baseline_over = (
                        (int(CR_OVERCAP_PENALTY_PER_POINT) * max(0, int(baseline_cr) - int(STAT_OVERCAP_LIMIT)))
                        + (int(RES_OVERCAP_PENALTY_PER_POINT) * max(0, int(baseline_res) - int(STAT_OVERCAP_LIMIT)))
                        + (int(ACC_OVERCAP_PENALTY_PER_POINT) * max(0, int(baseline_acc) - int(STAT_OVERCAP_LIMIT)))
                    )
                    baseline_score -= int(GLOBAL_SOLVER_OVERCAP_PENALTY_SCALE) * int(baseline_over)
                    shortfall_cap = max(300000, abs(int(baseline_score)) + 300000)
                    shortfall = model.NewIntVar(0, int(shortfall_cap), f"baseline_guard_shortfall_u{uid}")
                    model.Add(shortfall >= int(baseline_score) - guard_expr)
                    baseline_guard_shortfall_by_uid[int(uid)] = shortfall

        # build-conditioned constraints
        for b_idx, b in enumerate(builds):
            vb = use_build[(uid, b_idx)]
            for slot in (2, 4, 6):
                allowed = (b.mainstats or {}).get(slot) or []
                if not allowed:
                    continue
                for r in rune_candidates_by_slot[slot]:
                    key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(r.pri_eff[0] or 0), "")
                    if key and (key not in allowed):
                        model.Add(x[(uid, slot, int(r.rune_id))] == 0).OnlyEnforceIf(vb)

            # artifact filters
            artifact_focus_cfg = dict(getattr(b, "artifact_focus", {}) or {})
            artifact_sub_cfg = dict(getattr(b, "artifact_substats", {}) or {})
            for art_type, cfg_key in ((1, "attribute"), (2, "type")):
                allowed_focus = [str(x).upper() for x in (artifact_focus_cfg.get(cfg_key) or []) if str(x)]
                required_subs = [int(x) for x in (artifact_sub_cfg.get(cfg_key) or []) if int(x) > 0][:2]
                if not allowed_focus and not required_subs:
                    continue
                for art in artifacts_by_type_global[art_type]:
                    av = xa[(uid, art_type, int(art.artifact_id))]
                    if allowed_focus and _artifact_focus_key(art) not in allowed_focus:
                        model.Add(av == 0).OnlyEnforceIf(vb)
                        continue
                    if required_subs:
                        sec_ids = _artifact_substat_ids(art)
                        if any(req_id not in sec_ids for req_id in required_subs):
                            model.Add(av == 0).OnlyEnforceIf(vb)

            # set options
            if b.set_options:
                opt_vars: List[cp_model.IntVar] = []
                for o_idx, _opt in enumerate(b.set_options):
                    ov = model.NewBoolVar(f"use_opt_u{uid}_b{b_idx}_o{o_idx}")
                    opt_vars.append(ov)
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
                cr_terms: List[cp_model.LinearExpr] = []
                cd_terms: List[cp_model.LinearExpr] = []
                res_terms: List[cp_model.LinearExpr] = []
                acc_terms: List[cp_model.LinearExpr] = []
                hp_flat_terms: List[cp_model.LinearExpr] = []
                hp_pct_terms: List[cp_model.LinearExpr] = []
                atk_flat_terms: List[cp_model.LinearExpr] = []
                atk_pct_terms: List[cp_model.LinearExpr] = []
                def_flat_terms: List[cp_model.LinearExpr] = []
                def_pct_terms: List[cp_model.LinearExpr] = []
                for slot in range(1, 7):
                    for r in rune_candidates_by_slot[slot]:
                        xv = x[(uid, slot, int(r.rune_id))]
                        # stat totals from runes
                        cr = _rune_stat_total(r, 9)
                        cd = _rune_stat_total(r, 10)
                        rs = _rune_stat_total(r, 11)
                        ac = _rune_stat_total(r, 12)
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
                        if rs:
                            res_terms.append(rs * xv)
                        if ac:
                            acc_terms.append(ac * xv)
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

            spd_tick = int(getattr(b, "spd_tick", 0) or 0)
            min_spd_cfg = int((getattr(b, "min_stats", {}) or {}).get("SPD", 0) or 0)
            min_spd_no_base_cfg = int((getattr(b, "min_stats", {}) or {}).get("SPD_NO_BASE", 0) or 0)
            min_spd_tick = int(min_spd_for_tick(spd_tick, req.mode) or 0)
            if min_spd_cfg > 0:
                model.Add(final_spd_raw >= min_spd_cfg).OnlyEnforceIf(vb)
            if min_spd_no_base_cfg > 0:
                model.Add(final_spd_raw - int(base_spd or 0) >= min_spd_no_base_cfg).OnlyEnforceIf(vb)
            if min_spd_tick > 0:
                model.Add(final_spd >= min_spd_tick).OnlyEnforceIf(vb)
            if spd_tick != 0:
                max_spd_tick = int(max_spd_for_tick(spd_tick, req.mode) or 0)
                if max_spd_tick > 0:
                    model.Add(final_spd <= max_spd_tick).OnlyEnforceIf(vb)

    # Global uniqueness: each rune/artifact at most once
    rune_use_by_id: Dict[int, List[cp_model.IntVar]] = {}
    for (uid, slot, rid), vv in x.items():
        rune_use_by_id.setdefault(int(rid), []).append(vv)
    for rid, vars_for_rid in rune_use_by_id.items():
        model.Add(sum(vars_for_rid) <= 1)

    art_use_by_id: Dict[int, List[cp_model.IntVar]] = {}
    for (uid, _t, aid), vv in xa.items():
        art_use_by_id.setdefault(int(aid), []).append(vv)
    for aid, vars_for_aid in art_use_by_id.items():
        model.Add(sum(vars_for_aid) <= 1)

    # Global turn-order constraints
    if req.enforce_turn_order and req.unit_team_index and req.unit_team_turn_order:
        teams: Dict[int, List[int]] = {}
        for uid in unit_ids:
            t = req.unit_team_index.get(int(uid))
            trn = int(req.unit_team_turn_order.get(int(uid), 0) or 0)
            if t is None or trn <= 0:
                continue
            teams.setdefault(int(t), []).append(int(uid))
        for rows in teams.values():
            rows_sorted = sorted(rows, key=lambda u: int(req.unit_team_turn_order.get(int(u), 0) or 0))
            for i in range(1, len(rows_sorted)):
                prev_uid = int(rows_sorted[i - 1])
                cur_uid = int(rows_sorted[i])
                model.Add(final_speed_expr[prev_uid] >= final_speed_expr[cur_uid] + 1)

    # Objective: efficiency-first, speed as tie-break
    obj_terms: List[cp_model.LinearExpr] = []
    for (uid, slot, rid), vv in x.items():
        r = next((rr for rr in runes_by_slot_global[slot] if int(rr.rune_id) == int(rid)), None)
        if r is None:
            continue
        eff_score = int(round(float(rune_efficiency(r)) * 100.0))
        qual_score = int(_rune_quality_score(r, uid, None))
        if bool(favor_damage_by_uid.get(int(uid), False)):
            unit = account.units_by_id.get(int(uid))
            base_atk = int(unit.base_atk or 0) if unit else 0
            dmg_score = int(_rune_damage_score_proxy(r, base_atk))
            obj_terms.append(
                (
                    eff_score * int(ARENA_RUSH_ATK_EFFICIENCY_SCALE)
                    + qual_score
                    + (dmg_score * 140)
                ) * vv
            )
        elif bool(favor_defense_by_uid.get(int(uid), False)):
            unit = account.units_by_id.get(int(uid))
            base_hp = int((unit.base_con or 0) * 15) if unit else 0
            base_def = int(unit.base_def or 0) if unit else 0
            base_atk = int(unit.base_atk or 0) if unit else 0
            unit_arch = str(archetype_by_uid.get(int(uid), ""))
            qual_score = int(_rune_quality_score_defensive(r, uid, None))
            def_score = int(_rune_defensive_score_proxy(r, base_hp, base_def, unit_arch))
            dmg_penalty = int(_rune_damage_score_proxy(r, base_atk))
            obj_terms.append(
                (
                    eff_score * int(ARENA_RUSH_DEF_EFFICIENCY_SCALE)
                    + (int(ARENA_RUSH_DEF_QUALITY_WEIGHT) * qual_score)
                    + (int(ARENA_RUSH_DEF_RUNE_WEIGHT) * def_score)
                    - (int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * dmg_penalty)
                ) * vv
            )
        else:
            obj_terms.append((eff_score * 100 + qual_score) * vv)
    for (uid, t, aid), vv in xa.items():
        a = next((aa for aa in artifacts_by_type_global[t] if int(aa.artifact_id) == int(aid)), None)
        if a is None:
            continue
        base_hp, base_atk, base_def, base_spd = unit_base_stats_by_uid.get(int(uid), (0, 0, 0, 0))
        role_for_art = str(artifact_role_by_uid.get(int(uid), "unknown") or "unknown")
        unit_hint = dict((req.unit_artifact_hints_by_uid or {}).get(int(uid), {}) or {})
        hint_score = int(_artifact_hint_score(a, unit_hint))
        eff_score = int(round(float(artifact_efficiency(a)) * 100.0))
        qual_score = int(_artifact_quality_score(a, uid, None))
        if bool(favor_damage_by_uid.get(int(uid), False)):
            dmg_score = int(
                _artifact_damage_score_proxy(
                    a,
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    base_spd=int(base_spd or 0),
                )
            )
            obj_terms.append(
                (
                    eff_score * int(max(1, int(ARENA_RUSH_ATK_EFFICIENCY_SCALE * 0.8)))
                    + qual_score
                    + (dmg_score * 120)
                    + hint_score
                ) * vv
            )
        elif bool(favor_defense_by_uid.get(int(uid), False)):
            unit_arch = str(archetype_by_uid.get(int(uid), ""))
            qual_score = int(
                _artifact_quality_score_defensive(
                    a,
                    uid,
                    None,
                    archetype=unit_arch,
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    base_spd=int(base_spd or 0),
                )
            )
            def_score = int(
                _artifact_defensive_score_proxy(
                    a,
                    unit_arch,
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    base_spd=int(base_spd or 0),
                )
            )
            dmg_penalty = int(
                _artifact_damage_score_proxy(
                    a,
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    base_spd=int(base_spd or 0),
                )
            )
            obj_terms.append(
                (
                    eff_score * int(ARENA_RUSH_DEF_EFFICIENCY_SCALE)
                    + (int(ARENA_RUSH_DEF_QUALITY_WEIGHT) * qual_score)
                    + (int(ARENA_RUSH_DEF_ART_WEIGHT) * def_score)
                    - (int(ARENA_RUSH_DEF_OFFSTAT_PENALTY_WEIGHT) * dmg_penalty)
                    + hint_score
                ) * vv
            )
        else:
            context_score = int(
                _artifact_context_score_proxy(
                    a,
                    role=role_for_art,
                    base_hp=int(base_hp or 0),
                    base_atk=int(base_atk or 0),
                    base_def=int(base_def or 0),
                    base_spd=int(base_spd or 0),
                )
            )
            obj_terms.append(
                (
                    eff_score * 80
                    + qual_score
                    + (int(ARTIFACT_ROLE_CONTEXT_WEIGHT) * context_score)
                    + hint_score
                ) * vv
            )
    for uid in unit_ids:
        tie_raw = speed_tiebreak_weight_by_uid.get(int(uid), None)
        tie_w = 1 if tie_raw is None else int(tie_raw)
        if tie_w != 0:
            obj_terms.append(int(tie_w) * final_speed_expr[uid])
        over_expr = overcap_penalty_expr_by_uid.get(int(uid), None)
        if over_expr is not None:
            obj_terms.append((-int(GLOBAL_SOLVER_OVERCAP_PENALTY_SCALE)) * over_expr)
        shortfall_var = baseline_guard_shortfall_by_uid.get(int(uid), None)
        if shortfall_var is not None:
            guard_w = int(
                getattr(req, "baseline_regression_guard_weight", GLOBAL_BASELINE_REGRESSION_GUARD_WEIGHT)
                or GLOBAL_BASELINE_REGRESSION_GUARD_WEIGHT
            )
            obj_terms.append((-int(guard_w)) * shortfall_var)

    objective_expr = sum(obj_terms)
    solver = cp_model.CpSolver()
    if req.register_solver:
        try:
            req.register_solver(solver)
        except Exception:
            pass
    # Global model: budget scales with unit count.
    solver.parameters.max_time_in_seconds = float(max(10.0, float(req.time_limit_per_unit_s) * float(max(1, len(unit_ids))) * 1.5))
    solver.parameters.num_search_workers = int(max(1, int(req.workers or 1)))
    status = cp_model.UNKNOWN

    # Special rule: for Swift openers without extra min-stat requirements,
    # prioritize Swift usage and speed first, then optimize global quality.
    if force_speed_uids:
        forced_uids_sorted = sorted(int(uid) for uid in force_speed_uids)
        forced_swift_count_expr = sum(swift_active_by_uid[int(uid)] for uid in forced_uids_sorted)
        forced_speed_vars: Dict[int, cp_model.IntVar] = {}
        for uid in forced_uids_sorted:
            spd_var = model.NewIntVar(0, 2000, f"forced_speed_u{uid}")
            model.Add(spd_var == final_speed_expr[int(uid)])
            forced_speed_vars[int(uid)] = spd_var
        forced_speed_expr = sum(forced_speed_vars[int(uid)] for uid in forced_uids_sorted)
        forced_min_speed = model.NewIntVar(0, 2000, "forced_min_speed")
        model.AddMinEquality(forced_min_speed, [forced_speed_vars[int(uid)] for uid in forced_uids_sorted])

        # Stage 1: use Swift on as many forced openers as possible.
        model.Maximize(forced_swift_count_expr)
        status = solver.Solve(model)
        if req.is_cancelled and req.is_cancelled():
            return GreedyResult(False, tr("opt.cancelled"), [])
        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            best_swift_count = int(solver.Value(forced_swift_count_expr))
            model.Add(forced_swift_count_expr >= int(best_swift_count))

            # Stage 2: avoid one opener being too slow by maximizing the minimum speed.
            model.Maximize(forced_min_speed)
            status = solver.Solve(model)
            if req.is_cancelled and req.is_cancelled():
                return GreedyResult(False, tr("opt.cancelled"), [])
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                best_forced_min_speed = int(solver.Value(forced_min_speed))
                model.Add(forced_min_speed >= int(best_forced_min_speed))

                # Stage 3: then maximize total opener speed.
                model.Maximize(forced_speed_expr)
                status = solver.Solve(model)
                if req.is_cancelled and req.is_cancelled():
                    return GreedyResult(False, tr("opt.cancelled"), [])
                if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                    best_forced_speed = int(solver.Value(forced_speed_expr))
                    model.Add(forced_speed_expr >= int(best_forced_speed))

    run_count = int(max(1, int(req.multi_pass_count or 1))) if bool(req.multi_pass_enabled) else 1
    best_obj: Optional[int] = None
    best_x_assign: Set[Tuple[int, int, int]] = set()
    best_xa_assign: Set[Tuple[int, int, int]] = set()
    best_build_by_uid: Dict[int, int] = {}
    best_speed_by_uid: Dict[int, int] = {}
    seen_solution_signatures: Set[Tuple[Tuple[Tuple[int, int, int], ...], Tuple[Tuple[int, int, int], ...]]] = set()
    unique_solution_count = 0

    for run_idx in range(int(run_count)):
        try:
            seed_offset = int(getattr(req, "global_seed_offset", 0) or 0)
            solver.parameters.random_seed = int(101 + int(seed_offset) + (run_idx * 977))
            solver.parameters.randomize_search = bool(run_idx > 0)
        except Exception:
            pass
        model.Maximize(objective_expr)
        status = solver.Solve(model)
        if req.is_cancelled and req.is_cancelled():
            return GreedyResult(False, tr("opt.cancelled"), [])
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            break

        cur_x_assign: Set[Tuple[int, int, int]] = set()
        cur_xa_assign: Set[Tuple[int, int, int]] = set()
        cur_build_by_uid: Dict[int, int] = {}
        cur_speed_by_uid: Dict[int, int] = {}
        selected_vars: List[cp_model.IntVar] = []

        for key, vv in x.items():
            if int(solver.Value(vv)) == 1:
                cur_x_assign.add((int(key[0]), int(key[1]), int(key[2])))
                selected_vars.append(vv)
        for key, vv in xa.items():
            if int(solver.Value(vv)) == 1:
                cur_xa_assign.add((int(key[0]), int(key[1]), int(key[2])))
                selected_vars.append(vv)
        for uid in unit_ids:
            for b_idx, _b in enumerate(builds_by_uid[uid]):
                bv = use_build[(uid, b_idx)]
                if int(solver.Value(bv)) == 1:
                    cur_build_by_uid[int(uid)] = int(b_idx)
                    selected_vars.append(bv)
                    break
            cur_speed_by_uid[int(uid)] = int(solver.Value(final_speed_expr[int(uid)]))

        sig = (
            tuple(sorted(cur_x_assign)),
            tuple(sorted(cur_xa_assign)),
        )
        if sig not in seen_solution_signatures:
            seen_solution_signatures.add(sig)
            unique_solution_count += 1

        cur_obj = int(solver.Value(objective_expr))
        if best_obj is None or int(cur_obj) > int(best_obj):
            best_obj = int(cur_obj)
            best_x_assign = set(cur_x_assign)
            best_xa_assign = set(cur_xa_assign)
            best_build_by_uid = dict(cur_build_by_uid)
            best_speed_by_uid = dict(cur_speed_by_uid)

        if run_idx + 1 < int(run_count) and selected_vars:
            model.Add(sum(selected_vars) <= int(len(selected_vars) - 1))

    if best_obj is None:
        fallback = _run_greedy_pass(
            account=account,
            presets=presets,
            req=req,
            unit_ids=unit_ids,
            time_limit_per_unit_s=float(req.time_limit_per_unit_s),
            speed_slack_for_quality=0,
            rune_top_per_set_override=0,
        )
        ok_all = all(r.ok for r in fallback)
        msg = "Global infeasible/time limit; fallback heuristic used."
        return GreedyResult(ok_all, msg, fallback)

    # Extract
    results: List[GreedyUnitResult] = []
    for uid in unit_ids:
        chosen_runes: Dict[int, int] = {}
        for slot in range(1, 7):
            picked = 0
            for r in runes_by_slot_global[slot]:
                key = (uid, slot, int(r.rune_id))
                if key in best_x_assign:
                    picked = int(r.rune_id)
                    break
            if picked <= 0:
                results.append(GreedyUnitResult(uid, False, tr("opt.internal_no_rune", slot=slot), runes_by_slot={}))
                chosen_runes = {}
                break
            chosen_runes[slot] = picked
        if not chosen_runes:
            continue

        chosen_artifacts: Dict[int, int] = {}
        art_ok = True
        for t in (1, 2):
            picked_a = 0
            for a in artifacts_by_type_global[t]:
                akey = (uid, t, int(a.artifact_id))
                if akey in best_xa_assign:
                    picked_a = int(a.artifact_id)
                    break
            if picked_a <= 0:
                art_ok = False
                break
            chosen_artifacts[t] = picked_a

        chosen_build = builds_by_uid[uid][0]
        for b_idx, b in enumerate(builds_by_uid[uid]):
            if int(best_build_by_uid.get(int(uid), -1)) == int(b_idx):
                chosen_build = b
                break

        if not art_ok:
            results.append(GreedyUnitResult(uid, False, tr("opt.internal_no_artifact", art_type=1), runes_by_slot={}))
            continue

        # Post-check SPD guard (defensive; should already be guaranteed by constraints).
        floor_spd_raw = 0
        floor_spd_no_base = 0
        floor_tick_spd = 0
        for bb in builds_by_uid[uid]:
            cfg_min = int((getattr(bb, "min_stats", {}) or {}).get("SPD", 0) or 0)
            cfg_min_no_base = int((getattr(bb, "min_stats", {}) or {}).get("SPD_NO_BASE", 0) or 0)
            tick_min = int(min_spd_for_tick(int(getattr(bb, "spd_tick", 0) or 0), req.mode) or 0)
            floor_spd_raw = max(floor_spd_raw, cfg_min)
            floor_spd_no_base = max(floor_spd_no_base, cfg_min_no_base)
            floor_tick_spd = max(floor_tick_spd, tick_min)
        unit = account.units_by_id.get(int(uid))
        solved_spd = int(best_speed_by_uid.get(int(uid), 0))
        base_spd_u = int(unit.base_spd or 0) if unit else 0
        totem_spd_bonus_u = int(base_spd_u * int(account.sky_tribe_totem_spd_pct or 0) / 100)
        leader_spd_bonus_u = int((req.unit_spd_leader_bonus_flat or {}).get(int(uid), 0) or 0)
        solved_spd_raw = int(solved_spd - int(totem_spd_bonus_u) - int(leader_spd_bonus_u))
        solved_spd_no_base = solved_spd_raw - int(unit.base_spd or 0) if unit else solved_spd_raw
        if floor_spd_raw > 0 and solved_spd_raw < floor_spd_raw:
            results.append(
                GreedyUnitResult(
                    unit_id=uid,
                    ok=False,
                    message=f"Global raw SPD floor violated ({solved_spd_raw} < {floor_spd_raw})",
                    runes_by_slot={},
                )
            )
            continue
        if floor_spd_no_base > 0 and solved_spd_no_base < floor_spd_no_base:
            results.append(
                GreedyUnitResult(
                    unit_id=uid,
                    ok=False,
                    message=f"Global bonus SPD floor violated ({solved_spd_no_base} < {floor_spd_no_base})",
                    runes_by_slot={},
                )
            )
            continue
        if floor_tick_spd > 0 and solved_spd < floor_tick_spd:
            results.append(
                GreedyUnitResult(
                    unit_id=uid,
                    ok=False,
                    message=f"Global tick SPD floor violated ({solved_spd} < {floor_tick_spd})",
                    runes_by_slot={},
                )
            )
            continue
        results.append(
            GreedyUnitResult(
                unit_id=uid,
                ok=True,
                message="OK",
                chosen_build_id=str(chosen_build.id),
                chosen_build_name=str(chosen_build.name),
                runes_by_slot=chosen_runes,
                artifacts_by_type=chosen_artifacts,
                final_speed=solved_spd,
            )
        )

    ok_all = len(results) == len(unit_ids) and all(r.ok for r in results)
    msg_base = "Global optimization finished." if ok_all else "Global optimization partial."
    msg = f"{msg_base} runs={int(run_count)}, unique={int(max(1, unique_solution_count))}."
    return GreedyResult(ok_all, msg, results)
