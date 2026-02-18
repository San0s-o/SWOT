from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Set, Tuple

import requests
from PySide6.QtWidgets import QDialog, QMessageBox

from app.domain.presets import Build
from app.engine.arena_rush_optimizer import (
    ArenaRushOffenseTeam,
    ArenaRushRequest,
    optimize_arena_rush,
)
from app.engine.greedy_optimizer import BASELINE_REGRESSION_GUARD_WEIGHT
from app.engine.arena_rush_timing import OpeningTurnEffect
from app.i18n import tr
from app.services.monster_turn_effects_service import ensure_skill_icons, resolve_turn_effect_capabilities
from app.ui.dialogs.build_dialog import BuildDialog


@dataclass
class TeamSelection:
    team_index: int
    unit_ids: List[int]


def _store_compare_snapshot_from_build_dialog(window, mode: str, dlg: BuildDialog) -> None:
    mode_key = str(mode or "").strip().lower()
    if not mode_key:
        return
    store = dict(getattr(window, "_loaded_current_runes_compare_by_mode", {}) or {})
    snap = dlg.loaded_current_runes_snapshot()
    if not isinstance(snap, dict):
        store.pop(mode_key, None)
        window._loaded_current_runes_compare_by_mode = store
        return
    runes_raw = dict(snap.get("runes_by_unit") or {})
    artifacts_raw = dict(snap.get("artifacts_by_unit") or {})
    runes_by_unit: Dict[int, Dict[int, int]] = {}
    artifacts_by_unit: Dict[int, Dict[int, int]] = {}
    for uid, by_slot in runes_raw.items():
        ui = int(uid or 0)
        if ui <= 0:
            continue
        clean_slots: Dict[int, int] = {}
        for slot, rid in dict(by_slot or {}).items():
            s = int(slot or 0)
            r = int(rid or 0)
            if 1 <= s <= 6 and r > 0:
                clean_slots[int(s)] = int(r)
        if clean_slots:
            runes_by_unit[int(ui)] = clean_slots
    for uid, by_type in artifacts_raw.items():
        ui = int(uid or 0)
        if ui <= 0:
            continue
        clean_types: Dict[int, int] = {}
        for art_type, aid in dict(by_type or {}).items():
            t = int(art_type or 0)
            a = int(aid or 0)
            if t in (1, 2) and a > 0:
                clean_types[int(t)] = int(a)
        if clean_types:
            artifacts_by_unit[int(ui)] = clean_types
    if runes_by_unit or artifacts_by_unit:
        store[mode_key] = {
            "runes_by_unit": runes_by_unit,
            "artifacts_by_unit": artifacts_by_unit,
        }
    else:
        store.pop(mode_key, None)
    window._loaded_current_runes_compare_by_mode = store


def _baseline_assignments_for_mode(window, mode: str, unit_ids: List[int]) -> Tuple[Dict[int, Dict[int, int]], Dict[int, Dict[int, int]]]:
    mode_key = str(mode or "").strip().lower()
    if not mode_key:
        return {}, {}
    unit_set = {int(uid) for uid in (unit_ids or []) if int(uid) > 0}
    if not unit_set:
        return {}, {}
    compare_store = dict(getattr(window, "_loaded_current_runes_compare_by_mode", {}) or {})
    snap = dict(compare_store.get(mode_key, {}) or {})
    runes_by_unit: Dict[int, Dict[int, int]] = {}
    for uid, by_slot in dict(snap.get("runes_by_unit") or {}).items():
        ui = int(uid or 0)
        if ui <= 0 or ui not in unit_set:
            continue
        slots = {
            int(slot): int(rid)
            for slot, rid in dict(by_slot or {}).items()
            if 1 <= int(slot or 0) <= 6 and int(rid or 0) > 0
        }
        if slots:
            runes_by_unit[int(ui)] = slots
    arts_by_unit: Dict[int, Dict[int, int]] = {}
    for uid, by_type in dict(snap.get("artifacts_by_unit") or {}).items():
        ui = int(uid or 0)
        if ui <= 0 or ui not in unit_set:
            continue
        types = {
            int(t): int(aid)
            for t, aid in dict(by_type or {}).items()
            if int(t or 0) in (1, 2) and int(aid or 0) > 0
        }
        if types:
            arts_by_unit[int(ui)] = types
    return runes_by_unit, arts_by_unit


def _arena_rush_selection_path(window) -> Path:
    return Path(window.config_dir) / "arena_rush_selection.json"


def _arena_speed_lead_cache_path(window) -> Path:
    return Path(window.config_dir) / "arena_speed_lead_cache.json"


def _arena_archetype_cache_path(window) -> Path:
    return Path(window.config_dir) / "arena_archetype_cache.json"


