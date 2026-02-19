"""Rune and artifact efficiency calculations."""
from __future__ import annotations

from typing import Dict, List, Literal

from app.domain.models import Rune, Artifact


# ============================================================
# Rune efficiency
# ============================================================
# Formula (SWOP-style):
#   (1 + (HP%+ATK%+DEF%+ACC%+RES%)/40 + (SPD+CR%)/30 + CD%/35
#        + HP_flat/1875*0.35 + (ATK_flat+DEF_flat)/100*0.35) / 2.8
#
# Only substats (sec_eff incl. grinds) + prefix_eff. Main stat excluded.
# Returns percentage, e.g. 85.3  (max ~137.5 for perfect Legend with innate).

_GRINDABLE_EFF_IDS = {1, 2, 3, 4, 5, 6, 8}
_ANCIENT_RUNE_CLASSES = {11, 12, 13, 14, 15, 16}

_GEM_MAX: Dict[Literal["hero", "legend"], Dict[int, float]] = {
    "hero": {
        1: 500, 2: 10, 3: 27, 4: 10, 5: 27, 6: 10, 8: 11, 9: 8, 10: 9, 11: 10, 12: 10,
    },
    "legend": {
        1: 550, 2: 11, 3: 30, 4: 11, 5: 30, 6: 11, 8: 12, 9: 9, 10: 10, 11: 11, 12: 11,
    },
}

_GRIND_MAX: Dict[Literal["hero", "legend"], Dict[int, float]] = {
    "hero": {1: 430, 2: 7, 3: 22, 4: 7, 5: 22, 6: 7, 8: 4},
    "legend": {1: 550, 2: 10, 3: 30, 4: 10, 5: 30, 6: 10, 8: 5},
}

# Ancient rune caps (community-verified values, e.g. SWOP/SWRT references):
# https://www.reddit.com/r/summonerswar/comments/sf5f79/ancient_grindsgems_table/
_GEM_MAX_ANCIENT: Dict[Literal["hero", "legend"], Dict[int, float]] = {
    "hero": {
        1: 480, 2: 13, 3: 34, 4: 13, 5: 34, 6: 13, 8: 9, 9: 8, 10: 10, 11: 11, 12: 11,
    },
    "legend": {
        1: 640, 2: 15, 3: 44, 4: 15, 5: 44, 6: 15, 8: 11, 9: 10, 10: 12, 11: 13, 12: 13,
    },
}

_GRIND_MAX_ANCIENT: Dict[Literal["hero", "legend"], Dict[int, float]] = {
    "hero": {1: 510, 2: 9, 3: 26, 4: 9, 5: 26, 6: 9, 8: 5},
    "legend": {1: 610, 2: 12, 3: 34, 4: 12, 5: 34, 6: 12, 8: 6},
}


def _is_ancient_rune(rune: Rune) -> bool:
    cls = int(getattr(rune, "origin_class", 0) or 0)
    if cls <= 0:
        cls = int(rune.rune_class or 0)
    return cls in _ANCIENT_RUNE_CLASSES


