from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QListWidgetItem, QMessageBox

from app.domain.presets import Build
from app.domain.optimization_store import SavedUnitResult
from app.engine.greedy_optimizer import GreedyRequest, optimize_greedy
from app.engine.arena_rush_optimizer import (
    ArenaRushOffenseTeam,
    ArenaRushRequest,
    optimize_arena_rush,
)
from app.engine.arena_rush_timing import OpeningTurnEffect
from app.i18n import tr
from app.services.monster_turn_effects_service import ensure_skill_icons, resolve_turn_effect_capabilities
from app.ui.dialogs.build_dialog import BuildDialog


@dataclass
class TeamSelection:
    team_index: int
    unit_ids: List[int]


def on_take_current_siege(window) -> None:
    if not window.account:
        return
    teams = window.account.siege_def_teams()
    for t in range(min(len(teams), len(window.siege_team_combos))):
        team = teams[t]
        for s in range(min(3, len(team))):
            uid = team[s]
            cmb = window.siege_team_combos[t][s]
            idx = cmb.findData(uid)
            cmb.setCurrentIndex(idx if idx >= 0 else 0)
    window.lbl_siege_validate.setText(tr("status.siege_taken"))


def collect_siege_selections(window) -> List[TeamSelection]:
    window._ensure_unit_dropdowns_populated()
    selections: List[TeamSelection] = []
    for t, row in enumerate(window.siege_team_combos):
        ids = []
        for cmb in row:
            uid = int(cmb.currentData() or 0)
            if uid != 0:
                ids.append(uid)
        selections.append(TeamSelection(team_index=t, unit_ids=ids))
    return selections


def validate_team_structure(window, label: str, selections: List[TeamSelection], must_have_team_size: int) -> Tuple[bool, str, List[int]]:
    all_units: List[int] = []
    for sel in selections:
        if not sel.unit_ids:
            continue
        if len(sel.unit_ids) != must_have_team_size:
            return False, tr("val.incomplete_team", label=label, team=sel.team_index + 1, have=len(sel.unit_ids), need=must_have_team_size), []
        team_set: Set[int] = set()
        for uid in sel.unit_ids:
            if uid in team_set:
                name = window._unit_text(uid) if window.account else str(uid)
                return False, tr("val.duplicate_in_team", label=label, team=sel.team_index + 1, name=name), []
            team_set.add(uid)
        all_units.extend(sel.unit_ids)
    if not all_units:
        return False, tr("val.no_teams", label=label), []
    return True, tr("val.ok", label=label, count=len(all_units)), all_units


def on_validate_siege(window) -> None:
    if not window.account:
        return
    selections = window._collect_siege_selections()
    ok, msg, _all_units = window._validate_team_structure("Siege", selections, must_have_team_size=3)
    if not ok:
        window.lbl_siege_validate.setText(msg)
        QMessageBox.critical(window, tr("val.title_siege"), msg)
        return
    window.lbl_siege_validate.setText(msg)
    QMessageBox.information(window, tr("val.title_siege_ok"), msg)


def on_edit_presets_siege(window) -> None:
    if not window.account:
        return
    selections = window._collect_siege_selections()
    ok, msg, all_units = window._validate_team_structure("Siege", selections, must_have_team_size=3)
    if not ok:
        QMessageBox.critical(window, "Siege", tr("dlg.validate_first", msg=msg))
        return
    unit_rows: List[Tuple[int, str]] = [(uid, window._unit_text(uid)) for uid in all_units]
    dlg = BuildDialog(
        window,
        "Siege Builds",
        unit_rows,
        window.presets,
        "siege",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=3,
    )
    if dlg.exec() == QDialog.Accepted:
        try:
            dlg.apply_to_store()
        except ValueError as exc:
            QMessageBox.critical(window, "Builds", str(exc))
            return
        window.presets.save(window.presets_path)
        QMessageBox.information(window, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=window.presets_path))


