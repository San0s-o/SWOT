from __future__ import annotations

import time

from app.domain.models import AccountData, Artifact, Rune, Unit
from app.domain.presets import BuildStore, Build
from app.engine.arena_rush_optimizer import (
    LEO_LOW_TICK_SPEED_TIEBREAK_WEIGHT,
    ArenaRushOffenseTeam,
    ArenaRushResult,
    ArenaRushRequest,
    _max_speed_cap_by_unit_from_expected_order,
    optimize_arena_rush,
)
from app.engine.arena_rush_timing import OpeningTurnEffect, opening_order_penalty, simulate_opening_order
from app.engine.arena_rush_timing import min_speed_floor_by_unit_from_effects
from app.engine.greedy_optimizer import GreedyRequest, GreedyResult, GreedyUnitResult, optimize_greedy
from app.engine.greedy_optimizer import (
    _artifact_defensive_score_proxy,
    _artifact_quality_score_defensive,
    _is_attack_archetype,
    _is_defensive_archetype,
    _rune_flat_spd,
    _rune_quality_score_defensive,
    _rune_stat_total,
)
from app.domain.speed_ticks import LEO_LOW_SPD_TICK, allowed_spd_ticks, max_spd_for_tick, min_spd_for_tick


def _slots(base: int) -> dict[int, int]:
    return {slot: int(base + slot) for slot in range(1, 7)}


def test_simulate_opening_order_speed_buff_artifact_bonus() -> None:
    units = [1, 2, 3]
    speed = {1: 250, 2: 178, 3: 180}
    effects = {1: OpeningTurnEffect(applies_spd_buff=True)}

    without_artifact_bonus = simulate_opening_order(
        ordered_unit_ids=units,
        combat_speed_by_unit=speed,
        turn_effects_by_unit=effects,
        spd_buff_increase_pct_by_unit={2: 0.0, 3: 0.0},
        max_actions=3,
    )
    with_artifact_bonus = simulate_opening_order(
        ordered_unit_ids=units,
        combat_speed_by_unit=speed,
        turn_effects_by_unit=effects,
        spd_buff_increase_pct_by_unit={2: 40.0, 3: 0.0},
        max_actions=3,
    )

    assert without_artifact_bonus[0] == 1
    assert with_artifact_bonus[0] == 1
    assert without_artifact_bonus[1] == 3
    assert with_artifact_bonus[1] == 2
    assert opening_order_penalty([1, 2, 3], without_artifact_bonus) > 0
    assert opening_order_penalty([1, 2, 3], with_artifact_bonus) == 0


def test_buff_aware_speed_caps_tighten_for_later_unit_with_higher_spd_buff_gain() -> None:
    caps_plain = _max_speed_cap_by_unit_from_expected_order(
        expected_order=[1, 2, 3],
        combat_speed_by_unit={1: 250, 2: 180, 3: 178},
    )
    caps_buff_aware = _max_speed_cap_by_unit_from_expected_order(
        expected_order=[1, 2, 3],
        combat_speed_by_unit={1: 250, 2: 180, 3: 178},
        turn_effects_by_unit={1: OpeningTurnEffect(applies_spd_buff=True)},
        spd_buff_increase_pct_by_unit={3: 40.0},
    )

    # Legacy cap is predecessor - 1.
    assert int(caps_plain.get(3) or 0) == 179
    # With stronger buff scaling on unit 3, cap must be stricter than raw -1.
    assert int(caps_buff_aware.get(3) or 0) < 179


def test_rune_plus12_has_no_virtual_substat_roll_projection() -> None:
    rune = Rune(
        rune_id=1,
        slot_no=1,
        set_id=13,
        rank=6,
        rune_class=6,
        upgrade_curr=12,
        pri_eff=(1, 160),
        prefix_eff=(0, 0),
        sec_eff=[(8, 20, 0, 0), (2, 10, 0, 0), (9, 8, 0, 0), (12, 8, 0, 0)],
        occupied_type=0,
        occupied_id=0,
    )
    assert int(_rune_flat_spd(rune)) == 20
    assert int(_rune_stat_total(rune, 2)) == 10


def test_rune_plus12_projects_mainstat_to_plus15() -> None:
    spd_main = Rune(
        rune_id=2,
        slot_no=2,
        set_id=3,
        rank=6,
        rune_class=6,
        upgrade_curr=12,
        pri_eff=(8, 34),
        prefix_eff=(0, 0),
        sec_eff=[],
        occupied_type=0,
        occupied_id=0,
    )
    hp_pct_main = Rune(
        rune_id=3,
        slot_no=6,
        set_id=13,
        rank=6,
        rune_class=6,
        upgrade_curr=12,
        pri_eff=(2, 51),
        prefix_eff=(0, 0),
        sec_eff=[],
        occupied_type=0,
        occupied_id=0,
    )
    assert int(_rune_flat_spd(spd_main)) == 42
    assert int(_rune_stat_total(hp_pct_main, 2)) == 64


