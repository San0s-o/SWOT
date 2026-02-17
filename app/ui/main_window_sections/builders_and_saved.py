from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QScrollArea,
    QSpinBox,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
    QPushButton,
    QMessageBox,
)

from app.i18n import tr
from app.ui.siege_cards_widget import SiegeDefCardsWidget
from app.ui.widgets.selection_combos import _UnitSearchComboBox
from app.ui.main_window_sections.arena_rush_ui import (
    init_arena_rush_builder_ui as _sec_init_arena_rush_builder_ui,
)


def init_saved_siege_tab(window) -> None:
    v = QVBoxLayout(window.tab_saved_siege)
    top = QHBoxLayout()
    window.lbl_saved_siege = QLabel(tr("label.saved_opt"))
    top.addWidget(window.lbl_saved_siege)
    window.saved_siege_combo = QComboBox()
    window.saved_siege_combo.currentIndexChanged.connect(lambda: window._on_saved_opt_changed("siege"))
    window.saved_siege_combo.activated.connect(lambda: window._on_saved_opt_changed("siege"))
    top.addWidget(window.saved_siege_combo, 1)
    window.btn_delete_saved_siege = QPushButton(tr("btn.delete"))
    window.btn_delete_saved_siege.clicked.connect(lambda: window._on_delete_saved_opt("siege"))
    top.addWidget(window.btn_delete_saved_siege)
    v.addLayout(top)
    window.saved_siege_cards = SiegeDefCardsWidget()
    v.addWidget(window.saved_siege_cards, 1)
    window._refresh_saved_opt_combo("siege")


def init_saved_wgb_tab(window) -> None:
    v = QVBoxLayout(window.tab_saved_wgb)
    top = QHBoxLayout()
    window.lbl_saved_wgb = QLabel(tr("label.saved_opt"))
    top.addWidget(window.lbl_saved_wgb)
    window.saved_wgb_combo = QComboBox()
    window.saved_wgb_combo.currentIndexChanged.connect(lambda: window._on_saved_opt_changed("wgb"))
    window.saved_wgb_combo.activated.connect(lambda: window._on_saved_opt_changed("wgb"))
    top.addWidget(window.saved_wgb_combo, 1)
    window.btn_delete_saved_wgb = QPushButton(tr("btn.delete"))
    window.btn_delete_saved_wgb.clicked.connect(lambda: window._on_delete_saved_opt("wgb"))
    top.addWidget(window.btn_delete_saved_wgb)
    v.addLayout(top)
    window.saved_wgb_cards = SiegeDefCardsWidget()
    v.addWidget(window.saved_wgb_cards, 1)
    window._refresh_saved_opt_combo("wgb")


def init_saved_rta_tab(window) -> None:
    v = QVBoxLayout(window.tab_saved_rta)
    top = QHBoxLayout()
    window.lbl_saved_rta = QLabel(tr("label.saved_opt"))
    top.addWidget(window.lbl_saved_rta)
    window.saved_rta_combo = QComboBox()
    window.saved_rta_combo.currentIndexChanged.connect(lambda: window._on_saved_opt_changed("rta"))
    window.saved_rta_combo.activated.connect(lambda: window._on_saved_opt_changed("rta"))
    top.addWidget(window.saved_rta_combo, 1)
    window.btn_delete_saved_rta = QPushButton(tr("btn.delete"))
    window.btn_delete_saved_rta.clicked.connect(lambda: window._on_delete_saved_opt("rta"))
    top.addWidget(window.btn_delete_saved_rta)
    v.addLayout(top)
    window.saved_rta_cards = SiegeDefCardsWidget()
    v.addWidget(window.saved_rta_cards, 1)
    window._refresh_saved_opt_combo("rta")


