from __future__ import annotations

from types import SimpleNamespace
from typing import Dict, List, Tuple

from app.engine.arena_rush_timing import effective_spd_buff_pct_for_unit, spd_buff_increase_pct_for_unit

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


def _arena_rush_team_context(window, team_unit_ids: List[int]) -> Tuple[str, int]:
    ids = [int(uid) for uid in (team_unit_ids or []) if int(uid) > 0]
    if not ids:
        return "", -1
    ids_set = set(ids)
    try:
        def_ids = []
        for cmb in (getattr(window, "arena_def_combos", []) or []):
            uid = int(cmb.currentData() or 0)
            if uid > 0:
                def_ids.append(uid)
        if len(def_ids) == len(ids) and set(def_ids) == ids_set:
            return "defense", -1
    except Exception:
        pass
    try:
        off_rows = list(getattr(window, "arena_offense_team_combos", []) or [])
        off_enabled = list(getattr(window, "chk_arena_offense_enabled", []) or [])
        for team_index, row in enumerate(off_rows):
            if team_index < len(off_enabled) and not bool(off_enabled[team_index].isChecked()):
                continue
            sids = []
            for cmb in row:
                uid = int(cmb.currentData() or 0)
                if uid > 0:
                    sids.append(uid)
            if len(sids) == len(ids) and set(sids) == ids_set:
                return "offense", int(team_index)
    except Exception:
        pass
    return "", -1


def _arena_rush_selected_speed_lead(window, team_unit_ids: List[int]):
    if not window.account:
        return None
    ctx, off_idx = _arena_rush_team_context(window, team_unit_ids)
    lead_uid = 0
    lead_pct = 0
    if ctx == "defense":
        lead_uid = int(getattr(window, "arena_def_speed_lead_uid", 0) or 0)
        lead_pct = int(getattr(window, "arena_def_speed_lead_pct", 0) or 0)
    elif ctx == "offense":
        lead_uid = int(dict(getattr(window, "arena_offense_speed_lead_uid_by_team", {}) or {}).get(int(off_idx), 0) or 0)
        lead_pct = int(dict(getattr(window, "arena_offense_speed_lead_pct_by_team", {}) or {}).get(int(off_idx), 0) or 0)
    if lead_uid <= 0 or lead_uid not in {int(uid) for uid in (team_unit_ids or []) if int(uid) > 0}:
        return None
    if lead_pct <= 0:
        lead_unit = window.account.units_by_id.get(int(lead_uid))
        if lead_unit is None:
            return None
        ls = window.monster_db.leader_skill_for(int(lead_unit.unit_master_id))
        if not ls or str(ls.stat).strip().upper() != "SPD%" or str(ls.area).strip() not in ("Arena", "General"):
            return None
        lead_pct = int(ls.amount or 0)
    if lead_pct <= 0:
        return None
    return SimpleNamespace(stat="SPD%", amount=int(lead_pct), area="Arena", element="")


def _arena_rush_spd_buff_bonus_for_unit(
    window,
    unit_id: int,
    team_unit_ids: List[int],
    base_spd: int,
    artifacts_by_unit: Dict[int, Dict[int, int]] | None = None,
) -> int:
    mode_ctx = str(getattr(window, "_result_mode_context", "") or "").strip().lower()
    if mode_ctx != "arena_rush":
        return 0
    ctx, off_idx = _arena_rush_team_context(window, team_unit_ids)
    if ctx != "offense" or int(off_idx) < 0:
        return 0
    order = [int(uid) for uid in (team_unit_ids or []) if int(uid) > 0]
    target_uid = int(unit_id or 0)
    if target_uid <= 0 or target_uid not in order:
        return 0
    target_pos = order.index(int(target_uid))
    team_effects: Dict[int, Dict[str, object]] = {}
    payload_rows = list(getattr(window, "_arena_rush_last_offense_payload", []) or [])
    for row in payload_rows:
        r_off_idx = int((row or {}).get("team_index", -1) or -1)
        r_ids = [int(uid) for uid in ((row or {}).get("unit_ids") or []) if int(uid) > 0]
        if r_off_idx == int(off_idx) and r_ids == order:
            team_effects = {
                int(uid): dict(cfg or {})
                for uid, cfg in dict((row or {}).get("turn_effects_by_unit") or {}).items()
                if int(uid or 0) > 0
            }
            break
    if not team_effects:
        team_effects = dict(dict(getattr(window, "arena_offense_turn_effects", {}) or {}).get(int(off_idx), {}) or {})
    applies = False
    for pos, caster_uid in enumerate(order):
        if pos >= target_pos:
            break
        cfg = dict(team_effects.get(int(caster_uid), {}) or {})
        if not bool(cfg.get("applies_spd_buff", False)):
            continue
        applies = True
        break
    if not applies:
        return 0
    artifact_lookup = {int(a.artifact_id): a for a in (window.account.artifacts or [])}
    selected_artifacts = dict((artifacts_by_unit or {}).get(int(target_uid), {}) or {})
    artifact_ids = [int(aid) for aid in selected_artifacts.values() if int(aid or 0) > 0]
    inc_pct = spd_buff_increase_pct_for_unit(artifact_ids, artifact_lookup)
    eff_buff_pct = effective_spd_buff_pct_for_unit(inc_pct, base_spd_buff_pct=30.0)
    return int(int(base_spd or 0) * float(eff_buff_pct) / 100.0)


def unit_spd_buff_bonus(
    window,
    unit_id: int,
    team_unit_ids: List[int],
    artifacts_by_unit: Dict[int, Dict[int, int]] | None = None,
) -> Dict[str, int]:
    if not window.account:
        return {}
    u = window.account.units_by_id.get(int(unit_id))
    if u is None:
        return {}
    base_spd = int(u.base_spd or 0)
    bonus = _arena_rush_spd_buff_bonus_for_unit(
        window,
        int(unit_id),
        list(team_unit_ids or []),
        base_spd,
        artifacts_by_unit=artifacts_by_unit,
    )
    if bonus <= 0:
        return {}
    return {"SPD": int(bonus)}


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


def unit_final_spd_value(
    window,
    unit_id: int,
    team_unit_ids: List[int],
    runes_by_unit: Dict[int, Dict[int, int]],
    artifacts_by_unit: Dict[int, Dict[int, int]] | None = None,
) -> int:
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
    spd_buff_bonus = _arena_rush_spd_buff_bonus_for_unit(
        window, unit_id, team_unit_ids, base_spd, artifacts_by_unit=artifacts_by_unit
    )
    return int(base_spd + rune_spd_flat + set_spd_bonus + totem_spd_bonus + lead_spd_bonus + spd_buff_bonus)


def unit_final_stats_values(
    window,
    unit_id: int,
    team_unit_ids: List[int],
    runes_by_unit: Dict[int, Dict[int, int]],
    artifacts_by_unit: Dict[int, Dict[int, int]] | None = None,
) -> Dict[str, int]:
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
    spd_buff_bonus = _arena_rush_spd_buff_bonus_for_unit(
        window, unit_id, team_unit_ids, base_spd, artifacts_by_unit=artifacts_by_unit
    )
    spd = base_spd + add_spd + spd_from_swift + spd_from_totem + lead_spd + spd_buff_bonus

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
    mode_ctx = str(getattr(window, "_result_mode_context", "") or "").strip().lower()
    if mode_ctx == "arena_rush":
        selected = _arena_rush_selected_speed_lead(window, team_unit_ids)
        if selected is not None:
            return selected
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