def _rune_efficiency_internal(rune: Rune, max_tier: Literal["hero", "legend"] | None = None) -> float:
    hp_pct = atk_pct = def_pct = acc = res = 0.0
    spd = cr = cd = 0.0
    hp_flat = atk_flat = def_flat = 0.0

    def _acc_stat(eff_id: int, value: float) -> None:
        nonlocal hp_pct, atk_pct, def_pct, acc, res
        nonlocal spd, cr, cd, hp_flat, atk_flat, def_flat
        if eff_id == 1:
            hp_flat += value
        elif eff_id == 2:
            hp_pct += value
        elif eff_id == 3:
            atk_flat += value
        elif eff_id == 4:
            atk_pct += value
        elif eff_id == 5:
            def_flat += value
        elif eff_id == 6:
            def_pct += value
        elif eff_id == 8:
            spd += value
        elif eff_id == 9:
            cr += value
        elif eff_id == 10:
            cd += value
        elif eff_id == 11:
            res += value
        elif eff_id == 12:
            acc += value

    # prefix (innate) stat
    try:
        _acc_stat(int(rune.prefix_eff[0] or 0), float(rune.prefix_eff[1] or 0))
    except Exception:
        pass

    subs: List[tuple[int, float, int, float]] = []
    # substats (including grinds)
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        try:
            eff_id = int(sec[0] or 0)
            val = float(sec[1] or 0)
            enchanted = int(sec[2] or 0) if len(sec) >= 3 else 0
            grind = float(sec[3] or 0) if len(sec) >= 4 else 0.0
            subs.append((eff_id, val, enchanted, grind))
        except Exception:
            continue

    if max_tier in ("hero", "legend"):
        grind_caps = _GRIND_MAX_ANCIENT if _is_ancient_rune(rune) else _GRIND_MAX
        gem_caps = _GEM_MAX_ANCIENT if _is_ancient_rune(rune) else _GEM_MAX

        # 1) Max grinds on existing grindable substats
        totals: List[float] = []
        for eff_id, val, _enchanted, grind in subs:
            if eff_id in _GRINDABLE_EFF_IDS:
                grind_cap = float(grind_caps[max_tier].get(eff_id, 0.0))
                totals.append(val + max(grind, grind_cap))
            else:
                totals.append(val)

        # 2) At most one gem upgrade, and only if no sub was already enchanted
        #    (prevents unrealistic stacking and aligns with in-game one-gem behavior)
        has_enchanted = any(ench == 1 for _, _, ench, _ in subs)
        if not has_enchanted:
            best_idx = -1
            best_delta = 0.0
            for i, (eff_id, val, _enchanted, _grind) in enumerate(subs):
                gem_cap = float(gem_caps[max_tier].get(eff_id, val))
                if gem_cap <= val:
                    continue
                target = gem_cap
                if eff_id in _GRINDABLE_EFF_IDS:
                    target += float(grind_caps[max_tier].get(eff_id, 0.0))
                delta = target - totals[i]
                if delta > best_delta:
                    best_delta = delta
                    best_idx = i
            if best_idx >= 0 and best_delta > 0:
                eff_id, val, _enchanted, _grind = subs[best_idx]
                target = float(gem_caps[max_tier].get(eff_id, val))
                if eff_id in _GRINDABLE_EFF_IDS:
                    target += float(grind_caps[max_tier].get(eff_id, 0.0))
                totals[best_idx] = target

        for (eff_id, _val, _enchanted, _grind), total in zip(subs, totals):
            _acc_stat(eff_id, total)
    else:
        for eff_id, val, _enchanted, grind in subs:
            _acc_stat(eff_id, val + grind)

    score = (
        1
        + (hp_pct + atk_pct + def_pct + acc + res) / 40
        + (spd + cr) / 30
        + cd / 35
        + hp_flat / 1875 * 0.35
        + (atk_flat + def_flat) / 100 * 0.35
    )
    return round(score / 2.8 * 100, 2)


def rune_efficiency(rune: Rune) -> float:
    return _rune_efficiency_internal(rune)


def rune_efficiency_max(rune: Rune, tier: Literal["hero", "legend"]) -> float:
    return _rune_efficiency_internal(rune, max_tier=tier)


# ============================================================
# Artifact efficiency
# ============================================================
# Formula:
#   inner = SUM(4%Based)/20 + SUM(5%Based)/25 + SUM(6%Based)/30
#         + LifeDrain/40 + CDbad/60 + AddSPD/200
#         + AddHP/1.5 + (AddATK+AddDEF)/20
#   Efficiency% = inner / 1.6
#
# Optional score representation:
#   score = ROUND(inner * 125)
#   Eff% ~= score / 2

# Explicit effect IDs
_EFF_LIFEDRAIN = 215
_EFF_CDBAD = 223
_EFF_ADD_SPD = 221
_EFF_ADD_HP = 218
_EFF_ADD_ATK = 219
_EFF_ADD_DEF = 220