def init_saved_arena_rush_tab(window) -> None:
    v = QVBoxLayout(window.tab_saved_arena_rush)
    top = QHBoxLayout()
    window.lbl_saved_arena_rush = QLabel(tr("label.saved_opt"))
    top.addWidget(window.lbl_saved_arena_rush)
    window.saved_arena_rush_combo = QComboBox()
    window.saved_arena_rush_combo.currentIndexChanged.connect(lambda: window._on_saved_opt_changed("arena_rush"))
    window.saved_arena_rush_combo.activated.connect(lambda: window._on_saved_opt_changed("arena_rush"))
    top.addWidget(window.saved_arena_rush_combo, 1)
    window.btn_delete_saved_arena_rush = QPushButton(tr("btn.delete"))
    window.btn_delete_saved_arena_rush.clicked.connect(lambda: window._on_delete_saved_opt("arena_rush"))
    top.addWidget(window.btn_delete_saved_arena_rush)
    v.addLayout(top)
    window.saved_arena_rush_cards = SiegeDefCardsWidget()
    v.addWidget(window.saved_arena_rush_cards, 1)
    window._refresh_saved_opt_combo("arena_rush")


def new_unit_search_combo(window, min_width: int = 300) -> _UnitSearchComboBox:
    """Create a standardized monster-search combo used across builder tabs."""
    if not hasattr(window, "_all_unit_combos"):
        window._all_unit_combos = []
    cmb = _UnitSearchComboBox()
    cmb.setMinimumWidth(int(min_width))
    window._all_unit_combos.append(cmb)
    return cmb


def init_siege_builder_ui(window) -> None:
    v = QVBoxLayout(window.tab_siege_builder)

    window.box_siege_select = QGroupBox(tr("group.siege_select"))
    v.addWidget(window.box_siege_select, 1)
    box_layout = QVBoxLayout(window.box_siege_select)
    siege_scroll = QScrollArea()
    siege_scroll.setWidgetResizable(True)
    box_layout.addWidget(siege_scroll)
    siege_inner = QWidget()
    grid = QGridLayout(siege_inner)
    siege_scroll.setWidget(siege_inner)

    window._all_unit_combos: List[QComboBox] = []
    window.lbl_siege_defense: List[QLabel] = []

    window.siege_team_combos: List[List[QComboBox]] = []
    for t in range(10):
        lbl = QLabel(tr("label.defense", n=t + 1))
        window.lbl_siege_defense.append(lbl)
        grid.addWidget(lbl, t, 0)
        row: List[QComboBox] = []
        for s in range(3):
            cmb = new_unit_search_combo(window, min_width=300)
            grid.addWidget(cmb, t, 1 + s)
            row.append(cmb)
        window.siege_team_combos.append(row)

    btn_row = QHBoxLayout()
    v.addLayout(btn_row)

    window.btn_take_current_siege = QPushButton(tr("btn.take_siege"))
    window.btn_take_current_siege.setEnabled(False)
    window.btn_take_current_siege.clicked.connect(window.on_take_current_siege)
    btn_row.addWidget(window.btn_take_current_siege)

    window.btn_validate_siege = QPushButton(tr("btn.validate_pools"))
    window.btn_validate_siege.setEnabled(False)
    window.btn_validate_siege.clicked.connect(window.on_validate_siege)
    btn_row.addWidget(window.btn_validate_siege)

    window.btn_edit_presets_siege = QPushButton(tr("btn.builds"))
    window.btn_edit_presets_siege.setEnabled(False)
    window.btn_edit_presets_siege.clicked.connect(window.on_edit_presets_siege)
    btn_row.addWidget(window.btn_edit_presets_siege)

    window.btn_optimize_siege = QPushButton(tr("btn.optimize"))
    window.btn_optimize_siege.setEnabled(False)
    window.btn_optimize_siege.clicked.connect(window.on_optimize_siege)
    btn_row.addWidget(window.btn_optimize_siege)

    window.lbl_siege_passes = QLabel(tr("label.passes"))
    btn_row.addWidget(window.lbl_siege_passes)
    window.spin_multi_pass_siege = QSpinBox()
    window.spin_multi_pass_siege.setRange(1, 10)
    window.spin_multi_pass_siege.setValue(3)
    window.spin_multi_pass_siege.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_siege.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    btn_row.addWidget(window.spin_multi_pass_siege)
    window.lbl_siege_workers = QLabel(tr("label.workers"))
    btn_row.addWidget(window.lbl_siege_workers)
    window.combo_workers_siege = QComboBox()
    window._populate_worker_combo(window.combo_workers_siege)
    btn_row.addWidget(window.combo_workers_siege)
    window.lbl_siege_profile = QLabel("Profil")
    btn_row.addWidget(window.lbl_siege_profile)
    window.combo_quality_profile_siege = QComboBox()
    window.combo_quality_profile_siege.addItem("Fast", "fast")
    window.combo_quality_profile_siege.addItem("Balanced", "balanced")
    window.combo_quality_profile_siege.addItem("Max Qualität", "max_quality")
    if window._gpu_search_available():
        window.combo_quality_profile_siege.addItem("GPU Fast", "gpu_search_fast")
        window.combo_quality_profile_siege.addItem("GPU Balanced", "gpu_search_balanced")
        window.combo_quality_profile_siege.addItem("GPU Max", "gpu_search_max")
    window.combo_quality_profile_siege.setCurrentIndex(1)
    window.combo_quality_profile_siege.currentIndexChanged.connect(window._sync_worker_controls)
    btn_row.addWidget(window.combo_quality_profile_siege)
    window._sync_worker_controls()

    btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

    window.lbl_siege_validate = QLabel("—")
    v.addWidget(window.lbl_siege_validate)