def on_optimize_siege(window) -> None:
    if not window.account or window._siege_optimization_running:
        return
    window._siege_optimization_running = True
    window.btn_optimize_siege.setEnabled(False)
    try:
        pass_count = int(window.spin_multi_pass_siege.value())
        quality_profile = str(window.combo_quality_profile_siege.currentData() or "balanced")
        workers = window._effective_workers(quality_profile, window.combo_workers_siege)
        running_text = tr("result.opt_running", mode="Siege")
        window.lbl_siege_validate.setText(running_text)
        window.statusBar().showMessage(running_text)
        selections = window._collect_siege_selections()
        ok, msg, all_units = window._validate_team_structure("Siege", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(window, "Siege", tr("dlg.validate_first", msg=msg))
            return

        ordered_unit_ids = window._units_by_turn_order("siege", all_units)
        team_idx_by_uid: Dict[int, int] = {}
        for idx, sel in enumerate(selections):
            for uid in sel.unit_ids:
                team_idx_by_uid[int(uid)] = int(idx)
        leader_spd_bonus_by_uid = window._leader_spd_bonus_map([sel.unit_ids for sel in selections if sel.unit_ids])
        team_turn_by_uid: Dict[int, int] = {}
        for uid in all_units:
            builds = window.presets.get_unit_builds("siege", int(uid))
            b0 = builds[0] if builds else Build.default_any()
            team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
        res = window._run_with_busy_progress(
            running_text,
            lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
                window.account,
                window.presets,
                GreedyRequest(
                    mode="siege",
                    unit_ids_in_order=ordered_unit_ids,
                    time_limit_per_unit_s=5.0,
                    workers=workers,
                    multi_pass_enabled=bool(pass_count > 1),
                    multi_pass_count=pass_count,
                    multi_pass_strategy="greedy_refine",
                    quality_profile=quality_profile,
                    progress_callback=progress_cb,
                    is_cancelled=is_cancelled,
                    register_solver=register_solver,
                    enforce_turn_order=True,
                    unit_team_index=team_idx_by_uid,
                    unit_team_turn_order=team_turn_by_uid,
                    unit_spd_leader_bonus_flat=leader_spd_bonus_by_uid,
                ),
            ),
        )
        window.lbl_siege_validate.setText(res.message)
        window.statusBar().showMessage(res.message, 7000)
        unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(all_units)}
        siege_teams = [sel.unit_ids for sel in selections if sel.unit_ids]
        window._show_optimize_results(
            tr("result.title_siege"),
            res.message,
            res.results,
            unit_team_index=team_idx_by_uid,
            unit_display_order=unit_display_order,
            mode="siege",
            teams=siege_teams,
        )
    finally:
        window._siege_optimization_running = False
        window.btn_optimize_siege.setEnabled(bool(window.account))


def units_by_turn_order(window, mode: str, unit_ids: List[int]) -> List[int]:
    indexed: List[Tuple[int, int, int]] = []
    for pos, uid in enumerate(unit_ids):
        builds = window.presets.get_unit_builds(mode, int(uid))
        b0 = builds[0] if builds else Build.default_any()
        opt = int(getattr(b0, "optimize_order", 0) or 0)
        indexed.append((opt, pos, int(uid)))
    with_order = [x for x in indexed if x[0] > 0]
    without_order = [x for x in indexed if x[0] <= 0]
    with_order.sort(key=lambda t: (t[0], t[1]))
    without_order.sort(key=lambda t: t[1])
    return [uid for _, _, uid in (with_order + without_order)]


def units_by_turn_order_grouped(window, mode: str, unit_ids: List[int], group_size: int) -> List[int]:
    if group_size <= 0:
        return window._units_by_turn_order(mode, unit_ids)
    out: List[int] = []
    for i in range(0, len(unit_ids), group_size):
        group = unit_ids[i : i + group_size]
        out.extend(window._units_by_turn_order(mode, group))
    return out


