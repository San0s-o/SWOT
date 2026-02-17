from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

@dataclass(frozen=True)
class Unit:
    unit_id: int
    unit_master_id: int
    attribute: int
    unit_level: int
    unit_class: int
    base_con: int
    base_atk: int
    base_def: int
    base_spd: int
    base_res: int
    base_acc: int
    crit_rate: int
    crit_dmg: int

@dataclass(frozen=True)
class Rune:
    rune_id: int
    slot_no: int
    set_id: int
    rank: int
    rune_class: int
    upgrade_curr: int
    pri_eff: Tuple[int, int]
    prefix_eff: Tuple[int, int]
    sec_eff: List[Tuple[int, int, int, int]]
    occupied_type: int
    occupied_id: int
    origin_class: int = 0

@dataclass(frozen=True)
class Artifact:
    artifact_id: int          # rid oder artifact_id
    occupied_id: int
    slot: int                 # 1 = left, 2 = right
    type_: int                # 1/2 (bei rid-Objekten heißt es "type"; bei summary "artifact_type")
    attribute: int            # 0..5, bei summary ggf. nicht vorhanden -> 0
    rank: int                 # aktuelle Qualität (kann durch Upgrades steigen)
    level: int                # bei summary ggf. 0
    original_rank: int = 0    # Ausgangsqualität (natural_rank aus Export)
    pri_effect: Tuple[int, ...] = ()          # [effect_id, value, ...]
    sec_effects: List[List] = field(default_factory=list)  # [[eff_id, value, upgrades, ...], ...]

@dataclass
class AccountData:
    # In-memory normalized store
    units_by_id: Dict[int, Unit] = field(default_factory=dict)
    runes: List[Rune] = field(default_factory=list)
    artifacts: List[Artifact] = field(default_factory=list)

    # Raw defense lists
    guildsiege_defense_unit_list: List[int] = field(default_factory=list)
    arena_defense_unit_list: List[int] = field(default_factory=list)
    # deck_list entries for classic arena loadout/decks (deck_type=1)
    arena_deck_teams: List[List[int]] = field(default_factory=list)
    # Sky Tribe Totem (SPD building) extracted from account JSON.
    sky_tribe_totem_level: int = 0
    sky_tribe_totem_spd_pct: int = 0

    # Mode-specific rune equipment: unit_id -> [rune_id, ...]
    # These come from equip_info_list (siege/guild) and world_arena_rune_equip_list (RTA)
    guild_rune_equip: Dict[int, List[int]] = field(default_factory=dict)
    rta_rune_equip: Dict[int, List[int]] = field(default_factory=dict)
    # RTA artifact equipment: unit_id -> [artifact_id, ...]
    rta_artifact_equip: Dict[int, List[int]] = field(default_factory=dict)

    def siege_def_teams(self) -> List[List[int]]:
        ids = self.guildsiege_defense_unit_list
        # Group into chunks of 3 (4 defs typical, but we don't assume count)
        return [ids[i:i+3] for i in range(0, len(ids), 3) if ids[i:i+3]]

    def arena_def_team(self) -> List[int]:
        return [int(uid) for uid in (self.arena_defense_unit_list or []) if int(uid or 0) > 0][:4]

    def arena_offense_decks(self, limit: int = 12, exclude_current_defense: bool = True) -> List[List[int]]:
        out: List[List[int]] = []
        defense_set = set(self.arena_def_team())
        for team in (self.arena_deck_teams or []):
            ids = [int(uid) for uid in (team or []) if int(uid or 0) > 0][:4]
            if len(ids) != 4:
                continue
            if exclude_current_defense and defense_set and set(ids) == defense_set:
                continue
            out.append(ids)
            if len(out) >= int(max(1, int(limit or 1))):
                break
        return out

    def rta_active_unit_ids(self) -> List[int]:
        """Unit-IDs that are fully equipped for RTA (6 runes + 2 artifacts)."""
        result = []
        for uid in self.rta_rune_equip:
            if len(self.rta_rune_equip[uid]) >= 6:
                if len(self.rta_artifact_equip.get(uid, [])) >= 2:
                    result.append(uid)
        return result

    def runes_by_id(self) -> Dict[int, Rune]:
        """Fast lookup: rune_id -> Rune."""
        return {r.rune_id: r for r in self.runes}

    def equipped_runes_for(self, unit_id: int, mode: str = "pve") -> List[Rune]:
        """Return the runes equipped on *unit_id* for the given mode.

        mode: "pve" (default occupied_id), "siege"/"guild", "rta"
        Falls back to PVE runes if the mode has no data.
        """
        if mode in ("siege", "guild"):
            equip = self.guild_rune_equip
        elif mode == "rta":
            equip = self.rta_rune_equip
        else:
            equip = {}

        rune_ids = equip.get(unit_id)
        if rune_ids:
            by_id = self.runes_by_id()
            runes = [by_id[rid] for rid in rune_ids if rid in by_id]
            if runes:
                return sorted(runes, key=lambda r: int(r.slot_no or 0))

        # fallback: PVE runes (occupied_type==1, occupied_id==unit_id)
        return sorted(
            [r for r in self.runes if r.occupied_type == 1 and int(r.occupied_id or 0) == int(unit_id)],
            key=lambda r: int(r.slot_no or 0),
        )


