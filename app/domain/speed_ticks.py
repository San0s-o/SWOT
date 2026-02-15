from __future__ import annotations

from typing import Dict, List

# SPD breakpoints for 7.0% ATB gain per tick (normal mode),
# based on the in-game calculator setup currently used in the project.
SPD_TICK_MIN_SPD_NORMAL: Dict[int, int] = {
    11: 130,
    10: 143,
    9: 159,
    8: 179,
    7: 205,
    6: 239,
    5: 286,
    4: 358,
    3: 477,
}


def allowed_spd_ticks() -> List[int]:
    return sorted(SPD_TICK_MIN_SPD_NORMAL.keys(), reverse=True)


def min_spd_for_tick(tick: int) -> int:
    try:
        t = int(tick or 0)
    except Exception:
        return 0
    return int(SPD_TICK_MIN_SPD_NORMAL.get(t, 0))


def max_spd_for_tick(tick: int) -> int:
    """Inclusive max SPD that still remains in the given tick bucket.

    Returns 0 when no valid tick is given. For the fastest configured bucket
    (lowest tick count), returns a very high ceiling.
    """
    try:
        t = int(tick or 0)
    except Exception:
        return 0
    if t not in SPD_TICK_MIN_SPD_NORMAL:
        return 0

    faster_tick = t - 1
    faster_min = int(SPD_TICK_MIN_SPD_NORMAL.get(faster_tick, 0))
    if faster_min <= 0:
        return 10**9
    return int(faster_min - 1)