def init_wgb_builder_ui(window) -> None:
    v = QVBoxLayout(window.tab_wgb_builder)

    window.box_wgb_select = QGroupBox(tr("group.wgb_select"))
    v.addWidget(window.box_wgb_select)
    grid = QGridLayout(window.box_wgb_select)

    window.wgb_team_combos: List[List[QComboBox]] = []
    window.lbl_wgb_defense: List[QLabel] = []
    for t in range(5):
        lbl = QLabel(tr("label.defense", n=t + 1))
        window.lbl_wgb_defense.append(lbl)
        grid.addWidget(lbl, t, 0)
        row: List[QComboBox] = []
        for s in range(3):
            cmb = new_unit_search_combo(window, min_width=300)
            grid.addWidget(cmb, t, 1 + s)
            row.append(cmb)
        window.wgb_team_combos.append(row)

    btn_row = QHBoxLayout()
    v.addLayout(btn_row)

    window.btn_validate_wgb = QPushButton(tr("btn.validate_pools"))
    window.btn_validate_wgb.setEnabled(False)
    window.btn_validate_wgb.clicked.connect(window.on_validate_wgb)
    btn_row.addWidget(window.btn_validate_wgb)

    window.btn_edit_presets_wgb = QPushButton(tr("btn.builds"))
    window.btn_edit_presets_wgb.setEnabled(False)
    window.btn_edit_presets_wgb.clicked.connect(window.on_edit_presets_wgb)
    btn_row.addWidget(window.btn_edit_presets_wgb)

    window.btn_optimize_wgb = QPushButton(tr("btn.optimize"))
    window.btn_optimize_wgb.setEnabled(False)
    window.btn_optimize_wgb.clicked.connect(window.on_optimize_wgb)
    btn_row.addWidget(window.btn_optimize_wgb)

    window.lbl_wgb_passes = QLabel(tr("label.passes"))
    btn_row.addWidget(window.lbl_wgb_passes)
    window.spin_multi_pass_wgb = QSpinBox()
    window.spin_multi_pass_wgb.setRange(1, 10)
    window.spin_multi_pass_wgb.setValue(3)
    window.spin_multi_pass_wgb.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_wgb.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    btn_row.addWidget(window.spin_multi_pass_wgb)
    window.lbl_wgb_workers = QLabel(tr("label.workers"))
    btn_row.addWidget(window.lbl_wgb_workers)
    window.combo_workers_wgb = QComboBox()
    window._populate_worker_combo(window.combo_workers_wgb)
    btn_row.addWidget(window.combo_workers_wgb)
    window.lbl_wgb_profile = QLabel("Profil")
    btn_row.addWidget(window.lbl_wgb_profile)
    window.combo_quality_profile_wgb = QComboBox()
    window.combo_quality_profile_wgb.addItem("Fast", "fast")
    window.combo_quality_profile_wgb.addItem("Balanced", "balanced")
    window.combo_quality_profile_wgb.addItem("Max Qualität", "max_quality")
    if window._gpu_search_available():
        window.combo_quality_profile_wgb.addItem("GPU Fast", "gpu_search_fast")
        window.combo_quality_profile_wgb.addItem("GPU Balanced", "gpu_search_balanced")
        window.combo_quality_profile_wgb.addItem("GPU Max", "gpu_search_max")
    window.combo_quality_profile_wgb.setCurrentIndex(1)
    window.combo_quality_profile_wgb.currentIndexChanged.connect(window._sync_worker_controls)
    btn_row.addWidget(window.combo_quality_profile_wgb)
    window._sync_worker_controls()

    btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

    window.lbl_wgb_validate = QLabel("—")
    v.addWidget(window.lbl_wgb_validate)

    window.wgb_preview_cards = SiegeDefCardsWidget()
    v.addWidget(window.wgb_preview_cards, 1)