def leader_spd_bonus_map(window, teams: List[List[int]]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    if not window.account:
        return out
    for team in teams:
        ids = [int(uid) for uid in (team or []) if int(uid) != 0]
        if not ids:
            continue
        for uid in ids:
            out[int(uid)] = int(window._unit_leader_bonus(int(uid), ids).get("SPD", 0) or 0)
    return out


def collect_wgb_selections(window) -> List[TeamSelection]:
    window._ensure_unit_dropdowns_populated()
    selections: List[TeamSelection] = []
    for t, row in enumerate(window.wgb_team_combos):
        ids = []
        for cmb in row:
            uid = int(cmb.currentData() or 0)
            if uid != 0:
                ids.append(uid)
        selections.append(TeamSelection(team_index=t, unit_ids=ids))
    return selections


def validate_unique_monsters(window, all_unit_ids: List[int]) -> Tuple[bool, str]:
    if not window.account:
        return False, tr("val.no_account")
    seen: Dict[int, str] = {}
    for uid in all_unit_ids:
        u = window.account.units_by_id.get(uid)
        if not u:
            continue
        mid = u.unit_master_id
        name = window.monster_db.name_for(mid)
        if mid in seen:
            return False, tr("val.duplicate_monster_wgb", name=name)
        seen[mid] = name
    return True, ""


def on_validate_wgb(window) -> None:
    if not window.account:
        return
    selections = window._collect_wgb_selections()
    ok, msg, all_units = window._validate_team_structure("WGB", selections, must_have_team_size=3)
    if not ok:
        window.lbl_wgb_validate.setText(msg)
        QMessageBox.critical(window, tr("val.title_wgb"), msg)
        return
    ok2, msg2 = window._validate_unique_monsters(all_units)
    if not ok2:
        window.lbl_wgb_validate.setText(msg2)
        QMessageBox.critical(window, tr("val.title_wgb"), msg2)
        return
    window.lbl_wgb_validate.setText(msg)
    QMessageBox.information(window, tr("val.title_wgb_ok"), msg)
    window._render_wgb_preview(selections)


def on_edit_presets_wgb(window) -> None:
    if not window.account:
        return
    selections = window._collect_wgb_selections()
    ok, msg, all_units = window._validate_team_structure("WGB", selections, must_have_team_size=3)
    if not ok:
        QMessageBox.critical(window, "WGB", tr("dlg.validate_first", msg=msg))
        return
    ok2, msg2 = window._validate_unique_monsters(all_units)
    if not ok2:
        QMessageBox.critical(window, "WGB", msg2)
        return

    unit_rows: List[Tuple[int, str]] = [(uid, window._unit_text(uid)) for uid in all_units]
    dlg = BuildDialog(
        window,
        "WGB Builds",
        unit_rows,
        window.presets,
        "wgb",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=3,
    )
    if dlg.exec() == QDialog.Accepted:
        try:
            dlg.apply_to_store()
        except ValueError as exc:
            QMessageBox.critical(window, "Builds", str(exc))
            return
        window.presets.save(window.presets_path)
        QMessageBox.information(window, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=window.presets_path))


