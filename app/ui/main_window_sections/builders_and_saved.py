from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt, QSize, QRect
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QScrollArea,
    QSpinBox,
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


def _clear_combo(cmb: _UnitSearchComboBox) -> None:
    """Reset a unit search combo to the empty (no selection) state."""
    cmb.setCurrentIndex(0)
    cmb._sync_line_edit_to_current()


_CLEAR_ICON: QIcon | None = None


def _get_clear_icon() -> QIcon:
    """Lazily create a small × icon for inline combo clear actions."""
    global _CLEAR_ICON
    if _CLEAR_ICON is None:
        size = 14
        pix = QPixmap(size, size)
        pix.fill(QColor(0, 0, 0, 0))
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(140, 140, 140))
        font = p.font()
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.drawText(QRect(0, 0, size, size), Qt.AlignCenter, "×")
        p.end()
        _CLEAR_ICON = QIcon(pix)
    return _CLEAR_ICON
_ROW_CLEAR_STYLE = (
    "QPushButton { background: #3a3a3a; color: #888; border: 1px solid #555; "
    "border-radius: 3px; font-size: 8pt; padding: 1px 4px; min-width: 0; }"
    "QPushButton:hover { background: #c0392b; color: #fff; border-color: #e74c3c; }"
)

# ── shared toolbar styles ────────────────────────────────────
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
    """Thin vertical separator for toolbars."""
    sep = QFrame()
    sep.setFixedWidth(1)
    sep.setStyleSheet("background: #3a3a3a; border: none;")
    return sep


def _make_settings_frame(*widgets_with_labels) -> QFrame:
    """Wrap (label, widget) pairs in a styled settings frame."""
    frame = QFrame()
    frame.setObjectName("OptSettings")
    frame.setStyleSheet(_SETTINGS_FRAME_STYLE)
    layout = QHBoxLayout(frame)
    layout.setContentsMargins(8, 3, 8, 3)
    layout.setSpacing(5)
    for item in widgets_with_labels:
        if isinstance(item, str):
            lbl = QLabel(item)
            lbl.setStyleSheet("color: #999; font-size: 8pt; background: transparent; border: none;")
            layout.addWidget(lbl)
        else:
            layout.addWidget(item)
    return frame


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
    if not hasattr(window, "_unit_combos_by_tab"):
        window._unit_combos_by_tab = {}
    cmb = _UnitSearchComboBox()
    cmb.setMinimumWidth(int(min_width))
    window._all_unit_combos.append(cmb)
    tab_key = str(getattr(window, "_unit_combo_registration_tab", "") or "").strip().lower()
    if tab_key:
        window._unit_combos_by_tab.setdefault(tab_key, []).append(cmb)
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
    window._unit_combos_by_tab = {}
    window.lbl_siege_defense: List[QLabel] = []
    window.lbl_siege_slot_headers: List[QLabel] = []
    # col 0 = checkbox, col 1 = defense label, cols 2-4 = unit slots
    for col, key in enumerate(("label.team_slot_1_leader", "label.team_slot_2", "label.team_slot_3"), start=2):
        hdr = QLabel(tr(key))
        if col == 2:
            hdr.setToolTip(tr("tooltip.team_slot_leader"))
        window.lbl_siege_slot_headers.append(hdr)
        grid.addWidget(hdr, 0, col)

    window.siege_team_combos: List[List[QComboBox]] = []
    window.siege_optimize_checks: List[QCheckBox] = []
    window._unit_combo_registration_tab = "siege"
    try:
        for t in range(10):
            chk = QCheckBox()
            chk.setChecked(True)
            chk.setToolTip(tr("tooltip.siege_optimize_check"))
            window.siege_optimize_checks.append(chk)
            grid.addWidget(chk, t + 1, 0, alignment=Qt.AlignCenter)

            lbl = QLabel(tr("label.defense", n=t + 1))
            window.lbl_siege_defense.append(lbl)
            grid.addWidget(lbl, t + 1, 1)
            row: List[QComboBox] = []
            for s in range(3):
                cmb = new_unit_search_combo(window, min_width=300)
                if s == 0:
                    cmb.setToolTip(tr("tooltip.team_slot_leader"))
                le = cmb.lineEdit()
                if le is not None:
                    act = le.addAction(_get_clear_icon(), QLineEdit.TrailingPosition)
                    act.setToolTip(tr("tooltip.clear_slot"))
                    act.triggered.connect(lambda checked=False, c=cmb: _clear_combo(c))
                grid.addWidget(cmb, t + 1, 2 + s)
                row.append(cmb)
            row_btn = QPushButton("✕")
            row_btn.setFixedSize(28, 26)
            row_btn.setToolTip(tr("tooltip.clear_defense"))
            row_btn.setStyleSheet(_ROW_CLEAR_STYLE)
            row_btn.clicked.connect(lambda checked=False, r=row: [_clear_combo(c) for c in r])
            grid.addWidget(row_btn, t + 1, 5)
            window.siege_team_combos.append(row)
    finally:
        window._unit_combo_registration_tab = ""

    grid.setRowStretch(11, 1)  # absorb extra vertical space, push content to top
    grid.setColumnStretch(0, 0)  # checkbox column - minimal width
    grid.setColumnStretch(1, 0)  # defense label - minimal width
    grid.setColumnStretch(2, 1)
    grid.setColumnStretch(3, 1)
    grid.setColumnStretch(4, 1)
    grid.setColumnStretch(5, 0)  # row clear button - minimal width

    window.chk_siege_block_excluded = QCheckBox(tr("chk.siege_block_excluded"))
    window.chk_siege_block_excluded.setChecked(False)
    window.chk_siege_block_excluded.setToolTip(tr("tooltip.siege_block_excluded"))
    v.addWidget(window.chk_siege_block_excluded)

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
    window.btn_validate_siege.setVisible(False)

    window.btn_edit_presets_siege = QPushButton(tr("btn.builds"))
    window.btn_edit_presets_siege.setEnabled(False)
    window.btn_edit_presets_siege.setToolTip(tr("tooltip.builds"))
    window.btn_edit_presets_siege.clicked.connect(window.on_edit_presets_siege)
    btn_row.addWidget(window.btn_edit_presets_siege)

    btn_row.addWidget(_vsep())

    window.btn_optimize_siege = QPushButton(tr("btn.optimize"))
    window.btn_optimize_siege.setEnabled(False)
    window.btn_optimize_siege.setStyleSheet(_OPTIMIZE_BTN_STYLE)
    window.btn_optimize_siege.clicked.connect(window.on_optimize_siege)
    btn_row.addWidget(window.btn_optimize_siege)

    btn_row.addWidget(_vsep())

    window.spin_multi_pass_siege = QSpinBox()
    window.spin_multi_pass_siege.setRange(1, 10)
    window.spin_multi_pass_siege.setValue(3)
    window.spin_multi_pass_siege.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_siege.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    window.lbl_siege_passes = QLabel(tr("label.passes"))
    window.combo_workers_siege = QComboBox()
    window._populate_worker_combo(window.combo_workers_siege)
    window.lbl_siege_workers = QLabel(tr("label.workers"))
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
    window.lbl_siege_profile = QLabel("Profil")
    btn_row.addWidget(_make_settings_frame(
        window.lbl_siege_passes, window.spin_multi_pass_siege,
        window.lbl_siege_workers, window.combo_workers_siege,
        window.lbl_siege_profile, window.combo_quality_profile_siege,
    ))
    window._sync_worker_controls()

    btn_row.addStretch(1)

    window.lbl_siege_validate = QLabel("—")
    window.lbl_siege_validate.setStyleSheet(_STATUS_LBL_STYLE)
    btn_row.addWidget(window.lbl_siege_validate)


