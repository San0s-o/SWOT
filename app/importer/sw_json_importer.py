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


_RUNE_CLASS_IDS = {1, 2, 3, 4, 5, 6, 11, 12, 13, 14, 15, 16}


def _parse_rune_origin_class(r: Dict[str, Any]) -> int:
    extra = _safe_int(r.get("extra"), 0)
    if extra in _RUNE_CLASS_IDS:
        return extra
    cls = _safe_int(r.get("class"), 0)
    return cls if cls in _RUNE_CLASS_IDS else 0


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

    unit_list = data.get("unit_list", []) or []
    for u in unit_list:
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
            if art:
                full_arts_by_id[art.artifact_id] = art
        except Exception:
            continue

    equip_lists: List[List[dict]] = []
    if data.get("artifact_equip_list"):
        equip_lists.append(data.get("artifact_equip_list") or [])
    if data.get("world_arena_artifact_equip_list"):
        equip_lists.append(data.get("world_arena_artifact_equip_list") or [])

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
