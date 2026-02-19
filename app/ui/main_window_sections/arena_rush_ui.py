from __future__ import annotations

from typing import Callable, List

from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QSpacerItem,
    QSizePolicy,
    QVBoxLayout,
    QPushButton,
    QWidget,
)

from app.i18n import tr
from app.ui.main_window_sections.arena_rush_actions import (
    on_take_current_arena_def as _sec_on_take_current_arena_def,
    on_take_current_arena_off as _sec_on_take_current_arena_off,
    on_validate_arena_rush as _sec_on_validate_arena_rush,
    on_edit_presets_arena_rush as _sec_on_edit_presets_arena_rush,
    on_optimize_arena_rush as _sec_on_optimize_arena_rush,
)
from app.ui.siege_cards_widget import SiegeDefCardsWidget
from app.ui.widgets.selection_combos import _UnitSearchComboBox


def init_arena_rush_builder_ui(
    window,
    new_unit_search_combo_fn: Callable[..., _UnitSearchComboBox],
) -> None:
    v = QVBoxLayout(window.tab_arena_rush_builder)
    window.arena_offense_turn_effects = {}
    window.arena_def_speed_lead_uid = 0
    window.arena_def_speed_lead_pct = 0
    window.arena_offense_speed_lead_uid_by_team = {}
    window.arena_offense_speed_lead_pct_by_team = {}

    window.box_arena_def_select = QGroupBox(tr("group.arena_def_select"))
    v.addWidget(window.box_arena_def_select)
    def_grid = QGridLayout(window.box_arena_def_select)
    window.lbl_arena_defense = QLabel(tr("label.arena_defense"))
    def_grid.addWidget(window.lbl_arena_defense, 0, 0)
    window.arena_def_combos: List[_UnitSearchComboBox] = []
    for s in range(4):
        cmb = new_unit_search_combo_fn(window, min_width=260)
        def_grid.addWidget(cmb, 0, 1 + s)
        window.arena_def_combos.append(cmb)

    window.box_arena_off_select = QGroupBox(tr("group.arena_off_select"))
    v.addWidget(window.box_arena_off_select, 1)
    off_box_layout = QVBoxLayout(window.box_arena_off_select)
    off_scroll = QScrollArea()
    off_scroll.setWidgetResizable(True)
    off_box_layout.addWidget(off_scroll)
    off_inner = QWidget()
    off_grid = QGridLayout(off_inner)
    off_scroll.setWidget(off_inner)
    window.lbl_arena_offense: List[QLabel] = []
    window.chk_arena_offense_enabled: List[QCheckBox] = []
    window.arena_offense_team_combos: List[List[_UnitSearchComboBox]] = []
    max_rows = 15
    for t in range(max_rows):
        chk = QCheckBox(tr("label.active"))
        chk.setChecked(False)
        off_grid.addWidget(chk, t, 0)
        window.chk_arena_offense_enabled.append(chk)
        lbl = QLabel(tr("label.offense", n=t + 1))
        window.lbl_arena_offense.append(lbl)
        off_grid.addWidget(lbl, t, 1)
        row: List[_UnitSearchComboBox] = []
        for s in range(4):
            cmb = new_unit_search_combo_fn(window, min_width=260)
            off_grid.addWidget(cmb, t, 2 + s)
            row.append(cmb)
        window.arena_offense_team_combos.append(row)

    btn_row = QHBoxLayout()
    v.addLayout(btn_row)

    window.btn_take_current_arena_def = QPushButton(tr("btn.take_arena_def"))
    window.btn_take_current_arena_def.setEnabled(False)
    window.btn_take_current_arena_def.clicked.connect(lambda: _sec_on_take_current_arena_def(window))
    btn_row.addWidget(window.btn_take_current_arena_def)

    window.btn_take_arena_decks = QPushButton(tr("btn.take_arena_off"))
    window.btn_take_arena_decks.setEnabled(False)
    window.btn_take_arena_decks.clicked.connect(lambda: _sec_on_take_current_arena_off(window))
    btn_row.addWidget(window.btn_take_arena_decks)

    window.btn_validate_arena_rush = QPushButton(tr("btn.validate_pools"))
    window.btn_validate_arena_rush.setEnabled(False)
    window.btn_validate_arena_rush.clicked.connect(lambda: _sec_on_validate_arena_rush(window))
    btn_row.addWidget(window.btn_validate_arena_rush)
    window.btn_validate_arena_rush.setVisible(False)

    window.btn_edit_presets_arena_rush = QPushButton(tr("btn.builds"))
    window.btn_edit_presets_arena_rush.setEnabled(False)
    window.btn_edit_presets_arena_rush.clicked.connect(lambda: _sec_on_edit_presets_arena_rush(window))
    btn_row.addWidget(window.btn_edit_presets_arena_rush)

    window.btn_optimize_arena_rush = QPushButton(tr("btn.optimize"))
    window.btn_optimize_arena_rush.setEnabled(False)
    window.btn_optimize_arena_rush.clicked.connect(lambda: _sec_on_optimize_arena_rush(window))
    btn_row.addWidget(window.btn_optimize_arena_rush)

    window.lbl_arena_rush_passes = QLabel(tr("label.passes"))
    btn_row.addWidget(window.lbl_arena_rush_passes)
    window.spin_multi_pass_arena_rush = QSpinBox()
    window.spin_multi_pass_arena_rush.setRange(1, 10)
    window.spin_multi_pass_arena_rush.setValue(3)
    window.spin_multi_pass_arena_rush.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_arena_rush.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    btn_row.addWidget(window.spin_multi_pass_arena_rush)
    # Arena Rush uses global optimization; pass control is not applicable in UI.
    window.lbl_arena_rush_passes.setVisible(False)
    window.spin_multi_pass_arena_rush.setVisible(False)

    window.lbl_arena_rush_workers = QLabel(tr("label.workers"))
    btn_row.addWidget(window.lbl_arena_rush_workers)
    window.combo_workers_arena_rush = QComboBox()
    window._populate_worker_combo(window.combo_workers_arena_rush)
    btn_row.addWidget(window.combo_workers_arena_rush)

    window.lbl_arena_rush_profile = QLabel("Profil")
    btn_row.addWidget(window.lbl_arena_rush_profile)
    window.combo_quality_profile_arena_rush = QComboBox()
    window.combo_quality_profile_arena_rush.addItem("Max Qualität", "max_quality")
    window.combo_quality_profile_arena_rush.addItem("Ultra (langsam)", "ultra_quality")
    window.combo_quality_profile_arena_rush.setCurrentIndex(0)
    window.combo_quality_profile_arena_rush.setEnabled(True)
    window.combo_quality_profile_arena_rush.currentIndexChanged.connect(window._sync_worker_controls)
    btn_row.addWidget(window.combo_quality_profile_arena_rush)
    window._sync_worker_controls()

    btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

    window.lbl_arena_rush_validate = QLabel("—")
    v.addWidget(window.lbl_arena_rush_validate)

    window.arena_rush_result_cards = SiegeDefCardsWidget()
    window.arena_rush_result_cards.setVisible(False)
    v.addWidget(window.arena_rush_result_cards, 1)

