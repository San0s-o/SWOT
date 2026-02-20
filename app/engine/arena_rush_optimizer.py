from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from math import ceil
import time
from typing import Any, Dict, List

from app.domain.models import AccountData, Artifact
from app.domain.presets import BuildStore, Build
from app.domain.speed_ticks import LEO_LOW_SPD_TICK, min_spd_for_tick, max_spd_for_tick
from app.engine.efficiency import artifact_efficiency, rune_efficiency
from app.engine.arena_rush_timing import (
    OpeningTurnEffect,
    effective_spd_buff_pct_for_unit,
    min_speed_floor_by_unit_from_effects,
    opening_order_penalty,
    simulate_opening_order,
    spd_buff_increase_pct_by_unit_from_assignments,
)
from app.engine.greedy_optimizer import GreedyRequest, GreedyResult, GreedyUnitResult, optimize_greedy


LEO_LOW_TICK_SPEED_TIEBREAK_WEIGHT = 0


@dataclass
class ArenaRushOffenseTeam:
    unit_ids: List[int]
    expected_opening_order: List[int] = field(default_factory=list)
    unit_turn_order: Dict[int, int] = field(default_factory=dict)
    unit_spd_leader_bonus_flat: Dict[int, int] = field(default_factory=dict)
    turn_effects_by_unit: Dict[int, OpeningTurnEffect] = field(default_factory=dict)


@dataclass
class ArenaRushRequest:
    mode: str = "siege"
    defense_unit_ids: List[int] = field(default_factory=list)
    defense_unit_team_turn_order: Dict[int, int] = field(default_factory=dict)
    defense_unit_spd_leader_bonus_flat: Dict[int, int] = field(default_factory=dict)
    unit_archetype_by_uid: Dict[int, str] = field(default_factory=dict)
    unit_artifact_hints_by_uid: Dict[int, Dict[str, List[int]]] = field(default_factory=dict)
    unit_baseline_runes_by_slot: Dict[int, Dict[int, int]] = field(default_factory=dict)
    unit_baseline_artifacts_by_type: Dict[int, Dict[int, int]] = field(default_factory=dict)
    baseline_regression_guard_weight: int = 0
    offense_teams: List[ArenaRushOffenseTeam] = field(default_factory=list)
    workers: int = 8
    time_limit_per_unit_s: float = 5.0
    defense_pass_count: int = 1
    offense_pass_count: int = 3
    defense_quality_profile: str = "max_quality"
    offense_quality_profile: str = "balanced"
    defense_candidate_count: int = 1
    rune_top_per_set: int = 0
    max_runtime_s: float = 300.0
    is_cancelled: object | None = None
    register_solver: object | None = None
    progress_callback: object | None = None


@dataclass
class ArenaRushOffenseResult:
    team_index: int
    team_unit_ids: List[int]
    shared_unit_ids: List[int]
    swapped_in_unit_ids: List[int]
    optimization: GreedyResult
    expected_opening_order: List[int] = field(default_factory=list)
    simulated_opening_order: List[int] = field(default_factory=list)
    opening_penalty: int = 0


@dataclass
class ArenaRushResult:
    ok: bool
    message: str
    defense: GreedyResult
    offenses: List[ArenaRushOffenseResult]


def _unique_unit_ids(unit_ids: List[int]) -> List[int]:
    out: List[int] = []
    seen: set[int] = set()
    for uid in unit_ids:
        ui = int(uid or 0)
        if ui <= 0 or ui in seen:
            continue
        seen.add(ui)
        out.append(ui)
    return out


def _unit_order_from_presets(presets: BuildStore, mode: str, unit_ids: List[int]) -> List[int]:
    indexed: List[tuple[int, int, int]] = []
    for pos, uid in enumerate(unit_ids):
        builds = presets.get_unit_builds(mode, int(uid))
        b0 = builds[0] if builds else Build.default_any()
        opt = int(getattr(b0, "optimize_order", 0) or 0)
        indexed.append((opt, int(pos), int(uid)))
    with_order = [x for x in indexed if int(x[0]) > 0]
    without_order = [x for x in indexed if int(x[0]) <= 0]
    with_order.sort(key=lambda x: (int(x[0]), int(x[1])))
    without_order.sort(key=lambda x: int(x[1]))
    return [int(uid) for _, _, uid in (with_order + without_order)]


def _default_turn_order(unit_ids: List[int]) -> Dict[int, int]:
    return {int(uid): int(idx + 1) for idx, uid in enumerate(unit_ids)}


def _team_has_spd_buff(turn_effects_by_unit: Dict[int, OpeningTurnEffect] | None = None) -> bool:
    for effect in dict(turn_effects_by_unit or {}).values():
        if bool(getattr(effect, "applies_spd_buff", False)):
            return True
    return False


def _artifact_hints_for_units(
    base_hints_by_uid: Dict[int, Dict[str, List[int]]] | None,
    unit_ids: List[int],
    team_has_spd_buff_by_uid: Dict[int, bool] | None = None,
) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    for uid in (unit_ids or []):
        ui = int(uid or 0)
        if ui <= 0:
            continue
        base = dict((base_hints_by_uid or {}).get(int(ui), {}) or {})
        if team_has_spd_buff_by_uid is not None and int(ui) in team_has_spd_buff_by_uid:
            base["team_has_spd_buff"] = bool(team_has_spd_buff_by_uid.get(int(ui), False))
        if base:
            out[int(ui)] = base
    return out