def _allow_online_metadata_fetch(window) -> bool:
    settings_path = Path(window.config_dir) / "app_settings.json"
    try:
        if not settings_path.exists():
            return False
        raw = json.loads(settings_path.read_text(encoding="utf-8", errors="replace"))
        return bool((raw or {}).get("allow_online_metadata_fetch", False))
    except Exception:
        return False


def _load_arena_speed_lead_cache(path: Path) -> Dict[int, int]:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        out: Dict[int, int] = {}
        for k, v in dict(raw or {}).items():
            try:
                mid = int(k or 0)
                pct = int(v or 0)
            except Exception:
                continue
            if mid > 0:
                out[int(mid)] = max(0, int(pct))
        return out
    except Exception:
        return {}


def _save_arena_speed_lead_cache(path: Path, cache: Dict[int, int]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {str(int(mid)): int(max(0, int(pct or 0))) for mid, pct in dict(cache or {}).items() if int(mid) > 0}
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _fetch_arena_speed_lead_pct_for_com2us_id(com2us_id: int, timeout_s: float = 6.0) -> int:
    cid = int(com2us_id or 0)
    if cid <= 0:
        return 0
    try:
        resp = requests.get(
            "https://swarfarm.com/api/v2/monsters/",
            params={"com2us_id": int(cid)},
            timeout=float(timeout_s),
        )
        if int(resp.status_code) != 200:
            return 0
        payload = dict(resp.json() or {})
        results = list(payload.get("results") or [])
        if not results:
            return 0
        leader = dict((results[0] or {}).get("leader_skill") or {})
        stat = str(leader.get("stat") or "").strip().upper()
        area = str(leader.get("area") or "").strip()
        if stat != "SPD%" or area not in ("Arena", "General"):
            return 0
        return max(0, int(float(leader.get("amount") or 0)))
    except Exception:
        return 0


def _load_arena_archetype_cache(path: Path) -> Dict[int, str]:
    try:
        if not path.exists():
            return {}
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        out: Dict[int, str] = {}
        for k, v in dict(raw or {}).items():
            try:
                mid = int(k or 0)
            except Exception:
                continue
            if mid <= 0:
                continue
            archetype = str(v or "").strip()
            if archetype:
                out[int(mid)] = archetype
        return out
    except Exception:
        return {}


def _save_arena_archetype_cache(path: Path, cache: Dict[int, str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            str(int(mid)): str(arch)
            for mid, arch in dict(cache or {}).items()
            if int(mid) > 0 and str(arch or "").strip()
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def _fetch_archetype_for_com2us_id(com2us_id: int, timeout_s: float = 6.0) -> str:
    cid = int(com2us_id or 0)
    if cid <= 0:
        return ""
    try:
        resp = requests.get(
            "https://swarfarm.com/api/v2/monsters/",
            params={"com2us_id": int(cid)},
            timeout=float(timeout_s),
        )
        if int(resp.status_code) != 200:
            return ""
        payload = dict(resp.json() or {})
        results = list(payload.get("results") or [])
        if not results:
            return ""
        archetype = str((results[0] or {}).get("archetype") or "").strip()
        return archetype
    except Exception:
        return ""


def save_arena_rush_ui_state(window) -> None:
    path = _arena_rush_selection_path(window)
    raw_effects = dict(getattr(window, "arena_offense_turn_effects", {}) or {})
    saved_effects: Dict[str, Dict[str, Dict[str, object]]] = {}
    for t, team_cfg in raw_effects.items():
        try:
            ti = int(t)
        except Exception:
            continue
        team_out: Dict[str, Dict[str, object]] = {}
        for uid, cfg in dict(team_cfg or {}).items():
            try:
                ui = int(uid)
            except Exception:
                continue
            c = dict(cfg or {})
            team_out[str(int(ui))] = {
                "applies_spd_buff": bool(c.get("applies_spd_buff", False)),
                "atb_boost_pct": float(c.get("atb_boost_pct", 0.0) or 0.0),
            }
        if team_out:
            saved_effects[str(int(ti))] = team_out

    data: Dict[str, object] = {
        "version": "2026-02-17",
        "defense_ids": [int(cmb.currentData() or 0) for cmb in (getattr(window, "arena_def_combos", []) or [])],
        "defense_speed_lead_uid": int(getattr(window, "arena_def_speed_lead_uid", 0) or 0),
        "defense_speed_lead_pct": int(getattr(window, "arena_def_speed_lead_pct", 0) or 0),
        "offense_enabled": [bool(chk.isChecked()) for chk in (getattr(window, "chk_arena_offense_enabled", []) or [])],
        "offense_rows": [
            [int(cmb.currentData() or 0) for cmb in row]
            for row in (getattr(window, "arena_offense_team_combos", []) or [])
        ],
        "offense_speed_lead_uid_by_team": {
            str(int(t)): int(uid)
            for t, uid in dict(getattr(window, "arena_offense_speed_lead_uid_by_team", {}) or {}).items()
            if int(t) >= 0 and int(uid or 0) > 0
        },
        "offense_speed_lead_pct_by_team": {
            str(int(t)): int(pct)
            for t, pct in dict(getattr(window, "arena_offense_speed_lead_pct_by_team", {}) or {}).items()
            if int(t) >= 0 and int(pct or 0) > 0
        },
        "offense_turn_effects_by_team": saved_effects,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        return


def restore_arena_rush_ui_state(window) -> None:
    path = _arena_rush_selection_path(window)
    if not path.exists():
        return
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return
    window._ensure_unit_dropdowns_populated()
    defense_ids = [int(x or 0) for x in (raw.get("defense_ids") or [])]
    for idx, cmb in enumerate(window.arena_def_combos):
        uid = int(defense_ids[idx]) if idx < len(defense_ids) else 0
        _set_unit_combo_uid_safely(cmb, uid)
    window.arena_def_speed_lead_uid = int(raw.get("defense_speed_lead_uid", 0) or 0)
    window.arena_def_speed_lead_pct = int(raw.get("defense_speed_lead_pct", 0) or 0)

    offense_enabled = [bool(x) for x in (raw.get("offense_enabled") or [])]
    offense_rows = raw.get("offense_rows") or []
    for t, row in enumerate(window.arena_offense_team_combos):
        if t < len(window.chk_arena_offense_enabled):
            enabled = bool(offense_enabled[t]) if t < len(offense_enabled) else False
            window.chk_arena_offense_enabled[t].setChecked(enabled)
        row_ids = offense_rows[t] if t < len(offense_rows) and isinstance(offense_rows[t], list) else []
        for s, cmb in enumerate(row):
            uid = int(row_ids[s]) if s < len(row_ids) else 0
            _set_unit_combo_uid_safely(cmb, uid)
    raw_off_speed = dict(raw.get("offense_speed_lead_uid_by_team") or {})
    window.arena_offense_speed_lead_uid_by_team = {
        int(t): int(uid)
        for t, uid in raw_off_speed.items()
        if str(t).strip().isdigit() and int(uid or 0) > 0
    }
    raw_off_speed_pct = dict(raw.get("offense_speed_lead_pct_by_team") or {})
    window.arena_offense_speed_lead_pct_by_team = {
        int(t): int(pct)
        for t, pct in raw_off_speed_pct.items()
        if str(t).strip().isdigit() and int(pct or 0) > 0
    }
    raw_effects = dict(raw.get("offense_turn_effects_by_team") or {})
    restored_effects: Dict[int, Dict[int, Dict[str, object]]] = {}
    for t, team_cfg in raw_effects.items():
        if not str(t).strip().isdigit():
            continue
        ti = int(t)
        team_out: Dict[int, Dict[str, object]] = {}
        for uid, cfg in dict(team_cfg or {}).items():
            if not str(uid).strip().isdigit():
                continue
            ui = int(uid)
            c = dict(cfg or {})
            team_out[int(ui)] = {
                "applies_spd_buff": bool(c.get("applies_spd_buff", False)),
                "atb_boost_pct": float(c.get("atb_boost_pct", 0.0) or 0.0),
            }
        if team_out:
            restored_effects[int(ti)] = team_out
    window.arena_offense_turn_effects = restored_effects


def collect_arena_def_selection(window) -> List[int]:
    window._ensure_unit_dropdowns_populated()
    out: List[int] = []
    for cmb in (window.arena_def_combos or []):
        uid = int(cmb.currentData() or 0)
        if uid > 0:
            out.append(uid)
    return out


def collect_arena_offense_selections(window) -> List[TeamSelection]:
    window._ensure_unit_dropdowns_populated()
    out: List[TeamSelection] = []
    for t, row in enumerate(window.arena_offense_team_combos):
        if t < len(window.chk_arena_offense_enabled):
            if not bool(window.chk_arena_offense_enabled[t].isChecked()):
                continue
        ids: List[int] = []
        for cmb in row:
            uid = int(cmb.currentData() or 0)
            if uid > 0:
                ids.append(uid)
        out.append(TeamSelection(team_index=int(t), unit_ids=ids))
    return out


def _set_unit_combo_uid_safely(cmb, uid: int) -> None:
    target_uid = int(uid or 0)
    try:
        if hasattr(cmb, "set_filter_suspended"):
            cmb.set_filter_suspended(True)
    except Exception:
        pass
    try:
        cmb.blockSignals(True)
    except Exception:
        pass
    idx = cmb.findData(target_uid)
    cmb.setCurrentIndex(idx if idx >= 0 else 0)
    try:
        cmb.blockSignals(False)
    except Exception:
        pass
    try:
        if hasattr(cmb, "_clear_filter"):
            cmb._clear_filter()
        if hasattr(cmb, "_sync_line_edit_to_current"):
            cmb._sync_line_edit_to_current()
        if hasattr(cmb, "hidePopup"):
            cmb.hidePopup()
    except Exception:
        pass
    try:
        if hasattr(cmb, "set_filter_suspended"):
            cmb.set_filter_suspended(False)
    except Exception:
        pass


def on_take_current_arena_def(window) -> None:
    if not window.account:
        return
    ids = list(window.account.arena_def_team() or [])
    for idx, cmb in enumerate(window.arena_def_combos):
        uid = int(ids[idx]) if idx < len(ids) else 0
        _set_unit_combo_uid_safely(cmb, uid)
    window.arena_def_speed_lead_uid = 0
    window.arena_def_speed_lead_pct = 0
    save_arena_rush_ui_state(window)
    window.lbl_arena_rush_validate.setText(tr("status.arena_def_taken"))


def on_take_current_arena_off(window) -> None:
    if not window.account:
        return
    all_decks = window.account.arena_offense_decks(limit=9999)
    decks = all_decks[: len(window.arena_offense_team_combos)]
    for t, row in enumerate(window.arena_offense_team_combos):
        team = decks[t] if t < len(decks) else []
        if t < len(window.chk_arena_offense_enabled):
            window.chk_arena_offense_enabled[t].setChecked(bool(team))
        for s, cmb in enumerate(row):
            uid = int(team[s]) if s < len(team) else 0
            _set_unit_combo_uid_safely(cmb, uid)
    save_arena_rush_ui_state(window)
    window.arena_offense_turn_effects = {}
    window.arena_offense_speed_lead_uid_by_team = {}
    window.arena_offense_speed_lead_pct_by_team = {}
    if len(all_decks) > len(decks):
        window.lbl_arena_rush_validate.setText(
            tr("status.arena_off_taken_limited", count=len(decks), total=len(all_decks))
        )
    else:
        window.lbl_arena_rush_validate.setText(tr("status.arena_off_taken", count=len(decks)))


def _validate_arena_rush(window) -> Tuple[bool, str, List[int], List[TeamSelection]]:
    defense_ids = collect_arena_def_selection(window)
    if len(defense_ids) != 4:
        return False, tr("val.arena_def_need_4", have=len(defense_ids)), [], []
    if len(set(defense_ids)) != 4:
        return False, tr("val.arena_def_duplicate"), [], []

    offense_teams_raw = collect_arena_offense_selections(window)
    offense_teams: List[TeamSelection] = []
    for sel in offense_teams_raw:
        ids = list(sel.unit_ids or [])
        if not ids:
            continue
        if len(ids) != 4:
            return False, tr("val.arena_off_need_4", team=sel.team_index + 1, have=len(ids)), [], []
        if len(set(ids)) != 4:
            return False, tr("val.arena_off_duplicate", team=sel.team_index + 1), [], []
        offense_teams.append(sel)
    if not offense_teams:
        return False, tr("val.arena_need_off"), [], []
    return True, tr("val.arena_ok", off_count=len(offense_teams)), defense_ids, offense_teams


def _arena_effect_capabilities_by_unit(
    window,
    unit_ids: List[int],
    fetch_missing: bool = True,
    ensure_icons_for_dialog: bool = True,
) -> Dict[int, Dict[str, object]]:
    if not window.account:
        return {}
    uid_to_mid: Dict[int, int] = {}
    for uid in [int(x) for x in (unit_ids or []) if int(x) > 0]:
        unit = window.account.units_by_id.get(int(uid))
        if unit is None:
            continue
        mid = int(unit.unit_master_id or 0)
        if mid > 0:
            uid_to_mid[int(uid)] = mid
    caps_by_cid: Dict[int, Dict[str, object]] = {}
    if bool(fetch_missing):
        cache_path = window.project_root / "app" / "config" / "monster_turn_effect_capabilities.json"
        com2us_ids = sorted(set(uid_to_mid.values()))
        caps_by_cid = resolve_turn_effect_capabilities(
            com2us_ids,
            cache_path=cache_path,
            fetch_missing=True,
        )
        if bool(ensure_icons_for_dialog):
            skill_icons_dir = window.assets_dir / "skills"
            ensure_skill_icons(caps_by_cid, skill_icons_dir)
    out: Dict[int, Dict[str, object]] = {}
    for uid, mid in uid_to_mid.items():
        base = dict(window.monster_db.turn_effect_capability_for(mid) or {})
        cap = dict(caps_by_cid.get(mid) or {})
        if bool(fetch_missing):
            has_spd_buff = bool(cap.get("has_spd_buff", base.get("has_spd_buff", False)))
            has_atb_boost = bool(cap.get("has_atb_boost", base.get("has_atb_boost", False)))
            max_atb_boost_pct = int(cap.get("max_atb_boost_pct", base.get("max_atb_boost_pct", 0)) or 0)
            spd_icon = str(cap.get("spd_buff_skill_icon", base.get("spd_buff_skill_icon", "")) or "")
            atb_icon = str(cap.get("atb_boost_skill_icon", base.get("atb_boost_skill_icon", "")) or "")
        else:
            has_spd_buff = bool(base.get("has_spd_buff", False))
            has_atb_boost = bool(base.get("has_atb_boost", False))
            max_atb_boost_pct = int(base.get("max_atb_boost_pct", 0) or 0)
            spd_icon = str(base.get("spd_buff_skill_icon", "") or "")
            atb_icon = str(base.get("atb_boost_skill_icon", "") or "")
        if has_atb_boost and max_atb_boost_pct <= 0:
            max_atb_boost_pct = 100
        out[int(uid)] = {
            "has_spd_buff": has_spd_buff,
            "has_atb_boost": has_atb_boost,
            "max_atb_boost_pct": int(max_atb_boost_pct),
            "spd_buff_skill_icon": str(spd_icon),
            "atb_boost_skill_icon": str(atb_icon),
        }
    return out


def _arena_speed_lead_pct_by_uid(
    window,
    unit_ids: List[int],
    fetch_missing: bool = True,
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    if not window.account:
        return out
    cache_path = _arena_speed_lead_cache_path(window)
    cache = _load_arena_speed_lead_cache(cache_path)
    cache_changed = False
    for uid in [int(x) for x in (unit_ids or []) if int(x) > 0]:
        unit = window.account.units_by_id.get(int(uid))
        if unit is None:
            continue
        mid = int(unit.unit_master_id or 0)
        if mid <= 0:
            continue
        pct = 0
        ls = window.monster_db.leader_skill_for(int(mid))
        if ls and str(ls.stat).strip().upper() == "SPD%" and str(ls.area).strip() in ("Arena", "General"):
            pct = int(ls.amount or 0)
        if pct <= 0:
            if int(mid) in cache:
                pct = int(cache.get(int(mid), 0) or 0)
            else:
                if bool(fetch_missing):
                    fetched_pct = _fetch_arena_speed_lead_pct_for_com2us_id(int(mid))
                    cache[int(mid)] = int(fetched_pct)
                    cache_changed = True
                    pct = int(fetched_pct)
        if pct > 0:
            out[int(uid)] = int(pct)
    if cache_changed:
        _save_arena_speed_lead_cache(cache_path, cache)
    return out


def _arena_archetype_by_uid(
    window,
    unit_ids: List[int],
    fetch_missing: bool = True,
) -> Dict[int, str]:
    out: Dict[int, str] = {}
    if not window.account:
        return out
    cache_path = _arena_archetype_cache_path(window)
    cache = _load_arena_archetype_cache(cache_path)
    cache_changed = False
    for uid in [int(x) for x in (unit_ids or []) if int(x) > 0]:
        unit = window.account.units_by_id.get(int(uid))
        if unit is None:
            continue
        mid = int(unit.unit_master_id or 0)
        if mid <= 0:
            continue
        archetype = str(window.monster_db.archetype_for(int(mid)) or "").strip()
        if not archetype or archetype.lower() == "unknown":
            if int(mid) in cache:
                archetype = str(cache.get(int(mid), "") or "").strip()
            else:
                if bool(fetch_missing):
                    fetched = _fetch_archetype_for_com2us_id(int(mid))
                    if fetched:
                        cache[int(mid)] = str(fetched)
                        cache_changed = True
                        archetype = str(fetched)
        if archetype:
            out[int(uid)] = str(archetype)
    if cache_changed:
        _save_arena_archetype_cache(cache_path, cache)
    return out


def on_validate_arena_rush(window) -> None:
    if not window.account:
        return
    ok, msg, _defense, _offense = _validate_arena_rush(window)
    window.lbl_arena_rush_validate.setText(msg)
    if not ok:
        QMessageBox.critical(window, tr("val.title_arena"), msg)
        return
    QMessageBox.information(window, tr("val.title_arena_ok"), msg)


def on_edit_presets_arena_rush(window) -> None:
    if not window.account:
        return
    ok, msg, defense_ids, offense_teams = _validate_arena_rush(window)
    if not ok:
        QMessageBox.critical(window, tr("val.title_arena"), tr("dlg.validate_first", msg=msg))
        return
    all_ids: List[int] = []
    all_ids.extend(defense_ids)
    for sel in offense_teams:
        all_ids.extend(sel.unit_ids)
    seen: Set[int] = set()
    unit_rows: List[Tuple[int, str]] = []
    for uid in all_ids:
        if int(uid) in seen:
            continue
        seen.add(int(uid))
        unit_rows.append((int(uid), window._unit_text(int(uid))))
    order_teams: List[List[Tuple[int, str]]] = [
        [(int(uid), window._unit_text(int(uid))) for uid in defense_ids]
    ]
    order_team_titles: List[str] = [tr("label.arena_defense")]
    for sel in offense_teams:
        order_teams.append([(int(uid), window._unit_text(int(uid))) for uid in sel.unit_ids])
        order_team_titles.append(tr("label.offense", n=int(sel.team_index) + 1))
    # Keep dialog opening fast: use local/cached data only, no blocking web fetches.
    speed_lead_pct_by_uid = _arena_speed_lead_pct_by_uid(
        window,
        all_ids,
        fetch_missing=False,
    )
    order_speed_leaders: List[int] = [int(getattr(window, "arena_def_speed_lead_uid", 0) or 0)]
    order_speed_lead_pct_by_team: List[int] = [int(getattr(window, "arena_def_speed_lead_pct", 0) or 0)]
    off_speed_state = dict(getattr(window, "arena_offense_speed_lead_uid_by_team", {}) or {})
    off_speed_pct_state = dict(getattr(window, "arena_offense_speed_lead_pct_by_team", {}) or {})
    for sel in offense_teams:
        order_speed_leaders.append(int(off_speed_state.get(int(sel.team_index), 0) or 0))
        order_speed_lead_pct_by_team.append(int(off_speed_pct_state.get(int(sel.team_index), 0) or 0))
    # Keep dialog opening fast: strictly local capability data, no web fetches.
    effect_caps_by_uid = _arena_effect_capabilities_by_unit(
        window,
        all_ids,
        fetch_missing=False,
        ensure_icons_for_dialog=False,
    )
    arena_effect_state = dict(getattr(window, "arena_offense_turn_effects", {}) or {})
    order_turn_effects: List[Dict[int, Dict[str, object]]] = [{}]
    for sel in offense_teams:
        raw_team_cfg = dict(arena_effect_state.get(int(sel.team_index), {}) or {})
        team_cfg: Dict[int, Dict[str, object]] = {}
        for uid in sel.unit_ids:
            cfg = dict(raw_team_cfg.get(int(uid), {}) or {})
            atb = float(cfg.get("atb_boost_pct", 0.0) or 0.0)
            spd = bool(cfg.get("applies_spd_buff", False))
            if spd or atb > 0.0:
                team_cfg[int(uid)] = {
                    "applies_spd_buff": bool(spd),
                    "atb_boost_pct": float(atb),
                    "include_caster": bool(cfg.get("include_caster", True)),
                }
        order_turn_effects.append(team_cfg)

    dlg = BuildDialog(
        window,
        tr("dlg.arena_builds"),
        unit_rows,
        window.presets,
        "arena_rush",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=4,
        show_order_sections=True,
        order_teams=order_teams,
        order_team_titles=order_team_titles,
        order_turn_effects=order_turn_effects,
        show_turn_effect_controls=True,
        order_turn_effect_capabilities=effect_caps_by_uid,
        show_speed_lead_controls=True,
        order_speed_leaders=order_speed_leaders,
        order_speed_lead_pct_by_unit=speed_lead_pct_by_uid,
        order_speed_lead_pct_by_team=order_speed_lead_pct_by_team,
        persist_order_fields=True,
        skill_icons_dir=str(window.assets_dir / "skills"),
    )
    if dlg.exec() == QDialog.Accepted:
        ordered_teams = dlg.team_order_by_lists()
        speed_lead_teams = dlg.team_speed_lead_by_lists()
        speed_lead_pct_teams = dlg.team_speed_lead_pct_by_lists()
        effect_teams = dlg.team_turn_effects_by_lists()
        try:
            dlg.apply_to_store()
        except ValueError as exc:
            QMessageBox.critical(window, "Builds", str(exc))
            return
        _store_compare_snapshot_from_build_dialog(window, "arena_rush", dlg)
        if ordered_teams:
            defense_order = ordered_teams[0] if len(ordered_teams) > 0 else []
            for idx, cmb in enumerate(window.arena_def_combos):
                uid = int(defense_order[idx]) if idx < len(defense_order) else 0
                _set_unit_combo_uid_safely(cmb, uid)
            for off_idx, sel in enumerate(offense_teams):
                source_idx = int(off_idx + 1)
                if source_idx >= len(ordered_teams):
                    break
                row_idx = int(sel.team_index)
                if row_idx < 0 or row_idx >= len(window.arena_offense_team_combos):
                    continue
                row_order = ordered_teams[source_idx]
                row = window.arena_offense_team_combos[row_idx]
                for slot_idx, cmb in enumerate(row):
                    uid = int(row_order[slot_idx]) if slot_idx < len(row_order) else 0
                    _set_unit_combo_uid_safely(cmb, uid)
        if speed_lead_teams:
            window.arena_def_speed_lead_uid = int(speed_lead_teams[0] or 0)
            window.arena_def_speed_lead_pct = int(speed_lead_pct_teams[0] or 0) if speed_lead_pct_teams else 0
            new_speed_state: Dict[int, int] = {}
            new_speed_pct_state: Dict[int, int] = {}
            for off_idx, sel in enumerate(offense_teams):
                source_idx = int(off_idx + 1)
                if source_idx >= len(speed_lead_teams):
                    continue
                lead_uid = int(speed_lead_teams[source_idx] or 0)
                lead_pct = int(speed_lead_pct_teams[source_idx] or 0) if source_idx < len(speed_lead_pct_teams) else 0
                if lead_uid > 0:
                    new_speed_state[int(sel.team_index)] = int(lead_uid)
                if lead_pct > 0:
                    new_speed_pct_state[int(sel.team_index)] = int(lead_pct)
            window.arena_offense_speed_lead_uid_by_team = new_speed_state
            window.arena_offense_speed_lead_pct_by_team = new_speed_pct_state
        new_effect_state: Dict[int, Dict[int, Dict[str, object]]] = {}
        for off_idx, sel in enumerate(offense_teams):
            source_idx = int(off_idx + 1)
            if source_idx >= len(effect_teams):
                continue
            src_cfg = dict(effect_teams[source_idx] or {})
            team_cfg: Dict[int, Dict[str, object]] = {}
            for uid, cfg in src_cfg.items():
                ui = int(uid or 0)
                if ui <= 0:
                    continue
                atb = float((cfg or {}).get("atb_boost_pct", 0.0) or 0.0)
                spd = bool((cfg or {}).get("applies_spd_buff", False))
                if not spd and atb <= 0.0:
                    continue
                team_cfg[ui] = {
                    "applies_spd_buff": bool(spd),
                    "atb_boost_pct": float(atb),
                    "include_caster": bool((cfg or {}).get("include_caster", True)),
                }
            if team_cfg:
                new_effect_state[int(sel.team_index)] = team_cfg
        window.arena_offense_turn_effects = new_effect_state
        save_arena_rush_ui_state(window)
        window.presets.save(window.presets_path)
        QMessageBox.information(window, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=window.presets_path))


def _arena_speed_leader_bonus_map(
    window,
    team_unit_ids: List[int],
    leader_uid: int = 0,
    lead_pct_override: int = 0,
) -> Dict[int, int]:
    out: Dict[int, int] = {}
    ids = [int(uid) for uid in (team_unit_ids or []) if int(uid) > 0]
    if not ids or not window.account:
        return out
    candidate_leader_uid = int(leader_uid or 0)
    if candidate_leader_uid <= 0 or candidate_leader_uid not in ids:
        candidate_leader_uid = int(ids[0])
    pct = int(lead_pct_override or 0)
    if pct <= 0:
        leader = window.account.units_by_id.get(int(candidate_leader_uid))
        if leader is None:
            return out
        ls = window.monster_db.leader_skill_for(int(leader.unit_master_id))
        if not ls or str(ls.stat) != "SPD%" or str(ls.area) not in ("Arena", "General"):
            return out
        pct = int(ls.amount or 0)
    if pct <= 0:
        return out
    for uid in ids:
        u = window.account.units_by_id.get(int(uid))
        if u is None:
            continue
        out[int(uid)] = int(int(u.base_spd or 0) * pct / 100)
    return out


def on_optimize_arena_rush(window) -> None:
    if not window.account:
        return
    ok, msg, defense_ids, offense_teams = _validate_arena_rush(window)
    if not ok:
        QMessageBox.critical(window, tr("val.title_arena"), tr("dlg.validate_first", msg=msg))
        return

    pass_count = int(window.spin_multi_pass_arena_rush.value())
    quality_profile = str(window.combo_quality_profile_arena_rush.currentData() or "balanced")
    workers = window._effective_workers(quality_profile, window.combo_workers_arena_rush)
    running_text = tr("result.opt_running", mode=tr("arena_rush.mode"))
    window.lbl_arena_rush_validate.setText(running_text)
    window.statusBar().showMessage(running_text)

    defense_turn_order = {int(uid): idx + 1 for idx, uid in enumerate(defense_ids)}
    defense_lead_uid = int(getattr(window, "arena_def_speed_lead_uid", 0) or 0)
    defense_lead_pct = int(getattr(window, "arena_def_speed_lead_pct", 0) or 0)
    defense_leader_bonus = _arena_speed_leader_bonus_map(
        window, defense_ids, leader_uid=defense_lead_uid, lead_pct_override=defense_lead_pct
    )
    arena_effect_state = dict(getattr(window, "arena_offense_turn_effects", {}) or {})
    offense_speed_lead_state = dict(getattr(window, "arena_offense_speed_lead_uid_by_team", {}) or {})
    offense_speed_lead_pct_state = dict(getattr(window, "arena_offense_speed_lead_pct_by_team", {}) or {})
    offense_payload: List[ArenaRushOffenseTeam] = []
    offense_payload_debug: List[Dict[str, object]] = []
    for sel in offense_teams:
        ids = [int(uid) for uid in (sel.unit_ids or []) if int(uid) > 0]
        turn_by_uid: Dict[int, int] = {int(uid): int(pos + 1) for pos, uid in enumerate(ids)}
        expected_order = list(ids)
        team_effects: Dict[int, OpeningTurnEffect] = {}
        raw_team_cfg = dict(arena_effect_state.get(int(sel.team_index), {}) or {})
        for uid in ids:
            cfg = dict(raw_team_cfg.get(int(uid), {}) or {})
            atb = float(cfg.get("atb_boost_pct", 0.0) or 0.0)
            spd = bool(cfg.get("applies_spd_buff", False))
            include_caster = bool(cfg.get("include_caster", True))
            if spd or atb > 0.0:
                team_effects[int(uid)] = OpeningTurnEffect(
                    atb_boost_pct=float(atb),
                    applies_spd_buff=bool(spd),
                    include_caster=bool(include_caster),
                )
        lead_uid = int(offense_speed_lead_state.get(int(sel.team_index), 0) or 0)
        lead_pct = int(offense_speed_lead_pct_state.get(int(sel.team_index), 0) or 0)
        offense_payload.append(
            ArenaRushOffenseTeam(
                unit_ids=ids,
                expected_opening_order=expected_order,
                unit_turn_order=turn_by_uid,
                unit_spd_leader_bonus_flat=_arena_speed_leader_bonus_map(
                    window, ids, leader_uid=lead_uid, lead_pct_override=lead_pct
                ),
                turn_effects_by_unit=team_effects,
            )
        )
        offense_payload_debug.append(
            {
                "team_index": int(sel.team_index),
                "unit_ids": [int(uid) for uid in ids],
                "turn_effects_by_unit": {
                    int(uid): {
                        "applies_spd_buff": bool(getattr(effect, "applies_spd_buff", False)),
                        "atb_boost_pct": float(getattr(effect, "atb_boost_pct", 0.0) or 0.0),
                        "include_caster": bool(getattr(effect, "include_caster", True)),
                    }
                    for uid, effect in dict(team_effects or {}).items()
                },
            }
        )
    window._arena_rush_last_offense_payload = offense_payload_debug
    all_selected_uids: List[int] = list(defense_ids)
    for row in offense_payload:
        all_selected_uids.extend([int(uid) for uid in (row.unit_ids or []) if int(uid) > 0])
    baseline_runes_by_unit, baseline_arts_by_unit = _baseline_assignments_for_mode(
        window, "arena_rush", all_selected_uids
    )
    unit_archetype_by_uid = _arena_archetype_by_uid(
        window,
        all_selected_uids,
        fetch_missing=_allow_online_metadata_fetch(window),
    )

    def _run_arena_rush(
        is_cancelled,
        register_solver,
        progress_cb,
    ):
        arena_req = ArenaRushRequest(
            mode="arena_rush",
            defense_unit_ids=list(defense_ids),
            defense_unit_team_turn_order=defense_turn_order,
            defense_unit_spd_leader_bonus_flat=defense_leader_bonus,
            unit_archetype_by_uid=dict(unit_archetype_by_uid),
            unit_baseline_runes_by_slot=dict(baseline_runes_by_unit),
            unit_baseline_artifacts_by_type=dict(baseline_arts_by_unit),
            baseline_regression_guard_weight=(
                int(BASELINE_REGRESSION_GUARD_WEIGHT)
                if (baseline_runes_by_unit or baseline_arts_by_unit)
                else 0
            ),
            offense_teams=offense_payload,
            workers=workers,
            time_limit_per_unit_s=5.0,
            defense_pass_count=1,
            offense_pass_count=max(1, int(pass_count)),
            defense_quality_profile="max_quality",
            offense_quality_profile=quality_profile,
            progress_callback=progress_cb,
            is_cancelled=is_cancelled,
            register_solver=register_solver,
        )
        return optimize_arena_rush(window.account, window.presets, arena_req)

    res = window._run_with_busy_progress(
        running_text,
        _run_arena_rush,
    )

    window.lbl_arena_rush_validate.setText(res.message)
    window.statusBar().showMessage(res.message, 7000)
    window.arena_rush_result_cards.setVisible(False)

    combined_results = list(res.defense.results)
    teams_for_save: List[List[int]] = [list(defense_ids)]
    team_headers: Dict[int, str] = {0: tr("label.arena_defense")}
    for idx, off in enumerate(res.offenses, start=1):
        combined_results.extend(off.optimization.results)
        teams_for_save.append(list(off.team_unit_ids or []))
        team_headers[int(idx)] = tr("label.arena_offense", n=int(off.team_index) + 1)

    window._show_optimize_results(
        tr("arena_rush.mode"),
        res.message,
        combined_results,
        mode="arena_rush",
        teams=teams_for_save,
        team_header_by_index=team_headers,
        group_size=4,
    )
