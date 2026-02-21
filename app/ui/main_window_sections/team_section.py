from __future__ import annotations

from typing import Dict, List

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from app.domain.presets import Build
from app.engine.greedy_optimizer import (
    BASELINE_REGRESSION_GUARD_WEIGHT,
    GreedyRequest,
    optimize_greedy,
)
from app.i18n import tr
from app.ui.dialogs.team_editor_dialog import TeamEditorDialog


def _baseline_assignments_for_mode(window, mode: str, unit_ids: List[int]) -> tuple[Dict[int, Dict[int, int]], Dict[int, Dict[int, int]]]:
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


def _team_has_spd_buff_by_uid(window, teams: List[List[int]]) -> Dict[int, bool]:
    out: Dict[int, bool] = {}
    mdb = getattr(window, "monster_db", None)
    account = getattr(window, "account", None)
    if mdb is None or account is None:
        return out
    units_by_id = dict(getattr(account, "units_by_id", {}) or {})
    for team in (teams or []):
        ids = [int(uid) for uid in (team or []) if int(uid or 0) > 0]
        if not ids:
            continue
        has_spd = False
        for uid in ids:
            unit = units_by_id.get(int(uid))
            if unit is None:
                continue
            master_id = int(getattr(unit, "unit_master_id", 0) or 0)
            if master_id <= 0:
                continue
            cap = dict(mdb.turn_effect_capability_for(int(master_id)) or {})
            if bool(cap.get("has_spd_buff", False)):
                has_spd = True
                break
        for uid in ids:
            out[int(uid)] = bool(has_spd)
    return out


def init_team_tab_ui(window) -> None:
    layout = QVBoxLayout(window.tab_team_builder)

    row = QHBoxLayout()
    window.lbl_team = QLabel(tr("label.team"))
    row.addWidget(window.lbl_team)
    window.team_combo = QComboBox()
    window.team_combo.currentIndexChanged.connect(window._on_team_selected)
    row.addWidget(window.team_combo, 1)
    layout.addLayout(row)

    btn_row = QHBoxLayout()
    window.btn_new_team = QPushButton(tr("btn.new_team"))
    window.btn_new_team.clicked.connect(window._on_new_team)
    btn_row.addWidget(window.btn_new_team)
    window.btn_edit_team = QPushButton(tr("btn.edit_team"))
    window.btn_edit_team.clicked.connect(window._on_edit_team)
    btn_row.addWidget(window.btn_edit_team)
    window.btn_remove_team = QPushButton(tr("btn.delete_team"))
    window.btn_remove_team.clicked.connect(window._on_remove_team)
    btn_row.addWidget(window.btn_remove_team)
    layout.addLayout(btn_row)

    window.btn_optimize_team = QPushButton(tr("btn.optimize_team"))
    window.btn_optimize_team.clicked.connect(window._optimize_team)
    layout.addWidget(window.btn_optimize_team)

    pass_row = QHBoxLayout()
    window.lbl_team_passes = QLabel(tr("label.passes"))
    pass_row.addWidget(window.lbl_team_passes)
    window.spin_multi_pass_team = QSpinBox()
    window.spin_multi_pass_team.setRange(1, 10)
    window.spin_multi_pass_team.setValue(3)
    window.spin_multi_pass_team.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_team.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    pass_row.addWidget(window.spin_multi_pass_team)
    window.lbl_team_workers = QLabel(tr("label.workers"))
    pass_row.addWidget(window.lbl_team_workers)
    window.combo_workers_team = QComboBox()
    window._populate_worker_combo(window.combo_workers_team)
    pass_row.addWidget(window.combo_workers_team)
    window.lbl_team_profile = QLabel("Profil")
    pass_row.addWidget(window.lbl_team_profile)
    window.combo_quality_profile_team = QComboBox()
    window.combo_quality_profile_team.addItem("Fast", "fast")
    window.combo_quality_profile_team.addItem("Balanced", "balanced")
    window.combo_quality_profile_team.addItem("Max Qualität", "max_quality")
    if window._gpu_search_available():
        window.combo_quality_profile_team.addItem("GPU Fast", "gpu_search_fast")
        window.combo_quality_profile_team.addItem("GPU Balanced", "gpu_search_balanced")
        window.combo_quality_profile_team.addItem("GPU Max", "gpu_search_max")
    window.combo_quality_profile_team.setCurrentIndex(1)
    window.combo_quality_profile_team.currentIndexChanged.connect(window._sync_worker_controls)
    pass_row.addWidget(window.combo_quality_profile_team)
    window._sync_worker_controls()
    pass_row.addStretch(1)
    layout.addLayout(pass_row)

    window.lbl_team_opt_status = QLabel("—")
    layout.addWidget(window.lbl_team_opt_status)

    window.lbl_team_units = QLabel(tr("label.import_account_first"))
    layout.addWidget(window.lbl_team_units)

    window._refresh_team_combo()
    window._set_team_controls_enabled(False)