def on_optimize_wgb(window) -> None:
    if not window.account:
        return
    pass_count = int(window.spin_multi_pass_wgb.value())
    quality_profile = str(window.combo_quality_profile_wgb.currentData() or "balanced")
    workers = window._effective_workers(quality_profile, window.combo_workers_wgb)
    running_text = tr("result.opt_running", mode="WGB")
    window.lbl_wgb_validate.setText(running_text)
    window.statusBar().showMessage(running_text)
    selections = window._collect_wgb_selections()
    ok, msg, all_units = window._validate_team_structure("WGB", selections, must_have_team_size=3)
    if not ok:
        QMessageBox.critical(window, "WGB", tr("dlg.validate_first", msg=msg))
        return
    ok2, msg2 = window._validate_unique_monsters(all_units)
    if not ok2:
        QMessageBox.critical(window, "WGB", msg2)
        return

    ordered_unit_ids = window._units_by_turn_order("wgb", all_units)
    team_idx_by_uid: Dict[int, int] = {}
    for idx, sel in enumerate(selections):
        for uid in sel.unit_ids:
            team_idx_by_uid[int(uid)] = int(idx)
    leader_spd_bonus_by_uid = window._leader_spd_bonus_map([sel.unit_ids for sel in selections if sel.unit_ids])
    team_turn_by_uid: Dict[int, int] = {}
    for uid in all_units:
        builds = window.presets.get_unit_builds("wgb", int(uid))
        b0 = builds[0] if builds else Build.default_any()
        team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
    res = window._run_with_busy_progress(
        running_text,
        lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
            window.account,
            window.presets,
            GreedyRequest(
                mode="wgb",
                unit_ids_in_order=ordered_unit_ids,
                time_limit_per_unit_s=5.0,
                workers=workers,
                multi_pass_enabled=bool(pass_count > 1),
                multi_pass_count=pass_count,
                multi_pass_strategy="greedy_refine",
                quality_profile=quality_profile,
                progress_callback=progress_cb,
                is_cancelled=is_cancelled,
                register_solver=register_solver,
                enforce_turn_order=True,
                unit_team_index=team_idx_by_uid,
                unit_team_turn_order=team_turn_by_uid,
                unit_spd_leader_bonus_flat=leader_spd_bonus_by_uid,
            ),
        ),
    )
    window.lbl_wgb_validate.setText(res.message)
    window.statusBar().showMessage(res.message, 7000)
    unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(all_units)}
    wgb_teams = [sel.unit_ids for sel in selections if sel.unit_ids]
    window._show_optimize_results(
        tr("result.title_wgb"),
        res.message,
        res.results,
        unit_team_index=team_idx_by_uid,
        unit_display_order=unit_display_order,
        mode="wgb",
        teams=wgb_teams,
    )


def render_wgb_preview(window, selections: List[TeamSelection] | None = None) -> None:
    if not window.account:
        return
    if selections is None:
        selections = window._collect_wgb_selections()
    teams = [sel.unit_ids for sel in selections if sel.unit_ids]
    window.wgb_preview_cards.render_from_selections(teams, window.account, window.monster_db, window.assets_dir, rune_mode="siege")


def on_rta_add_monster(window) -> None:
    window._ensure_unit_dropdowns_populated()
    uid = int(window.rta_add_combo.currentData() or 0)
    if uid == 0:
        return
    if window.rta_selected_list.count() >= 15:
        QMessageBox.warning(window, "RTA", tr("dlg.max_15_rta"))
        return
    for i in range(window.rta_selected_list.count()):
        if int(window.rta_selected_list.item(i).data(Qt.UserRole) or 0) == uid:
            return
    item = QListWidgetItem(window._unit_text(uid))
    item.setData(Qt.UserRole, uid)
    item.setIcon(window._unit_icon_for_unit_id(uid))
    window.rta_selected_list.addItem(item)
    window.rta_add_combo.setCurrentIndex(0)
    if hasattr(window.rta_add_combo, "_reset_search_field"):
        window.rta_add_combo._reset_search_field()


def on_rta_remove_monster(window) -> None:
    for item in list(window.rta_selected_list.selectedItems()):
        window.rta_selected_list.takeItem(window.rta_selected_list.row(item))


def on_take_current_rta(window) -> None:
    if not window.account:
        return
    active_uids = window.account.rta_active_unit_ids()
    window.rta_selected_list.clear()
    for uid in active_uids[:15]:
        item = QListWidgetItem(window._unit_text(uid))
        item.setData(Qt.UserRole, uid)
        item.setIcon(window._unit_icon_for_unit_id(uid))
        window.rta_selected_list.addItem(item)
    window.lbl_rta_validate.setText(tr("status.rta_taken", count=min(len(active_uids), 15)))


