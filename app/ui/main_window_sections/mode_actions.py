from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Set, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QListWidgetItem, QMessageBox

from app.domain.presets import Build
from app.engine.greedy_optimizer import GreedyRequest, optimize_greedy
from app.i18n import tr
from app.ui.dialogs.build_dialog import BuildDialog


@dataclass
class TeamSelection:
    team_index: int
    unit_ids: List[int]


def save_arena_rush_ui_state(window) -> None:
    from app.ui.main_window_sections.arena_rush_actions import save_arena_rush_ui_state as _impl
    return _impl(window)


def restore_arena_rush_ui_state(window) -> None:
    from app.ui.main_window_sections.arena_rush_actions import restore_arena_rush_ui_state as _impl
    return _impl(window)


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
    from app.ui.main_window_sections.arena_rush_actions import collect_arena_def_selection as _impl
    return _impl(window)


def collect_arena_offense_selections(window) -> List[TeamSelection]:
    from app.ui.main_window_sections.arena_rush_actions import collect_arena_offense_selections as _impl
    return _impl(window)


def on_take_current_arena_def(window) -> None:
    from app.ui.main_window_sections.arena_rush_actions import on_take_current_arena_def as _impl
    return _impl(window)


def on_take_current_arena_off(window) -> None:
    from app.ui.main_window_sections.arena_rush_actions import on_take_current_arena_off as _impl
    return _impl(window)


def _validate_arena_rush(window) -> Tuple[bool, str, List[int], List[TeamSelection]]:
    from app.ui.main_window_sections.arena_rush_actions import _validate_arena_rush as _impl
    return _impl(window)


def on_validate_arena_rush(window) -> None:
    from app.ui.main_window_sections.arena_rush_actions import on_validate_arena_rush as _impl
    return _impl(window)


def on_edit_presets_arena_rush(window) -> None:
    from app.ui.main_window_sections.arena_rush_actions import on_edit_presets_arena_rush as _impl
    return _impl(window)


def _arena_speed_leader_bonus_map(
    window,
    team_unit_ids: List[int],
    leader_uid: int = 0,
    lead_pct_override: int = 0,
) -> Dict[int, int]:
    from app.ui.main_window_sections.arena_rush_actions import _arena_speed_leader_bonus_map as _impl
    return _impl(window, team_unit_ids, leader_uid=leader_uid, lead_pct_override=lead_pct_override)


def on_optimize_arena_rush(window) -> None:
    from app.ui.main_window_sections.arena_rush_actions import on_optimize_arena_rush as _impl
    return _impl(window)