def test_optimize_arena_rush_keeps_shared_units_fixed(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=300,
            )
        ],
    )
    offense1_result = GreedyResult(
        ok=True,
        message="off1",
        results=[
            GreedyUnitResult(unit_id=201, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=280),
            GreedyUnitResult(unit_id=202, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=260),
            GreedyUnitResult(unit_id=203, ok=True, message="OK", runes_by_slot=_slots(3000), artifacts_by_type={1: 7005, 2: 7006}, final_speed=240),
        ],
    )
    offense2_result = GreedyResult(
        ok=True,
        message="off2",
        results=[
            GreedyUnitResult(unit_id=202, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=260),
            GreedyUnitResult(unit_id=203, ok=True, message="OK", runes_by_slot=_slots(3000), artifacts_by_type={1: 7005, 2: 7006}, final_speed=240),
            GreedyUnitResult(unit_id=204, ok=True, message="OK", runes_by_slot=_slots(4000), artifacts_by_type={1: 7007, 2: 7008}, final_speed=220),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            assert not greedy_req.excluded_rune_ids
            return defense_result
        if call_idx == 2:
            assert 9001 in set(greedy_req.excluded_rune_ids or set())
            assert not greedy_req.unit_fixed_runes_by_slot
            return offense1_result
        if call_idx == 3:
            # Team 2 misses unit 204 in the global solve and should trigger repair.
            assert bool(greedy_req.enforce_turn_order) is True
            return offense2_result
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            offense_teams=[
                ArenaRushOffenseTeam(
                    unit_ids=[201, 202, 203],
                    expected_opening_order=[201, 202, 203],
                ),
                ArenaRushOffenseTeam(
                    unit_ids=[202, 203, 204],
                    expected_opening_order=[202, 203, 204],
                ),
            ],
        ),
    )

    assert len(calls) == 3
    assert result.defense.ok
    assert len(result.offenses) == 2


def test_optimize_arena_rush_repairs_when_global_has_failed_unit_without_penalty(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=300,
            )
        ],
    )
    global_offense_result = GreedyResult(
        ok=False,
        message="offense-global",
        results=[
            GreedyUnitResult(
                unit_id=201,
                ok=True,
                message="OK",
                runes_by_slot=_slots(1000),
                artifacts_by_type={1: 7001, 2: 7002},
                final_speed=220,
            ),
            GreedyUnitResult(
                unit_id=202,
                ok=False,
                message="infeasible",
                runes_by_slot={},
                artifacts_by_type={},
                final_speed=0,
            ),
        ],
    )
    repair_result = GreedyResult(
        ok=True,
        message="offense-repair",
        results=[
            GreedyUnitResult(
                unit_id=201,
                ok=True,
                message="OK",
                runes_by_slot=_slots(1100),
                artifacts_by_type={1: 7101, 2: 7102},
                final_speed=220,
            ),
            GreedyUnitResult(
                unit_id=202,
                ok=True,
                message="OK",
                runes_by_slot=_slots(2100),
                artifacts_by_type={1: 7103, 2: 7104},
                final_speed=219,
            ),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            return defense_result
        if call_idx == 2:
            return global_offense_result
        if call_idx == 3:
            # Team-level repair should be attempted even when opening penalty is 0
            # if a unit failed in the global offense solve.
            assert bool(greedy_req.enforce_turn_order) is True
            return repair_result
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            offense_teams=[ArenaRushOffenseTeam(unit_ids=[201, 202], expected_opening_order=[201, 202])],
        ),
    )

    assert len(calls) == 3
    assert len(result.offenses) == 1
    assert result.offenses[0].optimization.ok
    assert int(result.offenses[0].opening_penalty) == 0


def test_optimize_arena_rush_defense_uses_rescue_pass_when_initial_defense_fails(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_failed = GreedyResult(
        ok=False,
        message="def-fail",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=False,
                message="infeasible",
                runes_by_slot={},
                artifacts_by_type={},
                final_speed=0,
            )
        ],
    )
    defense_ok = GreedyResult(
        ok=True,
        message="def-ok",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=300,
            )
        ],
    )
    offense_ok = GreedyResult(
        ok=True,
        message="off-ok",
        results=[
            GreedyUnitResult(
                unit_id=201,
                ok=True,
                message="OK",
                runes_by_slot=_slots(1000),
                artifacts_by_type={1: 7001, 2: 7002},
                final_speed=220,
            )
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        idx = len(calls)
        if idx == 1:
            return defense_failed
        if idx == 2:
            assert float(greedy_req.time_limit_per_unit_s) >= 5.0
            assert bool(greedy_req.multi_pass_enabled) is True
            assert int(greedy_req.rune_top_per_set or 0) == 0
            return defense_ok
        if idx == 3:
            return offense_ok
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            offense_teams=[ArenaRushOffenseTeam(unit_ids=[201], expected_opening_order=[201])],
        ),
    )

    assert len(calls) == 3
    assert bool(result.defense.ok) is True
    assert len(result.offenses) == 1
    assert bool(result.offenses[0].optimization.ok) is True


