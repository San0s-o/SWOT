from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from app.domain.models import AccountData, Artifact
from app.domain.presets import BuildStore, Build
from app.engine.arena_rush_timing import (
    OpeningTurnEffect,
    min_speed_floor_by_unit_from_effects,
    opening_order_penalty,
    simulate_opening_order,
    spd_buff_increase_pct_by_unit_from_assignments,
)
from app.engine.greedy_optimizer import GreedyRequest, GreedyResult, GreedyUnitResult, optimize_greedy


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
    offense_teams: List[ArenaRushOffenseTeam] = field(default_factory=list)
    workers: int = 8
    time_limit_per_unit_s: float = 5.0
    defense_pass_count: int = 1
    offense_pass_count: int = 3
    defense_quality_profile: str = "max_quality"
    offense_quality_profile: str = "balanced"
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
    simulated_order = simulate_opening_order(
        ordered_unit_ids=expected_order,
        combat_speed_by_unit=speed_by_uid,
        turn_effects_by_unit=dict(turn_effects_by_unit or {}),
        spd_buff_increase_pct_by_unit=spd_buff_inc_by_uid,
        max_actions=len(expected_order),
    )
    penalty = opening_order_penalty(expected_order, simulated_order)
    return list(simulated_order), int(penalty), speed_by_uid, spd_buff_inc_by_uid


