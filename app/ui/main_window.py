from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List, Tuple, Set, Dict, Callable, Any

from PySide6.QtCore import Qt, QSize, QTimer, QThreadPool, QEventLoop
from PySide6.QtGui import QIcon, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel,
    QMessageBox, QTabWidget, QComboBox, QProgressDialog
)

from app.domain.models import AccountData, Rune, Artifact
from app.domain.monster_db import MonsterDB
from app.domain.presets import (
    BuildStore,
    SET_NAMES,
)
from app.engine.greedy_optimizer import GreedyUnitResult
from app.services.account_persistence import AccountPersistence
from app.domain.team_store import TeamStore, Team
from app.domain.optimization_store import OptimizationStore, SavedUnitResult
from app.ui.async_worker import _TaskWorker
from app.ui.dialogs.optimize_result_dialog import OptimizeResultDialog
from app.ui.license_flow import _apply_license_title, _ensure_license_accepted
from app.ui.main_window_sections.builders_and_saved import (
    init_saved_siege_tab as _sec_init_saved_siege_tab,
    init_saved_wgb_tab as _sec_init_saved_wgb_tab,
    init_saved_rta_tab as _sec_init_saved_rta_tab,
    init_saved_arena_rush_tab as _sec_init_saved_arena_rush_tab,
    saved_opt_widgets as _sec_saved_opt_widgets,
    refresh_saved_opt_combo as _sec_refresh_saved_opt_combo,
    on_saved_opt_changed as _sec_on_saved_opt_changed,
    on_delete_saved_opt as _sec_on_delete_saved_opt,
    new_unit_search_combo as _sec_new_unit_search_combo,
    init_siege_builder_ui as _sec_init_siege_builder_ui,
    init_wgb_builder_ui as _sec_init_wgb_builder_ui,
    init_rta_builder_ui as _sec_init_rta_builder_ui,
    init_arena_rush_builder_ui as _sec_init_arena_rush_builder_ui,
)
from app.ui.main_window_sections.mode_actions import (
    on_take_current_siege as _sec_on_take_current_siege,
    collect_siege_selections as _sec_collect_siege_selections,
    validate_team_structure as _sec_validate_team_structure,
    on_validate_siege as _sec_on_validate_siege,
    on_edit_presets_siege as _sec_on_edit_presets_siege,
    on_optimize_siege as _sec_on_optimize_siege,
    units_by_turn_order as _sec_units_by_turn_order,
    units_by_turn_order_grouped as _sec_units_by_turn_order_grouped,
    leader_spd_bonus_map as _sec_leader_spd_bonus_map,
    collect_wgb_selections as _sec_collect_wgb_selections,
    validate_unique_monsters as _sec_validate_unique_monsters,
    on_validate_wgb as _sec_on_validate_wgb,
    on_edit_presets_wgb as _sec_on_edit_presets_wgb,
    on_optimize_wgb as _sec_on_optimize_wgb,
    render_wgb_preview as _sec_render_wgb_preview,
    on_rta_add_monster as _sec_on_rta_add_monster,
    on_rta_remove_monster as _sec_on_rta_remove_monster,
    on_take_current_rta as _sec_on_take_current_rta,
    collect_rta_unit_ids as _sec_collect_rta_unit_ids,
    on_validate_rta as _sec_on_validate_rta,
    on_edit_presets_rta as _sec_on_edit_presets_rta,
    on_optimize_rta as _sec_on_optimize_rta,
    on_take_current_arena_def as _sec_on_take_current_arena_def,
    on_take_current_arena_off as _sec_on_take_current_arena_off,
    collect_arena_def_selection as _sec_collect_arena_def_selection,
    collect_arena_offense_selections as _sec_collect_arena_offense_selections,
    on_validate_arena_rush as _sec_on_validate_arena_rush,
    on_edit_presets_arena_rush as _sec_on_edit_presets_arena_rush,
    on_optimize_arena_rush as _sec_on_optimize_arena_rush,
    _validate_arena_rush as _sec_validate_arena_rush,
)
from app.ui.main_window_sections.team_section import (
    init_team_tab_ui as _sec_init_team_tab_ui,
    current_team as _sec_current_team,
    refresh_team_combo as _sec_refresh_team_combo,
    select_team_by_id as _sec_select_team_by_id,
    set_team_controls_enabled as _sec_set_team_controls_enabled,
    on_team_selected as _sec_on_team_selected,
    team_units_text as _sec_team_units_text,
    on_new_team as _sec_on_new_team,
    on_edit_team as _sec_on_edit_team,
    on_remove_team as _sec_on_remove_team,
    optimize_team as _sec_optimize_team,
    ensure_siege_team_defaults as _sec_ensure_siege_team_defaults,
)
from app.ui.main_window_sections.stats_helpers import (
    unit_base_stats as _sec_unit_base_stats,
    unit_leader_bonus as _sec_unit_leader_bonus,
    unit_totem_bonus as _sec_unit_totem_bonus,
    unit_final_spd_value as _sec_unit_final_spd_value,
    unit_final_stats_values as _sec_unit_final_stats_values,
    team_leader_skill as _sec_team_leader_skill,
    spd_from_stat_tuple as _sec_spd_from_stat_tuple,
    spd_from_substats as _sec_spd_from_substats,
)
from app.ui.main_window_sections.account_units_section import (
    on_import as _sec_on_import,
    apply_saved_account as _sec_apply_saved_account,
    try_restore_snapshot as _sec_try_restore_snapshot,
    icon_for_master_id as _sec_icon_for_master_id,
    rune_set_icon as _sec_rune_set_icon,
    unit_text as _sec_unit_text,
    unit_text_cached as _sec_unit_text_cached,
    populate_combo_with_units as _sec_populate_combo_with_units,
    build_unit_combo_model as _sec_build_unit_combo_model,
    ensure_unit_combo_model as _sec_ensure_unit_combo_model,
    populate_all_dropdowns as _sec_populate_all_dropdowns,
    tab_needs_unit_dropdowns as _sec_tab_needs_unit_dropdowns,
    on_tab_changed as _sec_on_tab_changed,
    ensure_unit_dropdowns_populated as _sec_ensure_unit_dropdowns_populated,
)
from app.ui.main_window_sections.presentation_section import (
    apply_tab_style as _sec_apply_tab_style,
    show_help_dialog as _sec_show_help_dialog,
    retranslate_ui as _sec_retranslate_ui,
)
from app.ui.main_window_sections.settings_section import (
    init_settings_ui as _sec_init_settings_ui,
    refresh_settings_import_status as _sec_refresh_settings_import_status,
    refresh_settings_license_status as _sec_refresh_settings_license_status,
    on_settings_import_json as _sec_on_settings_import_json,
    on_settings_clear_snapshot as _sec_on_settings_clear_snapshot,
    on_settings_activate_license as _sec_on_settings_activate_license,
    on_settings_reset_presets as _sec_on_settings_reset_presets,
    on_settings_clear_optimizations as _sec_on_settings_clear_optimizations,
    on_settings_clear_teams as _sec_on_settings_clear_teams,
    on_settings_check_update as _sec_on_settings_check_update,
    on_settings_language_changed as _sec_on_settings_language_changed,
    retranslate_settings as _sec_retranslate_settings,
)
from app.ui.theme import apply_dark_palette as _apply_dark_palette_impl
from app.ui.update_flow import _start_update_check
from app.ui.widgets.reorderable_tab_bar import ReorderableTabBar
from app.ui.widgets.selection_combos import _UnitSearchComboBox
from app.ui.siege_cards_widget import SiegeDefCardsWidget
from app.ui.overview_widget import OverviewWidget
from app.ui.rta_overview_widget import RtaOverviewWidget
from app.ui.rune_optimization_widget import RuneOptimizationWidget
from app.i18n import tr


