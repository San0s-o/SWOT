from __future__ import annotations

from app.domain.models import AccountData
from app.domain.presets import BuildStore
from app.engine.greedy_optimizer import (
    DEFAULT_BUILD_PRIORITY_PENALTY,
    REFINE_SAME_ARTIFACT_PENALTY,
    REFINE_SAME_RUNE_PENALTY,
    SET_OPTION_PREFERENCE_BONUS,
    GreedyRequest,
    GreedyUnitResult,
    _run_pass_with_profile,
)


def run_refine_pass(
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
    unit_ids: list[int],
    time_limit_per_unit_s: float,
    pass_idx: int,
    avoid_solution_by_unit: dict[int, GreedyUnitResult] | None = None,
    speed_slack_for_quality: int = 1,
    rune_top_per_set_override: int | None = None,
) -> list[GreedyUnitResult]:
    # Refinement pass: soften build-priority pressure and rotate set-option preference.
    penalty = max(40, int(DEFAULT_BUILD_PRIORITY_PENALTY - (int(pass_idx) * 60)))
    return _run_pass_with_profile(
        account=account,
        presets=presets,
        req=req,
        unit_ids=unit_ids,
        time_limit_per_unit_s=time_limit_per_unit_s,
        speed_hard_priority=False,
        build_priority_penalty=penalty,
        set_option_preference_offset_base=int(pass_idx),
        set_option_preference_bonus=SET_OPTION_PREFERENCE_BONUS,
        avoid_solution_by_unit=avoid_solution_by_unit,
        avoid_same_rune_penalty=REFINE_SAME_RUNE_PENALTY,
        avoid_same_artifact_penalty=REFINE_SAME_ARTIFACT_PENALTY,
        speed_slack_for_quality=max(0, int(speed_slack_for_quality)),
        objective_mode="efficiency",
        rune_top_per_set_override=rune_top_per_set_override,
    )
