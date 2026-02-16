from __future__ import annotations

from math import ceil
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

_RTA_ATB_GAIN_PER_TICK_PCT = 1.5
_RTA_TICK_MIN = 16
_RTA_TICK_MAX = 53


def _build_tick_table(atb_gain_per_tick_pct: float, tick_min: int, tick_max: int) -> Dict[int, int]:
    # ATB gain per tick is handled in percent, using the common SW formula.
    k = 10000.0 / float(atb_gain_per_tick_pct)
    out: Dict[int, int] = {}
    for tick in range(int(tick_min), int(tick_max) + 1):
        out[int(tick)] = int(ceil(k / float(tick)))
    return out


# SPD breakpoints for 1.5% ATB gain per tick (RTA mode).
SPD_TICK_MIN_SPD_RTA: Dict[int, int] = _build_tick_table(
    _RTA_ATB_GAIN_PER_TICK_PCT,
    _RTA_TICK_MIN,
    _RTA_TICK_MAX,
)


def _tick_table_for_mode(mode: str | None) -> Dict[int, int]:
    return SPD_TICK_MIN_SPD_RTA if str(mode or "").strip().lower() == "rta" else SPD_TICK_MIN_SPD_NORMAL


def allowed_spd_ticks(mode: str | None = None) -> List[int]:
    return sorted(_tick_table_for_mode(mode).keys(), reverse=True)


def min_spd_for_tick(tick: int, mode: str | None = None) -> int:
    try:
        t = int(tick or 0)
    except Exception:
        return 0
    return int(_tick_table_for_mode(mode).get(t, 0))


def max_spd_for_tick(tick: int, mode: str | None = None) -> int:
    """Inclusive max SPD that still remains in the given tick bucket.

    Returns 0 when no valid tick is given. For the fastest configured bucket
    (lowest tick count), returns a very high ceiling.
    """
    try:
        t = int(tick or 0)
    except Exception:
        return 0
    table = _tick_table_for_mode(mode)
    if t not in table:
        return 0

    faster_tick = t - 1
    faster_min = int(table.get(faster_tick, 0))
    if faster_min <= 0:
        return 10**9
    return int(faster_min - 1)