def init_wgb_builder_ui(window) -> None:
    v = QVBoxLayout(window.tab_wgb_builder)

    window.box_wgb_select = QGroupBox(tr("group.wgb_select"))
    v.addWidget(window.box_wgb_select)
    grid = QGridLayout(window.box_wgb_select)

    window.wgb_team_combos: List[List[QComboBox]] = []
    window.lbl_wgb_defense: List[QLabel] = []
    window.lbl_wgb_slot_headers: List[QLabel] = []
    for col, key in enumerate(("label.team_slot_1_leader", "label.team_slot_2", "label.team_slot_3"), start=1):
        hdr = QLabel(tr(key))
        if col == 1:
            hdr.setToolTip(tr("tooltip.team_slot_leader"))
        window.lbl_wgb_slot_headers.append(hdr)
        grid.addWidget(hdr, 0, col)
    window._unit_combo_registration_tab = "wgb"
    try:
        for t in range(5):
            lbl = QLabel(tr("label.defense", n=t + 1))
            window.lbl_wgb_defense.append(lbl)
            grid.addWidget(lbl, t + 1, 0)
            row: List[QComboBox] = []
            for s in range(3):
                cmb = new_unit_search_combo(window, min_width=300)
                if s == 0:
                    cmb.setToolTip(tr("tooltip.team_slot_leader"))
                le = cmb.lineEdit()
                if le is not None:
                    act = le.addAction(_get_clear_icon(), QLineEdit.TrailingPosition)
                    act.setToolTip(tr("tooltip.clear_slot"))
                    act.triggered.connect(lambda checked=False, c=cmb: _clear_combo(c))
                grid.addWidget(cmb, t + 1, 1 + s)
                row.append(cmb)
            row_btn = QPushButton("✕")
            row_btn.setFixedSize(28, 26)
            row_btn.setToolTip(tr("tooltip.clear_defense"))
            row_btn.setStyleSheet(_ROW_CLEAR_STYLE)
            row_btn.clicked.connect(lambda checked=False, r=row: [_clear_combo(c) for c in r])
            grid.addWidget(row_btn, t + 1, 4)
            window.wgb_team_combos.append(row)
    finally:
        window._unit_combo_registration_tab = ""

    btn_row = QHBoxLayout()
    v.addLayout(btn_row)

    window.btn_validate_wgb = QPushButton(tr("btn.validate_pools"))
    window.btn_validate_wgb.setEnabled(False)
    window.btn_validate_wgb.clicked.connect(window.on_validate_wgb)
    btn_row.addWidget(window.btn_validate_wgb)
    window.btn_validate_wgb.setVisible(False)

    window.btn_edit_presets_wgb = QPushButton(tr("btn.builds"))
    window.btn_edit_presets_wgb.setEnabled(False)
    window.btn_edit_presets_wgb.setToolTip(tr("tooltip.builds"))
    window.btn_edit_presets_wgb.clicked.connect(window.on_edit_presets_wgb)
    btn_row.addWidget(window.btn_edit_presets_wgb)

    btn_row.addWidget(_vsep())

    window.btn_optimize_wgb = QPushButton(tr("btn.optimize"))
    window.btn_optimize_wgb.setEnabled(False)
    window.btn_optimize_wgb.setStyleSheet(_OPTIMIZE_BTN_STYLE)
    window.btn_optimize_wgb.clicked.connect(window.on_optimize_wgb)
    btn_row.addWidget(window.btn_optimize_wgb)

    btn_row.addWidget(_vsep())

    window.spin_multi_pass_wgb = QSpinBox()
    window.spin_multi_pass_wgb.setRange(1, 10)
    window.spin_multi_pass_wgb.setValue(3)
    window.spin_multi_pass_wgb.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_wgb.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    window.lbl_wgb_passes = QLabel(tr("label.passes"))
    window.combo_workers_wgb = QComboBox()
    window._populate_worker_combo(window.combo_workers_wgb)
    window.lbl_wgb_workers = QLabel(tr("label.workers"))
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
    window.lbl_wgb_profile = QLabel("Profil")
    btn_row.addWidget(_make_settings_frame(
        window.lbl_wgb_passes, window.spin_multi_pass_wgb,
        window.lbl_wgb_workers, window.combo_workers_wgb,
        window.lbl_wgb_profile, window.combo_quality_profile_wgb,
    ))
    window._sync_worker_controls()

    btn_row.addStretch(1)

    window.lbl_wgb_validate = QLabel("—")
    window.lbl_wgb_validate.setStyleSheet(_STATUS_LBL_STYLE)
    btn_row.addWidget(window.lbl_wgb_validate)

    window.wgb_preview_cards = SiegeDefCardsWidget()
    v.addWidget(window.wgb_preview_cards, 1)