def init_rta_builder_ui(window) -> None:
    v = QVBoxLayout(window.tab_rta_builder)

    window.box_rta_select = QGroupBox(tr("group.rta_select"))
    v.addWidget(window.box_rta_select, 1)
    box_layout = QVBoxLayout(window.box_rta_select)

    top_row = QHBoxLayout()
    window.rta_add_combo = new_unit_search_combo(window, min_width=350)
    top_row.addWidget(window.rta_add_combo, 1)

    window.btn_rta_add = QPushButton(tr("btn.add"))
    window.btn_rta_add.clicked.connect(window._on_rta_add_monster)
    top_row.addWidget(window.btn_rta_add)

    window.btn_rta_remove = QPushButton(tr("btn.remove"))
    window.btn_rta_remove.clicked.connect(window._on_rta_remove_monster)
    top_row.addWidget(window.btn_rta_remove)

    window.btn_take_current_rta = QPushButton(tr("btn.take_rta"))
    window.btn_take_current_rta.setEnabled(False)
    window.btn_take_current_rta.clicked.connect(window.on_take_current_rta)
    top_row.addWidget(window.btn_take_current_rta)

    box_layout.addLayout(top_row)

    window.rta_selected_list = QListWidget()
    window.rta_selected_list.setDragDropMode(QAbstractItemView.InternalMove)
    window.rta_selected_list.setDefaultDropAction(Qt.MoveAction)
    window.rta_selected_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
    window.rta_selected_list.setIconSize(QSize(40, 40))
    box_layout.addWidget(window.rta_selected_list)

    btn_row = QHBoxLayout()
    v.addLayout(btn_row)

    window.btn_validate_rta = QPushButton(tr("btn.validate"))
    window.btn_validate_rta.setEnabled(False)
    window.btn_validate_rta.clicked.connect(window.on_validate_rta)
    btn_row.addWidget(window.btn_validate_rta)

    window.btn_edit_presets_rta = QPushButton(tr("btn.builds"))
    window.btn_edit_presets_rta.setEnabled(False)
    window.btn_edit_presets_rta.clicked.connect(window.on_edit_presets_rta)
    btn_row.addWidget(window.btn_edit_presets_rta)

    window.btn_optimize_rta = QPushButton(tr("btn.optimize"))
    window.btn_optimize_rta.setEnabled(False)
    window.btn_optimize_rta.clicked.connect(window.on_optimize_rta)
    btn_row.addWidget(window.btn_optimize_rta)

    window.lbl_rta_passes = QLabel(tr("label.passes"))
    btn_row.addWidget(window.lbl_rta_passes)
    window.spin_multi_pass_rta = QSpinBox()
    window.spin_multi_pass_rta.setRange(1, 10)
    window.spin_multi_pass_rta.setValue(3)
    window.spin_multi_pass_rta.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_rta.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    btn_row.addWidget(window.spin_multi_pass_rta)
    window.lbl_rta_workers = QLabel(tr("label.workers"))
    btn_row.addWidget(window.lbl_rta_workers)
    window.combo_workers_rta = QComboBox()
    window._populate_worker_combo(window.combo_workers_rta)
    btn_row.addWidget(window.combo_workers_rta)
    window.lbl_rta_profile = QLabel("Profil")
    btn_row.addWidget(window.lbl_rta_profile)
    window.combo_quality_profile_rta = QComboBox()
    window.combo_quality_profile_rta.addItem("Fast", "fast")
    window.combo_quality_profile_rta.addItem("Balanced", "balanced")
    window.combo_quality_profile_rta.addItem("Max Qualität", "max_quality")
    if window._gpu_search_available():
        window.combo_quality_profile_rta.addItem("GPU Fast", "gpu_search_fast")
        window.combo_quality_profile_rta.addItem("GPU Balanced", "gpu_search_balanced")
        window.combo_quality_profile_rta.addItem("GPU Max", "gpu_search_max")
    window.combo_quality_profile_rta.setCurrentIndex(1)
    window.combo_quality_profile_rta.currentIndexChanged.connect(window._sync_worker_controls)
    btn_row.addWidget(window.combo_quality_profile_rta)
    window._sync_worker_controls()

    btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

    window.lbl_rta_validate = QLabel("—")
    v.addWidget(window.lbl_rta_validate)