def collect_rta_unit_ids(window) -> List[int]:
    ids: List[int] = []
    for i in range(window.rta_selected_list.count()):
        uid = int(window.rta_selected_list.item(i).data(Qt.UserRole) or 0)
        if uid != 0:
            ids.append(uid)
    return ids


def on_validate_rta(window) -> None:
    if not window.account:
        return
    ids = window._collect_rta_unit_ids()
    if not ids:
        msg = tr("rta.no_monsters")
        window.lbl_rta_validate.setText(msg)
        QMessageBox.critical(window, tr("val.title_rta"), msg)
        return
    seen: Set[int] = set()
    for uid in ids:
        if uid in seen:
            name = window._unit_text(uid)
            msg = tr("rta.duplicate", name=name)
            window.lbl_rta_validate.setText(msg)
            QMessageBox.critical(window, tr("val.title_rta"), msg)
            return
        seen.add(uid)
    msg = tr("rta.ok", count=len(ids))
    window.lbl_rta_validate.setText(msg)
    QMessageBox.information(window, tr("val.title_rta_ok"), msg)


def on_edit_presets_rta(window) -> None:
    if not window.account:
        return
    ids = window._collect_rta_unit_ids()
    if not ids:
        QMessageBox.critical(window, "RTA", tr("dlg.select_monsters_first"))
        return
    if len(ids) != len(set(ids)):
        QMessageBox.critical(window, "RTA", tr("dlg.duplicates_found"))
        return
    unit_rows: List[Tuple[int, str]] = [(uid, window._unit_text(uid)) for uid in ids]
    dlg = BuildDialog(
        window,
        "RTA Builds",
        unit_rows,
        window.presets,
        "rta",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=len(ids),
        show_order_sections=False,
    )
    if dlg.exec() == QDialog.Accepted:
        try:
            dlg.apply_to_store()
        except ValueError as exc:
            QMessageBox.critical(window, "Builds", str(exc))
            return
        window.presets.save(window.presets_path)
        QMessageBox.information(window, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=window.presets_path))


def on_optimize_rta(window) -> None:
    if not window.account:
        return
    pass_count = int(window.spin_multi_pass_rta.value())
    quality_profile = str(window.combo_quality_profile_rta.currentData() or "balanced")
    workers = window._effective_workers(quality_profile, window.combo_workers_rta)
    running_text = tr("result.opt_running", mode="RTA")
    window.lbl_rta_validate.setText(running_text)
    window.statusBar().showMessage(running_text)
    ids = window._collect_rta_unit_ids()
    if not ids:
        QMessageBox.critical(window, "RTA", tr("dlg.select_monsters_first"))
        return
    if len(ids) != len(set(ids)):
        QMessageBox.critical(window, "RTA", tr("dlg.duplicates_found"))
        return

    team_idx_by_uid: Dict[int, int] = {int(uid): 0 for uid in ids}
    team_turn_by_uid: Dict[int, int] = {int(uid): pos + 1 for pos, uid in enumerate(ids)}
    res = window._run_with_busy_progress(
        running_text,
        lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
            window.account,
            window.presets,
            GreedyRequest(
                mode="rta",
                unit_ids_in_order=ids,
                time_limit_per_unit_s=5.0,
                workers=workers,
                multi_pass_enabled=bool(pass_count > 1),
                multi_pass_count=pass_count,
                multi_pass_strategy="greedy_refine",
                quality_profile=quality_profile,
                progress_callback=progress_cb,
                is_cancelled=is_cancelled,
                register_solver=register_solver,
                enforce_turn_order=True,
                unit_team_index=team_idx_by_uid,
                unit_team_turn_order=team_turn_by_uid,
                unit_spd_leader_bonus_flat={},
            ),
        ),
    )
    window.lbl_rta_validate.setText(res.message)
    window.statusBar().showMessage(res.message, 7000)
    unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(ids)}
    window._show_optimize_results(
        tr("result.title_rta"),
        res.message,
        res.results,
        unit_team_index=team_idx_by_uid,
        unit_display_order=unit_display_order,
        mode="rta",
        teams=[ids],
    )


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
    window.arena_offense_turn_effects = {}
    if len(all_decks) > len(decks):
        window.lbl_arena_rush_validate.setText(
            tr("status.arena_off_taken_limited", count=len(decks), total=len(all_decks))
        )
    else:
        window.lbl_arena_rush_validate.setText(tr("status.arena_off_taken", count=len(decks)))


