from __future__ import annotations

from typing import Dict, List, Tuple


def unit_base_stats(window, unit_id: int) -> Dict[str, int]:
    if not window.account:
        return {}
    u = window.account.units_by_id.get(unit_id)
    if not u:
        return {}
    return {
        "HP": int((u.base_con or 0) * 15),
        "ATK": int(u.base_atk or 0),
        "DEF": int(u.base_def or 0),
        "SPD": int(u.base_spd or 0),
        "CR": int(u.crit_rate or 15),
        "CD": int(u.crit_dmg or 50),
        "RES": int(u.base_res or 15),
        "ACC": int(u.base_acc or 0),
    }


def unit_leader_bonus(window, unit_id: int, team_unit_ids: List[int]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not window.account:
        return out
    u = window.account.units_by_id.get(unit_id)
    if not u:
        return out
    ls = window._team_leader_skill(team_unit_ids)
    if not ls:
        return out
    base_hp = int((u.base_con or 0) * 15)
    base_atk = int(u.base_atk or 0)
    base_def = int(u.base_def or 0)
    base_spd = int(u.base_spd or 0)
    s, a = ls.stat, ls.amount
    if s == "HP%":
        out["HP"] = int(base_hp * a / 100)
    elif s == "ATK%":
        out["ATK"] = int(base_atk * a / 100)
    elif s == "DEF%":
        out["DEF"] = int(base_def * a / 100)
    elif s == "SPD%":
        out["SPD"] = int(base_spd * a / 100)
    elif s == "CR%":
        out["CR"] = a
    elif s == "CD%":
        out["CD"] = a
    elif s == "RES%":
        out["RES"] = a
    elif s == "ACC%":
        out["ACC"] = a
    return out


def unit_totem_bonus(window, unit_id: int) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if not window.account:
        return out
    u = window.account.units_by_id.get(unit_id)
    if not u:
        return out
    pct = int(window.account.sky_tribe_totem_spd_pct or 0)
    if pct > 0:
        out["SPD"] = int(int(u.base_spd or 0) * pct / 100)
    return out


def unit_final_spd_value(window, unit_id: int, team_unit_ids: List[int], runes_by_unit: Dict[int, Dict[int, int]]) -> int:
    if not window.account:
        return 0
    u = window.account.units_by_id.get(unit_id)
    if not u:
        return 0
    base_spd = int(u.base_spd or 0)
    rune_lookup = {r.rune_id: r for r in window.account.runes}
    rune_ids = list((runes_by_unit.get(unit_id) or {}).values())

    rune_spd_flat = 0
    rune_set_ids: List[int] = []
    for rid in rune_ids:
        rune = rune_lookup.get(int(rid))
        if not rune:
            continue
        rune_set_ids.append(int(rune.set_id or 0))
        rune_spd_flat += window._spd_from_stat_tuple(rune.pri_eff)
        rune_spd_flat += window._spd_from_stat_tuple(rune.prefix_eff)
        rune_spd_flat += window._spd_from_substats(rune.sec_eff)

    swift_sets = rune_set_ids.count(3) // 4
    set_spd_pct = 25 * swift_sets
    set_spd_bonus = int(base_spd * set_spd_pct / 100)
    totem_spd_bonus = int(base_spd * int(window.account.sky_tribe_totem_spd_pct or 0) / 100)

    ls = window._team_leader_skill(team_unit_ids)
    lead_spd_bonus = int(base_spd * ls.amount / 100) if ls and ls.stat == "SPD%" else 0
    return int(base_spd + rune_spd_flat + set_spd_bonus + totem_spd_bonus + lead_spd_bonus)


def unit_final_stats_values(window, unit_id: int, team_unit_ids: List[int], runes_by_unit: Dict[int, Dict[int, int]]) -> Dict[str, int]:
    if not window.account:
        return {}
    u = window.account.units_by_id.get(unit_id)
    if not u:
        return {}

    base_hp = int((u.base_con or 0) * 15)
    base_atk = int(u.base_atk or 0)
    base_def = int(u.base_def or 0)
    base_spd = int(u.base_spd or 0)
    base_cr = int(u.crit_rate or 15)
    base_cd = int(u.crit_dmg or 50)
    base_res = int(u.base_res or 15)
    base_acc = int(u.base_acc or 0)

    flat_hp = flat_atk = flat_def = 0
    pct_hp = pct_atk = pct_def = 0
    add_spd = add_cr = add_cd = add_res = add_acc = 0

    rune_lookup = {r.rune_id: r for r in window.account.runes}
    rune_ids = list((runes_by_unit.get(unit_id) or {}).values())
    rune_set_ids: List[int] = []

    def _acc_stat(eff_id: int, value: int) -> None:
        nonlocal flat_hp, flat_atk, flat_def, pct_hp, pct_atk, pct_def
        nonlocal add_spd, add_cr, add_cd, add_res, add_acc
        if eff_id == 1:
            flat_hp += int(value or 0)
        elif eff_id == 2:
            pct_hp += int(value or 0)
        elif eff_id == 3:
            flat_atk += int(value or 0)
        elif eff_id == 4:
            pct_atk += int(value or 0)
        elif eff_id == 5:
            flat_def += int(value or 0)
        elif eff_id == 6:
            pct_def += int(value or 0)
        elif eff_id == 8:
            add_spd += int(value or 0)
        elif eff_id == 9:
            add_cr += int(value or 0)
        elif eff_id == 10:
            add_cd += int(value or 0)
        elif eff_id == 11:
            add_res += int(value or 0)
        elif eff_id == 12:
            add_acc += int(value or 0)

    for rid in rune_ids:
        rune = rune_lookup.get(int(rid))
        if not rune:
            continue
        rune_set_ids.append(int(rune.set_id or 0))
        try:
            _acc_stat(int(rune.pri_eff[0] or 0), int(rune.pri_eff[1] or 0))
        except Exception:
            pass
        try:
            _acc_stat(int(rune.prefix_eff[0] or 0), int(rune.prefix_eff[1] or 0))
        except Exception:
            pass
        for sec in (rune.sec_eff or []):
            if not sec:
                continue
            try:
                eff = int(sec[0] or 0)
                val = int(sec[1] or 0)
                grind = int(sec[3] or 0) if len(sec) >= 4 else 0
                _acc_stat(eff, val + grind)
            except Exception:
                continue

    swift_sets = rune_set_ids.count(3) // 4
    spd_from_swift = int(base_spd * (25 * swift_sets) / 100)
    spd_from_totem = int(base_spd * int(window.account.sky_tribe_totem_spd_pct or 0) / 100)

    ls = window._team_leader_skill(team_unit_ids)
    lead_hp = lead_atk = lead_def = lead_spd = 0
    lead_cr = lead_cd = lead_res = lead_acc = 0
    if ls:
        s, a = ls.stat, ls.amount
        if s == "HP%":
            lead_hp = int(base_hp * a / 100)
        elif s == "ATK%":
            lead_atk = int(base_atk * a / 100)
        elif s == "DEF%":
            lead_def = int(base_def * a / 100)
        elif s == "SPD%":
            lead_spd = int(base_spd * a / 100)
        elif s == "CR%":
            lead_cr = a
        elif s == "CD%":
            lead_cd = a
        elif s == "RES%":
            lead_res = a
        elif s == "ACC%":
            lead_acc = a

    hp = base_hp + flat_hp + int(base_hp * pct_hp / 100) + lead_hp
    atk = base_atk + flat_atk + int(base_atk * pct_atk / 100) + lead_atk
    deff = base_def + flat_def + int(base_def * pct_def / 100) + lead_def
    spd = base_spd + add_spd + spd_from_swift + spd_from_totem + lead_spd

    return {
        "HP": int(hp),
        "ATK": int(atk),
        "DEF": int(deff),
        "SPD": int(spd),
        "CR": int(base_cr + add_cr + lead_cr),
        "CD": int(base_cd + add_cd + lead_cd),
        "RES": int(base_res + add_res + lead_res),
        "ACC": int(base_acc + add_acc + lead_acc),
    }


def team_leader_skill(window, team_unit_ids: List[int]):
    if not window.account or not team_unit_ids:
        return None
    leader_uid = team_unit_ids[0]
    u = window.account.units_by_id.get(int(leader_uid))
    if not u:
        return None
    ls = window.monster_db.leader_skill_for(u.unit_master_id)
    if ls and ls.area in ("Guild", "General"):
        return ls
    return None


def spd_from_stat_tuple(_window, stat: Tuple[int, int] | Tuple[int, int, int, int]) -> int:
    if not stat:
        return 0
    try:
        if int(stat[0] or 0) != 8:
            return 0
        return int(stat[1] or 0)
    except Exception:
        return 0


def spd_from_substats(_window, subs: List[Tuple[int, int, int, int]]) -> int:
    total = 0
    for sec in subs or []:
        try:
            if int(sec[0] or 0) != 8:
                continue
            total += int(sec[1] or 0)
            if len(sec) >= 4:
                total += int(sec[3] or 0)
        except Exception:
            continue
    return total