def current_team(window):
    tid = str(window.team_combo.currentData() or "")
    if not tid:
        return None
    return window.team_store.teams.get(tid)


def refresh_team_combo(window) -> None:
    current_id = str(window.team_combo.currentData() or "")
    window.team_combo.blockSignals(True)
    window.team_combo.clear()
    teams = sorted(window.team_store.teams.values(), key=lambda t: t.name)
    for team in teams:
        window.team_combo.addItem(f"{team.name} ({len(team.unit_ids)} {tr('label.units')})", team.id)
    window.team_combo.blockSignals(False)
    if not teams:
        window.lbl_team_units.setText(tr("label.no_teams"))
        window._set_team_controls_enabled(False)
        return
    window._select_team_by_id(current_id or teams[0].id)
    window._on_team_selected()


def select_team_by_id(window, tid: str) -> None:
    idx = window.team_combo.findData(tid)
    if idx >= 0:
        window.team_combo.setCurrentIndex(idx)


def set_team_controls_enabled(window, has_account: bool) -> None:
    team_exists = window._current_team() is not None
    window.btn_new_team.setEnabled(has_account)
    window.btn_edit_team.setEnabled(has_account and team_exists)
    window.btn_remove_team.setEnabled(has_account and team_exists)
    window.btn_optimize_team.setEnabled(has_account and team_exists)
    window.team_combo.setEnabled(bool(window.team_store.teams))


def on_team_selected(window) -> None:
    team = window._current_team()
    if not team:
        if not window.team_store.teams:
            window.lbl_team_units.setText(tr("label.no_teams"))
        else:
            window.lbl_team_units.setText(tr("label.no_team_selected"))
        window._set_team_controls_enabled(bool(window.account))
        return
    window.lbl_team_units.setText(window._team_units_text(team))
    window._set_team_controls_enabled(bool(window.account))
    if not window.account:
        return


def team_units_text(window, team) -> str:
    if not team.unit_ids:
        return tr("label.no_units")
    return "\n".join(window._unit_text_cached(uid) for uid in team.unit_ids)


def on_new_team(window) -> None:
    if not window.account:
        QMessageBox.warning(window, tr("label.team"), tr("dlg.load_import_first"))
        return
    dlg = TeamEditorDialog(
        window,
        window.account,
        window._unit_text_cached,
        window._icon_for_master_id,
        unit_combo_model=window._ensure_unit_combo_model(),
    )
    if dlg.exec() != QDialog.Accepted:
        return
    try:
        team = window.team_store.upsert(dlg.team_name or "Team", dlg.unit_ids)
    except ValueError as exc:
        QMessageBox.warning(window, tr("label.team"), str(exc))
        return
    window.team_store.save(window.team_config_path)
    window._refresh_team_combo()
    window._select_team_by_id(team.id)