def init_arena_rush_builder_ui(window) -> None:
    return _sec_init_arena_rush_builder_ui(window, new_unit_search_combo)


def saved_opt_widgets(window, mode: str):
    if mode == "siege":
        return window.saved_siege_combo, window.saved_siege_cards
    if mode == "rta":
        return window.saved_rta_combo, window.saved_rta_cards
    if mode == "arena_rush":
        return window.saved_arena_rush_combo, window.saved_arena_rush_cards
    return window.saved_wgb_combo, window.saved_wgb_cards


def refresh_saved_opt_combo(window, mode: str) -> None:
    combo, _ = window._saved_opt_widgets(mode)
    combo.blockSignals(True)
    current_id = str(combo.currentData() or "")
    combo.clear()
    items = window.opt_store.get_by_mode(mode)
    for opt in items:
        display_name = str(opt.name)
        display_name = display_name.replace(" Opt ", tr("saved.opt_replace"))
        display_name = display_name.replace(" Optimizer ", tr("saved.opt_replace"))
        display_name = display_name.replace("SIEGE Opt", tr("saved.siege_opt"))
        display_name = display_name.replace("WGB Opt", tr("saved.wgb_opt"))
        display_name = display_name.replace("RTA Opt", tr("saved.rta_opt"))
        display_name = display_name.replace("ARENA_RUSH Opt", tr("saved.arena_rush_opt"))
        display_name = display_name.replace("SIEGE Optimizer", tr("saved.siege_opt"))
        display_name = display_name.replace("WGB Optimizer", tr("saved.wgb_opt"))
        display_name = display_name.replace("RTA Optimizer", tr("saved.rta_opt"))
        display_name = display_name.replace("ARENA_RUSH Optimizer", tr("saved.arena_rush_opt"))
        display_name = display_name.replace("ARENA_RUSH Optimization", tr("saved.arena_rush_opt"))
        combo.addItem(f"{display_name}  ({opt.timestamp})", opt.id)
    if current_id:
        idx = combo.findData(current_id)
        if idx >= 0:
            combo.setCurrentIndex(idx)
    combo.blockSignals(False)
    window._on_saved_opt_changed(mode)


def on_saved_opt_changed(window, mode: str) -> None:
    combo, cards = window._saved_opt_widgets(mode)
    oid = str(combo.currentData() or "")
    if not oid or not window.account:
        cards._clear()
        return
    opt = window.opt_store.optimizations.get(oid)
    if not opt:
        cards._clear()
        return
    rune_mode = "rta" if mode == "rta" else "siege"
    cards.render_saved_optimization(opt, window.account, window.monster_db, window.assets_dir, rune_mode=rune_mode)


def on_delete_saved_opt(window, mode: str) -> None:
    combo, _ = window._saved_opt_widgets(mode)
    oid = str(combo.currentData() or "")
    if not oid:
        return
    opt = window.opt_store.optimizations.get(oid)
    name = opt.name if opt else oid
    reply = QMessageBox.question(
        window,
        tr("btn.delete"),
        tr("dlg.delete_confirm", name=name),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return
    window.opt_store.remove(oid)
    window.opt_store.save(window.opt_store_path)
    window._refresh_saved_opt_combo(mode)