# Per-effect divisor overrides (applied before 4/5/6 bucket grouping).
_EFFECT_DIVISOR_OVERRIDE: Dict[int, float] = {
    200: 70.0,  # ATK+ proportional to lost HP (legacy)
    201: 70.0,  # DEF+ proportional to lost HP (legacy)
    202: 70.0,  # SPD+ proportional to lost HP (legacy)
    214: 20.0,  # CRIT DMG Received -
}

# Auto-categorized by observed max-per-roll from account data analysis.
# max_per_roll <= 5 → 4%Based (/20)
# max_per_roll <= 7 → 5%Based (/25)
# max_per_roll > 7  → 6%Based (/30)

_FOUR_PCT: set[int] = {
    210,  # Bomb Damage (+max ~4/roll)
    211,  # Reflected DMG (+max ~3/roll)
    212,  # Crushing Hit DMG (+max ~4/roll)
    213,  # DMG recv under inability (-max ~5/roll)
    224,  # Single-target CRIT DMG (+max ~4/roll)
}

_FIVE_PCT: set[int] = {
    204,  # ATK Increasing Effect
    205,  # DEF Increasing Effect
    207,  # CR Increasing Effect
    208,  # Counter DMG
    209,  # Coop DMG
    214,  # Received Crit DMG
    216,  # HP when Revived
    217,  # ATK Bar when Revived
    225,  # Counter/Coop DMG
    405,  # Skill recovery (observed ~6/roll)
}

# Everything else (200-202, 203, 206, 222, 226, 300-309, 400-411 etc.) → 6%Based
# These have max_per_roll > 7 from observed data.


def artifact_score(art: Artifact) -> float:
    json_score = float(getattr(art, "json_score", 0.0) or 0.0)
    if json_score > 0.0:
        return round(json_score, 2)

    if not art.sec_effects:
        return 0.0

    sum_4 = sum_5 = sum_6 = 0.0
    life_drain = cd_bad = add_spd = add_hp = add_atk = add_def = 0.0

    for sec in art.sec_effects:
        if not sec or len(sec) < 2:
            continue
        try:
            eid = int(sec[0])
            val = float(sec[1])
        except (ValueError, TypeError):
            continue

        override_div = float(_EFFECT_DIVISOR_OVERRIDE.get(eid, 0.0) or 0.0)
        if override_div > 0.0:
            # Keep the existing "sum_6 / 30" structure while applying a custom divisor:
            # val / override_div == (val * (30 / override_div)) / 30
            sum_6 += val * (30.0 / override_div)
            continue

        if eid == _EFF_LIFEDRAIN:
            life_drain += val
        elif eid == _EFF_CDBAD:
            cd_bad += val
        elif eid == _EFF_ADD_SPD:
            add_spd += val
        elif eid == _EFF_ADD_HP:
            add_hp += val
        elif eid == _EFF_ADD_ATK:
            add_atk += val
        elif eid == _EFF_ADD_DEF:
            add_def += val
        elif eid in _FOUR_PCT:
            sum_4 += val
        elif eid in _FIVE_PCT:
            sum_5 += val
        else:
            sum_6 += val

    inner = (
        sum_4 / 20
        + sum_5 / 25
        + sum_6 / 30
        + life_drain / 40
        + cd_bad / 60
        + add_spd / 200
        + add_hp / 1.5
        + (add_atk + add_def) / 20
    )
    return round(inner * 125.0, 2)


def artifact_efficiency(art: Artifact) -> float:
    return round(artifact_score(art) / 2.0, 2)


# ============================================================
# Batch helpers
# ============================================================

def rune_efficiencies(runes: List[Rune]) -> List[float]:
    return [rune_efficiency(r) for r in runes]


def artifact_efficiencies(artifacts: List[Artifact]) -> List[float]:
    return [artifact_efficiency(a) for a in artifacts if a.sec_effects]
