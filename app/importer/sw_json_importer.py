from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from app.domain.models import AccountData, Unit, Rune, Artifact


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if isinstance(x, str):
            txt = x.strip().replace("%", "").replace(",", ".")
            return float(txt)
        return float(x)
    except Exception:
        return default


def _extract_artifact_score(a: Dict[str, Any]) -> float:
    candidates = [
        a.get("efficiency"),
        a.get("score"),
        a.get("efficiency_current"),
        a.get("efficiency_score"),
        a.get("current_efficiency"),
        a.get("artifact_efficiency"),
    ]
    for c in candidates:
        if isinstance(c, dict):
            nested = [
                c.get("current"),
                c.get("score"),
                c.get("value"),
                c.get("efficiency"),
            ]
            for n in nested:
                v = _safe_float(n, 0.0)
                if v > 0.0:
                    return v
            continue
        v = _safe_float(c, 0.0)
        if v > 0.0:
            return v
    return 0.0


_RUNE_CLASS_IDS = {1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16}
_SKY_TRIBE_TOTEM_DECO_MASTER_ID = 6
_SKY_TRIBE_TOTEM_MAX_LEVEL = 20
_SKY_TRIBE_TOTEM_MAX_SPD_PCT = 15


def _parse_rune_origin_class(r: Dict[str, Any]) -> int:
    extra = _safe_int(r.get("extra"), 0)
    if extra in _RUNE_CLASS_IDS:
        return extra
    cls = _safe_int(r.get("class"), 0)
    return cls if cls in _RUNE_CLASS_IDS else 0


def _sky_tribe_totem_spd_pct_from_level(level: int) -> int:
    lvl = max(0, min(int(level or 0), _SKY_TRIBE_TOTEM_MAX_LEVEL))
    return int(lvl * _SKY_TRIBE_TOTEM_MAX_SPD_PCT / _SKY_TRIBE_TOTEM_MAX_LEVEL)


def _extract_sky_tribe_totem_level(data: Dict[str, Any]) -> int:
    for deco in (data.get("deco_list") or []):
        if not isinstance(deco, dict):
            continue
        if _safe_int(deco.get("master_id")) != _SKY_TRIBE_TOTEM_DECO_MASTER_ID:
            continue
        return max(0, _safe_int(deco.get("level"), 0))
    return 0


def _parse_artifact(a: Dict[str, Any], occupied_id_override: int | None = None) -> Artifact | None:
    art_id = _safe_int(a.get("artifact_id") or a.get("rid"))
    if art_id == 0:
        return None
    occ = occupied_id_override if occupied_id_override is not None else _safe_int(a.get("occupied_id", 0))
    raw_pri = a.get("pri_effect") or []
    raw_sec = a.get("sec_effects") or []
    original_rank = _safe_int(
        a.get("natural_rank")
        or a.get("original_rank")
        or a.get("orig_rank")
        or 0
    )
    # Vorberechneter Score aus dem Export (Format variiert je nach Tool)
    json_score = _extract_artifact_score(a)
    return Artifact(
        artifact_id=art_id,
        occupied_id=occ,
        slot=_safe_int(a.get("slot")),
        type_=_safe_int(a.get("type") or a.get("artifact_type")),
        attribute=_safe_int(a.get("attribute")),
        rank=_safe_int(a.get("rank")),
        level=_safe_int(a.get("level")),
        original_rank=original_rank,
        pri_effect=tuple(raw_pri) if raw_pri else (),
        sec_effects=[list(s) for s in raw_sec],
        json_score=json_score,
    )


def load_account_json(path: str | Path) -> AccountData:
    """
    Lädt einen Summoners-War-JSON-Export und normalisiert
    Units, Runen, Artefakte und Guild-Siege-Listen.
    """
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    return _normalize_account_data(data)


def load_account_from_data(raw_data: Dict[str, Any]) -> AccountData:
    """
    Normalisiert bereits eingelesene JSON-Daten (z.B. Snapshots).
    """
    return _normalize_account_data(raw_data)