def test_optimize_arena_rush_uses_full_rune_pool_by_default(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=300,
            )
        ],
    )
    offense_result = GreedyResult(
        ok=True,
        message="offense",
        results=[
            GreedyUnitResult(unit_id=201, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=220),
            GreedyUnitResult(unit_id=202, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=200),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        if len(calls) == 1:
            return defense_result
        return offense_result

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    _ = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            offense_teams=[ArenaRushOffenseTeam(unit_ids=[201, 202], expected_opening_order=[201, 202])],
        ),
    )

    assert len(calls) >= 2
    assert all(int(getattr(c, "rune_top_per_set", -1)) == 0 for c in calls)


def test_optimize_arena_rush_selects_best_defense_candidate(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result_1 = GreedyResult(
        ok=True,
        message="defense-1",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=300,
            )
        ],
    )
    offense_result_1 = GreedyResult(
        ok=True,
        message="offense-1",
        results=[
            GreedyUnitResult(unit_id=201, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=220),
            GreedyUnitResult(unit_id=202, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=200),
        ],
    )
    defense_result_2 = GreedyResult(
        ok=True,
        message="defense-2",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9100),
                artifacts_by_type={1: 8101, 2: 8102},
                final_speed=301,
            )
        ],
    )
    offense_result_2 = GreedyResult(
        ok=True,
        message="offense-2",
        results=[
            GreedyUnitResult(unit_id=201, ok=True, message="OK", runes_by_slot=_slots(1100), artifacts_by_type={1: 7101, 2: 7102}, final_speed=230),
            GreedyUnitResult(unit_id=202, ok=True, message="OK", runes_by_slot=_slots(2100), artifacts_by_type={1: 7103, 2: 7104}, final_speed=220),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            assert int(greedy_req.global_seed_offset or 0) == 0
            return defense_result_1
        if call_idx == 2:
            return offense_result_1
        if call_idx == 3:
            assert int(greedy_req.global_seed_offset or 0) > 0
            return defense_result_2
        if call_idx == 4:
            return offense_result_2
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            offense_teams=[ArenaRushOffenseTeam(unit_ids=[201, 202], expected_opening_order=[201, 202])],
            defense_candidate_count=2,
            workers=1,
        ),
    )

    assert len(calls) == 4
    assert result.ok
    assert int(result.offenses[0].opening_penalty) == 0
    assert int(result.defense.results[0].runes_by_slot.get(1) or 0) == 9101


def test_optimize_arena_rush_scores_duplicate_defense_candidates(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=300,
            )
        ],
    )
    offense_result_1 = GreedyResult(
        ok=True,
        message="offense-1",
        results=[
            GreedyUnitResult(unit_id=201, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=220),
            GreedyUnitResult(unit_id=202, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=200),
        ],
    )
    offense_result_2 = GreedyResult(
        ok=True,
        message="offense-2",
        results=[
            GreedyUnitResult(unit_id=201, ok=True, message="OK", runes_by_slot=_slots(1100), artifacts_by_type={1: 7101, 2: 7102}, final_speed=240),
            GreedyUnitResult(unit_id=202, ok=True, message="OK", runes_by_slot=_slots(2100), artifacts_by_type={1: 7103, 2: 7104}, final_speed=200),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx in (1, 3):
            return defense_result
        if call_idx == 2:
            assert int(greedy_req.global_seed_offset or 0) > 0
            return offense_result_1
        if call_idx == 4:
            assert int(greedy_req.global_seed_offset or 0) > int((calls[1].global_seed_offset or 0))
            return offense_result_2
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            offense_teams=[ArenaRushOffenseTeam(unit_ids=[201, 202], expected_opening_order=[201, 202])],
            defense_candidate_count=2,
            workers=1,
        ),
    )

    assert len(calls) == 4
    assert result.ok
    assert int(result.offenses[0].opening_penalty) == 0
    assert int(result.offenses[0].optimization.results[0].runes_by_slot.get(1) or 0) == 1101


def test_optimize_arena_rush_respects_max_runtime_budget(monkeypatch) -> None:
    calls = {"n": 0}

    def _fake_single(*_args, **_kwargs):  # noqa: ANN001
        calls["n"] += 1
        time.sleep(0.03)
        defense_global_seed_offset = int(_kwargs.get("defense_global_seed_offset", 0) or 0)
        offense_global_seed_offset = int(_kwargs.get("offense_global_seed_offset", 0) or 0)
        return ArenaRushResult(
            ok=True,
            message=f"fake-{defense_global_seed_offset}-{offense_global_seed_offset}",
            defense=GreedyResult(ok=True, message="def", results=[]),
            offenses=[],
        )

    monkeypatch.setattr("app.engine.arena_rush_optimizer._optimize_arena_rush_single", _fake_single)

    _ = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            defense_candidate_count=20,
            workers=1,
            max_runtime_s=0.08,
        ),
    )

    assert int(calls["n"]) < 20