# ============================================================
# Stat computation: base + rune bonuses
# ============================================================
def compute_unit_stats(unit: Unit, equipped_runes: List[Rune],
                       speed_lead_pct: int = 0,
                       sky_tribe_totem_spd_pct: int = 0) -> Dict[str, int]:
    """Compute total stats for a unit including all rune bonuses and set bonuses.

    *equipped_runes* must already be filtered to the runes on this unit.
    *speed_lead_pct* is the best speed-lead percentage in the team (0 if none).
    *sky_tribe_totem_spd_pct* is the account-wide SPD building bonus in percent.
    """
    base_hp  = int((unit.base_con or 0) * 15)
    base_atk = int(unit.base_atk or 0)
    base_def = int(unit.base_def or 0)
    base_spd = int(unit.base_spd or 0)
    base_cr  = int(unit.crit_rate or 15)
    base_cd  = int(unit.crit_dmg or 50)
    base_res = int(unit.base_res or 15)
    base_acc = int(unit.base_acc or 0)

    flat_hp = flat_atk = flat_def = 0
    pct_hp = pct_atk = pct_def = 0
    add_spd = add_cr = add_cd = add_res = add_acc = 0
    rune_set_ids: List[int] = []

    def _acc(eff_id: int, value: int) -> None:
        nonlocal flat_hp, flat_atk, flat_def, pct_hp, pct_atk, pct_def
        nonlocal add_spd, add_cr, add_cd, add_res, add_acc
        m = {1: 'fhp', 2: 'php', 3: 'fatk', 4: 'patk', 5: 'fdef', 6: 'pdef',
             8: 'spd', 9: 'cr', 10: 'cd', 11: 'res', 12: 'acc'}
        k = m.get(eff_id)
        if k == 'fhp':   flat_hp  += value
        elif k == 'php':  pct_hp   += value
        elif k == 'fatk': flat_atk += value
        elif k == 'patk': pct_atk  += value
        elif k == 'fdef': flat_def += value
        elif k == 'pdef': pct_def  += value
        elif k == 'spd':  add_spd  += value
        elif k == 'cr':   add_cr   += value
        elif k == 'cd':   add_cd   += value
        elif k == 'res':  add_res  += value
        elif k == 'acc':  add_acc  += value

    for rune in equipped_runes:
        rune_set_ids.append(int(rune.set_id or 0))
        try:
            _acc(int(rune.pri_eff[0] or 0), int(rune.pri_eff[1] or 0))
        except Exception:
            pass
        try:
            _acc(int(rune.prefix_eff[0] or 0), int(rune.prefix_eff[1] or 0))
        except Exception:
            pass
        for sec in (rune.sec_eff or []):
            if not sec:
                continue
            try:
                eff = int(sec[0] or 0)
                val = int(sec[1] or 0)
                grind = int(sec[3] or 0) if len(sec) >= 4 else 0
                _acc(eff, val + grind)
            except Exception:
                continue

    # set bonuses
    swift_sets = rune_set_ids.count(3) // 4
    spd_from_swift = int(base_spd * (25 * swift_sets) / 100)
    spd_from_lead = int(base_spd * speed_lead_pct / 100)
    spd_from_totem = int(base_spd * int(sky_tribe_totem_spd_pct or 0) / 100)

    return {
        "HP":  int(base_hp  + flat_hp  + base_hp  * pct_hp  // 100),
        "ATK": int(base_atk + flat_atk + base_atk * pct_atk // 100),
        "DEF": int(base_def + flat_def + base_def * pct_def // 100),
        "SPD": int(base_spd + add_spd + spd_from_swift + spd_from_lead + spd_from_totem),
        "CR":  int(base_cr  + add_cr),
        "CD":  int(base_cd  + add_cd),
        "RES": int(base_res + add_res),
        "ACC": int(base_acc + add_acc),
    }