def _normalize_account_data(data: Dict[str, Any]) -> AccountData:
    acc = AccountData()
    acc.sky_tribe_totem_level = _extract_sky_tribe_totem_level(data)
    acc.sky_tribe_totem_spd_pct = _sky_tribe_totem_spd_pct_from_level(acc.sky_tribe_totem_level)

    # Some exports split owned units between the active box and monster storage.
    # We need both sources so stored monsters (e.g. Shi Hou) appear in the UI.
    unit_sources = [
        data.get("unit_list", []) or [],
        data.get("unit_storage_normal_list", []) or [],
    ]
    for units in unit_sources:
        for u in units:
            unit_id = _safe_int(u.get("unit_id"))
            unit_master_id = _safe_int(u.get("unit_master_id"))
            if unit_id == 0 or unit_master_id == 0:
                continue

            unit = Unit(
                unit_id=unit_id,
                unit_master_id=unit_master_id,
                attribute=_safe_int(u.get("attribute")),
                unit_level=_safe_int(u.get("unit_level")),
                unit_class=_safe_int(u.get("class")),
                base_con=_safe_int(u.get("con")),
                base_atk=_safe_int(u.get("atk")),
                base_def=_safe_int(u.get("def")),
                base_spd=_safe_int(u.get("spd")),
                base_res=_safe_int(u.get("resist")),
                base_acc=_safe_int(u.get("accuracy")),
                crit_rate=_safe_int(u.get("critical_rate")),
                crit_dmg=_safe_int(u.get("critical_damage")),
            )
            acc.units_by_id[unit_id] = unit

            for r in (u.get("runes") or []):
                rune_id = _safe_int(r.get("rune_id"))
                if rune_id == 0:
                    continue
                try:
                    rune = Rune(
                        rune_id=rune_id,
                        slot_no=_safe_int(r.get("slot_no")),
                        set_id=_safe_int(r.get("set_id")),
                        rank=_safe_int(r.get("rank")),
                        rune_class=_safe_int(r.get("class")),
                        upgrade_curr=_safe_int(r.get("upgrade_curr")),
                        pri_eff=tuple(r.get("pri_eff") or [0, 0]),
                        prefix_eff=tuple(r.get("prefix_eff") or [0, 0]),
                        sec_eff=[tuple(x) for x in (r.get("sec_eff") or [])],
                        occupied_type=_safe_int(r.get("occupied_type")),
                        occupied_id=_safe_int(r.get("occupied_id")),
                        origin_class=_parse_rune_origin_class(r),
                    )
                    acc.runes.append(rune)
                except Exception:
                    continue

            for a in (u.get("artifacts") or []):
                try:
                    art = _parse_artifact(a)
                    if art and art.slot in (1, 2):
                        acc.artifacts.append(art)
                except Exception:
                    continue

    for r in (data.get("runes") or []):
        rune_id = _safe_int(r.get("rune_id"))
        if rune_id == 0:
            continue
        try:
            rune = Rune(
                rune_id=rune_id,
                slot_no=_safe_int(r.get("slot_no")),
                set_id=_safe_int(r.get("set_id")),
                rank=_safe_int(r.get("rank")),
                rune_class=_safe_int(r.get("class")),
                upgrade_curr=_safe_int(r.get("upgrade_curr")),
                pri_eff=tuple(r.get("pri_eff") or [0, 0]),
                prefix_eff=tuple(r.get("prefix_eff") or [0, 0]),
                sec_eff=[tuple(x) for x in (r.get("sec_eff") or [])],
                occupied_type=_safe_int(r.get("occupied_type")),
                occupied_id=_safe_int(r.get("occupied_id")),
                origin_class=_parse_rune_origin_class(r),
            )
            acc.runes.append(rune)
        except Exception:
            continue

    runes_by_id: Dict[int, Rune] = {}
    for ru in acc.runes:
        prev = runes_by_id.get(ru.rune_id)
        if prev is None:
            runes_by_id[ru.rune_id] = ru
        else:
            if len(ru.sec_eff or []) > len(prev.sec_eff or []):
                runes_by_id[ru.rune_id] = ru
            elif prev.upgrade_curr == 0 and ru.upgrade_curr != 0:
                runes_by_id[ru.rune_id] = ru
    acc.runes = list(runes_by_id.values())

    # Start with fully populated artifacts parsed from unit_list[*].artifacts.
    # Some exports do not provide a top-level "artifacts" list, so we must
    # preserve unit-level data and only enrich/override occupied mapping later.
    full_arts_by_id: Dict[int, Artifact] = {int(a.artifact_id): a for a in acc.artifacts}
    for a in (data.get("artifacts") or []):
        try:
            art = _parse_artifact(a)
            if not art:
                continue
            prev = full_arts_by_id.get(int(art.artifact_id))
            if prev is None:
                full_arts_by_id[art.artifact_id] = art
                continue

            full_arts_by_id[art.artifact_id] = Artifact(
                artifact_id=prev.artifact_id,
                occupied_id=int(art.occupied_id or 0) if int(art.occupied_id or 0) > 0 else prev.occupied_id,
                slot=int(art.slot or 0) if int(art.slot or 0) in (1, 2) else prev.slot,
                type_=int(art.type_ or 0) if int(art.type_ or 0) in (1, 2) else prev.type_,
                attribute=int(art.attribute or 0) if int(art.attribute or 0) > 0 else prev.attribute,
                rank=int(art.rank or 0) if int(art.rank or 0) > 0 else prev.rank,
                level=int(art.level or 0) if int(art.level or 0) > 0 else prev.level,
                original_rank=int(art.original_rank or 0) if int(art.original_rank or 0) > 0 else prev.original_rank,
                pri_effect=art.pri_effect if art.pri_effect and len(art.pri_effect) >= 2 else prev.pri_effect,
                sec_effects=art.sec_effects if len(art.sec_effects or []) >= len(prev.sec_effects or []) else prev.sec_effects,
                json_score=float(art.json_score or 0.0) if float(art.json_score or 0.0) > 0.0 else prev.json_score,
            )
        except Exception:
            continue

    equip_lists: List[List[dict]] = []
    # Canonical occupied_id for account artifacts should reflect normal/PVE equip state.
    # RTA equip (world_arena_artifact_equip_list) is tracked separately in acc.rta_artifact_equip
    # and must not overwrite the artifact overview assignment, otherwise units can appear with
    # multiple slot-1/slot-2 artifacts at the same time in the general artifact table.
    if data.get("artifact_equip_list"):
        equip_lists.append(data.get("artifact_equip_list") or [])

    for eq_list in equip_lists:
        for e in eq_list:
            art_id = _safe_int(e.get("artifact_id"))
            if art_id == 0:
                continue
            try:
                occupied_id = _safe_int(e.get("occupied_id", 0))
                slot = _safe_int(e.get("slot"))
                type_ = _safe_int(e.get("artifact_type") or e.get("type"))
                if art_id in full_arts_by_id:
                    prev = full_arts_by_id[art_id]
                    full_arts_by_id[art_id] = Artifact(
                        artifact_id=prev.artifact_id,
                        occupied_id=occupied_id,
                        slot=slot if slot else prev.slot,
                        type_=type_ if type_ else prev.type_,
                        attribute=prev.attribute,
                        rank=prev.rank,
                        level=prev.level,
                        original_rank=prev.original_rank,
                        pri_effect=prev.pri_effect,
                        sec_effects=prev.sec_effects,
                        json_score=prev.json_score,
                    )
                else:
                    full_arts_by_id[art_id] = Artifact(
                        artifact_id=art_id,
                        occupied_id=occupied_id,
                        slot=slot,
                        type_=type_,
                        attribute=0,
                        rank=0,
                        level=0,
                        original_rank=0,
                    )
            except Exception:
                continue

    acc.artifacts = list(full_arts_by_id.values())

    acc.guildsiege_defense_unit_list = [
        _safe_int(x) for x in (data.get("guildsiege_defense_unit_list") or [])
        if _safe_int(x) != 0
    ]

    # Classic Arena defense team
    # Prefer defense_deck_info (normal arena deck); server_arena_* can point to
    # interserver/special context depending on snapshot source.
    arena_def_from_deck = [
        _safe_int(x)
        for x in ((data.get("defense_deck_info") or {}).get("unit_id_list") or [])
        if _safe_int(x) > 0
    ]
    arena_def_from_server: List[int] = []
    for row in sorted(
        (data.get("server_arena_defense_unit_list") or []),
        key=lambda x: _safe_int((x or {}).get("pos_id"), 999),
    ):
        if not isinstance(row, dict):
            continue
        uid = _safe_int(row.get("unit_id"))
        if uid > 0:
            arena_def_from_server.append(uid)
    acc.arena_defense_unit_list = (arena_def_from_deck or arena_def_from_server)[:4]

    # Classic Arena deck presets (deck_type=1, 4 units)
    arena_deck_teams: List[List[int]] = []
    for d in (data.get("deck_list") or []):
        if not isinstance(d, dict):
            continue
        if _safe_int(d.get("deck_type")) != 1:
            continue
        unit_ids = [_safe_int(x) for x in (d.get("unit_id_list") or []) if _safe_int(x) > 0][:4]
        if len(unit_ids) != 4:
            continue
        arena_deck_teams.append(unit_ids)
    acc.arena_deck_teams = arena_deck_teams

    # ── mode-specific rune equipment ──────────────────────────
    # Guild/Siege: equip_info_list[*].rune_equip_list
    for equip_info in (data.get("equip_info_list") or []):
        for entry in (equip_info.get("rune_equip_list") or []):
            rid = _safe_int(entry.get("rune_id"))
            uid = _safe_int(entry.get("occupied_id"))
            if rid and uid:
                acc.guild_rune_equip.setdefault(uid, []).append(rid)

    # RTA: world_arena_rune_equip_list
    for entry in (data.get("world_arena_rune_equip_list") or []):
        rid = _safe_int(entry.get("rune_id"))
        uid = _safe_int(entry.get("occupied_id"))
        if rid and uid:
            acc.rta_rune_equip.setdefault(uid, []).append(rid)

    # RTA: world_arena_artifact_equip_list
    for entry in (data.get("world_arena_artifact_equip_list") or []):
        art_id = _safe_int(entry.get("artifact_id"))
        uid = _safe_int(entry.get("occupied_id"))
        if art_id and uid:
            acc.rta_artifact_equip.setdefault(uid, []).append(art_id)

    return acc