def test_optimize_arena_rush_parallel_keeps_first_finished_candidate_after_deadline(monkeypatch) -> None:
    def _fake_single(*_args, **_kwargs):  # noqa: ANN001
        time.sleep(0.03)
        seed = int(_kwargs.get("defense_global_seed_offset", 0) or 0)
        return ArenaRushResult(
            ok=True,
            message=f"cand-{seed}",
            defense=GreedyResult(
                ok=True,
                message="def",
                results=[GreedyUnitResult(unit_id=101, ok=True, message="OK", runes_by_slot=_slots(9000), artifacts_by_type={1: 8001, 2: 8002}, final_speed=300)],
            ),
            offenses=[],
        )

    monkeypatch.setattr("app.engine.arena_rush_optimizer._optimize_arena_rush_single", _fake_single)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            defense_candidate_count=2,
            workers=2,
            max_runtime_s=0.01,
        ),
    )

    assert result.defense.ok
    assert "evaluated=1" in str(result.message)


def test_min_speed_floor_from_effects_uses_atb_and_spd_buff() -> None:
    atb_floor = min_speed_floor_by_unit_from_effects(
        expected_order=[1, 2],
        combat_speed_by_unit={1: 300, 2: 180},
        turn_effects_by_unit={1: OpeningTurnEffect(atb_boost_pct=30.0)},
    )
    assert atb_floor.get(2) == 210

    spd_floor = min_speed_floor_by_unit_from_effects(
        expected_order=[10, 11],
        combat_speed_by_unit={10: 170, 11: 120},
        turn_effects_by_unit={10: OpeningTurnEffect(applies_spd_buff=True)},
        spd_buff_increase_pct_by_unit={11: 20.0},
    )
    # 30% buff with +20% increase => 36% effective buff.
    # Required raw speed = ceil(170 / 1.36) = 125.
    assert spd_floor.get(11) == 125


def test_optimize_arena_rush_refines_with_effect_speed_floor(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[GreedyUnitResult(unit_id=901, ok=True, message="OK", runes_by_slot=_slots(9100), artifacts_by_type={1: 9901, 2: 9902}, final_speed=260)],
    )
    offense_base = GreedyResult(
        ok=True,
        message="off-base",
        results=[
            GreedyUnitResult(unit_id=1001, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=300),
            GreedyUnitResult(unit_id=1002, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=180),
        ],
    )
    offense_refined = GreedyResult(
        ok=True,
        message="off-refined",
        results=[
            GreedyUnitResult(unit_id=1001, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=300),
            GreedyUnitResult(unit_id=1002, ok=True, message="OK", runes_by_slot=_slots(2001), artifacts_by_type={1: 7005, 2: 7006}, final_speed=220),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            return defense_result
        if call_idx == 2:
            assert not greedy_req.unit_min_final_speed
            return offense_base
        if call_idx == 3:
            floors = dict(greedy_req.unit_min_final_speed or {})
            assert floors.get(1002) == 210
            return offense_refined
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            defense_unit_ids=[901],
            offense_teams=[
                ArenaRushOffenseTeam(
                    unit_ids=[1001, 1002],
                    expected_opening_order=[1001, 1002],
                    turn_effects_by_unit={1001: OpeningTurnEffect(atb_boost_pct=30.0)},
                ),
            ],
        ),
    )

    assert len(calls) == 3
    assert len(result.offenses) == 1
    assert result.offenses[0].optimization.message == "off-refined"


def test_optimize_arena_rush_runs_global_rescue_when_compare_guard_blocks_opening_order(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[GreedyUnitResult(unit_id=901, ok=True, message="OK", runes_by_slot=_slots(9100), artifacts_by_type={1: 9901, 2: 9902}, final_speed=260)],
    )
    offense_blocked = GreedyResult(
        ok=True,
        message="off-blocked",
        results=[
            GreedyUnitResult(unit_id=1001, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=300),
            GreedyUnitResult(unit_id=1002, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=301),
        ],
    )
    offense_rescue = GreedyResult(
        ok=True,
        message="off-rescue",
        results=[
            GreedyUnitResult(unit_id=1001, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=300),
            GreedyUnitResult(unit_id=1002, ok=True, message="OK", runes_by_slot=_slots(2001), artifacts_by_type={1: 7005, 2: 7006}, final_speed=299),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            return defense_result
        if call_idx == 2:
            # Global offense with compare guard.
            assert int(greedy_req.baseline_regression_guard_weight or 0) == 3000
            return offense_blocked
        if call_idx == 3:
            # Refined global retry can still stay blocked.
            assert int(greedy_req.baseline_regression_guard_weight or 0) == 3000
            return offense_blocked
        if call_idx == 4:
            # Global rescue must relax compare guard.
            assert int(greedy_req.baseline_regression_guard_weight or 0) == 0
            assert str(greedy_req.quality_profile or "") == "fast"
            assert int(greedy_req.rune_top_per_set or 0) == 0
            return offense_rescue
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            defense_unit_ids=[901],
            offense_teams=[
                ArenaRushOffenseTeam(
                    unit_ids=[1001, 1002],
                    expected_opening_order=[1001, 1002],
                ),
            ],
            baseline_regression_guard_weight=3000,
        ),
    )

    assert len(calls) == 4
    assert len(result.offenses) == 1
    assert int(result.offenses[0].opening_penalty or 0) == 0
    assert result.offenses[0].optimization.ok
    assert str(result.offenses[0].optimization.message) == "off-rescue"