DEFAULT_TAB_ORDER = [
    "tab_overview",
    "tab_siege_raw",
    "tab_rta_overview",
    "tab_rune_optimization",
    "tab_siege_builder",
    "tab_saved_siege",
    "tab_wgb_builder",
    "tab_saved_wgb",
    "tab_rta_builder",
    "tab_saved_rta",
    "tab_arena_rush_builder",
    "tab_saved_arena_rush",
    "tab_settings",
]


@dataclass
class TeamSelection:
    team_index: int
    unit_ids: List[int]


class MainWindow(QMainWindow):
    @staticmethod
    def _max_solver_workers() -> int:
        total = max(1, int(os.cpu_count() or 8))
        return max(1, int(total * 0.9))

    @staticmethod
    def _default_solver_workers() -> int:
        m = MainWindow._max_solver_workers()
        return max(1, min(m, m // 2 if m > 1 else 1))

    @staticmethod
    def _gpu_search_available() -> bool:
        try:
            import torch  # type: ignore

            return bool(torch.cuda.is_available())
        except Exception:
            return False

    def _populate_worker_combo(self, combo: QComboBox) -> None:
        combo.clear()
        max_w = self._max_solver_workers()
        for w in range(1, max_w + 1):
            combo.addItem(str(w), int(w))
        default_w = self._default_solver_workers()
        idx = combo.findData(int(default_w))
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.setToolTip(tr("tooltip.workers"))

    def _effective_workers(self, quality_profile: str, combo: QComboBox) -> int:
        prof = str(quality_profile or "").strip().lower()
        if prof in ("max_quality", "gpu_search_max"):
            return int(combo.currentData() or self._default_solver_workers())
        return int(self._default_solver_workers())

    def _sync_worker_controls(self) -> None:
        def _apply(profile_combo_attr: str, workers_combo_attr: str) -> None:
            prof = getattr(self, profile_combo_attr, None)
            workers = getattr(self, workers_combo_attr, None)
            if prof is None or workers is None:
                return
            is_max = str(prof.currentData() or "").strip().lower() in ("max_quality", "gpu_search_max")
            workers.setEnabled(bool(is_max))

        _apply("combo_quality_profile_siege", "combo_workers_siege")
        _apply("combo_quality_profile_wgb", "combo_workers_wgb")
        _apply("combo_quality_profile_rta", "combo_workers_rta")
        _apply("combo_quality_profile_arena_rush", "combo_workers_arena_rush")
        _apply("combo_quality_profile_team", "combo_workers_team")

    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("main.title"))
        self.setMinimumSize(1360, 820)
        self.showMaximized()

        self.account: Optional[AccountData] = None
        self._icon_cache: Dict[int, QIcon] = {}
        self._unit_combo_model: Optional[QStandardItemModel] = None
        self._unit_combo_index_by_uid: Dict[int, int] = {}
        self._unit_text_cache_by_uid: Dict[int, str] = {}
        self._siege_optimization_running = False

        # paths
        self.project_root = Path(__file__).resolve().parents[2]
        self.assets_dir = self.project_root / "app" / "assets"
        self.config_dir = self.project_root / "app" / "config"
        self.presets_path = self.config_dir / "build_presets.json"

        # Monster DB (offline)
        self.monster_db = MonsterDB(self.assets_dir / "monsters.json")
        self.monster_db.load()

        # Presets/Builds
        self.presets = BuildStore.load(self.presets_path)
        self.account_persistence = AccountPersistence()
        self.team_config_path = self.config_dir / "team_presets.json"
        self.team_store = TeamStore.load(self.team_config_path)

        self.opt_store_path = self.config_dir / "saved_optimizations.json"
        self.opt_store = OptimizationStore.load(self.opt_store_path)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        self.lbl_status = QLabel("")

        top = QHBoxLayout()
        top.addStretch(1)
        btn_help = QPushButton("?")
        btn_help.setFixedSize(32, 32)
        btn_help.setStyleSheet(
            "QPushButton { background: #2b2b2b; color: #ddd; border: 1px solid #3a3a3a;"
            " border-radius: 16px; font-size: 14pt; font-weight: bold; }"
            "QPushButton:hover { background: #3498db; color: #fff; }"
        )
        btn_help.clicked.connect(self._show_help_dialog)
        top.addWidget(btn_help)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setTabBar(ReorderableTabBar(self.tabs))
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self._apply_tab_style()
        layout.addWidget(self.tabs, 1)

        # Overview
        self.tab_overview = QWidget()
        self.tabs.addTab(self.tab_overview, tr("tab.overview"))
        ov = QVBoxLayout(self.tab_overview)
        ov.setContentsMargins(0, 0, 0, 0)
        self.overview_widget = OverviewWidget()
        ov.addWidget(self.overview_widget)

        # Raw Siege – card-based layout
        self.tab_siege_raw = QWidget()
        self.tabs.addTab(self.tab_siege_raw, tr("tab.siege_current"))
        sv = QVBoxLayout(self.tab_siege_raw)
        self.siege_cards = SiegeDefCardsWidget()
        sv.addWidget(self.siege_cards)

        # RTA (aktuell) – card-based overview of current RTA monsters
        self.tab_rta_overview = QWidget()
        self.tabs.addTab(self.tab_rta_overview, tr("tab.rta_current"))
        rv = QVBoxLayout(self.tab_rta_overview)
        self.rta_overview = RtaOverviewWidget()
        rv.addWidget(self.rta_overview)

        # Rune optimization overview
        self.tab_rune_optimization = QWidget()
        self.tabs.addTab(self.tab_rune_optimization, tr("tab.rune_optimization"))
        rov = QVBoxLayout(self.tab_rune_optimization)
        rov.setContentsMargins(0, 0, 0, 0)
        self.rune_optimization_widget = RuneOptimizationWidget(rune_set_icon_fn=self._rune_set_icon)
        rov.addWidget(self.rune_optimization_widget)

        # Siege Builder
        self.tab_siege_builder = QWidget()
        self.tabs.addTab(self.tab_siege_builder, tr("tab.siege_builder"))
        self._init_siege_builder_ui()

        # Saved Siege Optimizations
        self.tab_saved_siege = QWidget()
        self.tabs.addTab(self.tab_saved_siege, tr("tab.siege_saved"))
        self._init_saved_siege_tab()

        # WGB Builder (nur Validierung)
        self.tab_wgb_builder = QWidget()
        self.tabs.addTab(self.tab_wgb_builder, tr("tab.wgb_builder"))
        self._init_wgb_builder_ui()

        # Saved WGB Optimizations
        self.tab_saved_wgb = QWidget()
        self.tabs.addTab(self.tab_saved_wgb, tr("tab.wgb_saved"))
        self._init_saved_wgb_tab()

        # RTA Builder
        self.tab_rta_builder = QWidget()
        self.tabs.addTab(self.tab_rta_builder, tr("tab.rta_builder"))
        self._init_rta_builder_ui()

        # Saved RTA Optimizations
        self.tab_saved_rta = QWidget()
        self.tabs.addTab(self.tab_saved_rta, tr("tab.rta_saved"))
        self._init_saved_rta_tab()

        # Arena Rush Builder
        self.tab_arena_rush_builder = QWidget()
        self.tabs.addTab(self.tab_arena_rush_builder, tr("tab.arena_rush_builder"))
        self._init_arena_rush_builder_ui()

        # Saved Arena Rush Optimizations
        self.tab_saved_arena_rush = QWidget()
        self.tabs.addTab(self.tab_saved_arena_rush, tr("tab.arena_rush_saved"))
        self._init_saved_arena_rush_tab()

        # Team Manager (fixed + custom teams)
        self.tab_team_builder = QWidget()
        self._init_team_tab_ui()

        # Settings
        self.tab_settings = QWidget()
        self.tabs.addTab(self.tab_settings, tr("tab.settings"))
        self._init_settings_ui()

        self._unit_dropdowns_populated = False
        self._restore_tab_order()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.tabs.tabBar().tabMoved.connect(self._on_tab_moved)

        self._try_restore_snapshot()

    def _apply_tab_style(self) -> None:
        return _sec_apply_tab_style(self)

    # ============================================================
    # Tab reordering
    # ============================================================
    _tab_move_guard = False

    def _on_tab_moved(self, from_index: int, to_index: int) -> None:
        if self._tab_move_guard:
            return
        overview_idx = self.tabs.indexOf(self.tab_overview)
        if overview_idx != 0:
            self._tab_move_guard = True
            self.tabs.tabBar().moveTab(overview_idx, 0)
            self._tab_move_guard = False
        self._save_tab_order()

    def _save_tab_order(self) -> None:
        order = []
        for i in range(self.tabs.count()):
            widget = self.tabs.widget(i)
            for attr_name in DEFAULT_TAB_ORDER:
                if getattr(self, attr_name, None) is widget:
                    order.append(attr_name)
                    break
        settings_path = self.config_dir / "app_settings.json"
        data: dict = {}
        if settings_path.exists():
            try:
                data = json.loads(settings_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        data["tab_order"] = order
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def _restore_tab_order(self) -> None:
        settings_path = self.config_dir / "app_settings.json"
        if not settings_path.exists():
            return
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            return
        saved_order = data.get("tab_order")
        if not saved_order or not isinstance(saved_order, list):
            return
        if saved_order[0] != "tab_overview":
            return

        known: Dict[str, QWidget] = {}
        for attr_name in DEFAULT_TAB_ORDER:
            widget = getattr(self, attr_name, None)
            if widget is not None:
                known[attr_name] = widget

        valid_order: List[str] = []
        seen: Set[str] = set()
        for name in saved_order:
            if name in known and name not in seen:
                valid_order.append(name)
                seen.add(name)
        for name in DEFAULT_TAB_ORDER:
            if name not in seen and name in known:
                valid_order.append(name)

        self._tab_move_guard = True
        for target_index, attr_name in enumerate(valid_order):
            widget = known[attr_name]
            current_index = self.tabs.indexOf(widget)
            if current_index != target_index and current_index >= 0:
                self.tabs.tabBar().moveTab(current_index, target_index)
        self._tab_move_guard = False

    # ============================================================
    # Help dialog
    # ============================================================
    def _show_help_dialog(self) -> None:
        return _sec_show_help_dialog(self)

    # ============================================================
    # Import
    # ============================================================
    def on_import(self):
        return _sec_on_import(self)

    def _apply_saved_account(self, account: AccountData, source_label: str) -> None:
        return _sec_apply_saved_account(self, account, source_label)

    def _try_restore_snapshot(self) -> None:
        return _sec_try_restore_snapshot(self)

    def _build_pass_progress_callback(self, label: QLabel, prefix: str) -> Callable[[int, int], None]:
        def _cb(current_pass: int, total_passes: int) -> None:
            text = tr("status.pass_progress", prefix=prefix, current=int(current_pass), total=int(total_passes))
            label.setText(text)
            self.statusBar().showMessage(text)
            QApplication.processEvents()
        return _cb

    def _run_with_busy_progress(
        self,
        text: str,
        work_fn: Callable[[Callable[[], bool], Callable[[Any], None], Callable[[int, int], None]], Any],
    ) -> Any:
        dlg = QProgressDialog(text, tr("btn.cancel"), 0, 0, self)
        dlg.setWindowTitle(tr("btn.optimize"))
        dlg.setLabelText(text)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setCancelButtonText(tr("btn.cancel"))
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setRange(0, 0)
        dlg.show()
        QApplication.processEvents()

        cancel_event = threading.Event()
        solver_lock = threading.Lock()
        active_solvers: List[Any] = []
        progress_lock = threading.Lock()
        progress_state: Dict[str, int] = {"current": 0, "total": 0}

        def _is_cancelled() -> bool:
            return bool(cancel_event.is_set())

        def _register_solver(solver_obj: Any) -> None:
            with solver_lock:
                active_solvers.append(solver_obj)

        def _report_progress(current: int, total: int) -> None:
            with progress_lock:
                progress_state["current"] = max(0, int(current or 0))
                progress_state["total"] = max(0, int(total or 0))

        def _refresh_progress() -> None:
            if cancel_event.is_set():
                return
            with progress_lock:
                current = int(progress_state.get("current", 0))
                total = int(progress_state.get("total", 0))
            if total <= 0:
                return
            if dlg.maximum() == 0:
                dlg.setRange(0, 100)
                dlg.setValue(0)
            pct = max(0, min(100, int(round((float(current) / float(total)) * 100.0))))
            dlg.setValue(pct)
            label_text = f"{text} ({pct}%)"
            dlg.setLabelText(label_text)
            self.statusBar().showMessage(label_text)

        progress_timer = QTimer(dlg)
        progress_timer.timeout.connect(_refresh_progress)
        progress_timer.start(120)

        def _request_cancel() -> None:
            cancel_event.set()
            dlg.setLabelText(tr("opt.cancelled"))
            with solver_lock:
                solvers = list(active_solvers)
            for s in solvers:
                try:
                    if hasattr(s, "StopSearch"):
                        s.StopSearch()
                    elif hasattr(s, "stop_search"):
                        s.stop_search()
                except Exception:
                    continue

        dlg.canceled.connect(_request_cancel)

        wait_loop = QEventLoop()
        out: Dict[str, Any] = {}
        err: Dict[str, str] = {}
        worker = _TaskWorker(lambda: work_fn(_is_cancelled, _register_solver, _report_progress))

        def _on_finished(result: Any) -> None:
            out["result"] = result
            wait_loop.quit()

        def _on_failed(msg: str) -> None:
            err["msg"] = str(msg)
            wait_loop.quit()

        worker.signals.finished.connect(_on_finished)
        worker.signals.failed.connect(_on_failed)
        QThreadPool.globalInstance().start(worker)
        wait_loop.exec()

        progress_timer.stop()
        dlg.close()
        dlg.deleteLater()
        QApplication.processEvents()
        if "msg" in err:
            raise RuntimeError(err["msg"])
        return out.get("result")

    # ============================================================
    # Helpers: names+icons
    # ============================================================
    def _icon_for_master_id(self, master_id: int) -> QIcon:
        return _sec_icon_for_master_id(self, master_id)

    def _rune_set_icon(self, set_id: int) -> QIcon:
        return _sec_rune_set_icon(self, set_id)

    def _unit_text(self, unit_id: int) -> str:
        return _sec_unit_text(self, unit_id)

    def _unit_text_cached(self, unit_id: int) -> str:
        return _sec_unit_text_cached(self, unit_id)

    def _populate_combo_with_units(self, cmb: QComboBox):
        return _sec_populate_combo_with_units(self, cmb)

    def _build_unit_combo_model(self) -> QStandardItemModel:
        return _sec_build_unit_combo_model(self)

    def _ensure_unit_combo_model(self) -> QStandardItemModel:
        return _sec_ensure_unit_combo_model(self)

    def _populate_all_dropdowns(self):
        return _sec_populate_all_dropdowns(self)

    def _tab_needs_unit_dropdowns(self, tab: QWidget | None) -> bool:
        return _sec_tab_needs_unit_dropdowns(self, tab)

    def _on_tab_changed(self, index: int) -> None:
        return _sec_on_tab_changed(self, index)

    def _ensure_unit_dropdowns_populated(self) -> None:
        return _sec_ensure_unit_dropdowns_populated(self)

    # ============================================================
    # Saved Optimization Tabs
    # ============================================================
    def _init_saved_siege_tab(self):
        return _sec_init_saved_siege_tab(self)

    def _init_saved_wgb_tab(self):
        return _sec_init_saved_wgb_tab(self)

    def _init_saved_rta_tab(self):
        return _sec_init_saved_rta_tab(self)

    def _init_saved_arena_rush_tab(self):
        return _sec_init_saved_arena_rush_tab(self)

    def _saved_opt_widgets(self, mode: str):
        return _sec_saved_opt_widgets(self, mode)

    def _refresh_saved_opt_combo(self, mode: str):
        return _sec_refresh_saved_opt_combo(self, mode)

    def _on_saved_opt_changed(self, mode: str):
        return _sec_on_saved_opt_changed(self, mode)

    def _on_delete_saved_opt(self, mode: str):
        return _sec_on_delete_saved_opt(self, mode)

    # ============================================================
    # Siege raw view
    # ============================================================
    def _render_siege_raw(self):
        if not self.account:
            return
        self.siege_cards.render(self.account, self.monster_db, self.assets_dir)

    def _refresh_rune_optimization(self) -> None:
        self.rune_optimization_widget.set_account(self.account)

    # ============================================================
    # Custom Builders UI
    # ============================================================
    def _new_unit_search_combo(self, min_width: int = 300) -> _UnitSearchComboBox:
        return _sec_new_unit_search_combo(self, min_width=min_width)

    def _init_siege_builder_ui(self):
        return _sec_init_siege_builder_ui(self)

    def _init_wgb_builder_ui(self):
        return _sec_init_wgb_builder_ui(self)

    def _init_rta_builder_ui(self):
        return _sec_init_rta_builder_ui(self)

    def _init_arena_rush_builder_ui(self):
        return _sec_init_arena_rush_builder_ui(self)

    def _init_team_tab_ui(self):
        return _sec_init_team_tab_ui(self)

    def _current_team(self) -> Team | None:
        return _sec_current_team(self)

    def _refresh_team_combo(self) -> None:
        return _sec_refresh_team_combo(self)

    def _select_team_by_id(self, tid: str) -> None:
        return _sec_select_team_by_id(self, tid)

    def _set_team_controls_enabled(self, has_account: bool) -> None:
        return _sec_set_team_controls_enabled(self, has_account)

    def _on_team_selected(self) -> None:
        return _sec_on_team_selected(self)

    def _team_units_text(self, team: Team) -> str:
        return _sec_team_units_text(self, team)

    def _on_new_team(self) -> None:
        return _sec_on_new_team(self)

    def _on_edit_team(self) -> None:
        return _sec_on_edit_team(self)

    def _on_remove_team(self) -> None:
        return _sec_on_remove_team(self)

    def _optimize_team(self) -> None:
        return _sec_optimize_team(self)

    def _show_optimize_results(
        self,
        title: str,
        summary: str,
        results: List[GreedyUnitResult],
        unit_team_index: Optional[Dict[int, int]] = None,
        unit_display_order: Optional[Dict[int, int]] = None,
        mode: str = "",
        teams: Optional[List[List[int]]] = None,
    ) -> None:
        if not self.account:
            QMessageBox.warning(self, tr("result.title_siege"), tr("dlg.load_import_first"))
            return
        rune_lookup: Dict[int, Rune] = {r.rune_id: r for r in self.account.runes}
        artifact_lookup: Dict[int, Artifact] = {int(a.artifact_id): a for a in self.account.artifacts}
        # Build mode-specific rune owner lookup (rune_id -> unit_id)
        mode_rune_owner: Dict[int, int] = {}
        if mode in ("siege", "guild", "wgb"):
            for uid, rids in self.account.guild_rune_equip.items():
                for rid in rids:
                    mode_rune_owner[rid] = uid
        elif mode == "rta":
            for uid, rids in self.account.rta_rune_equip.items():
                for rid in rids:
                    mode_rune_owner[rid] = uid
        dlg = OptimizeResultDialog(
            self,
            title,
            summary,
            results,
            rune_lookup,
            artifact_lookup,
            self._unit_text,
            self._unit_icon_for_unit_id,
            self._unit_final_spd_value,
            self._unit_final_stats_values,
            self._rune_set_icon,
            self._unit_base_stats,
            self._unit_leader_bonus,
            self._unit_totem_bonus,
            unit_team_index=unit_team_index,
            unit_display_order=unit_display_order,
            mode_rune_owner=mode_rune_owner,
        )
        dlg.exec()

        if dlg.saved and mode and teams:
            from datetime import datetime
            ts = datetime.now().strftime("%d.%m.%Y %H:%M")
            name = tr("result.opt_name", mode=mode.upper(), ts=ts)
            saved_results: List[SavedUnitResult] = []
            for r in results:
                if r.ok and r.runes_by_slot:
                    saved_results.append(SavedUnitResult(
                        unit_id=r.unit_id,
                        runes_by_slot=dict(r.runes_by_slot),
                        artifacts_by_type=dict(r.artifacts_by_type or {}),
                        final_speed=r.final_speed,
                    ))
            self.opt_store.upsert(mode, name, teams, saved_results)
            self.opt_store.save(self.opt_store_path)
            self._refresh_saved_opt_combo(mode)

    def _unit_icon_for_unit_id(self, unit_id: int) -> QIcon:
        if not self.account:
            return QIcon()
        u = self.account.units_by_id.get(unit_id)
        if not u:
            return QIcon()
        return self._icon_for_master_id(u.unit_master_id)

    def _unit_base_stats(self, unit_id: int) -> Dict[str, int]:
        return _sec_unit_base_stats(self, unit_id)

    def _unit_leader_bonus(self, unit_id: int, team_unit_ids: List[int]) -> Dict[str, int]:
        return _sec_unit_leader_bonus(self, unit_id, team_unit_ids)

    def _unit_totem_bonus(self, unit_id: int) -> Dict[str, int]:
        return _sec_unit_totem_bonus(self, unit_id)

    def _unit_final_spd_value(
        self,
        unit_id: int,
        team_unit_ids: List[int],
        runes_by_unit: Dict[int, Dict[int, int]],
    ) -> int:
        return _sec_unit_final_spd_value(self, unit_id, team_unit_ids, runes_by_unit)

    def _unit_final_stats_values(
        self,
        unit_id: int,
        team_unit_ids: List[int],
        runes_by_unit: Dict[int, Dict[int, int]],
    ) -> Dict[str, int]:
        return _sec_unit_final_stats_values(self, unit_id, team_unit_ids, runes_by_unit)

    def _team_leader_skill(self, team_unit_ids: List[int]):
        return _sec_team_leader_skill(self, team_unit_ids)

    def _spd_from_stat_tuple(self, stat: Tuple[int, int] | Tuple[int, int, int, int]) -> int:
        return _sec_spd_from_stat_tuple(self, stat)

    def _spd_from_substats(self, subs: List[Tuple[int, int, int, int]]) -> int:
        return _sec_spd_from_substats(self, subs)

    def _ensure_siege_team_defaults(self) -> None:
        return _sec_ensure_siege_team_defaults(self)

    # ============================================================
    # Siege actions
    # ============================================================
    def on_take_current_siege(self):
        return _sec_on_take_current_siege(self)

    def _collect_siege_selections(self) -> List[TeamSelection]:
        return _sec_collect_siege_selections(self)

    def _validate_team_structure(self, label: str, selections: List[TeamSelection], must_have_team_size: int) -> Tuple[bool, str, List[int]]:
        return _sec_validate_team_structure(self, label, selections, must_have_team_size)

    def on_validate_siege(self):
        return _sec_on_validate_siege(self)

    def on_edit_presets_siege(self):
        return _sec_on_edit_presets_siege(self)

    def on_optimize_siege(self):
        return _sec_on_optimize_siege(self)

    def _units_by_turn_order(self, mode: str, unit_ids: List[int]) -> List[int]:
        return _sec_units_by_turn_order(self, mode, unit_ids)

    def _units_by_turn_order_grouped(self, mode: str, unit_ids: List[int], group_size: int) -> List[int]:
        return _sec_units_by_turn_order_grouped(self, mode, unit_ids, group_size)

    def _leader_spd_bonus_map(self, teams: List[List[int]]) -> Dict[int, int]:
        return _sec_leader_spd_bonus_map(self, teams)

    # ============================================================
    # WGB Builder
    # ============================================================
    def _collect_wgb_selections(self) -> List[TeamSelection]:
        return _sec_collect_wgb_selections(self)

    def _validate_unique_monsters(self, all_unit_ids: List[int]) -> Tuple[bool, str]:
        return _sec_validate_unique_monsters(self, all_unit_ids)

    def on_validate_wgb(self):
        return _sec_on_validate_wgb(self)

    def on_edit_presets_wgb(self):
        return _sec_on_edit_presets_wgb(self)

    def on_optimize_wgb(self):
        return _sec_on_optimize_wgb(self)

    def _render_wgb_preview(self, selections: List[TeamSelection] | None = None):
        return _sec_render_wgb_preview(self, selections)

    # ============================================================
    # RTA Builder
    # ============================================================
    def _on_rta_add_monster(self):
        return _sec_on_rta_add_monster(self)

    def _on_rta_remove_monster(self):
        return _sec_on_rta_remove_monster(self)

    def on_take_current_rta(self):
        return _sec_on_take_current_rta(self)

    def _collect_rta_unit_ids(self) -> List[int]:
        return _sec_collect_rta_unit_ids(self)

    def on_validate_rta(self):
        return _sec_on_validate_rta(self)

    def on_edit_presets_rta(self):
        return _sec_on_edit_presets_rta(self)

    def on_optimize_rta(self):
        return _sec_on_optimize_rta(self)

    # ============================================================
    # Arena Rush Builder
    # ============================================================
    def on_take_current_arena_def(self):
        return _sec_on_take_current_arena_def(self)

    def on_take_current_arena_off(self):
        return _sec_on_take_current_arena_off(self)

    def _collect_arena_def_selection(self) -> List[int]:
        return _sec_collect_arena_def_selection(self)

    def _collect_arena_offense_selections(self) -> List[TeamSelection]:
        return _sec_collect_arena_offense_selections(self)

    def _validate_arena_rush(self):
        return _sec_validate_arena_rush(self)

    def on_validate_arena_rush(self):
        return _sec_on_validate_arena_rush(self)

    def on_edit_presets_arena_rush(self):
        return _sec_on_edit_presets_arena_rush(self)

    def on_optimize_arena_rush(self):
        return _sec_on_optimize_arena_rush(self)

    def _retranslate_ui(self) -> None:
        return _sec_retranslate_ui(self)

    # ============================================================
    # Settings tab
    # ============================================================
    def _init_settings_ui(self):
        return _sec_init_settings_ui(self)

    def _refresh_settings_import_status(self):
        return _sec_refresh_settings_import_status(self)

    def _refresh_settings_license_status(self):
        return _sec_refresh_settings_license_status(self)

    def _on_settings_import_json(self):
        return _sec_on_settings_import_json(self)

    def _on_settings_clear_snapshot(self):
        return _sec_on_settings_clear_snapshot(self)

    def _on_settings_activate_license(self):
        return _sec_on_settings_activate_license(self)

    def _on_settings_reset_presets(self):
        return _sec_on_settings_reset_presets(self)

    def _on_settings_clear_optimizations(self):
        return _sec_on_settings_clear_optimizations(self)

    def _on_settings_clear_teams(self):
        return _sec_on_settings_clear_teams(self)

    def _on_settings_check_update(self):
        return _sec_on_settings_check_update(self)

    def _on_settings_language_changed(self, index: int):
        return _sec_on_settings_language_changed(self, index)


def _apply_dark_palette(app: QApplication) -> None:
    return _apply_dark_palette_impl(app)


def _acquire_single_instance():
    """Ensure only one instance of the application is running.

    Uses a Windows named mutex.  Falls back to a lock-file approach on
    other platforms.  Returns a handle that must be kept alive for the
    lifetime of the process (preventing GC / early release).
    """
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        mutex_name = "Global\\SWOT_SingleInstance_Mutex"
        handle = kernel32.CreateMutexW(None, True, mutex_name)
        ERROR_ALREADY_EXISTS = 183
        if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
            return None  # another instance is running
        return handle  # keep alive
    else:
        import fcntl
        lock_path = Path.home() / ".swot.lock"
        lock_file = open(lock_path, "w")
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return None
        return lock_file  # keep alive


def run_app():
    instance_lock = _acquire_single_instance()
    if instance_lock is None:
        # Show a message and exit – no QApplication yet, use a temporary one
        _tmp = QApplication(sys.argv)
        QMessageBox.warning(
            None,
            "SWOT",
            "Die Anwendung läuft bereits.",
        )
        sys.exit(0)

    app = QApplication(sys.argv)
    _apply_dark_palette(app)
    # Set application icon
    icon_path = Path(__file__).resolve().parents[1] / "assets" / "app_icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    import app.i18n as i18n
    config_dir = Path(__file__).resolve().parents[1] / "config"
    i18n.init(config_dir)
    license_info = _ensure_license_accepted()
    if not license_info:
        sys.exit(1)
    w = MainWindow()
    _apply_license_title(w, license_info)
    w.show()
    QTimer.singleShot(1200, lambda: _start_update_check(w))
    sys.exit(app.exec())







