from __future__ import annotations

from typing import Callable, List

from PySide6.QtCore import QRect
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
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

_OPTIMIZE_BTN_STYLE = (
    "QPushButton { background: #1a6fa8; color: #fff; border: 1px solid #2980b9; "
    "border-radius: 4px; padding: 4px 18px; font-weight: bold; }"
    "QPushButton:hover { background: #2980b9; border-color: #3498db; }"
    "QPushButton:disabled { background: #252525; color: #555; border-color: #3a3a3a; }"
)
_SETTINGS_FRAME_STYLE = (
    "QFrame#OptSettings { background: #232323; border: 1px solid #3a3a3a; border-radius: 4px; }"
    "QLabel { background: transparent; border: none; color: #999; font-size: 8pt; }"
)
_STATUS_LBL_STYLE = "color: #888; font-style: italic; font-size: 9pt;"


def _vsep() -> QFrame:
    sep = QFrame()
    sep.setFixedWidth(1)
    sep.setStyleSheet("background: #3a3a3a; border: none;")
    return sep


def _make_settings_frame(*items) -> QFrame:
    frame = QFrame()
    frame.setObjectName("OptSettings")
    frame.setStyleSheet(_SETTINGS_FRAME_STYLE)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(8, 3, 8, 3)
    layout.setSpacing(5)
    for item in items:
        if isinstance(item, str):
            lbl = QLabel(item)
            lbl.setStyleSheet("color: #999; font-size: 8pt; background: transparent; border: none;")
            layout.addWidget(lbl)
        else:
            layout.addWidget(item)
    return frame


_ROW_CLEAR_STYLE = (
    "QPushButton { background: #3a3a3a; color: #888; border: 1px solid #555; "
    "border-radius: 3px; font-size: 8pt; padding: 1px 4px; min-width: 0; }"
    "QPushButton:hover { background: #c0392b; color: #fff; border-color: #e74c3c; }"
)
_CLEAR_ICON: QIcon | None = None


def _get_clear_icon() -> QIcon:
    global _CLEAR_ICON
    if _CLEAR_ICON is None:
        size = 14
        pix = QPixmap(size, size)
        pix.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pix)
        painter.setPen(QColor("#888888"))
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.drawText(QRect(0, 0, size, size), 0x84 | 0x04, "×")
        painter.end()
        _CLEAR_ICON = QIcon(pix)
    return _CLEAR_ICON


def _clear_combo(cmb) -> None:
    cmb.setCurrentIndex(0)
    if hasattr(cmb, "_sync_line_edit_to_current"):
        cmb._sync_line_edit_to_current()


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
        le = cmb.lineEdit()
        if le is not None:
            act = le.addAction(_get_clear_icon(), QLineEdit.TrailingPosition)
            act.setToolTip(tr("tooltip.clear_slot"))
            act.triggered.connect(lambda checked=False, c=cmb: _clear_combo(c))
        def_grid.addWidget(cmb, 0, 1 + s)
        window.arena_def_combos.append(cmb)
    def_row_btn = QPushButton("✕")
    def_row_btn.setFixedSize(28, 26)
    def_row_btn.setToolTip(tr("tooltip.clear_defense"))
    def_row_btn.setStyleSheet(_ROW_CLEAR_STYLE)
    def_row_btn.clicked.connect(lambda: [_clear_combo(c) for c in window.arena_def_combos])
    def_grid.addWidget(def_row_btn, 0, 5)
    def_grid.setColumnStretch(5, 0)

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
            le = cmb.lineEdit()
            if le is not None:
                act = le.addAction(_get_clear_icon(), QLineEdit.TrailingPosition)
                act.setToolTip(tr("tooltip.clear_slot"))
                act.triggered.connect(lambda checked=False, c=cmb: _clear_combo(c))
            off_grid.addWidget(cmb, t, 2 + s)
            row.append(cmb)
        row_btn = QPushButton("✕")
        row_btn.setFixedSize(28, 26)
        row_btn.setToolTip(tr("tooltip.clear_defense"))
        row_btn.setStyleSheet(_ROW_CLEAR_STYLE)
        row_btn.clicked.connect(lambda checked=False, r=row: [_clear_combo(c) for c in r])
        off_grid.addWidget(row_btn, t, 6)
        window.arena_offense_team_combos.append(row)

    off_grid.setColumnStretch(0, 0)  # "Aktiv" checkbox - minimal width
    off_grid.setColumnStretch(1, 0)  # offense label - minimal width
    off_grid.setColumnStretch(2, 1)
    off_grid.setColumnStretch(3, 1)
    off_grid.setColumnStretch(4, 1)
    off_grid.setColumnStretch(5, 1)
    off_grid.setColumnStretch(6, 0)  # row clear button - minimal width

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
    window.btn_edit_presets_arena_rush.setToolTip(tr("tooltip.builds"))
    window.btn_edit_presets_arena_rush.clicked.connect(lambda: _sec_on_edit_presets_arena_rush(window))
    btn_row.addWidget(window.btn_edit_presets_arena_rush)

    btn_row.addWidget(_vsep())

    window.btn_optimize_arena_rush = QPushButton(tr("btn.optimize"))
    window.btn_optimize_arena_rush.setEnabled(False)
    window.btn_optimize_arena_rush.setStyleSheet(_OPTIMIZE_BTN_STYLE)
    window.btn_optimize_arena_rush.clicked.connect(lambda: _sec_on_optimize_arena_rush(window))
    btn_row.addWidget(window.btn_optimize_arena_rush)

    btn_row.addWidget(_vsep())

    # Arena Rush uses global optimization; pass control is not applicable in UI.
    window.lbl_arena_rush_passes = QLabel(tr("label.passes"))
    window.lbl_arena_rush_passes.setVisible(False)
    window.spin_multi_pass_arena_rush = QSpinBox()
    window.spin_multi_pass_arena_rush.setRange(1, 10)
    window.spin_multi_pass_arena_rush.setValue(3)
    window.spin_multi_pass_arena_rush.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_arena_rush.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    window.spin_multi_pass_arena_rush.setVisible(False)

    window.combo_workers_arena_rush = QComboBox()
    window._populate_worker_combo(window.combo_workers_arena_rush)
    window.lbl_arena_rush_workers = QLabel(tr("label.workers"))
    window.combo_quality_profile_arena_rush = QComboBox()
    window.combo_quality_profile_arena_rush.addItem("Max Qualität", "max_quality")
    window.combo_quality_profile_arena_rush.addItem("Ultra (langsam)", "ultra_quality")
    window.combo_quality_profile_arena_rush.setCurrentIndex(0)
    window.combo_quality_profile_arena_rush.setEnabled(True)
    window.combo_quality_profile_arena_rush.currentIndexChanged.connect(window._sync_worker_controls)
    window.lbl_arena_rush_profile = QLabel("Profil")
    btn_row.addWidget(_make_settings_frame(
        window.lbl_arena_rush_workers, window.combo_workers_arena_rush,
        window.lbl_arena_rush_profile, window.combo_quality_profile_arena_rush,
    ))
    window._sync_worker_controls()

    btn_row.addStretch(1)

    window.lbl_arena_rush_validate = QLabel("—")
    window.lbl_arena_rush_validate.setStyleSheet(_STATUS_LBL_STYLE)
    btn_row.addWidget(window.lbl_arena_rush_validate)

    window.arena_rush_result_cards = SiegeDefCardsWidget()
    window.arena_rush_result_cards.setVisible(False)
    v.addWidget(window.arena_rush_result_cards, 1)

