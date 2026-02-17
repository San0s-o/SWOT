from __future__ import annotations

from app.domain.models import AccountData
from app.domain.presets import BuildStore
from app.engine.arena_rush_optimizer import (
    ArenaRushOffenseTeam,
    ArenaRushRequest,
    optimize_arena_rush,
)
from app.engine.arena_rush_timing import OpeningTurnEffect, opening_order_penalty, simulate_opening_order
from app.engine.arena_rush_timing import min_speed_floor_by_unit_from_effects
from app.engine.greedy_optimizer import GreedyRequest, GreedyResult, GreedyUnitResult


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
            fixed = dict(greedy_req.unit_fixed_runes_by_slot or {})
            assert fixed.get(202) == _slots(2000)
            assert fixed.get(203) == _slots(3000)
            return offense2_result
        raise AssertionError("unexpected optimize_greedy call")

    monkeypatch.setattr("app.engine.arena_rush_optimizer.optimize_greedy", _fake_optimize)

    result = optimize_arena_rush(
        account=AccountData(),
        presets=BuildStore(),
        req=ArenaRushRequest(
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
    assert result.offenses[1].shared_unit_ids == [202, 203]
    assert result.offenses[1].swapped_in_unit_ids == [204]


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