def test_optimize_arena_rush_reuses_defense_assignments_for_overlapping_offense_unit(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=300,
            )
        ],
    )
    offense_result = GreedyResult(
        ok=True,
        message="offense",
        results=[
            GreedyUnitResult(unit_id=101, ok=True, message="OK", runes_by_slot=_slots(9000), artifacts_by_type={1: 8001, 2: 8002}, final_speed=300),
            GreedyUnitResult(unit_id=102, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=200),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            return defense_result
        if call_idx == 2:
            fixed_runes = dict(greedy_req.unit_fixed_runes_by_slot or {})
            fixed_arts = dict(greedy_req.unit_fixed_artifacts_by_type or {})
            assert fixed_runes.get(101) == _slots(9000)
            assert fixed_arts.get(101) == {1: 8001, 2: 8002}
            excluded_runes = set(greedy_req.excluded_rune_ids or set())
            excluded_arts = set(greedy_req.excluded_artifact_ids or set())
            assert 9001 not in excluded_runes
            assert 8001 not in excluded_arts
            return offense_result
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            defense_unit_ids=[101],
            offense_teams=[ArenaRushOffenseTeam(unit_ids=[101, 102], expected_opening_order=[101, 102])],
        ),
    )

    assert len(calls) == 2
    assert result.defense.ok
    assert len(result.offenses) == 1
    assert result.offenses[0].optimization.ok


def test_optimize_arena_rush_enforces_low_leo_tick_cap(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[GreedyUnitResult(unit_id=901, ok=True, message="OK", runes_by_slot=_slots(9100), artifacts_by_type={1: 9901, 2: 9902}, final_speed=260)],
    )
    offense_result = GreedyResult(
        ok=True,
        message="offense",
        results=[GreedyUnitResult(unit_id=1002, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=120)],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            return defense_result
        if call_idx == 2:
            caps = dict(greedy_req.unit_max_final_speed or {})
            assert caps.get(1002) == 129
            speed_tie = dict(greedy_req.unit_speed_tiebreak_weight or {})
            assert speed_tie.get(1002) == int(LEO_LOW_TICK_SPEED_TIEBREAK_WEIGHT)
            return offense_result
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    presets = BuildStore()
    presets.set_unit_builds(
        "arena_rush",
        1002,
        [
            Build(
                id="leo-low",
                name="leo-low",
                enabled=True,
                priority=1,
                spd_tick=int(LEO_LOW_SPD_TICK),
            )
        ],
    )

    result = optimize_arena_rush(
        account=AccountData(),
        presets=presets,
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[901],
            offense_teams=[ArenaRushOffenseTeam(unit_ids=[1002], expected_opening_order=[1002])],
        ),
    )

    assert len(calls) == 2
    assert result.defense.ok
    assert len(result.offenses) == 1
    assert result.offenses[0].optimization.ok


def test_optimize_arena_rush_opening_uses_first_unique_actions(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[GreedyUnitResult(unit_id=901, ok=True, message="OK", runes_by_slot=_slots(9100), artifacts_by_type={1: 9901, 2: 9902}, final_speed=260)],
    )
    offense_result = GreedyResult(
        ok=True,
        message="offense",
        results=[
            GreedyUnitResult(unit_id=1001, ok=True, message="OK", runes_by_slot=_slots(1000), artifacts_by_type={1: 7001, 2: 7002}, final_speed=286),
            GreedyUnitResult(unit_id=1002, ok=True, message="OK", runes_by_slot=_slots(2000), artifacts_by_type={1: 7003, 2: 7004}, final_speed=129),
            GreedyUnitResult(unit_id=1003, ok=True, message="OK", runes_by_slot=_slots(3000), artifacts_by_type={1: 7005, 2: 7006}, final_speed=129),
            GreedyUnitResult(unit_id=1004, ok=True, message="OK", runes_by_slot=_slots(4000), artifacts_by_type={1: 7007, 2: 7008}, final_speed=129),
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            return defense_result
        if call_idx == 2:
            return offense_result
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
            defense_unit_ids=[901],
            offense_teams=[
                ArenaRushOffenseTeam(
                    unit_ids=[1001, 1002, 1003, 1004],
                    expected_opening_order=[1001, 1002, 1003, 1004],
                ),
            ],
        ),
    )

    assert len(calls) == 2
    assert len(result.offenses) == 1
    assert int(result.offenses[0].opening_penalty) == 0
    assert result.offenses[0].optimization.ok