def _unit_spd_tick_map_from_presets(presets: BuildStore, mode: str, unit_ids: List[int]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for uid in [int(x) for x in (unit_ids or []) if int(x) > 0]:
        builds = presets.get_unit_builds(str(mode), int(uid))
        b0 = builds[0] if builds else Build.default_any()
        tick = int(getattr(b0, "spd_tick", 0) or 0)
        if tick != 0:
            out[int(uid)] = int(tick)
    return out


def _unit_speed_tiebreak_weight_from_ticks(unit_spd_tick_by_uid: Dict[int, int]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for uid, tick in dict(unit_spd_tick_by_uid or {}).items():
        ui = int(uid or 0)
        if ui <= 0:
            continue
        if int(tick or 0) == int(LEO_LOW_SPD_TICK):
            out[int(ui)] = int(LEO_LOW_TICK_SPEED_TIEBREAK_WEIGHT)
    return out


def _has_spd_buff_before_turn(
    expected_order: List[int],
    target_uid: int,
    turn_effects_by_unit: Dict[int, OpeningTurnEffect],
) -> bool:
    order = [int(uid) for uid in (expected_order or []) if int(uid) > 0]
    tu = int(target_uid or 0)
    if tu <= 0 or tu not in order:
        return False
    pos_target = order.index(int(tu))
    for pos, caster_uid in enumerate(order):
        if pos >= pos_target:
            break
        effect = turn_effects_by_unit.get(int(caster_uid))
        if effect is None:
            continue
        if bool(effect.applies_spd_buff):
            return True
    return False


def _atb_boost_pct_before_turn(
    expected_order: List[int],
    target_uid: int,
    turn_effects_by_unit: Dict[int, OpeningTurnEffect],
) -> float:
    order = [int(uid) for uid in (expected_order or []) if int(uid) > 0]
    tu = int(target_uid or 0)
    if tu <= 0 or tu not in order:
        return 0.0
    pos_target = order.index(int(tu))
    total = 0.0
    for pos, caster_uid in enumerate(order):
        if pos >= pos_target:
            break
        effect = turn_effects_by_unit.get(int(caster_uid))
        if effect is None:
            continue
        total += max(0.0, float(effect.atb_boost_pct or 0.0))
    return max(0.0, min(95.0, float(total)))


def _min_speed_floor_by_unit_from_spd_ticks(
    expected_order: List[int],
    unit_spd_tick_by_uid: Dict[int, int],
    turn_effects_by_unit: Dict[int, OpeningTurnEffect],
    spd_buff_increase_pct_by_unit: Dict[int, float] | None = None,
    mode: str | None = None,
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    buff_inc = {int(uid): float(v) for uid, v in dict(spd_buff_increase_pct_by_unit or {}).items()}
    for uid in [int(x) for x in (expected_order or []) if int(x) > 0]:
        tick = int((unit_spd_tick_by_uid or {}).get(int(uid), 0) or 0)
        if tick == 0:
            continue
        min_tick_spd = int(min_spd_for_tick(int(tick), str(mode or "")) or 0)
        if min_tick_spd <= 0:
            continue
        speed_factor = 1.0
        if _has_spd_buff_before_turn(expected_order, int(uid), turn_effects_by_unit):
            eff_buff_pct = effective_spd_buff_pct_for_unit(
                buff_inc.get(int(uid), 0.0),
                base_spd_buff_pct=30.0,
            )
            speed_factor += max(0.0, float(eff_buff_pct)) / 100.0
        atb_boost_before = _atb_boost_pct_before_turn(expected_order, int(uid), turn_effects_by_unit)
        atb_factor = 1.0 - (max(0.0, float(atb_boost_before)) / 100.0)
        atb_factor = max(0.05, min(1.0, atb_factor))
        required = int(ceil((float(min_tick_spd) * float(atb_factor)) / max(1e-9, speed_factor)))
        if required > 0:
            out[int(uid)] = int(required)
    return out


def _max_speed_cap_by_unit_from_spd_ticks(
    expected_order: List[int],
    unit_spd_tick_by_uid: Dict[int, int],
    mode: str | None = None,
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for uid in [int(x) for x in (expected_order or []) if int(x) > 0]:
        tick = int((unit_spd_tick_by_uid or {}).get(int(uid), 0) or 0)
        if tick == 0:
            continue
        max_tick_spd = int(max_spd_for_tick(int(tick), str(mode or "")) or 0)
        if max_tick_spd <= 0:
            continue
        out[int(uid)] = int(max_tick_spd)
    return out


def _merge_speed_caps_min(
    left: Dict[int, int] | None,
    right: Dict[int, int] | None,
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for src in (dict(left or {}), dict(right or {})):
        for uid, cap in src.items():
            ui = int(uid or 0)
            cv = int(cap or 0)
            if ui <= 0 or cv <= 0:
                continue
            prev = int(out.get(ui, 0) or 0)
            if prev <= 0:
                out[ui] = int(cv)
            else:
                out[ui] = min(int(prev), int(cv))
    return out


def _context_base_spd_bonus_flat(
    account: AccountData,
    uid: int,
    leader_bonus_flat_by_uid: Dict[int, int] | None = None,
) -> int:
    unit = account.units_by_id.get(int(uid))
    base_spd = int(unit.base_spd or 0) if unit is not None else 0
    totem_spd_bonus_flat = int(base_spd * int(account.sky_tribe_totem_spd_pct or 0) / 100)
    leader_bonus_flat = int((leader_bonus_flat_by_uid or {}).get(int(uid), 0) or 0)
    return int(totem_spd_bonus_flat + leader_bonus_flat)


def _preflight_defense_shared_speed_bounds_from_offense_ticks(
    account: AccountData,
    presets: BuildStore,
    req: ArenaRushRequest,
    defense_unit_ids: List[int],
) -> tuple[Dict[int, int], Dict[int, int]]:
    defense_set = {int(uid) for uid in (defense_unit_ids or []) if int(uid) > 0}
    if not defense_set:
        return {}, {}

    defense_bonus_by_uid: Dict[int, int] = {
        int(uid): int(_context_base_spd_bonus_flat(account, int(uid), dict(req.defense_unit_spd_leader_bonus_flat or {})))
        for uid in defense_set
    }
    min_final_by_uid: Dict[int, int] = {}
    max_final_by_uid: Dict[int, int] = {}

    for team in list(req.offense_teams or []):
        unit_ids = _unique_unit_ids(list(team.unit_ids or []))
        if not unit_ids:
            continue
        ordered_team = _unit_order_from_presets(presets, req.mode, unit_ids)
        expected_order = _unique_unit_ids(list(team.expected_opening_order or []))
        if expected_order:
            for uid in ordered_team:
                if uid not in expected_order:
                    expected_order.append(uid)
        else:
            expected_order = list(ordered_team)
        team_effects = dict(team.turn_effects_by_unit or {})
        team_spd_ticks = _unit_spd_tick_map_from_presets(presets, req.mode, expected_order)
        tick_floor = _min_speed_floor_by_unit_from_spd_ticks(
            expected_order=list(expected_order),
            unit_spd_tick_by_uid=dict(team_spd_ticks),
            turn_effects_by_unit=team_effects,
            spd_buff_increase_pct_by_unit={},
            mode=req.mode,
        )
        tick_cap = _max_speed_cap_by_unit_from_spd_ticks(
            expected_order=list(expected_order),
            unit_spd_tick_by_uid=dict(team_spd_ticks),
            mode=req.mode,
        )
        offense_bonus_by_uid: Dict[int, int] = {
            int(uid): int(_context_base_spd_bonus_flat(account, int(uid), dict(team.unit_spd_leader_bonus_flat or {})))
            for uid in expected_order
        }
        for uid in expected_order:
            ui = int(uid)
            if ui not in defense_set:
                continue
            defense_bonus = int(defense_bonus_by_uid.get(ui, 0) or 0)
            offense_bonus = int(offense_bonus_by_uid.get(ui, 0) or 0)

            floor_final = int(tick_floor.get(ui, 0) or 0)
            if floor_final > 0:
                required_raw = max(0, int(floor_final) - int(offense_bonus))
                required_def_final = int(required_raw + defense_bonus)
                prev_floor = int(min_final_by_uid.get(ui, 0) or 0)
                if required_def_final > prev_floor:
                    min_final_by_uid[ui] = int(required_def_final)

            cap_final = int(tick_cap.get(ui, 0) or 0)
            if cap_final > 0:
                cap_raw = max(0, int(cap_final) - int(offense_bonus))
                cap_def_final = int(cap_raw + defense_bonus)
                prev_cap = int(max_final_by_uid.get(ui, 0) or 0)
                if prev_cap <= 0:
                    max_final_by_uid[ui] = int(cap_def_final)
                else:
                    max_final_by_uid[ui] = min(int(prev_cap), int(cap_def_final))

    return dict(min_final_by_uid), dict(max_final_by_uid)


def _max_speed_cap_by_unit_from_expected_order(
    expected_order: List[int],
    combat_speed_by_unit: Dict[int, int],
    turn_effects_by_unit: Dict[int, OpeningTurnEffect] | None = None,
    spd_buff_increase_pct_by_unit: Dict[int, float] | None = None,
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    order = [int(uid) for uid in (expected_order or []) if int(uid) > 0]
    if not order:
        return out
    effects = dict(turn_effects_by_unit or {})
    buff_inc = {int(uid): float(v) for uid, v in dict(spd_buff_increase_pct_by_unit or {}).items()}

    def _first_unique_opening(sim_order: List[int]) -> List[int]:
        out: List[int] = []
        seen: set[int] = set()
        for uid in sim_order:
            ui = int(uid)
            if ui in seen:
                continue
            seen.add(ui)
            out.append(ui)
            if len(out) >= len(order):
                break
        return out

    def _pair_is_ordered(prev_uid: int, cur_uid: int, speed_map: Dict[int, int]) -> bool:
        sim_raw = simulate_opening_order(
            ordered_unit_ids=list(order),
            combat_speed_by_unit=dict(speed_map),
            turn_effects_by_unit=dict(effects),
            spd_buff_increase_pct_by_unit=dict(buff_inc),
            max_actions=max(int(len(order) * 6), int(len(order))),
        )
        sim = _first_unique_opening(list(sim_raw))
        if int(prev_uid) not in sim or int(cur_uid) not in sim:
            return False
        return bool(int(sim.index(int(prev_uid))) < int(sim.index(int(cur_uid))))

    def _initiative_coeff(uid: int) -> float:
        speed_factor = 1.0
        if _has_spd_buff_before_turn(order, int(uid), effects):
            eff_buff_pct = effective_spd_buff_pct_for_unit(
                buff_inc.get(int(uid), 0.0),
                base_spd_buff_pct=30.0,
            )
            speed_factor += max(0.0, float(eff_buff_pct)) / 100.0
        atb_boost_before = _atb_boost_pct_before_turn(order, int(uid), effects)
        atb_factor = 1.0 - (max(0.0, float(atb_boost_before)) / 100.0)
        atb_factor = max(0.05, min(1.0, atb_factor))
        return float(speed_factor / atb_factor)

    for idx, uid in enumerate(order):
        if idx <= 0:
            continue
        prev_uid = int(order[idx - 1])
        prev_spd = int((combat_speed_by_unit or {}).get(prev_uid, 0) or 0)
        if prev_spd <= 1:
            continue
        prev_coeff = _initiative_coeff(int(prev_uid))
        cur_coeff = _initiative_coeff(int(uid))
        if float(cur_coeff) <= 0.0:
            continue
        # Keep successor initiative slightly below predecessor initiative.
        # This tightens caps when successor gains more speed from buff scaling.
        cap_raw = int((float(prev_spd) * float(prev_coeff)) / float(cur_coeff))
        cap = int(cap_raw - 1)
        if cap <= 0:
            continue
        if effects:
            # Refine the cap against the actual opening simulation (discrete ATB ticks).
            # This is tighter than pure ratio math and prevents edge cases where a unit
            # with slightly lower raw SPD still overtakes due to buff scaling.
            lo = 1
            hi = max(1, int(prev_spd) - 1)
            best = 0
            base_speed_map = {
                int(oid): int((combat_speed_by_unit or {}).get(int(oid), 0) or 0)
                for oid in order
            }
            while lo <= hi:
                mid = int((lo + hi) // 2)
                trial = dict(base_speed_map)
                trial[int(uid)] = int(mid)
                if _pair_is_ordered(int(prev_uid), int(uid), trial):
                    best = int(mid)
                    lo = int(mid + 1)
                else:
                    hi = int(mid - 1)
            if best > 0:
                cap = int(best)
        out[int(uid)] = int(cap)
    return out


def _rune_ids_from_ok_results(results: List[GreedyUnitResult]) -> set[int]:
    out: set[int] = set()
    for res in results:
        if not res.ok:
            continue
        for rid in (res.runes_by_slot or {}).values():
            if int(rid or 0) > 0:
                out.add(int(rid))
    return out


def _artifact_ids_from_ok_results(results: List[GreedyUnitResult]) -> set[int]:
    out: set[int] = set()
    for res in results:
        if not res.ok:
            continue
        for aid in (res.artifacts_by_type or {}).values():
            if int(aid or 0) > 0:
                out.add(int(aid))
    return out


def _ok_results_by_uid(results: List[GreedyUnitResult]) -> Dict[int, GreedyUnitResult]:
    out: Dict[int, GreedyUnitResult] = {}
    for res in results:
        if res.ok:
            out[int(res.unit_id)] = res
    return out


def _evaluate_opening(
    expected_order: List[int],
    turn_effects_by_unit: Dict[int, OpeningTurnEffect],
    ok_by_uid: Dict[int, GreedyUnitResult],
    artifact_lookup: Dict[int, Artifact],
) -> tuple[List[int], int, Dict[int, int], Dict[int, float]]:
    if not expected_order:
        return [], 0, {}, {}
    speed_by_uid = {
        int(uid): int(ok_by_uid[int(uid)].final_speed or 0)
        for uid in expected_order
        if int(uid) in ok_by_uid
    }
    if len(speed_by_uid) != len(expected_order):
        return [], 0, {}, {}
    artifacts_by_uid = {
        int(uid): dict(ok_by_uid[int(uid)].artifacts_by_type or {})
        for uid in expected_order
        if int(uid) in ok_by_uid
    }
    spd_buff_inc_by_uid = spd_buff_increase_pct_by_unit_from_assignments(
        artifacts_by_uid,
        artifact_lookup,
    )
    simulated_order_raw = simulate_opening_order(
        ordered_unit_ids=expected_order,
        combat_speed_by_unit=speed_by_uid,
        turn_effects_by_unit=dict(turn_effects_by_unit or {}),
        spd_buff_increase_pct_by_unit=spd_buff_inc_by_uid,
        # Evaluate opening by each unit's first action, not by the first N total actions.
        # Fast openers can otherwise appear multiple times before slower units act once.
        max_actions=max(int(len(expected_order) * 6), int(len(expected_order))),
    )
    simulated_order: List[int] = []
    seen: set[int] = set()
    for uid in simulated_order_raw:
        ui = int(uid)
        if ui in seen:
            continue
        seen.add(ui)
        simulated_order.append(ui)
        if len(simulated_order) >= len(expected_order):
            break
    penalty = opening_order_penalty(expected_order, simulated_order)
    return list(simulated_order), int(penalty), speed_by_uid, spd_buff_inc_by_uid


def _greedy_result_signature(results: List[GreedyUnitResult]) -> tuple[tuple[object, ...], ...]:
    rows: List[tuple[object, ...]] = []
    for res in list(results or []):
        runes = tuple(
            (int(slot), int(rid))
            for slot, rid in sorted(dict(res.runes_by_slot or {}).items(), key=lambda x: int(x[0]))
            if int(rid or 0) > 0
        )
        arts = tuple(
            (int(kind), int(aid))
            for kind, aid in sorted(dict(res.artifacts_by_type or {}).items(), key=lambda x: int(x[0]))
            if int(aid or 0) > 0
        )
        rows.append(
            (
                int(res.unit_id),
                bool(res.ok),
                runes,
                arts,
                int(res.final_speed or 0),
                str(res.chosen_build_id or ""),
            )
        )
    rows.sort(key=lambda x: int(x[0]))
    return tuple(rows)


def _arena_rush_all_results(res: ArenaRushResult) -> List[GreedyUnitResult]:
    out: List[GreedyUnitResult] = []
    out.extend(list(res.defense.results or []))
    for off in list(res.offenses or []):
        out.extend(list((off.optimization.results or [])))
    return out


def _arena_rush_efficiency_score(account: AccountData, res: ArenaRushResult) -> int:
    runes_by_id = account.runes_by_id()
    artifacts_by_id: Dict[int, Artifact] = {int(a.artifact_id): a for a in account.artifacts}
    total = 0
    for row in _arena_rush_all_results(res):
        if not bool(getattr(row, "ok", False)):
            continue
        for rid in dict(row.runes_by_slot or {}).values():
            rune = runes_by_id.get(int(rid or 0))
            if rune is None:
                continue
            total += int(round(float(rune_efficiency(rune)) * 1000.0))
        for aid in dict(row.artifacts_by_type or {}).values():
            art = artifacts_by_id.get(int(aid or 0))
            if art is None:
                continue
            total += int(round(float(artifact_efficiency(art)) * 1000.0))
    return int(total)


def _arena_rush_candidate_score(account: AccountData, res: ArenaRushResult) -> tuple[int, int, int, int, int, int, int, int]:
    offense_count = int(len(res.offenses or []))
    offense_ok_count = int(sum(1 for off in list(res.offenses or []) if bool(off.optimization.ok)))
    total_penalty = int(sum(int(off.opening_penalty or 0) for off in list(res.offenses or [])))
    all_results = _arena_rush_all_results(res)
    ok_unit_count = int(sum(1 for row in all_results if bool(getattr(row, "ok", False))))
    speed_sum = int(sum(int(getattr(row, "final_speed", 0) or 0) for row in all_results if bool(getattr(row, "ok", False))))
    return (
        int(bool(res.defense.ok)),
        int(offense_ok_count == offense_count),
        int(total_penalty == 0),
        int(offense_ok_count),
        int(-total_penalty),
        int(ok_unit_count),
        int(_arena_rush_efficiency_score(account, res)),
        int(speed_sum),
    )


def _optimize_arena_rush_single(
    account: AccountData,
    presets: BuildStore,
    req: ArenaRushRequest,
    defense_global_seed_offset: int = 0,
    offense_global_seed_offset: int = 0,
) -> ArenaRushResult:
    def _ok_count(rows: List[GreedyUnitResult]) -> int:
        return int(sum(1 for r in list(rows or []) if bool(getattr(r, "ok", False))))

    def _eff_speed_score(rows: List[GreedyUnitResult]) -> tuple[int, int]:
        runes_by_id = account.runes_by_id()
        artifacts_by_id: Dict[int, Artifact] = {int(a.artifact_id): a for a in account.artifacts}
        eff_sum = 0
        speed_sum = 0
        for rr in list(rows or []):
            if not bool(getattr(rr, "ok", False)):
                continue
            speed_sum += int(getattr(rr, "final_speed", 0) or 0)
            for rid in dict(getattr(rr, "runes_by_slot", {}) or {}).values():
                rune = runes_by_id.get(int(rid or 0))
                if rune is None:
                    continue
                eff_sum += int(round(float(rune_efficiency(rune)) * 1000.0))
            for aid in dict(getattr(rr, "artifacts_by_type", {}) or {}).values():
                art = artifacts_by_id.get(int(aid or 0))
                if art is None:
                    continue
                eff_sum += int(round(float(artifact_efficiency(art)) * 1000.0))
        return int(eff_sum), int(speed_sum)

    defense_unit_ids = _unique_unit_ids(list(req.defense_unit_ids or []))
    if not defense_unit_ids:
        empty = GreedyResult(False, "Arena Rush: no defense units selected.", [])
        return ArenaRushResult(False, empty.message, empty, [])

    preflight_defense_min_final_by_uid, preflight_defense_max_final_by_uid = (
        _preflight_defense_shared_speed_bounds_from_offense_ticks(
            account=account,
            presets=presets,
            req=req,
            defense_unit_ids=list(defense_unit_ids),
        )
    )

    ordered_defense = _unit_order_from_presets(presets, req.mode, defense_unit_ids)
    defense_turn_order = dict(req.defense_unit_team_turn_order or {}) or _default_turn_order(ordered_defense)
    defense_team_index = {int(uid): 0 for uid in ordered_defense}
    defense_result = optimize_greedy(
        account,
        presets,
        GreedyRequest(
            mode=str(req.mode),
            arena_rush_context="defense",
            unit_ids_in_order=ordered_defense,
            unit_archetype_by_uid={
                int(uid): str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
                for uid in ordered_defense
            },
            unit_artifact_hints_by_uid=_artifact_hints_for_units(
                base_hints_by_uid=req.unit_artifact_hints_by_uid,
                unit_ids=list(ordered_defense),
            ),
            unit_baseline_runes_by_slot={
                int(uid): dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                for uid in ordered_defense
                if dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
            },
            unit_baseline_artifacts_by_type={
                int(uid): dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                for uid in ordered_defense
                if dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
            },
            baseline_regression_guard_weight=int(req.baseline_regression_guard_weight or 0),
            time_limit_per_unit_s=float(req.time_limit_per_unit_s),
            workers=int(req.workers),
            multi_pass_enabled=bool(int(req.defense_pass_count) > 1),
            multi_pass_count=max(1, int(req.defense_pass_count)),
            multi_pass_strategy="greedy_refine",
            quality_profile=str(req.defense_quality_profile),
            rune_top_per_set=max(0, int(req.rune_top_per_set or 0)),
            global_seed_offset=int(defense_global_seed_offset or 0),
            progress_callback=req.progress_callback if callable(req.progress_callback) else None,
            is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
            register_solver=req.register_solver if callable(req.register_solver) else None,
            enforce_turn_order=True,
            unit_team_index=defense_team_index,
            unit_team_turn_order=defense_turn_order,
            unit_spd_leader_bonus_flat=dict(req.defense_unit_spd_leader_bonus_flat or {}),
            unit_min_final_speed=(preflight_defense_min_final_by_uid or None),
            unit_max_final_speed=(preflight_defense_max_final_by_uid or None),
        ),
    )
    if not bool(defense_result.ok):
        if not (callable(req.is_cancelled) and bool(req.is_cancelled())):
            defense_rescue = optimize_greedy(
                account,
                presets,
                GreedyRequest(
                    mode=str(req.mode),
                    arena_rush_context="defense",
                    unit_ids_in_order=ordered_defense,
                    unit_archetype_by_uid={
                        int(uid): str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
                        for uid in ordered_defense
                    },
                    unit_artifact_hints_by_uid=_artifact_hints_for_units(
                        base_hints_by_uid=req.unit_artifact_hints_by_uid,
                        unit_ids=list(ordered_defense),
                    ),
                    unit_baseline_runes_by_slot={
                        int(uid): dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                        for uid in ordered_defense
                        if dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                    },
                    unit_baseline_artifacts_by_type={
                        int(uid): dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                        for uid in ordered_defense
                        if dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                    },
                    baseline_regression_guard_weight=int(req.baseline_regression_guard_weight or 0),
                    time_limit_per_unit_s=max(5.0, float(req.time_limit_per_unit_s) * 2.5),
                    workers=int(req.workers),
                    multi_pass_enabled=True,
                    multi_pass_count=max(3, int(req.defense_pass_count or 1)),
                    multi_pass_strategy="greedy_refine",
                    quality_profile=str(req.defense_quality_profile),
                    rune_top_per_set=0,
                    global_seed_offset=int(defense_global_seed_offset or 0) + 17,
                    progress_callback=req.progress_callback if callable(req.progress_callback) else None,
                    is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
                    register_solver=req.register_solver if callable(req.register_solver) else None,
                    enforce_turn_order=True,
                    unit_team_index=defense_team_index,
                    unit_team_turn_order=defense_turn_order,
                    unit_spd_leader_bonus_flat=dict(req.defense_unit_spd_leader_bonus_flat or {}),
                    unit_min_final_speed=(preflight_defense_min_final_by_uid or None),
                    unit_max_final_speed=(preflight_defense_max_final_by_uid or None),
                ),
            )
            base_ok = _ok_count(defense_result.results)
            rescue_ok = _ok_count(defense_rescue.results)
            base_eff, base_speed = _eff_speed_score(defense_result.results)
            rescue_eff, rescue_speed = _eff_speed_score(defense_rescue.results)
            if (
                int(rescue_ok) > int(base_ok)
                or (
                    int(rescue_ok) == int(base_ok)
                    and (
                        (bool(defense_rescue.ok) and not bool(defense_result.ok))
                        or int(rescue_eff) > int(base_eff)
                        or (int(rescue_eff) == int(base_eff) and int(rescue_speed) > int(base_speed))
                    )
                )
            ):
                defense_result = defense_rescue

    defense_locked_runes = _rune_ids_from_ok_results(defense_result.results)
    defense_locked_artifacts = _artifact_ids_from_ok_results(defense_result.results)
    global_locked_runes: set[int] = set(defense_locked_runes)
    global_locked_artifacts: set[int] = set(defense_locked_artifacts)

    artifact_lookup: Dict[int, Artifact] = {int(a.artifact_id): a for a in account.artifacts}
    offense_results: List[ArenaRushOffenseResult] = []
    offense_cfg_rows: List[Dict[str, object]] = []
    seen_offense_units: set[int] = set()
    unit_occurrences: Dict[int, int] = {}
    for team_index, team in enumerate(list(req.offense_teams or [])):
        unit_ids = _unique_unit_ids(list(team.unit_ids or []))
        if not unit_ids:
            offense_results.append(
                ArenaRushOffenseResult(
                    team_index=int(team_index),
                    team_unit_ids=[],
                    shared_unit_ids=[],
                    swapped_in_unit_ids=[],
                    optimization=GreedyResult(False, "Arena Rush: offense team is empty.", []),
                )
            )
            continue
        ordered_team = _unit_order_from_presets(presets, req.mode, unit_ids)
        expected_order = _unique_unit_ids(list(team.expected_opening_order or []))
        if expected_order:
            for uid in ordered_team:
                if uid not in expected_order:
                    expected_order.append(uid)
        else:
            expected_order = list(ordered_team)
        unit_turn_order = dict(team.unit_turn_order or {})
        if not unit_turn_order:
            unit_turn_order = _default_turn_order(expected_order)
        turn_effects_by_unit = dict(team.turn_effects_by_unit or {})
        unit_spd_tick_by_uid = _unit_spd_tick_map_from_presets(presets, req.mode, expected_order)
        offense_cfg_rows.append(
            {
                "team_index": int(team_index),
                "unit_ids": list(unit_ids),
                "expected_order": list(expected_order),
                "unit_turn_order": dict(unit_turn_order),
                "turn_effects_by_unit": dict(turn_effects_by_unit),
                "unit_spd_leader_bonus_flat": dict(team.unit_spd_leader_bonus_flat or {}),
                "unit_spd_tick_by_uid": dict(unit_spd_tick_by_uid),
            }
        )
        for uid in unit_ids:
            unit_occurrences[int(uid)] = int(unit_occurrences.get(int(uid), 0) or 0) + 1
            seen_offense_units.add(int(uid))

    # Keep global turn-order constraints active even when duplicate units exist
    # across offense teams. The global map already stores first occurrence per uid,
    # which is enough to enforce ordering for unique units inside each team and
    # reduces expensive post-repair mismatches.
    global_enforce_turn_order = True
    defense_ok_by_uid = _ok_results_by_uid(defense_result.results)
    defense_overlap_uids: set[int] = {
        int(uid) for uid in seen_offense_units
        if int(uid) in defense_ok_by_uid
    }
    defense_fixed_runes_by_uid: Dict[int, Dict[int, int]] = {}
    defense_fixed_artifacts_by_uid: Dict[int, Dict[int, int]] = {}
    for uid in sorted(defense_overlap_uids):
        dres = defense_ok_by_uid.get(int(uid))
        if dres is None:
            continue
        rb = dict(dres.runes_by_slot or {})
        ab = dict(dres.artifacts_by_type or {})
        if rb:
            defense_fixed_runes_by_uid[int(uid)] = rb
        if ab:
            defense_fixed_artifacts_by_uid[int(uid)] = ab
    defense_fixed_rune_ids: set[int] = {
        int(rid)
        for by_slot in defense_fixed_runes_by_uid.values()
        for rid in by_slot.values()
        if int(rid or 0) > 0
    }
    defense_fixed_artifact_ids: set[int] = {
        int(aid)
        for by_type in defense_fixed_artifacts_by_uid.values()
        for aid in by_type.values()
        if int(aid or 0) > 0
    }
    offense_excluded_rune_ids = set(global_locked_runes) - defense_fixed_rune_ids
    offense_excluded_artifact_ids = set(global_locked_artifacts) - defense_fixed_artifact_ids

    all_offense_units_in_order: List[int] = []
    all_team_index_by_uid: Dict[int, int] = {}
    all_turn_order_by_uid: Dict[int, int] = {}
    all_spd_leader_bonus_by_uid: Dict[int, int] = {}
    all_speed_tiebreak_weight_by_uid: Dict[int, int] = {}
    base_tick_floor_by_uid: Dict[int, int] = {}
    base_tick_cap_by_uid: Dict[int, int] = {}
    for row in offense_cfg_rows:
        expected_order = list(row["expected_order"] or [])
        team_index = int(row["team_index"])
        team_turn_order = dict(row["unit_turn_order"] or {})
        team_leader_bonus = dict(row["unit_spd_leader_bonus_flat"] or {})
        team_spd_ticks = dict(row["unit_spd_tick_by_uid"] or {})
        team_speed_tie_weights = _unit_speed_tiebreak_weight_from_ticks(team_spd_ticks)
        team_effects = dict(row["turn_effects_by_unit"] or {})
        tick_floor = _min_speed_floor_by_unit_from_spd_ticks(
            expected_order=list(expected_order),
            unit_spd_tick_by_uid=team_spd_ticks,
            turn_effects_by_unit=team_effects,
            spd_buff_increase_pct_by_unit={},
            mode=req.mode,
        )
        tick_cap = _max_speed_cap_by_unit_from_spd_ticks(
            expected_order=list(expected_order),
            unit_spd_tick_by_uid=team_spd_ticks,
            mode=req.mode,
        )
        for uid in expected_order:
            if int(uid) not in all_offense_units_in_order:
                all_offense_units_in_order.append(int(uid))
            if int(uid) not in all_team_index_by_uid:
                all_team_index_by_uid[int(uid)] = int(team_index)
            if int(uid) not in all_turn_order_by_uid:
                all_turn_order_by_uid[int(uid)] = int(team_turn_order.get(int(uid), 0) or 0)
            if int(uid) not in all_spd_leader_bonus_by_uid:
                all_spd_leader_bonus_by_uid[int(uid)] = int(team_leader_bonus.get(int(uid), 0) or 0)
            speed_tie_raw = team_speed_tie_weights.get(int(uid), None)
            speed_tie_weight = 1 if speed_tie_raw is None else int(speed_tie_raw)
            if int(uid) not in all_speed_tiebreak_weight_by_uid:
                all_speed_tiebreak_weight_by_uid[int(uid)] = int(speed_tie_weight)
            else:
                all_speed_tiebreak_weight_by_uid[int(uid)] = min(
                    int(all_speed_tiebreak_weight_by_uid[int(uid)]),
                    int(speed_tie_weight),
                )
            floor = int(tick_floor.get(int(uid), 0) or 0)
            if floor > int(base_tick_floor_by_uid.get(int(uid), 0) or 0):
                base_tick_floor_by_uid[int(uid)] = int(floor)
            cap = int(tick_cap.get(int(uid), 0) or 0)
            if cap > 0:
                prev_cap = int(base_tick_cap_by_uid.get(int(uid), 0) or 0)
                if prev_cap <= 0:
                    base_tick_cap_by_uid[int(uid)] = int(cap)
                else:
                    base_tick_cap_by_uid[int(uid)] = min(int(prev_cap), int(cap))

    offense_team_has_spd_buff_by_uid: Dict[int, bool] = {}
    for row in offense_cfg_rows:
        has_team_spd_buff = bool(_team_has_spd_buff(dict(row.get("turn_effects_by_unit") or {})))
        for uid in (row.get("expected_order") or []):
            ui = int(uid or 0)
            if ui <= 0:
                continue
            if ui not in offense_team_has_spd_buff_by_uid:
                offense_team_has_spd_buff_by_uid[ui] = bool(has_team_spd_buff)

    global_offense_result = optimize_greedy(
        account,
        presets,
        GreedyRequest(
            mode=str(req.mode),
            arena_rush_context="offense",
            unit_ids_in_order=list(all_offense_units_in_order),
            unit_archetype_by_uid={
                int(uid): str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
                for uid in all_offense_units_in_order
            },
            unit_artifact_hints_by_uid=_artifact_hints_for_units(
                base_hints_by_uid=req.unit_artifact_hints_by_uid,
                unit_ids=list(all_offense_units_in_order),
                team_has_spd_buff_by_uid=dict(offense_team_has_spd_buff_by_uid),
            ),
            unit_baseline_runes_by_slot={
                int(uid): dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                for uid in all_offense_units_in_order
                if dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
            },
            unit_baseline_artifacts_by_type={
                int(uid): dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                for uid in all_offense_units_in_order
                if dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
            },
            baseline_regression_guard_weight=int(req.baseline_regression_guard_weight or 0),
            time_limit_per_unit_s=float(req.time_limit_per_unit_s),
            workers=int(req.workers),
            multi_pass_enabled=bool(int(req.offense_pass_count) > 1),
            multi_pass_count=max(1, int(req.offense_pass_count)),
            multi_pass_strategy="greedy_refine",
            quality_profile=str(req.offense_quality_profile),
            rune_top_per_set=max(0, int(req.rune_top_per_set or 0)),
            global_seed_offset=int(offense_global_seed_offset or 0),
            progress_callback=req.progress_callback if callable(req.progress_callback) else None,
            is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
            register_solver=req.register_solver if callable(req.register_solver) else None,
            enforce_turn_order=bool(global_enforce_turn_order),
            unit_team_index=dict(all_team_index_by_uid),
            unit_team_turn_order=dict(all_turn_order_by_uid),
            unit_spd_leader_bonus_flat=dict(all_spd_leader_bonus_by_uid),
            unit_speed_tiebreak_weight=dict(all_speed_tiebreak_weight_by_uid or {}),
            excluded_rune_ids=set(offense_excluded_rune_ids),
            excluded_artifact_ids=set(offense_excluded_artifact_ids),
            unit_fixed_runes_by_slot=(defense_fixed_runes_by_uid or None),
            unit_fixed_artifacts_by_type=(defense_fixed_artifacts_by_uid or None),
            unit_min_final_speed=(base_tick_floor_by_uid or None),
            unit_max_final_speed=(base_tick_cap_by_uid or None),
        ),
    )

    ok_by_uid_global = _ok_results_by_uid(global_offense_result.results)
    refined_floor_by_uid = dict(base_tick_floor_by_uid)
    refined_order_cap_by_uid: Dict[int, int] = {}
    for row in offense_cfg_rows:
        expected_order = list(row["expected_order"] or [])
        team_effects = dict(row["turn_effects_by_unit"] or {})
        simulated_order, penalty, speed_by_uid, spd_buff_inc_by_uid = _evaluate_opening(
            expected_order=list(expected_order),
            turn_effects_by_unit=team_effects,
            ok_by_uid=ok_by_uid_global,
            artifact_lookup=artifact_lookup,
        )
        _ = (simulated_order, penalty)
        if not speed_by_uid or len(speed_by_uid) != len(expected_order):
            continue
        if int(penalty) > 0:
            mismatch_caps = _max_speed_cap_by_unit_from_expected_order(
                expected_order=list(expected_order),
                combat_speed_by_unit=dict(speed_by_uid),
                turn_effects_by_unit=team_effects,
                spd_buff_increase_pct_by_unit=dict(spd_buff_inc_by_uid),
            )
            for uid, cap in mismatch_caps.items():
                ui = int(uid or 0)
                cv = int(cap or 0)
                if ui <= 0 or cv <= 0:
                    continue
                prev = int(refined_order_cap_by_uid.get(ui, 0) or 0)
                if prev <= 0:
                    refined_order_cap_by_uid[ui] = int(cv)
                else:
                    refined_order_cap_by_uid[ui] = min(int(prev), int(cv))
        effect_floor = min_speed_floor_by_unit_from_effects(
            expected_order=list(expected_order),
            combat_speed_by_unit=speed_by_uid,
            turn_effects_by_unit=team_effects,
            spd_buff_increase_pct_by_unit=spd_buff_inc_by_uid,
        )
        tick_floor_refined = _min_speed_floor_by_unit_from_spd_ticks(
            expected_order=list(expected_order),
            unit_spd_tick_by_uid=dict(row["unit_spd_tick_by_uid"] or {}),
            turn_effects_by_unit=team_effects,
            spd_buff_increase_pct_by_unit=spd_buff_inc_by_uid,
            mode=req.mode,
        )
        for uid, floor in {**effect_floor, **tick_floor_refined}.items():
            if int(uid) <= 0 or int(floor or 0) <= 0:
                continue
            prev = int(refined_floor_by_uid.get(int(uid), 0) or 0)
            if int(floor) > prev:
                refined_floor_by_uid[int(uid)] = int(floor)

    if refined_floor_by_uid or refined_order_cap_by_uid:
        global_offense_result = optimize_greedy(
            account,
            presets,
            GreedyRequest(
                mode=str(req.mode),
                arena_rush_context="offense",
                unit_ids_in_order=list(all_offense_units_in_order),
                unit_archetype_by_uid={
                    int(uid): str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
                    for uid in all_offense_units_in_order
                },
                unit_artifact_hints_by_uid=_artifact_hints_for_units(
                    base_hints_by_uid=req.unit_artifact_hints_by_uid,
                    unit_ids=list(all_offense_units_in_order),
                    team_has_spd_buff_by_uid=dict(offense_team_has_spd_buff_by_uid),
                ),
                unit_baseline_runes_by_slot={
                    int(uid): dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                    for uid in all_offense_units_in_order
                    if dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                },
                unit_baseline_artifacts_by_type={
                    int(uid): dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                    for uid in all_offense_units_in_order
                    if dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                },
                baseline_regression_guard_weight=int(req.baseline_regression_guard_weight or 0),
                time_limit_per_unit_s=float(req.time_limit_per_unit_s),
                workers=int(req.workers),
                multi_pass_enabled=bool(int(req.offense_pass_count) > 1),
                multi_pass_count=max(1, int(req.offense_pass_count)),
                multi_pass_strategy="greedy_refine",
                quality_profile=str(req.offense_quality_profile),
                rune_top_per_set=max(0, int(req.rune_top_per_set or 0)),
                global_seed_offset=int(offense_global_seed_offset or 0),
                progress_callback=req.progress_callback if callable(req.progress_callback) else None,
                is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
                register_solver=req.register_solver if callable(req.register_solver) else None,
                enforce_turn_order=bool(global_enforce_turn_order),
                unit_team_index=dict(all_team_index_by_uid),
                unit_team_turn_order=dict(all_turn_order_by_uid),
                unit_spd_leader_bonus_flat=dict(all_spd_leader_bonus_by_uid),
                unit_speed_tiebreak_weight=dict(all_speed_tiebreak_weight_by_uid or {}),
                excluded_rune_ids=set(offense_excluded_rune_ids),
                excluded_artifact_ids=set(offense_excluded_artifact_ids),
                unit_fixed_runes_by_slot=(defense_fixed_runes_by_uid or None),
                unit_fixed_artifacts_by_type=(defense_fixed_artifacts_by_uid or None),
                unit_min_final_speed=(refined_floor_by_uid or None),
                unit_max_final_speed=(
                    _merge_speed_caps_min(base_tick_cap_by_uid, refined_order_cap_by_uid)
                    or None
                ),
            ),
        )
        ok_by_uid_global = _ok_results_by_uid(global_offense_result.results)

    if int(req.baseline_regression_guard_weight or 0) > 0 and offense_cfg_rows:
        def _offense_health(res: GreedyResult) -> tuple[int, int]:
            ok_map = _ok_results_by_uid(res.results)
            ok_count = int(sum(1 for r in (res.results or []) if bool(getattr(r, "ok", False))))
            total_penalty = 0
            for _row in offense_cfg_rows:
                _expected_order = list(_row["expected_order"] or [])
                _team_effects = dict(_row["turn_effects_by_unit"] or {})
                _sim, _pen, _spd, _buff = _evaluate_opening(
                    expected_order=list(_expected_order),
                    turn_effects_by_unit=_team_effects,
                    ok_by_uid=ok_map,
                    artifact_lookup=artifact_lookup,
                )
                _ = (_sim, _spd, _buff)
                total_penalty += int(_pen)
            return int(ok_count), int(total_penalty)

        global_ok_count, global_penalty_sum = _offense_health(global_offense_result)
        if int(global_ok_count) < int(len(all_offense_units_in_order)) or int(global_penalty_sum) > 0:
            rescue_result = optimize_greedy(
                account,
                presets,
                GreedyRequest(
                    mode=str(req.mode),
                    arena_rush_context="offense",
                    unit_ids_in_order=list(all_offense_units_in_order),
                    unit_archetype_by_uid={
                        int(uid): str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
                        for uid in all_offense_units_in_order
                    },
                    unit_artifact_hints_by_uid=_artifact_hints_for_units(
                        base_hints_by_uid=req.unit_artifact_hints_by_uid,
                        unit_ids=list(all_offense_units_in_order),
                        team_has_spd_buff_by_uid=dict(offense_team_has_spd_buff_by_uid),
                    ),
                    unit_baseline_runes_by_slot={
                        int(uid): dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                        for uid in all_offense_units_in_order
                        if dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                    },
                    unit_baseline_artifacts_by_type={
                        int(uid): dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                        for uid in all_offense_units_in_order
                        if dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                    },
                    baseline_regression_guard_weight=0,
                    time_limit_per_unit_s=max(5.0, float(req.time_limit_per_unit_s) * 2.0),
                    workers=int(req.workers),
                    multi_pass_enabled=True,
                    multi_pass_count=max(3, int(req.offense_pass_count or 1)),
                    multi_pass_strategy="greedy_refine",
                    quality_profile="fast",
                    rune_top_per_set=0,
                    global_seed_offset=int(offense_global_seed_offset or 0) + 7331,
                    progress_callback=req.progress_callback if callable(req.progress_callback) else None,
                    is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
                    register_solver=req.register_solver if callable(req.register_solver) else None,
                    enforce_turn_order=bool(global_enforce_turn_order),
                    unit_team_index=dict(all_team_index_by_uid),
                    unit_team_turn_order=dict(all_turn_order_by_uid),
                    unit_spd_leader_bonus_flat=dict(all_spd_leader_bonus_by_uid),
                    unit_speed_tiebreak_weight=dict(all_speed_tiebreak_weight_by_uid or {}),
                    excluded_rune_ids=set(offense_excluded_rune_ids),
                    excluded_artifact_ids=set(offense_excluded_artifact_ids),
                    unit_fixed_runes_by_slot=(defense_fixed_runes_by_uid or None),
                    unit_fixed_artifacts_by_type=(defense_fixed_artifacts_by_uid or None),
                    unit_min_final_speed=(refined_floor_by_uid or base_tick_floor_by_uid or None),
                    unit_max_final_speed=(
                        _merge_speed_caps_min(base_tick_cap_by_uid, refined_order_cap_by_uid)
                        or None
                    ),
                ),
            )
            rescue_ok_count, rescue_penalty_sum = _offense_health(rescue_result)
            if int(rescue_ok_count) > int(global_ok_count) or (
                int(rescue_ok_count) == int(global_ok_count) and int(rescue_penalty_sum) < int(global_penalty_sum)
            ):
                global_offense_result = rescue_result
                ok_by_uid_global = _ok_results_by_uid(global_offense_result.results)

    by_uid_global_result: Dict[int, GreedyUnitResult] = {
        int(r.unit_id): r for r in (global_offense_result.results or [])
    }
    for row in offense_cfg_rows:
        team_index = int(row["team_index"])
        unit_ids = list(row["unit_ids"] or [])
        expected_order = list(row["expected_order"] or [])
        unit_turn_order = dict(row["unit_turn_order"] or {})
        unit_spd_tick_by_uid = dict(row["unit_spd_tick_by_uid"] or {})
        unit_speed_tiebreak_weight = _unit_speed_tiebreak_weight_from_ticks(unit_spd_tick_by_uid)
        unit_spd_leader_bonus_flat = dict(row["unit_spd_leader_bonus_flat"] or {})
        team_effects = dict(row["turn_effects_by_unit"] or {})
        team_res_list = [by_uid_global_result[int(uid)] for uid in unit_ids if int(uid) in by_uid_global_result]
        simulated_order, penalty, _speed_by_uid, _spd_buff_inc_by_uid = _evaluate_opening(
            expected_order=list(expected_order),
            turn_effects_by_unit=team_effects,
            ok_by_uid=ok_by_uid_global,
            artifact_lookup=artifact_lookup,
        )
        current_ok_count = int(sum(1 for r in team_res_list if bool(r.ok)))
        needs_repair = bool(int(penalty) > 0 or int(current_ok_count) < int(len(unit_ids)))
        if needs_repair:
            # Keep baseline-compare influence in the main offense solve, but
            # relax it in repair so hard feasibility/order issues can be fixed.
            repair_guard_weight = max(0, int(req.baseline_regression_guard_weight or 0) // 6)
            fixed_shared_uids = [int(uid) for uid in unit_ids if int(unit_occurrences.get(int(uid), 0) or 0) > 1]
            fixed_defense_overlap_uids = [int(uid) for uid in unit_ids if int(uid) in defense_overlap_uids]
            fixed_uids = sorted(set(fixed_shared_uids) | set(fixed_defense_overlap_uids))
            fixed_runes_by_uid: Dict[int, Dict[int, int]] = {}
            fixed_artifacts_by_uid: Dict[int, Dict[int, int]] = {}
            for uid in fixed_uids:
                g = by_uid_global_result.get(int(uid)) or defense_ok_by_uid.get(int(uid))
                if g is None:
                    continue
                rb = dict(g.runes_by_slot or {})
                ab = dict(g.artifacts_by_type or {})
                if rb:
                    fixed_runes_by_uid[int(uid)] = rb
                if ab:
                    fixed_artifacts_by_uid[int(uid)] = ab
            fixed_rune_ids: set[int] = {int(rid) for by_slot in fixed_runes_by_uid.values() for rid in by_slot.values() if int(rid or 0) > 0}
            fixed_artifact_ids: set[int] = {
                int(aid) for by_type in fixed_artifacts_by_uid.values() for aid in by_type.values() if int(aid or 0) > 0
            }
            used_outside_runes: set[int] = set()
            used_outside_artifacts: set[int] = set()
            team_set = {int(uid) for uid in unit_ids}
            for uid, gres in by_uid_global_result.items():
                if int(uid) in team_set:
                    continue
                for rid in (gres.runes_by_slot or {}).values():
                    if int(rid or 0) > 0:
                        used_outside_runes.add(int(rid))
                for aid in (gres.artifacts_by_type or {}).values():
                    if int(aid or 0) > 0:
                        used_outside_artifacts.add(int(aid))
            base_floor = _min_speed_floor_by_unit_from_spd_ticks(
                expected_order=list(expected_order),
                unit_spd_tick_by_uid=unit_spd_tick_by_uid,
                turn_effects_by_unit=team_effects,
                spd_buff_increase_pct_by_unit={},
                mode=req.mode,
            )
            base_tick_cap = _max_speed_cap_by_unit_from_spd_ticks(
                expected_order=list(expected_order),
                unit_spd_tick_by_uid=unit_spd_tick_by_uid,
                mode=req.mode,
            )
            repair_kwargs = dict(
                mode=str(req.mode),
                arena_rush_context="offense",
                unit_ids_in_order=list(expected_order),
                unit_archetype_by_uid={
                    int(uid): str((req.unit_archetype_by_uid or {}).get(int(uid), "") or "")
                    for uid in expected_order
                },
                unit_artifact_hints_by_uid=_artifact_hints_for_units(
                    base_hints_by_uid=req.unit_artifact_hints_by_uid,
                    unit_ids=list(expected_order),
                    team_has_spd_buff_by_uid={
                        int(uid): bool(_team_has_spd_buff(team_effects))
                        for uid in expected_order
                        if int(uid or 0) > 0
                    },
                ),
                unit_baseline_runes_by_slot={
                    int(uid): dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                    for uid in expected_order
                    if dict((req.unit_baseline_runes_by_slot or {}).get(int(uid), {}) or {})
                },
                unit_baseline_artifacts_by_type={
                    int(uid): dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                    for uid in expected_order
                    if dict((req.unit_baseline_artifacts_by_type or {}).get(int(uid), {}) or {})
                },
                baseline_regression_guard_weight=int(repair_guard_weight),
                time_limit_per_unit_s=float(req.time_limit_per_unit_s),
                workers=int(req.workers),
                multi_pass_enabled=bool(int(req.offense_pass_count) > 1),
                multi_pass_count=max(1, int(req.offense_pass_count)),
                multi_pass_strategy="greedy_refine",
                quality_profile=str(req.offense_quality_profile),
                rune_top_per_set=max(0, int(req.rune_top_per_set or 0)),
                global_seed_offset=(int(offense_global_seed_offset or 0) + (int(team_index) * 1009) + 1),
                progress_callback=req.progress_callback if callable(req.progress_callback) else None,
                is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
                register_solver=req.register_solver if callable(req.register_solver) else None,
                enforce_turn_order=True,
                unit_team_index={int(uid): 0 for uid in expected_order},
                unit_team_turn_order=dict(unit_turn_order or {int(uid): int(pos + 1) for pos, uid in enumerate(expected_order)}),
                unit_spd_leader_bonus_flat=dict(unit_spd_leader_bonus_flat),
                unit_speed_tiebreak_weight=dict(unit_speed_tiebreak_weight or {}),
                excluded_rune_ids=(set(offense_excluded_rune_ids) | used_outside_runes) - fixed_rune_ids,
                excluded_artifact_ids=(set(offense_excluded_artifact_ids) | used_outside_artifacts) - fixed_artifact_ids,
                unit_fixed_runes_by_slot=(fixed_runes_by_uid or None),
                unit_fixed_artifacts_by_type=(fixed_artifacts_by_uid or None),
                unit_min_final_speed=(base_floor or None),
                unit_max_final_speed=(base_tick_cap or None),
            )
            repair_result = optimize_greedy(account, presets, GreedyRequest(**repair_kwargs))
            repair_ok_by_uid = _ok_results_by_uid(repair_result.results)
            rep_sim, rep_pen, rep_speed_by_uid, rep_spd_inc_by_uid = _evaluate_opening(
                expected_order=list(expected_order),
                turn_effects_by_unit=team_effects,
                ok_by_uid=repair_ok_by_uid,
                artifact_lookup=artifact_lookup,
            )
            active_floor = dict(base_floor)
            if rep_speed_by_uid and len(rep_speed_by_uid) == len(expected_order):
                effect_floor = min_speed_floor_by_unit_from_effects(
                    expected_order=list(expected_order),
                    combat_speed_by_unit=rep_speed_by_uid,
                    turn_effects_by_unit=team_effects,
                    spd_buff_increase_pct_by_unit=rep_spd_inc_by_uid,
                )
                tick_floor_ref = _min_speed_floor_by_unit_from_spd_ticks(
                    expected_order=list(expected_order),
                    unit_spd_tick_by_uid=unit_spd_tick_by_uid,
                    turn_effects_by_unit=team_effects,
                    spd_buff_increase_pct_by_unit=rep_spd_inc_by_uid,
                    mode=req.mode,
                )
                merged_floor = dict(base_floor)
                for uid, floor in {**effect_floor, **tick_floor_ref}.items():
                    if int(uid or 0) <= 0 or int(floor or 0) <= 0:
                        continue
                    prev = int(merged_floor.get(int(uid), 0) or 0)
                    if int(floor) > prev:
                        merged_floor[int(uid)] = int(floor)
                if merged_floor != dict(base_floor):
                    repair_kwargs2 = dict(repair_kwargs)
                    repair_kwargs2["unit_min_final_speed"] = (merged_floor or None)
                    repair_result2 = optimize_greedy(account, presets, GreedyRequest(**repair_kwargs2))
                    repair_ok_by_uid2 = _ok_results_by_uid(repair_result2.results)
                    rep_sim2, rep_pen2, rep_speed_by_uid2, rep_spd_inc_by_uid2 = _evaluate_opening(
                        expected_order=list(expected_order),
                        turn_effects_by_unit=team_effects,
                        ok_by_uid=repair_ok_by_uid2,
                        artifact_lookup=artifact_lookup,
                    )
                    if int(rep_pen2) <= int(rep_pen):
                        repair_result = repair_result2
                        rep_pen = int(rep_pen2)
                        rep_sim = list(rep_sim2)
                        rep_speed_by_uid = dict(rep_speed_by_uid2)
                        rep_spd_inc_by_uid = dict(rep_spd_inc_by_uid2)
                        active_floor = dict(merged_floor)
            if rep_speed_by_uid and len(rep_speed_by_uid) == len(expected_order) and int(rep_pen) > 0:
                cap_map = _max_speed_cap_by_unit_from_expected_order(
                    expected_order=list(expected_order),
                    combat_speed_by_unit=dict(rep_speed_by_uid),
                    turn_effects_by_unit=team_effects,
                    spd_buff_increase_pct_by_unit=dict(rep_spd_inc_by_uid),
                )
                if cap_map:
                    repair_kwargs3 = dict(repair_kwargs)
                    repair_kwargs3["unit_min_final_speed"] = (active_floor or None)
                    repair_kwargs3["unit_max_final_speed"] = (
                        _merge_speed_caps_min(base_tick_cap, cap_map) or None
                    )
                    repair_result3 = optimize_greedy(account, presets, GreedyRequest(**repair_kwargs3))
                    repair_ok_by_uid3 = _ok_results_by_uid(repair_result3.results)
                    rep_sim3, rep_pen3, rep_speed_by_uid3, rep_spd_inc_by_uid3 = _evaluate_opening(
                        expected_order=list(expected_order),
                        turn_effects_by_unit=team_effects,
                        ok_by_uid=repair_ok_by_uid3,
                        artifact_lookup=artifact_lookup,
                    )
                    if int(rep_pen3) <= int(rep_pen):
                        repair_result = repair_result3
                        rep_pen = int(rep_pen3)
                        rep_sim = list(rep_sim3)
                        rep_speed_by_uid = dict(rep_speed_by_uid3)
                        rep_spd_inc_by_uid = dict(rep_spd_inc_by_uid3)
            rep_ok_count = int(sum(1 for r in (repair_result.results or []) if bool(getattr(r, "ok", False))))
            if int(rep_pen) > 0 or int(rep_ok_count) < int(len(unit_ids)):
                deep_kwargs = dict(repair_kwargs)
                deep_kwargs["time_limit_per_unit_s"] = max(5.0, float(req.time_limit_per_unit_s) * 2.5)
                deep_kwargs["multi_pass_enabled"] = True
                deep_kwargs["multi_pass_count"] = max(3, int(req.offense_pass_count or 1))
                deep_kwargs["rune_top_per_set"] = 0
                deep_kwargs["baseline_regression_guard_weight"] = 0
                if rep_speed_by_uid and len(rep_speed_by_uid) == len(expected_order):
                    deep_cap_map = _max_speed_cap_by_unit_from_expected_order(
                        expected_order=list(expected_order),
                        combat_speed_by_unit=dict(rep_speed_by_uid),
                        turn_effects_by_unit=team_effects,
                        spd_buff_increase_pct_by_unit=dict(rep_spd_inc_by_uid),
                    )
                    deep_kwargs["unit_max_final_speed"] = (
                        _merge_speed_caps_min(base_tick_cap, deep_cap_map) or None
                    )
                if active_floor:
                    deep_kwargs["unit_min_final_speed"] = (dict(active_floor) or None)
                deep_result = optimize_greedy(account, presets, GreedyRequest(**deep_kwargs))
                deep_ok_by_uid = _ok_results_by_uid(deep_result.results)
                deep_sim, deep_pen, deep_speed_by_uid, deep_spd_inc_by_uid = _evaluate_opening(
                    expected_order=list(expected_order),
                    turn_effects_by_unit=team_effects,
                    ok_by_uid=deep_ok_by_uid,
                    artifact_lookup=artifact_lookup,
                )
                deep_ok_count = int(sum(1 for r in (deep_result.results or []) if bool(getattr(r, "ok", False))))
                if int(deep_ok_count) > int(rep_ok_count) or (
                    int(deep_ok_count) == int(rep_ok_count) and int(deep_pen) < int(rep_pen)
                ):
                    repair_result = deep_result
                    rep_pen = int(deep_pen)
                    rep_sim = list(deep_sim)
                    rep_speed_by_uid = dict(deep_speed_by_uid)
                    rep_spd_inc_by_uid = dict(deep_spd_inc_by_uid)
                    rep_ok_count = int(deep_ok_count)
            if int(rep_pen) > 0 and rep_speed_by_uid and len(rep_speed_by_uid) == len(expected_order):
                strict_cap_map = _max_speed_cap_by_unit_from_expected_order(
                    expected_order=list(expected_order),
                    combat_speed_by_unit=dict(rep_speed_by_uid),
                    turn_effects_by_unit=team_effects,
                    spd_buff_increase_pct_by_unit=dict(rep_spd_inc_by_uid),
                )
                strict_floor: Dict[int, int] = dict(active_floor)
                for uid in list(expected_order[:-1]):
                    ui = int(uid)
                    sv = int(rep_speed_by_uid.get(ui, 0) or 0)
                    if sv <= 0:
                        continue
                    prev = int(strict_floor.get(ui, 0) or 0)
                    strict_floor[ui] = max(int(prev), int(sv))
                for uid, cap in dict(strict_cap_map).items():
                    ui = int(uid or 0)
                    cv = int(cap or 0)
                    if ui <= 0 or cv <= 0:
                        continue
                    fv = int(strict_floor.get(ui, 0) or 0)
                    if fv > cv:
                        strict_floor[ui] = int(cv)
                strict_kwargs = dict(repair_kwargs)
                strict_kwargs["baseline_regression_guard_weight"] = 0
                strict_kwargs["time_limit_per_unit_s"] = max(8.0, float(req.time_limit_per_unit_s) * 3.0)
                strict_kwargs["multi_pass_enabled"] = True
                strict_kwargs["multi_pass_count"] = max(4, int(req.offense_pass_count or 1))
                strict_kwargs["quality_profile"] = "fast"
                strict_kwargs["rune_top_per_set"] = 0
                strict_kwargs["unit_min_final_speed"] = (strict_floor or None)
                strict_kwargs["unit_max_final_speed"] = (
                    _merge_speed_caps_min(base_tick_cap, strict_cap_map) or None
                )
                strict_result = optimize_greedy(account, presets, GreedyRequest(**strict_kwargs))
                strict_ok_by_uid = _ok_results_by_uid(strict_result.results)
                strict_sim, strict_pen, strict_speed_by_uid, strict_spd_inc_by_uid = _evaluate_opening(
                    expected_order=list(expected_order),
                    turn_effects_by_unit=team_effects,
                    ok_by_uid=strict_ok_by_uid,
                    artifact_lookup=artifact_lookup,
                )
                strict_ok_count = int(sum(1 for r in (strict_result.results or []) if bool(getattr(r, "ok", False))))
                if int(strict_ok_count) > int(rep_ok_count) or (
                    int(strict_ok_count) == int(rep_ok_count) and int(strict_pen) < int(rep_pen)
                ):
                    repair_result = strict_result
                    rep_pen = int(strict_pen)
                    rep_sim = list(strict_sim)
                    rep_speed_by_uid = dict(strict_speed_by_uid)
                    rep_spd_inc_by_uid = dict(strict_spd_inc_by_uid)
                    rep_ok_count = int(strict_ok_count)
            should_accept_repair = bool(
                int(rep_ok_count) > int(current_ok_count)
                or (int(rep_ok_count) == int(current_ok_count) and int(rep_pen) < int(penalty))
            )
            if should_accept_repair:
                team_res_list = list(repair_result.results or [])
                simulated_order = list(rep_sim)
                penalty = int(rep_pen)
                # Keep global offense assignment state in sync with accepted repairs.
                # Otherwise later team-repairs can accidentally reuse newly selected
                # runes/artifacts because they only exclude "outside team" assignments.
                for rr in (repair_result.results or []):
                    if not bool(getattr(rr, "ok", False)):
                        continue
                    by_uid_global_result[int(rr.unit_id)] = rr
                    ok_by_uid_global[int(rr.unit_id)] = rr
        team_ok = bool(
            len(team_res_list) == len(unit_ids)
            and all(bool(r.ok) for r in team_res_list)
            and int(penalty) == 0
        )
        if not team_ok and int(penalty) > 0:
            team_res_list = [
                GreedyUnitResult(
                    unit_id=int(r.unit_id),
                    ok=False,
                    message=f"Opening order mismatch (penalty={int(penalty)}).",
                    chosen_build_id=str(r.chosen_build_id or ""),
                    chosen_build_name=str(r.chosen_build_name or ""),
                    runes_by_slot=dict(r.runes_by_slot or {}),
                    artifacts_by_type=dict(r.artifacts_by_type or {}),
                    final_speed=int(r.final_speed or 0),
                )
                for r in team_res_list
            ]
        team_opt = GreedyResult(
            ok=bool(team_ok),
            message=(
                str(global_offense_result.message)
                if int(penalty) == 0
                else f"{str(global_offense_result.message)} Opening order mismatch (penalty={int(penalty)})."
            ),
            results=list(team_res_list),
        )
        offense_results.append(
            ArenaRushOffenseResult(
                team_index=int(team_index),
                team_unit_ids=list(unit_ids),
                shared_unit_ids=[],
                swapped_in_unit_ids=list(unit_ids),
                optimization=team_opt,
                expected_opening_order=list(expected_order),
                simulated_opening_order=list(simulated_order),
                opening_penalty=int(penalty),
            )
        )

    defense_ok = bool(defense_result.ok)
    offense_ok = all(bool(off.optimization.ok) for off in offense_results) if offense_results else True
    total_penalty = sum(int(off.opening_penalty or 0) for off in offense_results)
    ok_all = bool(defense_ok and offense_ok and total_penalty == 0)
    msg = (
        f"Arena Rush finished: defense_ok={int(defense_ok)}, "
        f"offense_ok={int(offense_ok)}, opening_penalty={int(total_penalty)}."
    )
    return ArenaRushResult(ok=ok_all, message=msg, defense=defense_result, offenses=offense_results)


def optimize_arena_rush(account: AccountData, presets: BuildStore, req: ArenaRushRequest) -> ArenaRushResult:
    candidate_count = max(1, int(req.defense_candidate_count or 1))
    max_runtime_s = max(0.0, float(req.max_runtime_s or 0.0))
    deadline_ts = (float(time.monotonic()) + float(max_runtime_s)) if float(max_runtime_s) > 0.0 else 0.0

    def _deadline_reached() -> bool:
        return bool(float(deadline_ts) > 0.0 and float(time.monotonic()) >= float(deadline_ts))

    base_cancel = req.is_cancelled if callable(req.is_cancelled) else None
    if candidate_count <= 1:
        def _single_cancel() -> bool:
            if callable(base_cancel) and bool(base_cancel()):
                return True
            return bool(_deadline_reached())

        single_req = replace(req, is_cancelled=_single_cancel)
        return _optimize_arena_rush_single(
            account=account,
            presets=presets,
            req=single_req,
            defense_global_seed_offset=0,
            offense_global_seed_offset=0,
        )

    max_workers = max(1, int(req.workers or 1))
    parallel_candidates = max(1, min(int(candidate_count), int(max_workers)))
    # Split worker budget across parallel candidate jobs.
    workers_per_candidate = max(1, int(max_workers // parallel_candidates))

    best_result: ArenaRushResult | None = None
    best_score: tuple[int, int, int, int, int, int, int, int] | None = None
    best_idx = 10**9
    seen_defense_signatures: set[tuple[tuple[object, ...], ...]] = set()
    evaluated = 0
    unique_defense = 0

    def _run_candidate(idx: int) -> tuple[int, ArenaRushResult]:
        seed_offset = int(idx * 100003)
        def _sub_cancel() -> bool:
            if callable(base_cancel) and bool(base_cancel()):
                return True
            return bool(_deadline_reached())

        sub_req = replace(
            req,
            workers=int(workers_per_candidate),
            progress_callback=None,
            is_cancelled=_sub_cancel,
        )
        candidate = _optimize_arena_rush_single(
            account=account,
            presets=presets,
            req=sub_req,
            defense_global_seed_offset=seed_offset,
            offense_global_seed_offset=(seed_offset + 50021),
        )
        return int(idx), candidate

    if parallel_candidates <= 1:
        for idx in range(int(candidate_count)):
            if (callable(base_cancel) and bool(base_cancel())) or bool(_deadline_reached()):
                break
            ridx, candidate = _run_candidate(int(idx))
            evaluated += 1
            if callable(req.progress_callback):
                try:
                    req.progress_callback(int(evaluated), int(candidate_count))
                except Exception:
                    pass
            defense_sig = _greedy_result_signature(list(candidate.defense.results or []))
            if defense_sig not in seen_defense_signatures:
                seen_defense_signatures.add(defense_sig)
                unique_defense += 1
            cand_score = _arena_rush_candidate_score(account, candidate)
            if best_score is None or cand_score > best_score or (cand_score == best_score and int(ridx) < int(best_idx)):
                best_score = cand_score
                best_result = candidate
                best_idx = int(ridx)
    else:
        with ThreadPoolExecutor(max_workers=int(parallel_candidates)) as ex:
            futures = {
                ex.submit(_run_candidate, int(idx)): int(idx)
                for idx in range(int(candidate_count))
            }
            for fut in as_completed(futures):
                try:
                    ridx, candidate = fut.result()
                except Exception:
                    if (callable(base_cancel) and bool(base_cancel())) or bool(_deadline_reached()):
                        for ff in futures:
                            ff.cancel()
                        break
                    continue
                evaluated += 1
                if callable(req.progress_callback):
                    try:
                        req.progress_callback(int(evaluated), int(candidate_count))
                    except Exception:
                        pass
                defense_sig = _greedy_result_signature(list(candidate.defense.results or []))
                if defense_sig not in seen_defense_signatures:
                    seen_defense_signatures.add(defense_sig)
                    unique_defense += 1
                cand_score = _arena_rush_candidate_score(account, candidate)
                if best_score is None or cand_score > best_score or (cand_score == best_score and int(ridx) < int(best_idx)):
                    best_score = cand_score
                    best_result = candidate
                    best_idx = int(ridx)
                if (callable(base_cancel) and bool(base_cancel())) or bool(_deadline_reached()):
                    for ff in futures:
                        ff.cancel()
                    break

    if best_result is None:
        def _fallback_cancel() -> bool:
            if callable(base_cancel) and bool(base_cancel()):
                return True
            return bool(_deadline_reached())

        fallback_req = replace(req, is_cancelled=_fallback_cancel)
        best_result = _optimize_arena_rush_single(
            account=account,
            presets=presets,
            req=fallback_req,
            defense_global_seed_offset=0,
            offense_global_seed_offset=0,
        )

    msg_suffix = f" Defense candidates: unique={int(unique_defense)}/{int(candidate_count)}, evaluated={int(evaluated)}."
    return ArenaRushResult(
        ok=bool(best_result.ok),
        message=f"{str(best_result.message)}{msg_suffix}",
        defense=best_result.defense,
        offenses=list(best_result.offenses),
    )