def _validate_arena_rush(window) -> Tuple[bool, str, List[int], List[TeamSelection]]:
    defense_ids = window._collect_arena_def_selection()
    if len(defense_ids) != 4:
        return False, tr("val.arena_def_need_4", have=len(defense_ids)), [], []
    if len(set(defense_ids)) != 4:
        return False, tr("val.arena_def_duplicate"), [], []

    offense_teams_raw = window._collect_arena_offense_selections()
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


def _arena_effect_capabilities_by_unit(window, unit_ids: List[int]) -> Dict[int, Dict[str, object]]:
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
    cache_path = window.project_root / "app" / "config" / "monster_turn_effect_capabilities.json"
    com2us_ids = sorted(set(uid_to_mid.values()))
    caps_by_cid = resolve_turn_effect_capabilities(
        com2us_ids, cache_path=cache_path, fetch_missing=False,
    )
    skill_icons_dir = window.assets_dir / "skills"
    ensure_skill_icons(caps_by_cid, skill_icons_dir)
    out: Dict[int, Dict[str, object]] = {}
    for uid, mid in uid_to_mid.items():
        cap = dict(caps_by_cid.get(mid) or {})
        base = dict(window.monster_db.turn_effect_capability_for(mid) or {})
        base["spd_buff_skill_icon"] = str(cap.get("spd_buff_skill_icon", "") or "")
        base["atb_boost_skill_icon"] = str(cap.get("atb_boost_skill_icon", "") or "")
        out[int(uid)] = base
    return out


def on_validate_arena_rush(window) -> None:
    if not window.account:
        return
    ok, msg, _defense, _offense = window._validate_arena_rush()
    window.lbl_arena_rush_validate.setText(msg)
    if not ok:
        QMessageBox.critical(window, tr("val.title_arena"), msg)
        return
    QMessageBox.information(window, tr("val.title_arena_ok"), msg)


def on_edit_presets_arena_rush(window) -> None:
    if not window.account:
        return
    ok, msg, defense_ids, offense_teams = window._validate_arena_rush()
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
    effect_caps_by_uid = _arena_effect_capabilities_by_unit(window, all_ids)
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
        # Reuse siege presets for arena rush until a dedicated mode is introduced.
        "siege",
        window.account,
        window._unit_icon_for_unit_id,
        team_size=4,
        show_order_sections=True,
        order_teams=order_teams,
        order_team_titles=order_team_titles,
        order_turn_effects=order_turn_effects,
        show_turn_effect_controls=True,
        order_turn_effect_capabilities=effect_caps_by_uid,
        persist_order_fields=True,
        skill_icons_dir=str(window.assets_dir / "skills"),
    )
    if dlg.exec() == QDialog.Accepted:
        ordered_teams = dlg.team_order_by_lists()
        effect_teams = dlg.team_turn_effects_by_lists()
        try:
            dlg.apply_to_store()
        except ValueError as exc:
            QMessageBox.critical(window, "Builds", str(exc))
            return
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
        window.presets.save(window.presets_path)
        QMessageBox.information(window, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=window.presets_path))