def init_rta_builder_ui(window) -> None:
    v = QVBoxLayout(window.tab_rta_builder)

    window.box_rta_select = QGroupBox(tr("group.rta_select"))
    v.addWidget(window.box_rta_select, 1)
    box_layout = QVBoxLayout(window.box_rta_select)

    top_row = QHBoxLayout()
    window._unit_combo_registration_tab = "rta"
    try:
        window.rta_add_combo = new_unit_search_combo(window, min_width=350)
    finally:
        window._unit_combo_registration_tab = ""
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
    window.btn_validate_rta.setVisible(False)

    window.btn_edit_presets_rta = QPushButton(tr("btn.builds"))
    window.btn_edit_presets_rta.setEnabled(False)
    window.btn_edit_presets_rta.setToolTip(tr("tooltip.builds"))
    window.btn_edit_presets_rta.clicked.connect(window.on_edit_presets_rta)
    btn_row.addWidget(window.btn_edit_presets_rta)

    btn_row.addWidget(_vsep())

    window.btn_optimize_rta = QPushButton(tr("btn.optimize"))
    window.btn_optimize_rta.setEnabled(False)
    window.btn_optimize_rta.setStyleSheet(_OPTIMIZE_BTN_STYLE)
    window.btn_optimize_rta.clicked.connect(window.on_optimize_rta)
    btn_row.addWidget(window.btn_optimize_rta)

    btn_row.addWidget(_vsep())

    window.spin_multi_pass_rta = QSpinBox()
    window.spin_multi_pass_rta.setRange(1, 10)
    window.spin_multi_pass_rta.setValue(3)
    window.spin_multi_pass_rta.setToolTip(tr("tooltip.passes"))
    window.spin_multi_pass_rta.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
    window.lbl_rta_passes = QLabel(tr("label.passes"))
    window.combo_workers_rta = QComboBox()
    window._populate_worker_combo(window.combo_workers_rta)
    window.lbl_rta_workers = QLabel(tr("label.workers"))
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
    window.lbl_rta_profile = QLabel("Profil")
    btn_row.addWidget(_make_settings_frame(
        window.lbl_rta_passes, window.spin_multi_pass_rta,
        window.lbl_rta_workers, window.combo_workers_rta,
        window.lbl_rta_profile, window.combo_quality_profile_rta,
    ))
    window._sync_worker_controls()

    btn_row.addStretch(1)

    window.lbl_rta_validate = QLabel("—")
    window.lbl_rta_validate.setStyleSheet(_STATUS_LBL_STYLE)
    btn_row.addWidget(window.lbl_rta_validate)


def init_arena_rush_builder_ui(window) -> None:
    window._unit_combo_registration_tab = "arena_rush"
    try:
        return _sec_init_arena_rush_builder_ui(window, new_unit_search_combo)
    finally:
        window._unit_combo_registration_tab = ""


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