def test_optimize_arena_rush_preflights_shared_tick_requirements_into_defense(monkeypatch) -> None:
    calls: list[GreedyRequest] = []

    defense_result = GreedyResult(
        ok=True,
        message="defense",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=320,
            )
        ],
    )
    offense_result = GreedyResult(
        ok=True,
        message="offense",
        results=[
            GreedyUnitResult(
                unit_id=101,
                ok=True,
                message="OK",
                runes_by_slot=_slots(9000),
                artifacts_by_type={1: 8001, 2: 8002},
                final_speed=286,
            )
        ],
    )

    def _fake_optimize(_account, _presets, greedy_req: GreedyRequest) -> GreedyResult:
        calls.append(greedy_req)
        call_idx = len(calls)
        if call_idx == 1:
            floors = dict(greedy_req.unit_min_final_speed or {})
            # Offense tick 5 => >=286 without leader. Defense has +31 leader,
            # so defense needs >=317 to guarantee same raw speed for offense.
            assert floors.get(101) == 317
            return defense_result
        if call_idx in (2, 3):
            return offense_result
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    presets = BuildStore()
    presets.set_unit_builds(
        "arena_rush",
        101,
        [
            Build(
                id="tick5",
                name="tick5",
                enabled=True,
                priority=1,
                spd_tick=5,
            )
        ],
    )

    result = optimize_arena_rush(
        account=AccountData(),
        presets=presets,
        req=ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=[101],
            defense_unit_spd_leader_bonus_flat={101: 31},
            offense_teams=[
                ArenaRushOffenseTeam(
                    unit_ids=[101],
                    expected_opening_order=[101],
                    unit_spd_leader_bonus_flat={101: 0},
                )
            ],
        ),
    )

    assert len(calls) == 3
    assert result.defense.ok
    assert len(result.offenses) == 1
    assert result.offenses[0].optimization.ok


def test_turn_effect_capability_ignores_passive_self_atb() -> None:
    from app.services.monster_turn_effects_service import _capability_from_skill_payload

    payload = {
        "passive": True,
        "aoe": False,
        "icon_filename": "skill_icon_0027_8_7.png",
        "effects": [
            {"effect": {"id": 17}, "quantity": 50, "self_effect": True},
        ],
    }

    out = _capability_from_skill_payload(payload)

    assert out["has_atb_boost"] is False
    assert int(out["max_atb_boost_pct"]) == 0
    assert str(out["atb_boost_skill_icon"]) == ""


def test_turn_effect_capability_detects_active_teamwide_atb() -> None:
    from app.services.monster_turn_effects_service import _capability_from_skill_payload

    payload = {
        "passive": False,
        "aoe": True,
        "icon_filename": "skill_icon_0000_9_6.png",
        "effects": [
            {"effect": {"id": 17}, "quantity": 30, "self_effect": False},
        ],
    }

    out = _capability_from_skill_payload(payload)

    assert out["has_atb_boost"] is True
    assert int(out["max_atb_boost_pct"]) == 30
    assert str(out["atb_boost_skill_icon"]) == "skill_icon_0000_9_6.png"


def test_turn_effect_capability_ignores_single_target_atb() -> None:
    from app.services.monster_turn_effects_service import _capability_from_skill_payload

    payload = {
        "passive": False,
        "aoe": False,
        "icon_filename": "skill_icon_0027_8_6.png",
        "effects": [
            {"effect": {"id": 17}, "quantity": 50, "self_effect": False},
        ],
    }

    out = _capability_from_skill_payload(payload)

    assert out["has_atb_boost"] is False
    assert int(out["max_atb_boost_pct"]) == 0


def test_low_leo_tick_is_available_in_normal_mode() -> None:
    ticks = allowed_spd_ticks("normal")
    assert int(LEO_LOW_SPD_TICK) in ticks
    idx_high = ticks.index(11)
    idx_low = ticks.index(int(LEO_LOW_SPD_TICK))
    assert idx_low + 1 == idx_high


def test_low_leo_tick_enforces_only_upper_bound() -> None:
    assert int(min_spd_for_tick(int(LEO_LOW_SPD_TICK), "normal") or 0) == 0


def test_arena_archetype_role_mapping_for_defensive_units() -> None:
    assert _is_attack_archetype("Attack") is True
    assert _is_attack_archetype("Support") is False
    assert _is_attack_archetype("HP") is False
    assert _is_attack_archetype("Defense") is False
    assert _is_attack_archetype("Rückhalt") is False
    assert _is_attack_archetype("Abwehr") is False

    assert _is_defensive_archetype("Support") is True
    assert _is_defensive_archetype("HP") is True
    assert _is_defensive_archetype("Defense") is True
    assert _is_defensive_archetype("Rückhalt") is True
    assert _is_defensive_archetype("Abwehr") is True