def optimize_arena_rush(account: AccountData, presets: BuildStore, req: ArenaRushRequest) -> ArenaRushResult:
    defense_unit_ids = _unique_unit_ids(list(req.defense_unit_ids or []))
    if not defense_unit_ids:
        empty = GreedyResult(False, "Arena Rush: no defense units selected.", [])
        return ArenaRushResult(False, empty.message, empty, [])

    ordered_defense = _unit_order_from_presets(presets, req.mode, defense_unit_ids)
    defense_turn_order = dict(req.defense_unit_team_turn_order or {}) or _default_turn_order(ordered_defense)
    defense_team_index = {int(uid): 0 for uid in ordered_defense}
    defense_result = optimize_greedy(
        account,
        presets,
        GreedyRequest(
            mode=str(req.mode),
            unit_ids_in_order=ordered_defense,
            time_limit_per_unit_s=float(req.time_limit_per_unit_s),
            workers=int(req.workers),
            multi_pass_enabled=bool(int(req.defense_pass_count) > 1),
            multi_pass_count=max(1, int(req.defense_pass_count)),
            multi_pass_strategy="greedy_refine",
            quality_profile=str(req.defense_quality_profile),
            progress_callback=req.progress_callback if callable(req.progress_callback) else None,
            is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
            register_solver=req.register_solver if callable(req.register_solver) else None,
            enforce_turn_order=True,
            unit_team_index=defense_team_index,
            unit_team_turn_order=defense_turn_order,
            unit_spd_leader_bonus_flat=dict(req.defense_unit_spd_leader_bonus_flat or {}),
        ),
    )

    defense_locked_runes = _rune_ids_from_ok_results(defense_result.results)
    defense_locked_artifacts = _artifact_ids_from_ok_results(defense_result.results)

    artifact_lookup: Dict[int, Artifact] = {int(a.artifact_id): a for a in account.artifacts}
    offense_results: List[ArenaRushOffenseResult] = []
    shared_assignments_by_uid: Dict[int, GreedyUnitResult] = _ok_results_by_uid(defense_result.results)

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

        shared_unit_ids = [int(uid) for uid in unit_ids if int(uid) in shared_assignments_by_uid]
        swapped_in_unit_ids = [int(uid) for uid in unit_ids if int(uid) not in shared_assignments_by_uid]
        fixed_runes_by_uid = {
            int(uid): dict(shared_assignments_by_uid[int(uid)].runes_by_slot or {})
            for uid in shared_unit_ids
            if (shared_assignments_by_uid[int(uid)].runes_by_slot or {})
        }
        fixed_artifacts_by_uid = {
            int(uid): dict(shared_assignments_by_uid[int(uid)].artifacts_by_type or {})
            for uid in shared_unit_ids
            if (shared_assignments_by_uid[int(uid)].artifacts_by_type or {})
        }
        fixed_rune_ids: set[int] = set()
        for by_slot in fixed_runes_by_uid.values():
            for rid in (by_slot or {}).values():
                if int(rid or 0) > 0:
                    fixed_rune_ids.add(int(rid))
        fixed_artifact_ids: set[int] = set()
        for by_type in fixed_artifacts_by_uid.values():
            for aid in (by_type or {}).values():
                if int(aid or 0) > 0:
                    fixed_artifact_ids.add(int(aid))

        unit_turn_order = dict(team.unit_turn_order or {})
        if not unit_turn_order:
            unit_turn_order = _default_turn_order(expected_order)
        turn_effects_by_unit = dict(team.turn_effects_by_unit or {})
        shared_request_kwargs = dict(
            mode=str(req.mode),
            unit_ids_in_order=list(expected_order),
            time_limit_per_unit_s=float(req.time_limit_per_unit_s),
            workers=int(req.workers),
            multi_pass_enabled=bool(int(req.offense_pass_count) > 1),
            multi_pass_count=max(1, int(req.offense_pass_count)),
            multi_pass_strategy="greedy_refine",
            quality_profile=str(req.offense_quality_profile),
            progress_callback=req.progress_callback if callable(req.progress_callback) else None,
            is_cancelled=req.is_cancelled if callable(req.is_cancelled) else None,
            register_solver=req.register_solver if callable(req.register_solver) else None,
            enforce_turn_order=True,
            unit_team_index={int(uid): 0 for uid in expected_order},
            unit_team_turn_order=unit_turn_order,
            unit_spd_leader_bonus_flat=dict(team.unit_spd_leader_bonus_flat or {}),
            excluded_rune_ids=set(defense_locked_runes) - fixed_rune_ids,
            excluded_artifact_ids=set(defense_locked_artifacts) - fixed_artifact_ids,
            unit_fixed_runes_by_slot=fixed_runes_by_uid or None,
            unit_fixed_artifacts_by_type=fixed_artifacts_by_uid or None,
        )
        team_result = optimize_greedy(
            account,
            presets,
            GreedyRequest(
                **shared_request_kwargs,
            ),
        )

        ok_by_uid = _ok_results_by_uid(team_result.results)
        simulated_order, penalty, speed_by_uid, spd_buff_inc_by_uid = _evaluate_opening(
            expected_order=list(expected_order),
            turn_effects_by_unit=turn_effects_by_unit,
            ok_by_uid=ok_by_uid,
            artifact_lookup=artifact_lookup,
        )
        if turn_effects_by_unit and len(speed_by_uid) == len(expected_order):
            min_speed_floor_by_uid = min_speed_floor_by_unit_from_effects(
                expected_order=list(expected_order),
                combat_speed_by_unit=speed_by_uid,
                turn_effects_by_unit=turn_effects_by_unit,
                spd_buff_increase_pct_by_unit=spd_buff_inc_by_uid,
            )
            min_speed_floor_by_uid = {
                int(uid): int(spd)
                for uid, spd in min_speed_floor_by_uid.items()
                if int(uid) in expected_order and int(spd or 0) > 0
            }
            if min_speed_floor_by_uid:
                refined_result = optimize_greedy(
                    account,
                    presets,
                    GreedyRequest(
                        **shared_request_kwargs,
                        unit_min_final_speed=min_speed_floor_by_uid,
                    ),
                )
                refined_ok_by_uid = _ok_results_by_uid(refined_result.results)
                refined_simulated, refined_penalty, _, _ = _evaluate_opening(
                    expected_order=list(expected_order),
                    turn_effects_by_unit=turn_effects_by_unit,
                    ok_by_uid=refined_ok_by_uid,
                    artifact_lookup=artifact_lookup,
                )
                if refined_result.ok:
                    team_result = refined_result
                    ok_by_uid = refined_ok_by_uid
                    simulated_order = list(refined_simulated)
                    penalty = int(refined_penalty)

        offense_results.append(
            ArenaRushOffenseResult(
                team_index=int(team_index),
                team_unit_ids=list(unit_ids),
                shared_unit_ids=list(shared_unit_ids),
                swapped_in_unit_ids=list(swapped_in_unit_ids),
                optimization=team_result,
                expected_opening_order=list(expected_order),
                simulated_opening_order=list(simulated_order),
                opening_penalty=int(penalty),
            )
        )
        shared_assignments_by_uid.update(ok_by_uid)

    defense_ok = bool(defense_result.ok)
    offense_ok = all(bool(off.optimization.ok) for off in offense_results) if offense_results else True
    total_penalty = sum(int(off.opening_penalty or 0) for off in offense_results)
    ok_all = bool(defense_ok and offense_ok and total_penalty == 0)
    msg = (
        f"Arena Rush finished: defense_ok={int(defense_ok)}, "
        f"offense_ok={int(offense_ok)}, opening_penalty={int(total_penalty)}."
    )
    return ArenaRushResult(ok=ok_all, message=msg, defense=defense_result, offenses=offense_results)