def on_edit_team(window) -> None:
    if not window.account:
        QMessageBox.warning(window, tr("label.team"), tr("dlg.load_import_first"))
        return
    team = window._current_team()
    if not team:
        return
    dlg = TeamEditorDialog(
        window,
        window.account,
        window._unit_text_cached,
        window._icon_for_master_id,
        team=team,
        unit_combo_model=window._ensure_unit_combo_model(),
    )
    if dlg.exec() != QDialog.Accepted:
        return
    try:
        window.team_store.upsert(dlg.team_name or team.name, dlg.unit_ids, tid=team.id)
    except ValueError as exc:
        QMessageBox.warning(window, tr("label.team"), str(exc))
        return
    window.team_store.save(window.team_config_path)
    window._refresh_team_combo()
    window._select_team_by_id(team.id)


def on_remove_team(window) -> None:
    team = window._current_team()
    if not team:
        return
    window.team_store.remove(team.id)
    window.team_store.save(window.team_config_path)
    window._refresh_team_combo()


def optimize_team(window) -> None:
    team = window._current_team()
    if not window.account or not team:
        QMessageBox.warning(window, tr("label.team"), tr("dlg.load_import_and_team"))
        return
    quality_profile = str(window.combo_quality_profile_team.currentData() or "balanced")
    pass_count = int(window.spin_multi_pass_team.value())
    if str(quality_profile or "").strip().lower() in ("max_quality", "ultra_quality", "gpu_search_max"):
        pass_count = 1
    workers = window._effective_workers(quality_profile, window.combo_workers_team)
    running_text = tr("result.team_opt_running", name=team.name)
    window.lbl_team_opt_status.setText(running_text)
    window.statusBar().showMessage(running_text)
    ordered_unit_ids = window._units_by_turn_order("siege", team.unit_ids)
    team_idx_by_uid: Dict[int, int] = {int(uid): 0 for uid in team.unit_ids}
    leader_spd_bonus_by_uid = window._leader_spd_bonus_map([team.unit_ids])
    team_turn_by_uid: Dict[int, int] = {}
    for uid in team.unit_ids:
        builds = window.presets.get_unit_builds("siege", int(uid))
        b0 = builds[0] if builds else Build.default_any()
        team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
    baseline_runes_by_unit, baseline_arts_by_unit = _baseline_assignments_for_mode(
        window, "siege", ordered_unit_ids
    )
    from app.ui.main_window_sections.arena_rush_actions import (
        optimizer_archetype_by_uid,
        optimizer_artifact_hints_by_uid,
    )
    unit_archetype_by_uid = optimizer_archetype_by_uid(window, ordered_unit_ids)
    unit_artifact_hints_by_uid = optimizer_artifact_hints_by_uid(window, ordered_unit_ids)
    team_spd_buff_by_uid = _team_has_spd_buff_by_uid(window, [team.unit_ids])
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
                unit_archetype_by_uid=dict(unit_archetype_by_uid),
                unit_artifact_hints_by_uid=dict(unit_artifact_hints_by_uid),
                unit_team_has_spd_buff_by_uid=dict(team_spd_buff_by_uid),
                unit_baseline_runes_by_slot=(baseline_runes_by_unit or None),
                unit_baseline_artifacts_by_type=(baseline_arts_by_unit or None),
                baseline_regression_guard_weight=(
                    int(BASELINE_REGRESSION_GUARD_WEIGHT)
                    if (baseline_runes_by_unit or baseline_arts_by_unit)
                    else 0
                ),
            ),
        ),
    )
    window.lbl_team_opt_status.setText(res.message)
    window.statusBar().showMessage(res.message, 7000)
    window._show_optimize_results(
        tr("result.title_team", name=team.name),
        res.message,
        res.results,
        mode="siege",
        teams=[team.unit_ids],
    )


def ensure_siege_team_defaults(window) -> None:
    if not window.account:
        return
    existing_names = {team.name for team in window.team_store.teams.values()}
    added = False
    for idx, units in enumerate(window.account.siege_def_teams(), start=1):
        if not units:
            continue
        name = tr("label.defense", n=idx)
        legacy_name = f"Siege Verteidigung {idx}"
        if name in existing_names or legacy_name in existing_names:
            continue
        try:
            window.team_store.upsert(name, units)
        except ValueError:
            continue
        existing_names.add(name)
        added = True
    if added:
        window.team_store.save(window.team_config_path)
