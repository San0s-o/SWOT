from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Dict, List, Sequence

from app.domain.models import Artifact

# Swarfarm artifact effect id:
# 206 -> "SPD Increasing Effect +{}%"
SPD_BUFF_INCREASE_EFFECT_ID = 206
DEFAULT_ATB_GAIN_PER_TICK_PCT = 7.0
DEFAULT_SPD_BUFF_PCT = 30.0


@dataclass(frozen=True)
class OpeningTurnEffect:
    atb_boost_pct: float = 0.0
    applies_spd_buff: bool = False
    include_caster: bool = True


def artifact_effect_total_percent(artifact: Artifact, effect_id: int) -> float:
    target = int(effect_id or 0)
    if target <= 0:
        return 0.0
    total = 0.0
    for sec in (artifact.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        try:
            if int(sec[0] or 0) != target:
                continue
            total += float(sec[1] or 0.0)
        except Exception:
            continue
    return float(total)


def spd_buff_increase_pct_for_unit(
    artifact_ids: Sequence[int],
    artifact_lookup: Dict[int, Artifact],
) -> float:
    total = 0.0
    for aid in artifact_ids:
        art = artifact_lookup.get(int(aid))
        if art is None:
            continue
        total += artifact_effect_total_percent(art, SPD_BUFF_INCREASE_EFFECT_ID)
    return float(total)


def spd_buff_increase_pct_by_unit_from_assignments(
    artifacts_by_unit: Dict[int, Dict[int, int]],
    artifact_lookup: Dict[int, Artifact],
) -> Dict[int, float]:
    out: Dict[int, float] = {}
    for uid, by_type in (artifacts_by_unit or {}).items():
        artifact_ids = [int(aid) for aid in (by_type or {}).values() if int(aid or 0) > 0]
        out[int(uid)] = spd_buff_increase_pct_for_unit(artifact_ids, artifact_lookup)
    return out


def effective_spd_buff_pct_for_unit(
    spd_buff_increase_pct: float,
    base_spd_buff_pct: float = DEFAULT_SPD_BUFF_PCT,
) -> float:
    inc_pct = max(0.0, float(spd_buff_increase_pct or 0.0))
    return float(base_spd_buff_pct) * (1.0 + (inc_pct / 100.0))


def min_speed_floor_by_unit_from_effects(
    expected_order: Sequence[int],
    combat_speed_by_unit: Dict[int, int],
    turn_effects_by_unit: Dict[int, OpeningTurnEffect] | None = None,
    spd_buff_increase_pct_by_unit: Dict[int, float] | None = None,
    base_spd_buff_pct: float = DEFAULT_SPD_BUFF_PCT,
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    if not expected_order:
        return out
    effects = dict(turn_effects_by_unit or {})
    buff_inc = {int(uid): float(v) for uid, v in (spd_buff_increase_pct_by_unit or {}).items()}
    order = [int(uid) for uid in expected_order if int(uid) > 0]
    for idx, caster_uid in enumerate(order):
        caster_speed = int(combat_speed_by_unit.get(int(caster_uid), 0) or 0)
        if caster_speed <= 0:
            continue
        effect = effects.get(int(caster_uid))
        if effect is None:
            continue
        atb_boost_factor = 1.0 - (max(0.0, float(effect.atb_boost_pct or 0.0)) / 100.0)
        atb_boost_factor = max(0.0, min(1.0, atb_boost_factor))
        for target_uid in order[idx + 1 :]:
            target_boost_pct = 0.0
            if bool(effect.applies_spd_buff):
                target_boost_pct = effective_spd_buff_pct_for_unit(
                    buff_inc.get(int(target_uid), 0.0),
                    base_spd_buff_pct=base_spd_buff_pct,
                )
            speed_buff_factor = 1.0 + (max(0.0, float(target_boost_pct)) / 100.0)
            raw_required = (float(caster_speed) * atb_boost_factor) / max(1e-9, speed_buff_factor)
            required = int(ceil(raw_required - 1e-9))
            if required > int(out.get(int(target_uid), 0) or 0):
                out[int(target_uid)] = int(required)
    return out


def simulate_opening_order(
    ordered_unit_ids: Sequence[int],
    combat_speed_by_unit: Dict[int, int],
    turn_effects_by_unit: Dict[int, OpeningTurnEffect] | None = None,
    spd_buff_increase_pct_by_unit: Dict[int, float] | None = None,
    max_actions: int | None = None,
    one_action_per_unit: bool = False,
    atb_gain_per_tick_pct: float = DEFAULT_ATB_GAIN_PER_TICK_PCT,
    base_spd_buff_pct: float = DEFAULT_SPD_BUFF_PCT,
) -> List[int]:
    order_seed = [int(uid) for uid in ordered_unit_ids]
    unique_units: List[int] = []
    seen: set[int] = set()
    for uid in order_seed:
        if uid in seen:
            continue
        if int(combat_speed_by_unit.get(int(uid), 0) or 0) <= 0:
            continue
        seen.add(uid)
        unique_units.append(uid)
    if not unique_units:
        return []

    action_limit = int(max_actions) if max_actions is not None else len(unique_units)
    if action_limit <= 0:
        return []

    turn_effects = dict(turn_effects_by_unit or {})
    buff_inc = {int(uid): float(v) for uid, v in (spd_buff_increase_pct_by_unit or {}).items()}
    atb: Dict[int, float] = {int(uid): 0.0 for uid in unique_units}
    spd_buff_active: Dict[int, bool] = {int(uid): False for uid in unique_units}
    acted_once: Dict[int, bool] = {int(uid): False for uid in unique_units}
    position = {int(uid): idx for idx, uid in enumerate(unique_units)}

    gain_per_tick_ratio = float(atb_gain_per_tick_pct) / 100.0
    out: List[int] = []

    def _unit_gain(uid: int) -> float:
        speed = float(int(combat_speed_by_unit.get(int(uid), 0) or 0))
        if speed <= 0.0:
            return 0.0
        speed_mult = 1.0
        if bool(spd_buff_active.get(int(uid), False)):
            # Inference: artifact bonus scales the base SPD-buff value.
            # e.g. 30% buff with +20% increase -> 30 * 1.2 = 36% speed buff.
            inc_pct = max(0.0, float(buff_inc.get(int(uid), 0.0)))
            speed_mult += (float(base_spd_buff_pct) * (1.0 + (inc_pct / 100.0))) / 100.0
        return float(gain_per_tick_ratio * speed * speed_mult)

    safety_steps = max(16, action_limit * 20)
    for _ in range(safety_steps):
        if len(out) >= action_limit:
            break

        gains = {int(uid): _unit_gain(int(uid)) for uid in unique_units}
        ticks_needed: Dict[int, int] = {}
        for uid in unique_units:
            if bool(one_action_per_unit) and bool(acted_once.get(int(uid), False)):
                ticks_needed[int(uid)] = 10**9
                continue
            gain = float(gains.get(int(uid), 0.0))
            if gain <= 0.0:
                ticks_needed[int(uid)] = 10**9
                continue
            remain = max(0.0, 100.0 - float(atb.get(int(uid), 0.0)))
            if remain <= 0.0:
                ticks_needed[int(uid)] = 0
            else:
                ticks_needed[int(uid)] = int(ceil(remain / gain))

        min_ticks = min(ticks_needed.values()) if ticks_needed else 10**9
        if min_ticks >= 10**9:
            break

        if min_ticks > 0:
            for uid in unique_units:
                atb[int(uid)] = float(atb.get(int(uid), 0.0) + (float(gains[int(uid)]) * float(min_ticks)))

        ready = [
            int(uid)
            for uid in unique_units
            if (not bool(one_action_per_unit) or not bool(acted_once.get(int(uid), False)))
            and float(atb.get(int(uid), 0.0)) >= 100.0 - 1e-9
        ]
        if not ready:
            continue

        actor = max(
            ready,
            key=lambda uid: (
                float(atb.get(int(uid), 0.0)),
                float(gains.get(int(uid), 0.0)),
                -int(position.get(int(uid), 9999)),
            ),
        )
        out.append(int(actor))
        if bool(one_action_per_unit):
            acted_once[int(actor)] = True
        atb[int(actor)] = max(0.0, float(atb.get(int(actor), 0.0)) - 100.0)

        effect = turn_effects.get(int(actor))
        if effect is None:
            continue

        boost = max(0.0, float(effect.atb_boost_pct or 0.0))
        if boost > 0.0:
            for uid in unique_units:
                if int(uid) == int(actor) and not bool(effect.include_caster):
                    continue
                atb[int(uid)] = float(atb.get(int(uid), 0.0) + boost)

        if bool(effect.applies_spd_buff):
            for uid in unique_units:
                if int(uid) == int(actor) and not bool(effect.include_caster):
                    continue
                spd_buff_active[int(uid)] = True

    return out


def opening_order_penalty(expected_order: Sequence[int], observed_order: Sequence[int]) -> int:
    expected = [int(uid) for uid in expected_order]
    observed = [int(uid) for uid in observed_order]
    if not expected:
        return 0
    penalty = 0
    for idx, expected_uid in enumerate(expected):
        if idx >= len(observed):
            penalty += (len(expected) - idx) * 5
            break
        if int(observed[idx]) == int(expected_uid):
            continue
        penalty += int(1 + idx)
    return int(penalty)