def test_defensive_quality_score_prefers_hp_def_res_runes() -> None:
    r_def = Rune(
        rune_id=1,
        slot_no=2,
        set_id=13,
        rank=6,
        rune_class=6,
        upgrade_curr=15,
        pri_eff=(2, 63),  # HP%
        prefix_eff=(6, 8),  # DEF%
        sec_eff=[(11, 10, 0, 0), (8, 6, 0, 0), (5, 30, 0, 0)],
        occupied_type=1,
        occupied_id=1001,
    )
    r_off = Rune(
        rune_id=2,
        slot_no=2,
        set_id=13,
        rank=6,
        rune_class=6,
        upgrade_curr=15,
        pri_eff=(4, 63),  # ATK%
        prefix_eff=(9, 8),  # CR
        sec_eff=[(10, 14, 0, 0), (8, 6, 0, 0), (3, 30, 0, 0)],
        occupied_type=1,
        occupied_id=1001,
    )

    s_def = _rune_quality_score_defensive(r_def, uid=1001)
    s_off = _rune_quality_score_defensive(r_off, uid=1001)
    assert int(s_def) > int(s_off)


def test_defensive_quality_score_prefers_defensive_artifacts() -> None:
    a_def = Artifact(
        artifact_id=1,
        occupied_id=1001,
        slot=1,
        type_=2,
        attribute=3,
        rank=6,
        level=15,
        original_rank=6,
        pri_effect=(100, 1500),
        sec_effects=[[201, 18], [213, 12], [404, 12]],
    )
    a_off = Artifact(
        artifact_id=2,
        occupied_id=1001,
        slot=1,
        type_=2,
        attribute=3,
        rank=6,
        level=15,
        original_rank=6,
        pri_effect=(101, 100),
        sec_effects=[[219, 18], [400, 14], [210, 12]],
    )

    s_def = _artifact_quality_score_defensive(a_def, uid=1001, archetype="Support")
    s_off = _artifact_quality_score_defensive(a_off, uid=1001, archetype="Support")
    assert int(s_def) > int(s_off)
    assert int(max_spd_for_tick(int(LEO_LOW_SPD_TICK), "normal") or 0) == 129


def test_defensive_artifact_score_penalizes_atk_main_for_defensive_roles() -> None:
    hp_main = Artifact(
        artifact_id=11,
        occupied_id=0,
        slot=1,
        type_=1,
        attribute=3,
        rank=6,
        level=15,
        original_rank=6,
        pri_effect=(100, 1500),
        sec_effects=[[218, 0.2], [213, 4], [214, 4]],
    )
    atk_main = Artifact(
        artifact_id=12,
        occupied_id=0,
        slot=1,
        type_=1,
        attribute=3,
        rank=6,
        level=15,
        original_rank=6,
        pri_effect=(101, 100),
        sec_effects=[[218, 0.2], [213, 4], [214, 4]],
    )
    assert int(_artifact_defensive_score_proxy(hp_main, archetype="Support")) > int(
        _artifact_defensive_score_proxy(atk_main, archetype="Support")
    )


def test_overcap_penalty_prefers_non_overcap_stats_in_max_quality() -> None:
    uid = 9001
    account = AccountData(
        units_by_id={
            uid: Unit(
                unit_id=uid,
                unit_master_id=10101,
                attribute=3,
                unit_level=40,
                unit_class=6,
                base_con=800,
                base_atk=700,
                base_def=700,
                base_spd=100,
                base_res=95,
                base_acc=95,
                crit_rate=95,
                crit_dmg=50,
            )
        },
        runes=[
            Rune(
                rune_id=91001,
                slot_no=1,
                set_id=13,
                rank=6,
                rune_class=6,
                upgrade_curr=15,
                pri_eff=(1, 120),
                prefix_eff=(0, 0),
                sec_eff=[(9, 20, 0, 0), (11, 20, 0, 0), (12, 20, 0, 0)],
                occupied_type=0,
                occupied_id=0,
            ),
            Rune(
                rune_id=91002,
                slot_no=1,
                set_id=13,
                rank=6,
                rune_class=6,
                upgrade_curr=15,
                pri_eff=(1, 120),
                prefix_eff=(0, 0),
                sec_eff=[(2, 8, 0, 0)],
                occupied_type=0,
                occupied_id=0,
            ),
            Rune(92002, 2, 13, 6, 6, 15, (2, 63), (0, 0), [], 0, 0),
            Rune(92003, 3, 13, 6, 6, 15, (3, 160), (0, 0), [], 0, 0),
            Rune(92004, 4, 13, 6, 6, 15, (2, 63), (0, 0), [], 0, 0),
            Rune(92005, 5, 13, 6, 6, 15, (1, 2448), (0, 0), [], 0, 0),
            Rune(92006, 6, 13, 6, 6, 15, (2, 63), (0, 0), [], 0, 0),
        ],
        artifacts=[
            Artifact(
                artifact_id=93001,
                occupied_id=0,
                slot=1,
                type_=1,
                attribute=3,
                rank=6,
                level=15,
                original_rank=6,
                pri_effect=(100, 1500),
                sec_effects=[],
            ),
            Artifact(
                artifact_id=93002,
                occupied_id=0,
                slot=2,
                type_=2,
                attribute=0,
                rank=6,
                level=15,
                original_rank=6,
                pri_effect=(100, 1500),
                sec_effects=[],
            ),
        ],
    )

    req = GreedyRequest(
        mode="arena_rush",
        arena_rush_context="offense",
        unit_ids_in_order=[uid],
        unit_archetype_by_uid={uid: "Support"},
        workers=1,
        time_limit_per_unit_s=1.0,
        multi_pass_enabled=False,
        quality_profile="max_quality",
    )
    res = optimize_greedy(account, BuildStore(), req)
    assert bool(res.ok)
    assert len(res.results) == 1
    picked = dict(res.results[0].runes_by_slot or {})
    assert int(picked.get(1, 0)) == 91002