def _arena_speed_leader_bonus_map(window, team_unit_ids: List[int]) -> Dict[int, int]:
    out: Dict[int, int] = {}
    ids = [int(uid) for uid in (team_unit_ids or []) if int(uid) > 0]
    if not ids or not window.account:
        return out
    leader_uid = int(ids[0])
    leader = window.account.units_by_id.get(int(leader_uid))
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
    ok, msg, defense_ids, offense_teams = window._validate_arena_rush()
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
    defense_leader_bonus = _arena_speed_leader_bonus_map(window, defense_ids)
    arena_effect_state = dict(getattr(window, "arena_offense_turn_effects", {}) or {})
    offense_payload: List[ArenaRushOffenseTeam] = []
    for sel in offense_teams:
        ids = [int(uid) for uid in (sel.unit_ids or []) if int(uid) > 0]
        # Arena Rush uses explicit per-team order from the UI rows (slot 1..4).
        # This avoids cross-team order drift when the same monster is reused.
        turn_by_uid: Dict[int, int] = {int(uid): int(pos + 1) for pos, uid in enumerate(ids)}
        expected_order = list(ids)
        raw_team_cfg = dict(arena_effect_state.get(int(sel.team_index), {}) or {})
        team_effects: Dict[int, OpeningTurnEffect] = {}
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
        offense_payload.append(
            ArenaRushOffenseTeam(
                unit_ids=ids,
                expected_opening_order=expected_order,
                unit_turn_order=turn_by_uid,
                unit_spd_leader_bonus_flat=_arena_speed_leader_bonus_map(window, ids),
                turn_effects_by_unit=team_effects,
            )
        )

    def _run_arena_rush(
        is_cancelled,
        register_solver,
        progress_cb,
    ):
        arena_req = ArenaRushRequest(
            mode="siege",
            defense_unit_ids=list(defense_ids),
            defense_unit_team_turn_order=defense_turn_order,
            defense_unit_spd_leader_bonus_flat=defense_leader_bonus,
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

    # Build rune/artifact overrides from optimization results and render card view.
    runes_by_id = {r.rune_id: r for r in window.account.runes}
    artifacts_by_id = {int(a.artifact_id): a for a in window.account.artifacts}
    rune_overrides = {}
    artifact_overrides = {}
    all_results = list(res.defense.results)
    for off in res.offenses:
        all_results.extend(off.optimization.results)
    for ur in all_results:
        runes = []
        for slot in sorted((ur.runes_by_slot or {}).keys()):
            rid = (ur.runes_by_slot or {})[slot]
            r = runes_by_id.get(rid)
            if r:
                runes.append(r)
        if runes:
            rune_overrides[int(ur.unit_id)] = runes
        arts = []
        for art_type in (1, 2):
            aid = int((ur.artifacts_by_type or {}).get(art_type, 0) or 0)
            a = artifacts_by_id.get(aid)
            if a:
                arts.append(a)
        if arts:
            artifact_overrides[int(ur.unit_id)] = arts
    teams_for_cards = [list(defense_ids)]
    team_titles = [tr("result.title_arena_def")]
    for off in res.offenses:
        teams_for_cards.append(list(off.team_unit_ids or []))
        team_titles.append(tr("result.title_arena_off", n=int(off.team_index) + 1))
    window.arena_rush_result_cards.render_from_selections(
        teams_for_cards,
        window.account,
        window.monster_db,
        window.assets_dir,
        rune_mode="siege",
        rune_overrides=rune_overrides,
        artifact_overrides=artifact_overrides,
        team_titles=team_titles,
    )

    saved_results: List[SavedUnitResult] = []
    for unit_res in all_results:
        if not bool(unit_res.ok):
            continue
        if not (unit_res.runes_by_slot or {}):
            continue
        saved_results.append(
            SavedUnitResult(
                unit_id=int(unit_res.unit_id),
                runes_by_slot=dict(unit_res.runes_by_slot or {}),
                artifacts_by_type=dict(unit_res.artifacts_by_type or {}),
                final_speed=int(unit_res.final_speed or 0),
            )
        )
    if saved_results:
        ts = datetime.now().strftime("%d.%m.%Y %H:%M")
        name = tr("result.opt_name", mode=tr("arena_rush.mode"), ts=ts)
        window.opt_store.upsert("arena_rush", name, teams_for_cards, saved_results)
        window.opt_store.save(window.opt_store_path)
        window._refresh_saved_opt_combo("arena_rush")