def test_baseline_guard_avoids_regression_when_loaded_current_runes_exist() -> None:
    uid = 9101
    account = AccountData(
        units_by_id={
            uid: Unit(
                unit_id=uid,
                unit_master_id=10102,
                attribute=3,
                unit_level=40,
                unit_class=6,
                base_con=820,
                base_atk=620,
                base_def=720,
                base_spd=100,
                base_res=25,
                base_acc=15,
                crit_rate=15,
                crit_dmg=50,
            )
        },
        runes=[
            Rune(91101, 1, 13, 6, 6, 15, (1, 160), (0, 0), [(2, 22, 0, 0), (6, 18, 0, 0), (11, 18, 0, 0)], 0, 0),
            Rune(91102, 1, 13, 6, 6, 15, (3, 160), (0, 0), [(9, 22, 0, 0), (10, 22, 0, 0), (4, 18, 0, 0)], 0, 0),
            Rune(91202, 2, 13, 6, 6, 15, (2, 63), (0, 0), [], 0, 0),
            Rune(91203, 3, 13, 6, 6, 15, (5, 160), (0, 0), [], 0, 0),
            Rune(91204, 4, 13, 6, 6, 15, (2, 63), (0, 0), [], 0, 0),
            Rune(91205, 5, 13, 6, 6, 15, (1, 2448), (0, 0), [], 0, 0),
            Rune(91206, 6, 13, 6, 6, 15, (2, 63), (0, 0), [], 0, 0),
        ],
        artifacts=[
            Artifact(91301, 0, 1, 1, 3, 6, 15, 6, (100, 1500), []),
            Artifact(91302, 0, 2, 2, 0, 6, 15, 6, (100, 1500), []),
        ],
    )
    req = GreedyRequest(
        mode="siege",
        unit_ids_in_order=[uid],
        workers=1,
        time_limit_per_unit_s=1.0,
        multi_pass_enabled=False,
        quality_profile="max_quality",
        unit_baseline_runes_by_slot={uid: {1: 91101, 2: 91202, 3: 91203, 4: 91204, 5: 91205, 6: 91206}},
        unit_baseline_artifacts_by_type={uid: {1: 91301, 2: 91302}},
        baseline_regression_guard_weight=3000,
    )
    res = optimize_greedy(account, BuildStore(), req)
    assert bool(res.ok)
    assert len(res.results) == 1
    picked = dict(res.results[0].runes_by_slot or {})
    assert int(picked.get(1, 0)) == 91101


def test_max_quality_runs_global_in_parallel_multiple_launches(monkeypatch) -> None:
    account = AccountData(
        units_by_id={
            1: Unit(
                unit_id=1,
                unit_master_id=10001,
                attribute=3,
                unit_level=40,
                unit_class=6,
                base_con=700,
                base_atk=700,
                base_def=700,
                base_spd=100,
                base_res=15,
                base_acc=0,
                crit_rate=15,
                crit_dmg=50,
            )
        },
        runes=[],
        artifacts=[],
    )

    calls: list[tuple[int, int]] = []

    def _fake_global(_account, _presets, req):  # noqa: ANN001
        calls.append((int(getattr(req, "global_seed_offset", 0) or 0), int(req.workers or 0)))
        return GreedyResult(
            ok=True,
            message="fake",
            results=[
                GreedyUnitResult(
                    unit_id=1,
                    ok=True,
                    message="OK",
                    runes_by_slot={},
                    artifacts_by_type={},
                    final_speed=100 + len(calls),
                )
            ],
        )

    import app.engine.global_optimizer as go

    monkeypatch.setattr(go, "optimize_global", _fake_global)
    req = GreedyRequest(
        mode="siege",
        unit_ids_in_order=[1],
        quality_profile="max_quality",
        multi_pass_enabled=True,
        multi_pass_count=3,
        workers=3,
    )
    res = optimize_greedy(account, BuildStore(), req)
    assert bool(res.ok)
    assert len(calls) == 3
    assert len({seed for seed, _w in calls}) == 3
    assert "parallel_runs=" in str(res.message)
