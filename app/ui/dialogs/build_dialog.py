from __future__ import annotations

import copy
import json
from math import ceil
from itertools import combinations, product
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import AccountData
from app.domain.presets import (
    ARTIFACT_MAIN_KEYS,
    Build,
    BuildStore,
    EFFECT_ID_TO_MAINSTAT_KEY,
    MAINSTAT_KEYS,
    SET_NAMES,
    SET_SIZES,
    SLOT2_DEFAULT,
    SLOT4_DEFAULT,
    SLOT6_DEFAULT,
)
from app.domain.speed_ticks import LEO_LOW_SPD_TICK, allowed_spd_ticks, max_spd_for_tick, min_spd_for_tick
from app.domain.artifact_effects import (
    ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE,
    artifact_effect_label,
    artifact_effect_is_legacy,
)
from app.i18n import tr
from app.ui.widgets.selection_combos import _MainstatMultiCombo, _NoScrollComboBox, _SetMultiCombo


def _artifact_kind_label(type_id: int) -> str:
    if type_id == 1:
        return tr("artifact.attribute")
    if type_id == 2:
        return tr("artifact.type")
    return str(type_id)


def _artifact_effect_label(effect_id: int) -> str:
    return artifact_effect_label(effect_id, fallback_prefix="Effekt")


_MIN_BASE_STATS = ("SPD", "HP", "ATK", "DEF")
_MIN_BASE_AWARE_STATS = ("SPD", "HP", "ATK", "DEF", "CR", "CD", "RES", "ACC")
_RUNE_PREFS_PATH = Path(__file__).resolve().parents[2] / "config" / "monster_rune_set_preferences.json"


class BuildDialog(QDialog):
    """
    Build editor for team presets:
    - one build per unit (Default)
    - sets/mainstats per unit
    - optimization/turn order via dedicated drag & drop lists
    """

    def __init__(
        self,
        parent: QWidget,
        title: str,
        unit_rows: List[Tuple[int, str]],
        preset_store: BuildStore,
        mode: str,
        account: AccountData | None,
        unit_icon_fn: Callable[[int], QIcon],
        team_size: int = 3,
        show_order_sections: bool = True,
        order_teams: List[List[Tuple[int, str]]] | None = None,
        order_team_titles: List[str] | None = None,
        order_turn_effects: List[Dict[int, Dict[str, Any]]] | None = None,
        show_turn_effect_controls: bool = False,
        order_turn_effect_capabilities: Dict[int, Dict[str, Any]] | None = None,
        show_speed_lead_controls: bool = False,
        order_speed_leaders: List[int] | None = None,
        order_speed_lead_pct_by_unit: Dict[int, int] | None = None,
        order_speed_lead_pct_by_team: List[int] | None = None,
        persist_order_fields: bool = True,
        skill_icons_dir: str | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        screen = QApplication.primaryScreen()
        if screen:
            avail = screen.availableGeometry()
            self.setMinimumSize(int(avail.width() * 0.55), int(avail.height() * 0.65))
        else:
            self.setMinimumSize(980, 620)

        self.preset_store = preset_store
        self.mode = mode
        self._account = account
        self.team_size = max(1, int(team_size))
        self._unit_icon_fn = unit_icon_fn
        self._skill_icons_dir = Path(skill_icons_dir) if skill_icons_dir else None
        self._unit_rows = list(unit_rows)
        self._unit_rows_by_uid: Dict[int, Tuple[int, str]] = {int(uid): (int(uid), str(lbl)) for uid, lbl in self._unit_rows}
        self._order_teams: List[List[Tuple[int, str]]] | None = None
        if order_teams:
            self._order_teams = [
                [(int(uid), str(lbl)) for uid, lbl in team if int(uid) > 0]
                for team in order_teams
                if team
            ]
        self._order_team_titles: List[str] = [str(x) for x in (order_team_titles or [])]
        self._order_turn_effects: List[Dict[int, Dict[str, Any]]] = []
        for team_cfg in (order_turn_effects or []):
            cleaned_team: Dict[int, Dict[str, Any]] = {}
            for uid, cfg in (team_cfg or {}).items():
                ui = int(uid or 0)
                if ui <= 0:
                    continue
                cleaned_team[ui] = dict(cfg or {})
            self._order_turn_effects.append(cleaned_team)
        self._show_turn_effect_controls = bool(show_turn_effect_controls)
        self._order_turn_effect_capabilities: Dict[int, Dict[str, Any]] = {
            int(uid): dict(cfg or {})
            for uid, cfg in dict(order_turn_effect_capabilities or {}).items()
            if int(uid or 0) > 0
        }
        self._show_speed_lead_controls = bool(show_speed_lead_controls)
        self._order_speed_leaders: List[int] = [int(uid or 0) for uid in (order_speed_leaders or [])]
        self._order_speed_lead_pct_by_unit: Dict[int, int] = {
            int(uid): int(pct or 0)
            for uid, pct in dict(order_speed_lead_pct_by_unit or {}).items()
            if int(uid or 0) > 0 and int(pct or 0) > 0
        }
        self._order_speed_lead_pct_by_team: List[int] = [int(v or 0) for v in (order_speed_lead_pct_by_team or [])]
        self._persist_order_fields = bool(persist_order_fields)
        self._artifact_substat_options_by_type = self._collect_artifact_substat_options_by_type(self._account)

        layout = QVBoxLayout(self)

        self._opt_order_list: QListWidget | None = None
        self._team_order_lists: List[QListWidget] = []
        self._team_spd_tick_combo_by_unit: Dict[int, List[QComboBox]] = {}
        self._syncing_team_spd_tick = False
        self._team_effect_controls: Dict[Tuple[int, int], Tuple[QCheckBox, QCheckBox, QSpinBox]] = {}
        self._team_speed_lead_combo_by_team: Dict[int, QComboBox] = {}
        self._team_speed_lead_pct_spin_by_team: Dict[int, QSpinBox] = {}
        self._syncing_focus_selection = False
        self._loaded_current_runes = False
        self._loaded_current_runes_snapshot: Dict[str, Any] = {}
        self._rune_pref_entries_by_master_id: Dict[int, Dict[str, Any]] | None = None
        self._initial_build_by_unit: Dict[int, Build] = {
            int(uid): copy.deepcopy((self.preset_store.get_unit_builds(self.mode, int(uid)) or [Build.default_any()])[0])
            for uid, _label in self._unit_rows
            if int(uid) > 0
        }
        self._initial_unit_list_order: List[int] = []
        self._initial_team_speed_lead_by_team: Dict[int, int] = {}
        self._initial_team_speed_lead_pct_by_team: Dict[int, int] = {}
        self._initial_team_effect_control_state: Dict[Tuple[int, int], Dict[str, Any]] = {}

        if show_order_sections:
            order_box = QGroupBox(tr("group.turn_order"))
            order_outer = QVBoxLayout(order_box)
            if self._order_teams:
                teams: List[List[Tuple[int, str]]] = [list(team) for team in self._order_teams if team]
            else:
                teams = [
                    self._unit_rows[i : i + self.team_size]
                    for i in range(0, len(self._unit_rows), self.team_size)
                    if self._unit_rows[i : i + self.team_size]
                ]

            # Defense team (first team) on top, offense teams in grid below
            def _build_team_list(t: int, team_units: List[Tuple[int, str]]) -> QListWidget:
                team_effect_cfg = dict(self._order_turn_effects[t]) if t < len(self._order_turn_effects) else {}
                lw = QListWidget()
                lw.setDragDropMode(QAbstractItemView.InternalMove)
                lw.setDefaultDropAction(Qt.MoveAction)
                lw.setSelectionMode(QAbstractItemView.SingleSelection)
                lw.setIconSize(QSize(36, 36))
                lw.setMinimumHeight(140)
                lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                sortable: List[Tuple[int, int, int, str, int, int]] = []
                for pos, (uid, label) in enumerate(team_units):
                    builds = self.preset_store.get_unit_builds(self.mode, uid)
                    b0 = builds[0] if builds else Build.default_any()
                    turn = int(getattr(b0, "turn_order", 0) or 0)
                    key = int(pos) if self._order_teams is not None else (turn if turn > 0 else 999)
                    spd_tick = int(getattr(b0, "spd_tick", 0) or 0)
                    min_cfg = dict(getattr(b0, "min_stats", {}) or {})
                    min_spd_val = int(min_cfg.get("SPD", 0) or 0) or int(min_cfg.get("SPD_NO_BASE", 0) or 0)
                    sortable.append((key, pos, uid, label, spd_tick, min_spd_val))
                sortable.sort(key=lambda x: (x[0], x[1]))
                for _, _, uid, label, spd_tick, min_spd_val in sortable:
                    it = QListWidgetItem()
                    it.setData(Qt.UserRole, int(uid))
                    lw.addItem(it)
                    effect_cfg = dict(team_effect_cfg.get(int(uid), {}) or {})
                    effect_spd_buff = bool(effect_cfg.get("applies_spd_buff", False))
                    effect_atb_boost_pct = int(float(effect_cfg.get("atb_boost_pct", 0.0) or 0.0))
                    capability_cfg = dict(self._order_turn_effect_capabilities.get(int(uid), {}) or {})
                    can_spd_buff = bool(capability_cfg.get("has_spd_buff", False))
                    can_atb_boost = bool(capability_cfg.get("has_atb_boost", False))
                    max_atb_boost_pct = int(capability_cfg.get("max_atb_boost_pct", 0) or 0)
                    if max_atb_boost_pct <= 0:
                        max_atb_boost_pct = 100
                    spd_buff_icon_file = str(capability_cfg.get("spd_buff_skill_icon", "") or "")
                    atb_boost_icon_file = str(capability_cfg.get("atb_boost_skill_icon", "") or "")

                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(2, 2, 2, 2)
                    row_layout.setSpacing(4)

                    icon_lbl = QLabel()
                    icon = self._unit_icon_fn(uid)
                    if not icon.isNull():
                        icon_lbl.setPixmap(icon.pixmap(28, 28))
                    row_layout.addWidget(icon_lbl)

                    txt_lbl = QLabel(label)
                    row_layout.addWidget(txt_lbl, 1)

                    spd_text = f"SPD {min_spd_val}" if min_spd_val > 0 else ""
                    spd_lbl = QLabel(spd_text)
                    spd_lbl.setStyleSheet("color: #aaa; font-size: 11px;")
                    row_layout.addWidget(spd_lbl)

                    tick_lbl = QLabel(tr("label.spd_tick_short"))

                    tick_cmb = _NoScrollComboBox()
                    tick_cmb.setMinimumWidth(80)
                    tick_cmb.setMaximumWidth(100)
                    tick_cmb.addItem("-", 0)
                    for tick in allowed_spd_ticks(self.mode):
                        tick_i = int(tick)
                        if str(self.mode).strip().lower() != "rta" and tick_i == int(LEO_LOW_SPD_TICK):
                            low_max = int(max_spd_for_tick(tick_i, self.mode) or 0)
                            threshold = int(low_max + 1) if low_max > 0 else 130
                            tick_cmb.addItem(f"11 (<{threshold})", tick_i)
                            continue
                        spd_bp = min_spd_for_tick(tick_i, self.mode)
                        tick_cmb.addItem(f"{tick_i} (>={spd_bp})", tick_i)
                    idx = tick_cmb.findData(int(spd_tick))
                    tick_cmb.setCurrentIndex(idx if idx >= 0 else 0)
                    tick_cmb.setToolTip(tr("tooltip.spd_tick"))
                    tick_cmb.currentIndexChanged.connect(
                        lambda _i, _uid=int(uid), _cmb=tick_cmb: self._on_team_spd_tick_changed(_uid, _cmb)
                    )

                    if self._show_turn_effect_controls:
                        # Only show controls on monsters that have the capability
                        if can_spd_buff:
                            spd_buff_chk = QCheckBox()
                            _skill_icon = self._load_skill_icon(spd_buff_icon_file)
                            if _skill_icon:
                                spd_buff_chk.setIcon(_skill_icon)
                                spd_buff_chk.setIconSize(QSize(20, 20))
                            else:
                                spd_buff_chk.setText("S")
                            spd_buff_chk.setChecked(bool(effect_spd_buff))
                            spd_buff_chk.setToolTip(tr("tooltip.effect_spd_buff"))
                            row_layout.addWidget(spd_buff_chk)
                        else:
                            spd_buff_chk = QCheckBox()
                            spd_buff_chk.setChecked(False)
                            spd_buff_chk.setVisible(False)

                        if can_atb_boost:
                            atb_boost_chk = QCheckBox()
                            _atb_icon = self._load_skill_icon(atb_boost_icon_file)
                            if _atb_icon:
                                atb_boost_chk.setIcon(_atb_icon)
                                atb_boost_chk.setIconSize(QSize(20, 20))
                            else:
                                atb_boost_chk.setText("A")
                            atb_boost_chk.setChecked(bool(effect_atb_boost_pct > 0))
                            atb_boost_chk.setToolTip(tr("tooltip.effect_atb_boost"))
                            row_layout.addWidget(atb_boost_chk)

                            atb_boost_spin = QSpinBox()
                            atb_boost_spin.setMinimum(0)
                            atb_boost_spin.setMaximum(int(max_atb_boost_pct))
                            atb_boost_spin.setSingleStep(5)
                            atb_boost_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
                            atb_boost_spin.setSuffix("%")
                            atb_boost_spin.setMaximumWidth(56)
                            if int(effect_atb_boost_pct) > 0:
                                atb_boost_spin.setValue(min(int(effect_atb_boost_pct), int(max_atb_boost_pct)))
                            else:
                                atb_boost_spin.setValue(min(30, int(max_atb_boost_pct)))
                            atb_boost_spin.setEnabled(bool(atb_boost_chk.isChecked()))
                            atb_boost_chk.toggled.connect(lambda checked, spin=atb_boost_spin: spin.setEnabled(bool(checked)))
                            row_layout.addWidget(atb_boost_spin)
                        else:
                            atb_boost_chk = QCheckBox()
                            atb_boost_chk.setChecked(False)
                            atb_boost_chk.setVisible(False)
                            atb_boost_spin = QSpinBox()
                            atb_boost_spin.setValue(0)
                            atb_boost_spin.setVisible(False)

                        self._team_effect_controls[(int(t), int(uid))] = (spd_buff_chk, atb_boost_chk, atb_boost_spin)

                    # Keep tick controls at the far right for consistent alignment.
                    row_layout.addWidget(tick_lbl)
                    row_layout.addWidget(tick_cmb)

                    self._team_spd_tick_combo_by_unit.setdefault(int(uid), []).append(tick_cmb)
                    it.setSizeHint(row_widget.sizeHint())
                    lw.setItemWidget(it, row_widget)
                self._team_order_lists.append(lw)
                lw.currentItemChanged.connect(
                    lambda current, _prev, _lw=lw: self._on_team_list_current_item_changed(_lw, current)
                )
                return lw

            if teams and self._order_teams:
                # Arena rush: Defense (first team) on top, offense teams in grid below
                def_title = self._order_team_titles[0] if self._order_team_titles else "Team 1"
                if self._show_speed_lead_controls:
                    order_outer.addLayout(self._build_team_header_with_speed_lead(0, def_title, teams[0]))
                else:
                    def_label = QLabel(f"<b>{def_title}</b>")
                    order_outer.addWidget(def_label)
                def_lw = _build_team_list(0, teams[0])
                order_outer.addWidget(def_lw)

                if len(teams) > 1:
                    max_offense_cols = 5
                    off_grid = QGridLayout()
                    for t_off, team_units in enumerate(teams[1:], start=1):
                        off_idx = int(t_off - 1)
                        col = int(off_idx % max_offense_cols)
                        row_block = int(off_idx // max_offense_cols)
                        header_row = int(row_block * 2)
                        list_row = int(header_row + 1)
                        team_title = (
                            self._order_team_titles[t_off]
                            if t_off < len(self._order_team_titles) and self._order_team_titles[t_off]
                            else f"Team {t_off+1}"
                        )
                        if self._show_speed_lead_controls:
                            hdr = QWidget()
                            hdr.setLayout(self._build_team_header_with_speed_lead(int(t_off), team_title, team_units))
                            off_grid.addWidget(hdr, header_row, col)
                        else:
                            off_grid.addWidget(QLabel(f"<b>{team_title}</b>"), header_row, col)
                        off_lw = _build_team_list(t_off, team_units)
                        off_grid.addWidget(off_lw, list_row, col)
                    order_outer.addLayout(off_grid)
            elif teams:
                # Siege/WGB: all teams in a horizontal grid
                teams_grid = QGridLayout()
                for t, team_units in enumerate(teams):
                    team_title = self._order_team_titles[t] if t < len(self._order_team_titles) and self._order_team_titles[t] else f"Team {t+1}"
                    teams_grid.addWidget(QLabel(f"<b>{team_title}</b>"), 0, t)
                    lw = _build_team_list(t, team_units)
                    teams_grid.addWidget(lw, 1, t)
                order_outer.addLayout(teams_grid)

            if str(self.mode).strip().lower() == "arena_rush":
                # In arena rush the content height is stable; avoid an extra inner scrollbar.
                layout.addWidget(order_box)
            else:
                order_scroll = QScrollArea()
                order_scroll.setWidgetResizable(True)
                order_scroll.setWidget(order_box)
                order_scroll.setMaximumHeight(340)
                layout.addWidget(order_scroll)

        self._set1_combo: Dict[int, _SetMultiCombo] = {}
        self._set2_combo: Dict[int, _SetMultiCombo] = {}
        self._set3_combo: Dict[int, _SetMultiCombo] = {}
        self._ms2_combo: Dict[int, _MainstatMultiCombo] = {}
        self._ms4_combo: Dict[int, _MainstatMultiCombo] = {}
        self._ms6_combo: Dict[int, _MainstatMultiCombo] = {}
        self._art_attr_focus_combo: Dict[int, QComboBox] = {}
        self._art_type_focus_combo: Dict[int, QComboBox] = {}
        self._art_attr_sub1_combo: Dict[int, QComboBox] = {}
        self._art_attr_sub2_combo: Dict[int, QComboBox] = {}
        self._art_type_sub1_combo: Dict[int, QComboBox] = {}
        self._art_type_sub2_combo: Dict[int, QComboBox] = {}
        self._min_mode_combo: Dict[int, QComboBox] = {}
        self._min_spd_spin: Dict[int, QSpinBox] = {}
        self._min_hp_spin: Dict[int, QSpinBox] = {}
        self._min_atk_spin: Dict[int, QSpinBox] = {}
        self._min_def_spin: Dict[int, QSpinBox] = {}
        self._min_cr_spin: Dict[int, QSpinBox] = {}
        self._min_cd_spin: Dict[int, QSpinBox] = {}
        self._min_res_spin: Dict[int, QSpinBox] = {}
        self._min_acc_spin: Dict[int, QSpinBox] = {}
        self._unit_label_by_id: Dict[int, str] = {uid: lbl for uid, lbl in self._unit_rows}
        self._unit_editor_stack = QStackedWidget()
        self._unit_list = QListWidget()
        self._unit_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._unit_list.setIconSize(QSize(34, 34))
        self._unit_list.setDragDropMode(QAbstractItemView.InternalMove)
        self._unit_list.setDefaultDropAction(Qt.MoveAction)
        self._unit_list.setToolTip(tr("tooltip.optimize_order_priority"))

        editor_split = QSplitter(Qt.Horizontal)
        editor_split.setChildrenCollapsible(False)
        editor_split.setHandleWidth(8)

        list_box = QGroupBox(tr("group.build_monster_list"))
        list_box.setToolTip(tr("tooltip.optimize_order_priority"))
        list_layout = QVBoxLayout(list_box)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.addWidget(self._unit_list, 1)
        if self._can_load_current_runes():
            btn_load_runes = QPushButton(tr("btn.load_current_runes"))
            btn_load_runes.setToolTip(tr("tooltip.load_current_runes"))
            btn_load_runes.clicked.connect(self._on_load_current_runes)
            list_layout.addWidget(btn_load_runes)
        btn_load_preferred_all = QPushButton(tr("btn.load_preferred_runes_all"))
        btn_load_preferred_all.setToolTip(tr("tooltip.load_preferred_runes_all"))
        btn_load_preferred_all.clicked.connect(self._on_load_preferred_runes_for_all)
        list_layout.addWidget(btn_load_preferred_all)
        btn_restore_saved_preset = QPushButton(tr("btn.restore_saved_preset"))
        btn_restore_saved_preset.setToolTip(tr("tooltip.restore_saved_preset"))
        btn_restore_saved_preset.clicked.connect(self._on_restore_saved_preset)
        list_layout.addWidget(btn_restore_saved_preset)
        editor_split.addWidget(list_box)

        detail_box = QGroupBox(tr("group.build_editor"))
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        detail_layout.addWidget(self._unit_editor_stack, 1)
        editor_split.addWidget(detail_box)
        editor_split.setStretchFactor(0, 0)
        editor_split.setStretchFactor(1, 1)
        editor_split.setSizes([340, 1100])
        layout.addWidget(editor_split, 1)

        table_rows = list(self._unit_rows)
        table_rows.sort(
            key=lambda x: (
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0) <= 0,
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0),
                next((idx for idx, it in enumerate(self._unit_rows) if int(it[0]) == int(x[0])), 10000),
            )
        )

        self._uid_to_stack_index: Dict[int, int] = {}
        for unit_id, label in table_rows:
            item = QListWidgetItem(label)
            icon = self._unit_icon_fn(unit_id)
            if not icon.isNull():
                item.setIcon(icon)
            item.setData(Qt.UserRole, int(unit_id))
            self._unit_list.addItem(item)
            self._uid_to_stack_index[int(unit_id)] = -1

        self._unit_list.currentRowChanged.connect(self._on_unit_row_changed)
        if self._unit_list.count() > 0:
            self._unit_list.setCurrentRow(0)
        self._initial_unit_list_order = self._unit_list_uid_order()
        self._initial_team_speed_lead_by_team = self._team_speed_lead_uid_state()
        self._initial_team_speed_lead_pct_by_team = self._team_speed_lead_pct_state()
        self._initial_team_effect_control_state = self._capture_team_effect_control_state()

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Show only after the full UI is constructed to avoid a brief white flash.
        self.showMaximized()

    def accept(self) -> None:
        try:
            self.apply_to_store()
        except ValueError as exc:
            QMessageBox.critical(self, "Builds", str(exc))
            return
        super().accept()

    def _on_unit_row_changed(self, row: int) -> None:
        if row < 0 or row >= self._unit_list.count():
            return
        item = self._unit_list.item(row)
        uid = int(item.data(Qt.UserRole) or 0) if item else 0
        stack_idx = self._ensure_editor_page(int(uid))
        if 0 <= stack_idx < self._unit_editor_stack.count():
            self._unit_editor_stack.setCurrentIndex(stack_idx)

    def _ensure_editor_page(self, unit_id: int) -> int:
        uid = int(unit_id or 0)
        if uid <= 0:
            return -1
        existing = int(self._uid_to_stack_index.get(uid, -1) or -1)
        if existing >= 0 and existing < self._unit_editor_stack.count():
            return int(existing)
        builds = self.preset_store.get_unit_builds(self.mode, uid)
        b0 = builds[0] if builds else Build.default_any()
        editor_page = self._build_unit_editor(int(uid), b0)
        stack_idx = int(self._unit_editor_stack.addWidget(editor_page))
        self._uid_to_stack_index[int(uid)] = int(stack_idx)
        return int(stack_idx)

    def _ensure_all_editor_pages(self) -> None:
        for row in range(self._unit_list.count()):
            item = self._unit_list.item(row)
            uid = int(item.data(Qt.UserRole) or 0) if item else 0
            if uid > 0:
                self._ensure_editor_page(int(uid))

    def _row_for_uid_in_unit_list(self, uid: int) -> int:
        target = int(uid or 0)
        if target <= 0:
            return -1
        for row in range(self._unit_list.count()):
            item = self._unit_list.item(row)
            if int(item.data(Qt.UserRole) or 0) == target:
                return int(row)
        return -1

    def _unit_list_uid_order(self) -> List[int]:
        order: List[int] = []
        for row in range(self._unit_list.count()):
            item = self._unit_list.item(row)
            uid = int(item.data(Qt.UserRole) or 0) if item else 0
            if uid > 0:
                order.append(int(uid))
        return order

    def _restore_unit_list_uid_order(self, uid_order: List[int]) -> None:
        target_order = [int(uid) for uid in (uid_order or []) if int(uid) > 0]
        if not target_order:
            return
        selected_uid = 0
        current_item = self._unit_list.currentItem()
        if current_item is not None:
            selected_uid = int(current_item.data(Qt.UserRole) or 0)

        rank_by_uid = {int(uid): idx for idx, uid in enumerate(target_order)}
        items: List[QListWidgetItem] = []
        while self._unit_list.count() > 0:
            item = self._unit_list.takeItem(0)
            if item is not None:
                items.append(item)
        items.sort(
            key=lambda it: (
                rank_by_uid.get(int(it.data(Qt.UserRole) or 0), 999999),
                str(it.text() or "").lower(),
            )
        )
        for item in items:
            self._unit_list.addItem(item)

        restore_uid = int(selected_uid or 0)
        if restore_uid <= 0 and target_order:
            restore_uid = int(target_order[0])
        row = self._row_for_uid_in_unit_list(int(restore_uid))
        if row >= 0:
            self._unit_list.setCurrentRow(int(row))

    def _team_speed_lead_uid_state(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for team_idx, cmb in self._team_speed_lead_combo_by_team.items():
            out[int(team_idx)] = int(cmb.currentData() or 0)
        return out

    def _team_speed_lead_pct_state(self) -> Dict[int, int]:
        out: Dict[int, int] = {}
        for team_idx, spin in self._team_speed_lead_pct_spin_by_team.items():
            out[int(team_idx)] = int(spin.value() or 0)
        return out

    def _capture_team_effect_control_state(self) -> Dict[Tuple[int, int], Dict[str, Any]]:
        out: Dict[Tuple[int, int], Dict[str, Any]] = {}
        for key, controls in self._team_effect_controls.items():
            team_idx = int(key[0])
            uid = int(key[1])
            spd_chk, atb_chk, atb_spin = controls
            out[(team_idx, uid)] = {
                "applies_spd_buff": bool(spd_chk.isChecked()),
                "atb_boost_enabled": bool(atb_chk.isChecked()),
                "atb_boost_pct": int(atb_spin.value() or 0),
            }
        return out

    def _on_team_list_current_item_changed(self, source_list: QListWidget, current: QListWidgetItem | None) -> None:
        if self._syncing_focus_selection:
            return
        if source_list not in self._team_order_lists:
            return
        if current is None:
            return
        uid = int(current.data(Qt.UserRole) or 0)
        if uid <= 0:
            return
        self._syncing_focus_selection = True
        try:
            for lw in self._team_order_lists:
                if lw is source_list:
                    continue
                if lw.currentRow() >= 0:
                    lw.setCurrentRow(-1)
                lw.clearSelection()
            row = self._row_for_uid_in_unit_list(int(uid))
            if row >= 0 and self._unit_list.currentRow() != row:
                self._unit_list.setCurrentRow(int(row))
        finally:
            self._syncing_focus_selection = False

    def _load_skill_icon(self, icon_filename: str) -> QIcon | None:
        if not icon_filename or not self._skill_icons_dir:
            return None
        path = self._skill_icons_dir / icon_filename
        if not path.exists():
            return None
        pix = QPixmap(str(path))
        if pix.isNull():
            return None
        return QIcon(pix)

    def _make_mainstat_combo(self, defaults: List[str]) -> _MainstatMultiCombo:
        cmb = _MainstatMultiCombo(MAINSTAT_KEYS)
        # Keep true "Any" as initial state. Concrete values are applied only
        # when an explicit build mainstat selection exists or user action sets it.
        _ = defaults
        cmb.setToolTip(tr("tooltip.mainstat_multi"))
        cmb.setMinimumWidth(190)
        return cmb

    def _make_art_focus_combo(self) -> QComboBox:
        cmb = _NoScrollComboBox()
        cmb.addItem("Any", "")
        for key in ARTIFACT_MAIN_KEYS:
            cmb.addItem(str(key), str(key))
        cmb.setMinimumWidth(190)
        return cmb

    def _set_art_focus_combo_value(self, cmb: QComboBox, value: str) -> None:
        sval = str(value or "").upper()
        if sval not in ("HP", "ATK", "DEF"):
            return
        idx = cmb.findData(sval)
        if idx >= 0:
            cmb.setCurrentIndex(idx)

    def _min_mode_for_build(self, min_cfg: Dict[str, int]) -> str:
        for key in _MIN_BASE_STATS:
            if int(min_cfg.get(f"{key}_NO_BASE", 0) or 0) > 0:
                return "without_base"
        return "with_base"

    def _min_value_for_build(self, min_cfg: Dict[str, int], key: str, mode: str, base_stats: Dict[str, int]) -> int:
        stat_key = str(key).upper()
        if str(mode) == "without_base" and stat_key in _MIN_BASE_STATS:
            return int(min_cfg.get(f"{stat_key}_NO_BASE", 0) or 0)
        if str(mode) == "with_base" and stat_key in _MIN_BASE_AWARE_STATS:
            raw_total = int(min_cfg.get(stat_key, 0) or 0)
            base_val = int(base_stats.get(stat_key, 0) or 0)
            return max(0, raw_total - base_val)
        return int(min_cfg.get(stat_key, 0) or 0)

    def _make_min_mode_combo(self, mode: str) -> QComboBox:
        cmb = _NoScrollComboBox()
        cmb.addItem(tr("min.mode.with_base"), "with_base")
        cmb.addItem(tr("min.mode.without_base"), "without_base")
        idx = cmb.findData(str(mode))
        cmb.setCurrentIndex(idx if idx >= 0 else 0)
        cmb.setMinimumWidth(190)
        return cmb

    def _unit_base_stats_for_min(self, unit_id: int) -> Dict[str, int]:
        if not self._account:
            return {"SPD": 0, "HP": 0, "ATK": 0, "DEF": 0, "CR": 0, "CD": 0, "RES": 0, "ACC": 0}
        unit = self._account.units_by_id.get(int(unit_id))
        if unit is None:
            return {"SPD": 0, "HP": 0, "ATK": 0, "DEF": 0, "CR": 0, "CD": 0, "RES": 0, "ACC": 0}
        return {
            "SPD": int(unit.base_spd or 0),
            "HP": int((unit.base_con or 0) * 15),
            "ATK": int(unit.base_atk or 0),
            "DEF": int(unit.base_def or 0),
            "CR": int(unit.crit_rate or 15),
            "CD": int(unit.crit_dmg or 50),
            "RES": int(unit.base_res or 15),
            "ACC": int(unit.base_acc or 0),
        }

    def _make_art_sub_combo(self, artifact_type: int) -> QComboBox:
        cmb = _NoScrollComboBox()
        cmb.addItem("Any", 0)
        eids = list(self._artifact_substat_options_by_type.get(int(artifact_type), []))
        eids.sort(key=lambda x: (artifact_effect_is_legacy(int(x)), int(x)))
        for eid in eids:
            cmb.addItem(_artifact_effect_label(int(eid)), int(eid))
        cmb.setToolTip(tr("tooltip.art_sub", kind=_artifact_kind_label(int(artifact_type))))
        cmb.setMinimumWidth(190)
        return cmb

    def _set_art_sub_combo_value(self, cmb: QComboBox, effect_id: int) -> None:
        eid = int(effect_id or 0)
        if eid <= 0:
            return
        idx = cmb.findData(eid)
        if idx < 0:
            cmb.addItem(_artifact_effect_label(eid), eid)
            idx = cmb.findData(eid)
        if idx >= 0:
            cmb.setCurrentIndex(idx)

    def _make_min_stat_spin(self, value: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setMinimum(0)
        spin.setMaximum(99999)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setValue(int(value))
        spin.setMaximumWidth(110)
        return spin

    def _build_unit_editor(self, unit_id: int, build: Build) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(10, 10, 10, 10)
        content_layout.setSpacing(10)

        cmb_set1 = _SetMultiCombo()
        cmb_set2 = _SetMultiCombo()
        cmb_set3 = _SetMultiCombo()
        cmb_set1.setToolTip(tr("tooltip.set_multi"))
        cmb_set2.setToolTip(tr("tooltip.set_multi"))
        cmb_set3.setToolTip(tr("tooltip.set3"))
        cmb_set1.setMinimumWidth(190)
        cmb_set2.setMinimumWidth(190)
        cmb_set3.setMinimumWidth(190)

        slot1_ids, slot2_ids, slot3_ids = self._parse_set_options_to_slot_ids(build.set_options or [])
        cmb_set1.set_checked_ids(slot1_ids)
        cmb_set2.set_checked_ids(slot2_ids)
        cmb_set3.set_checked_ids(slot3_ids)
        cmb_set1.selection_changed.connect(lambda _uid=int(unit_id): self._sync_set_combo_constraints_for_unit(_uid))
        cmb_set2.selection_changed.connect(lambda _uid=int(unit_id): self._sync_set_combo_constraints_for_unit(_uid))
        cmb_set3.selection_changed.connect(lambda _uid=int(unit_id): self._sync_set_combo_constraints_for_unit(_uid))

        cmb2 = self._make_mainstat_combo(SLOT2_DEFAULT)
        cmb4 = self._make_mainstat_combo(SLOT4_DEFAULT)
        cmb6 = self._make_mainstat_combo(SLOT6_DEFAULT)
        if build.mainstats:
            if 2 in build.mainstats and build.mainstats[2]:
                cmb2.set_checked_values([str(x) for x in (build.mainstats[2] or [])])
            if 4 in build.mainstats and build.mainstats[4]:
                cmb4.set_checked_values([str(x) for x in (build.mainstats[4] or [])])
            if 6 in build.mainstats and build.mainstats[6]:
                cmb6.set_checked_values([str(x) for x in (build.mainstats[6] or [])])

        art_attr_focus = self._make_art_focus_combo()
        art_type_focus = self._make_art_focus_combo()
        art_attr_focus.setToolTip(tr("tooltip.art_attr_focus"))
        art_type_focus.setToolTip(tr("tooltip.art_type_focus"))

        artifact_focus = dict(getattr(build, "artifact_focus", {}) or {})
        attr_focus_values = [str(x).upper() for x in (artifact_focus.get("attribute") or []) if str(x)]
        type_focus_values = [str(x).upper() for x in (artifact_focus.get("type") or []) if str(x)]
        if attr_focus_values:
            self._set_art_focus_combo_value(art_attr_focus, attr_focus_values[0])
        if type_focus_values:
            self._set_art_focus_combo_value(art_type_focus, type_focus_values[0])

        art_attr_sub1 = self._make_art_sub_combo(1)
        art_attr_sub2 = self._make_art_sub_combo(1)
        art_type_sub1 = self._make_art_sub_combo(2)
        art_type_sub2 = self._make_art_sub_combo(2)

        artifact_substats = dict(getattr(build, "artifact_substats", {}) or {})
        attr_subs = [int(x) for x in (artifact_substats.get("attribute") or []) if int(x) > 0][:2]
        type_subs = [int(x) for x in (artifact_substats.get("type") or []) if int(x) > 0][:2]
        if attr_subs:
            self._set_art_sub_combo_value(art_attr_sub1, attr_subs[0])
        if len(attr_subs) > 1:
            self._set_art_sub_combo_value(art_attr_sub2, attr_subs[1])
        if type_subs:
            self._set_art_sub_combo_value(art_type_sub1, type_subs[0])
        if len(type_subs) > 1:
            self._set_art_sub_combo_value(art_type_sub2, type_subs[1])

        current_min = dict(getattr(build, "min_stats", {}) or {})
        base_stats = self._unit_base_stats_for_min(int(unit_id))
        min_mode = self._min_mode_for_build(current_min)
        min_mode_combo = self._make_min_mode_combo(min_mode)
        min_spd = self._make_min_stat_spin(self._min_value_for_build(current_min, "SPD", min_mode, base_stats))
        min_hp = self._make_min_stat_spin(self._min_value_for_build(current_min, "HP", min_mode, base_stats))
        min_atk = self._make_min_stat_spin(self._min_value_for_build(current_min, "ATK", min_mode, base_stats))
        min_def = self._make_min_stat_spin(self._min_value_for_build(current_min, "DEF", min_mode, base_stats))
        min_cr = self._make_min_stat_spin(self._min_value_for_build(current_min, "CR", min_mode, base_stats))
        min_cd = self._make_min_stat_spin(self._min_value_for_build(current_min, "CD", min_mode, base_stats))
        min_res = self._make_min_stat_spin(self._min_value_for_build(current_min, "RES", min_mode, base_stats))
        min_acc = self._make_min_stat_spin(self._min_value_for_build(current_min, "ACC", min_mode, base_stats))

        min_spins: Dict[str, QSpinBox] = {
            "SPD": min_spd,
            "HP": min_hp,
            "ATK": min_atk,
            "DEF": min_def,
            "CR": min_cr,
            "CD": min_cd,
            "RES": min_res,
            "ACC": min_acc,
        }
        min_base_prefix_labels: Dict[str, QLabel] = {}

        def _base_prefix(key: str) -> QLabel:
            lbl = QLabel(tr("label.min_base_prefix", value=int(base_stats.get(key, 0) or 0)))
            min_base_prefix_labels[str(key)] = lbl
            return lbl

        rune_sets_box = QGroupBox(tr("group.build_rune_sets"))
        rune_sets_layout = QFormLayout(rune_sets_box)
        rune_sets_layout.addRow(tr("header.set1"), cmb_set1)
        rune_sets_layout.addRow(tr("header.set2"), cmb_set2)
        rune_sets_layout.addRow(tr("header.set3"), cmb_set3)
        pref_btn_row = QWidget()
        pref_btn_layout = QHBoxLayout(pref_btn_row)
        pref_btn_layout.setContentsMargins(0, 0, 0, 0)
        pref_btn_layout.setSpacing(6)
        btn_load_pref_runes = QPushButton(tr("btn.load_preferred_runes"))
        btn_load_pref_runes.setToolTip(
            tr("tooltip.load_preferred_runes") if self._has_rune_pref_for_unit(int(unit_id))
            else tr("tooltip.load_preferred_runes_missing")
        )
        btn_load_pref_runes.clicked.connect(lambda _checked=False, _uid=int(unit_id): self._on_load_preferred_runes_for_unit(_uid))
        btn_save_pref_runes = QPushButton(tr("btn.save_preferred_runes"))
        btn_save_pref_runes.setToolTip(tr("tooltip.save_preferred_runes"))
        btn_save_pref_runes.clicked.connect(lambda _checked=False, _uid=int(unit_id): self._on_save_preferred_runes_for_unit(_uid))
        pref_btn_layout.addWidget(btn_load_pref_runes)
        pref_btn_layout.addWidget(btn_save_pref_runes)
        pref_btn_layout.addStretch(1)
        rune_sets_layout.addRow("", pref_btn_row)

        mainstats_box = QGroupBox(tr("group.build_mainstats"))
        mainstats_layout = QFormLayout(mainstats_box)
        mainstats_layout.addRow(tr("header.slot2_main"), cmb2)
        mainstats_layout.addRow(tr("header.slot4_main"), cmb4)
        mainstats_layout.addRow(tr("header.slot6_main"), cmb6)

        artifact_box = QGroupBox(tr("group.build_artifacts"))
        artifact_layout = QFormLayout(artifact_box)
        artifact_layout.addRow(tr("header.attr_main"), art_attr_focus)
        artifact_layout.addRow(tr("header.attr_sub1"), art_attr_sub1)
        artifact_layout.addRow(tr("header.attr_sub2"), art_attr_sub2)
        artifact_layout.addRow(tr("header.type_main"), art_type_focus)
        artifact_layout.addRow(tr("header.type_sub1"), art_type_sub1)
        artifact_layout.addRow(tr("header.type_sub2"), art_type_sub2)

        top_grid = QGridLayout()
        top_grid.setContentsMargins(0, 0, 0, 0)
        top_grid.setHorizontalSpacing(10)
        top_grid.setVerticalSpacing(8)
        top_grid.addWidget(rune_sets_box, 0, 0)
        top_grid.addWidget(mainstats_box, 0, 1)
        top_grid.addWidget(artifact_box, 0, 2)
        top_grid.setColumnStretch(0, 1)
        top_grid.setColumnStretch(1, 1)
        top_grid.setColumnStretch(2, 1)
        content_layout.addLayout(top_grid)

        min_stats_box = QGroupBox(tr("group.build_min_stats"))
        min_stats_layout = QGridLayout(min_stats_box)
        min_stats_layout.setHorizontalSpacing(12)
        min_stats_layout.setVerticalSpacing(8)
        min_stats_layout.addWidget(QLabel(tr("label.min_mode")), 0, 0)
        min_stats_layout.addWidget(min_mode_combo, 0, 1, 1, 2)
        min_stats_layout.addWidget(QLabel(tr("label.min_mode_hint")), 1, 0, 1, 4)

        def _make_min_stat_cell(label_text: str, stat_key: str, spin: QSpinBox) -> QWidget:
            cell = QWidget()
            row = QHBoxLayout(cell)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(6)
            lbl = QLabel(label_text)
            lbl.setMinimumWidth(56)
            row.addWidget(lbl)
            base_lbl = _base_prefix(stat_key)
            base_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            base_lbl.setMinimumWidth(56)
            row.addWidget(base_lbl)
            spin.setMaximumWidth(92)
            row.addWidget(spin)
            row.addStretch(1)
            return cell

        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_hp"), "HP", min_hp), 2, 0)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_atk"), "ATK", min_atk), 2, 1)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_def"), "DEF", min_def), 2, 2)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_spd"), "SPD", min_spd), 2, 3)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_cr"), "CR", min_cr), 3, 0)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_cd"), "CD", min_cd), 3, 1)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_res"), "RES", min_res), 3, 2)
        min_stats_layout.addWidget(_make_min_stat_cell(tr("header.min_acc"), "ACC", min_acc), 3, 3)
        min_stats_layout.setColumnStretch(4, 1)

        def _sync_min_mode_ui() -> None:
            mode = str(min_mode_combo.currentData() or "with_base")
            use_base = mode == "with_base"
            for lbl in min_base_prefix_labels.values():
                lbl.setVisible(use_base)

        def _on_min_mode_changed() -> None:
            mode = str(min_mode_combo.currentData() or "with_base")
            for key, spin in min_spins.items():
                spin.setValue(self._min_value_for_build(current_min, key, mode, base_stats))
            _sync_min_mode_ui()

        min_mode_combo.currentIndexChanged.connect(lambda *_args: _on_min_mode_changed())
        _sync_min_mode_ui()

        content_layout.addWidget(min_stats_box)
        content_layout.addStretch(1)

        self._set1_combo[unit_id] = cmb_set1
        self._set2_combo[unit_id] = cmb_set2
        self._set3_combo[unit_id] = cmb_set3
        self._ms2_combo[unit_id] = cmb2
        self._ms4_combo[unit_id] = cmb4
        self._ms6_combo[unit_id] = cmb6
        self._art_attr_focus_combo[unit_id] = art_attr_focus
        self._art_type_focus_combo[unit_id] = art_type_focus
        self._art_attr_sub1_combo[unit_id] = art_attr_sub1
        self._art_attr_sub2_combo[unit_id] = art_attr_sub2
        self._art_type_sub1_combo[unit_id] = art_type_sub1
        self._art_type_sub2_combo[unit_id] = art_type_sub2
        self._min_mode_combo[unit_id] = min_mode_combo
        self._min_spd_spin[unit_id] = min_spd
        self._min_hp_spin[unit_id] = min_hp
        self._min_atk_spin[unit_id] = min_atk
        self._min_def_spin[unit_id] = min_def
        self._min_cr_spin[unit_id] = min_cr
        self._min_cd_spin[unit_id] = min_cd
        self._min_res_spin[unit_id] = min_res
        self._min_acc_spin[unit_id] = min_acc
        self._sync_set_combo_constraints_for_unit(int(unit_id))
        return scroll

    def _parse_set_options_to_slot_ids(self, set_options: List[List[str]]) -> Tuple[List[int], List[int], List[int]]:
        parsed: List[List[int]] = []
        for opt in (set_options or []):
            if not isinstance(opt, list):
                continue
            row: List[int] = []
            for name in opt:
                sid = next((int(k) for k, sname in SET_NAMES.items() if sname == str(name)), 0)
                if sid > 0:
                    row.append(int(sid))
            if row:
                parsed.append(row)

        if not parsed:
            return [], [], []

        lengths = {len(r) for r in parsed if r}
        if len(lengths) == 1 and 1 <= next(iter(lengths)) <= 3:
            width = int(next(iter(lengths)))
            slots: List[List[int]] = []
            for pos in range(width):
                vals: List[int] = []
                seen: Set[int] = set()
                for row in parsed:
                    sid = int(row[pos])
                    if sid <= 0 or sid in seen:
                        continue
                    seen.add(sid)
                    vals.append(sid)
                slots.append(vals)
            while len(slots) < 3:
                slots.append([])
            return slots[0], slots[1], slots[2]

        first = [int(x) for x in (parsed[0] if parsed else [])]
        while len(first) < 3:
            first.append(0)
        return [first[0]] if first[0] > 0 else [], [first[1]] if first[1] > 0 else [], [first[2]] if first[2] > 0 else []

    def _is_set3_allowed_for_unit(self, unit_id: int) -> bool:
        c1 = self._set1_combo.get(int(unit_id))
        c2 = self._set2_combo.get(int(unit_id))
        if c1 is None or c2 is None:
            return False
        s1 = c1.checked_sizes()
        s2 = c2.checked_sizes()
        if not c1.checked_ids() or not c2.checked_ids():
            return False
        return s1 == {2} and s2 == {2}

    def _sync_set_combo_constraints_for_unit(self, unit_id: int) -> None:
        c1 = self._set1_combo.get(int(unit_id))
        c2 = self._set2_combo.get(int(unit_id))
        c3 = self._set3_combo.get(int(unit_id))
        if c1 is None or c2 is None or c3 is None:
            return

        c1.set_enforced_size(None)
        c2.set_enforced_size(None)

        allow_set3 = self._is_set3_allowed_for_unit(int(unit_id))
        if allow_set3:
            c3.setEnabled(True)
            c3.set_enforced_size(2)
        else:
            c3.clear_checked()
            c3.set_enforced_size(None)
            c3.setEnabled(False)

    def _load_rune_pref_entries(self) -> Dict[int, Dict[str, Any]]:
        if self._rune_pref_entries_by_master_id is not None:
            return dict(self._rune_pref_entries_by_master_id)
        out: Dict[int, Dict[str, Any]] = {}
        p = Path(_RUNE_PREFS_PATH)
        if p.exists():
            try:
                raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                raw = {}
            if isinstance(raw, dict):
                by_id = raw.get("by_com2us_id", raw)
                if isinstance(by_id, dict):
                    for mid_raw, entry_raw in by_id.items():
                        try:
                            mid = int(mid_raw or 0)
                        except Exception:
                            continue
                        if mid <= 0 or not isinstance(entry_raw, dict):
                            continue
                        out[int(mid)] = dict(entry_raw or {})
        self._rune_pref_entries_by_master_id = dict(out)
        return dict(out)

    def _unit_master_id_for_unit(self, unit_id: int) -> int:
        uid = int(unit_id or 0)
        if uid <= 0:
            return 0
        if self._account:
            u = self._account.units_by_id.get(int(uid))
            if u is not None and int(getattr(u, "unit_master_id", 0) or 0) > 0:
                return int(getattr(u, "unit_master_id", 0) or 0)
        # Fallback (e.g. without account context).
        return int(uid)

    def _rune_pref_entry_for_unit(self, unit_id: int) -> Dict[str, Any] | None:
        entries = self._load_rune_pref_entries()
        mid = self._unit_master_id_for_unit(int(unit_id))
        if int(mid) > 0 and isinstance(entries.get(int(mid)), dict):
            return dict(entries[int(mid)])
        uid = int(unit_id or 0)
        if uid > 0 and isinstance(entries.get(int(uid)), dict):
            return dict(entries[int(uid)])
        return None

    def _has_rune_pref_for_unit(self, unit_id: int) -> bool:
        return isinstance(self._rune_pref_entry_for_unit(int(unit_id)), dict)

    def _normalize_mainstat_pref_key(self, value: Any) -> str:
        raw = str(value or "").strip().upper().replace(" ", "")
        if not raw:
            return ""
        mapping = {
            "HP": "HP%",
            "HP%": "HP%",
            "HPP": "HP%",
            "ATK": "ATK%",
            "ATK%": "ATK%",
            "ATKP": "ATK%",
            "DEF": "DEF%",
            "DEF%": "DEF%",
            "DEFP": "DEF%",
            "SPD": "SPD",
            "CR": "CR",
            "CD": "CD",
            "RES": "RES",
            "ACC": "ACC",
        }
        key = mapping.get(raw, raw)
        return str(key) if str(key) in MAINSTAT_KEYS else ""

    def _rune_pref_slot_set_ids(self, entry: Dict[str, Any]) -> Tuple[List[int], List[int], List[int]]:
        combos_raw = list(entry.get("top_set_combos") or []) + list(entry.get("preferred_set_combos") or [])
        combos: List[List[int]] = []
        seen_combo_keys: Set[Tuple[int, ...]] = set()
        for combo in combos_raw:
            if not isinstance(combo, (list, tuple)):
                continue
            row: List[int] = []
            for x in list(combo)[:3]:
                sid = int(x or 0)
                if sid > 0 and sid in SET_NAMES:
                    row.append(int(sid))
            if row:
                key = tuple(int(v) for v in row)
                if key in seen_combo_keys:
                    continue
                seen_combo_keys.add(key)
                combos.append(row)

        # Fallback: derive coverage-friendly combos from top/preferred set IDs.
        if not combos:
            ranked_ids: List[int] = []
            for sid in [int(x) for x in (entry.get("top_set_ids") or []) + (entry.get("preferred_set_ids") or [])]:
                if sid > 0 and sid in SET_NAMES and sid not in ranked_ids:
                    ranked_ids.append(int(sid))
                if len(ranked_ids) >= 8:
                    break
            four_sets = [sid for sid in ranked_ids if int(SET_SIZES.get(int(sid), 2) or 2) == 4]
            two_sets = [sid for sid in ranked_ids if int(SET_SIZES.get(int(sid), 2) or 2) == 2]
            if four_sets and two_sets:
                for a in four_sets:
                    for b in two_sets:
                        combos.append([int(a), int(b)])
                        if len(combos) >= 12:
                            break
                    if len(combos) >= 12:
                        break
            elif len(two_sets) >= 2:
                for a, b in combinations(two_sets, 2):
                    combos.append([int(a), int(b)])
                    if len(combos) >= 12:
                        break
                if len(two_sets) >= 3 and len(combos) < 12:
                    for a, b, c in combinations(two_sets, 3):
                        combos.append([int(a), int(b), int(c)])
                        if len(combos) >= 12:
                            break
            elif ranked_ids:
                combos = [[int(sid)] for sid in ranked_ids[:3]]

        if combos:
            by_width: Dict[int, List[List[int]]] = {1: [], 2: [], 3: []}
            for row in combos:
                w = int(len(row))
                if 1 <= w <= 3:
                    by_width[w].append(list(row))

            best_layout: Tuple[List[int], List[int], List[int]] | None = None
            best_score: Tuple[int, int] = (-1, -1)  # (covered combos, width)
            for width in (3, 2, 1):
                rows = list(by_width.get(int(width), []) or [])
                if not rows:
                    continue
                slots: List[List[int]] = []
                for pos in range(int(width)):
                    vals: List[int] = []
                    seen_vals: Set[int] = set()
                    for row in rows:
                        sid = int(row[pos] or 0)
                        if sid <= 0 or sid in seen_vals:
                            continue
                        seen_vals.add(int(sid))
                        vals.append(int(sid))
                    slots.append(vals)
                while len(slots) < 3:
                    slots.append([])
                s1, s2, s3 = slots[0], slots[1], slots[2]
                # UI constraint: Set 3 only available if Set1+Set2 are both 2-set only.
                if width == 3:
                    if any(int(SET_SIZES.get(int(sid), 2) or 2) != 2 for sid in (s1 + s2)):
                        continue
                covered = len(rows)
                score = (int(covered), int(width))
                if score > best_score:
                    best_score = score
                    best_layout = (list(s1), list(s2), list(s3))

            if best_layout is not None:
                return best_layout

            first = list(combos[0])
            while len(first) < 3:
                first.append(0)
            return (
                [int(first[0])] if int(first[0]) > 0 else [],
                [int(first[1])] if int(first[1]) > 0 else [],
                [int(first[2])] if int(first[2]) > 0 else [],
            )

        top_set_ids = [int(x) for x in (entry.get("top_set_ids") or []) if int(x) > 0 and int(x) in SET_NAMES]
        while len(top_set_ids) < 3:
            top_set_ids.append(0)
        return (
            [int(top_set_ids[0])] if int(top_set_ids[0]) > 0 else [],
            [int(top_set_ids[1])] if int(top_set_ids[1]) > 0 else [],
            [int(top_set_ids[2])] if int(top_set_ids[2]) > 0 else [],
        )

    def _rune_pref_mainstats_by_slot(self, entry: Dict[str, Any]) -> Dict[int, List[str]]:
        out: Dict[int, List[str]] = {2: [], 4: [], 6: []}
        by_slot = entry.get("top_mainstats_by_slot")
        if isinstance(by_slot, dict):
            for slot in (2, 4, 6):
                vals_raw = by_slot.get(str(slot), by_slot.get(int(slot), []))
                for raw in list(vals_raw or []):
                    key = self._normalize_mainstat_pref_key(raw)
                    if key and key not in out[slot]:
                        out[slot].append(key)

        combos_raw = list(entry.get("top_mainstat_combos_246") or [])
        for combo in combos_raw:
            if not isinstance(combo, (list, tuple)) or len(combo) < 3:
                continue
            for idx, slot in enumerate((2, 4, 6)):
                key = self._normalize_mainstat_pref_key(combo[idx])
                if key and key not in out[slot]:
                    out[slot].append(key)

        return {
            2: [str(x) for x in out[2] if str(x) in MAINSTAT_KEYS],
            4: [str(x) for x in out[4] if str(x) in MAINSTAT_KEYS],
            6: [str(x) for x in out[6] if str(x) in MAINSTAT_KEYS],
        }

    def _normalized_set_options_for_unit(self, unit_id: int) -> List[List[int]]:
        self._sync_set_combo_constraints_for_unit(int(unit_id))
        c1 = self._set1_combo.get(int(unit_id))
        c2 = self._set2_combo.get(int(unit_id))
        c3 = self._set3_combo.get(int(unit_id))
        if c1 is None or c2 is None or c3 is None:
            return []

        set1_ids = [int(x) for x in c1.checked_ids()]
        set2_ids = [int(x) for x in c2.checked_ids()]
        set3_ids = [int(x) for x in c3.checked_ids()] if self._is_set3_allowed_for_unit(int(unit_id)) else []

        groups: List[List[int]] = []
        if set1_ids:
            groups.append(set1_ids)
        if set2_ids:
            groups.append(set2_ids)
        if set3_ids:
            groups.append(set3_ids)
        if not groups:
            return []

        normalized: List[List[int]] = []
        seen_opts: Set[Tuple[int, ...]] = set()
        for opt in product(*groups):
            cleaned: List[int] = []
            for sid in opt:
                sid_i = int(sid or 0)
                if sid_i <= 0 or sid_i not in SET_NAMES:
                    continue
                cleaned.append(int(sid_i))
            if not cleaned:
                continue
            total_pieces = sum(int(SET_SIZES.get(int(sid), 2) or 2) for sid in cleaned)
            if int(total_pieces) > 6:
                continue
            key = tuple(cleaned)
            if key in seen_opts:
                continue
            seen_opts.add(key)
            normalized.append(list(cleaned))
        return normalized

    def _current_mainstats_by_slot_for_unit(self, unit_id: int) -> Dict[int, List[str]]:
        out: Dict[int, List[str]] = {2: [], 4: [], 6: []}
        cmb2 = self._ms2_combo.get(int(unit_id))
        cmb4 = self._ms4_combo.get(int(unit_id))
        cmb6 = self._ms6_combo.get(int(unit_id))
        if cmb2 is not None:
            out[2] = [str(x) for x in (cmb2.checked_values() or []) if str(x) in MAINSTAT_KEYS]
        if cmb4 is not None:
            out[4] = [str(x) for x in (cmb4.checked_values() or []) if str(x) in MAINSTAT_KEYS]
        if cmb6 is not None:
            out[6] = [str(x) for x in (cmb6.checked_values() or []) if str(x) in MAINSTAT_KEYS]
        return out

    def _current_mainstat_combos_246_for_unit(self, unit_id: int, limit: int = 12) -> List[List[str]]:
        by_slot = self._current_mainstats_by_slot_for_unit(int(unit_id))
        s2 = list(by_slot.get(2) or [])
        s4 = list(by_slot.get(4) or [])
        s6 = list(by_slot.get(6) or [])
        if not s2 or not s4 or not s6:
            return []
        out: List[List[str]] = []
        for a, b, c in product(s2, s4, s6):
            out.append([str(a), str(b), str(c)])
            if len(out) >= int(max(1, int(limit or 1))):
                break
        return out

    def _element_name_for_master_id(self, master_id: int) -> str:
        elem_map = {1: "Water", 2: "Fire", 3: "Wind", 4: "Light", 5: "Dark"}
        m = int(master_id or 0)
        if m <= 0:
            return ""
        return str(elem_map.get(int(m % 10), "") or "")

    def _save_rune_pref_entry(self, master_id: int, payload: Dict[str, Any]) -> bool:
        mid = int(master_id or 0)
        if mid <= 0:
            return False
        p = Path(_RUNE_PREFS_PATH)
        raw: Dict[str, Any] = {}
        if p.exists():
            try:
                loaded = json.loads(p.read_text(encoding="utf-8", errors="replace"))
                if isinstance(loaded, dict):
                    raw = dict(loaded)
            except Exception:
                raw = {}
        by_id = raw.get("by_com2us_id")
        if isinstance(by_id, dict):
            entries = dict(by_id)
            raw["by_com2us_id"] = entries
        else:
            # Keep compat for legacy flat files, but prefer explicit envelope.
            entries = {}
            for k, v in dict(raw).items():
                try:
                    if int(k) > 0 and isinstance(v, dict):
                        entries[str(int(k))] = dict(v)
                except Exception:
                    continue
            raw["by_com2us_id"] = entries

        existing = dict(entries.get(str(mid), {}) or {})
        existing.update(dict(payload or {}))
        entries[str(mid)] = existing
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self._rune_pref_entries_by_master_id = None
        return True

    def _on_load_preferred_runes_for_unit(self, unit_id: int) -> None:
        entry = self._rune_pref_entry_for_unit(int(unit_id))
        if not isinstance(entry, dict):
            return

        slot1_ids, slot2_ids, slot3_ids = self._rune_pref_slot_set_ids(entry)
        c1 = self._set1_combo.get(int(unit_id))
        c2 = self._set2_combo.get(int(unit_id))
        c3 = self._set3_combo.get(int(unit_id))
        if c1 is not None and slot1_ids:
            c1.set_checked_ids(slot1_ids)
        if c2 is not None and slot2_ids:
            c2.set_checked_ids(slot2_ids)
        if c3 is not None and slot3_ids:
            c3.set_checked_ids(slot3_ids)
        self._sync_set_combo_constraints_for_unit(int(unit_id))

        by_slot = self._rune_pref_mainstats_by_slot(entry)
        cmb2 = self._ms2_combo.get(int(unit_id))
        cmb4 = self._ms4_combo.get(int(unit_id))
        cmb6 = self._ms6_combo.get(int(unit_id))
        if cmb2 is not None and by_slot.get(2):
            cmb2.set_checked_values(list(by_slot[2]))
        if cmb4 is not None and by_slot.get(4):
            cmb4.set_checked_values(list(by_slot[4]))
        if cmb6 is not None and by_slot.get(6):
            cmb6.set_checked_values(list(by_slot[6]))

    def _on_load_preferred_runes_for_all(self) -> None:
        """Load preferred rune sets and mainstats for all units that have preferences."""
        self._ensure_all_editor_pages()
        for unit_id in list(self._set1_combo.keys()):
            self._on_load_preferred_runes_for_unit(int(unit_id))

    def _on_save_preferred_runes_for_unit(self, unit_id: int) -> None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return
        master_id = self._unit_master_id_for_unit(uid)
        if master_id <= 0:
            return

        combos = self._normalized_set_options_for_unit(uid)
        top_set_combos = [list(c) for c in combos[:6]]
        top_set_ids: List[int] = []
        for combo in top_set_combos:
            for sid in combo:
                si = int(sid or 0)
                if si > 0 and si in SET_NAMES and si not in top_set_ids:
                    top_set_ids.append(int(si))
                if len(top_set_ids) >= 6:
                    break
            if len(top_set_ids) >= 6:
                break
        if not top_set_ids:
            return

        main_by_slot = self._current_mainstats_by_slot_for_unit(uid)
        main_combos = self._current_mainstat_combos_246_for_unit(uid, limit=12)
        existing = self._rune_pref_entry_for_unit(uid) or {}
        merged_pref_ids: List[int] = []
        for sid in top_set_ids + [int(x) for x in (existing.get("preferred_set_ids") or []) if int(x) > 0]:
            si = int(sid or 0)
            if si > 0 and si in SET_NAMES and si not in merged_pref_ids:
                merged_pref_ids.append(int(si))
            if len(merged_pref_ids) >= 10:
                break

        unit_label = str(self._unit_label_by_id.get(uid, f"Unit {uid}") or f"Unit {uid}")
        payload: Dict[str, Any] = {
            "name": str(existing.get("name") or unit_label),
            "element": str(existing.get("element") or self._element_name_for_master_id(master_id)),
            "archetype": str(existing.get("archetype") or "Unknown"),
            "awaken_level": int(existing.get("awaken_level", 1) or 1),
            "top_set_ids": list(top_set_ids[:3]),
            "preferred_set_ids": list(merged_pref_ids[:10]),
            "top_set_combos": list(top_set_combos),
            "preferred_set_combos": list(top_set_combos),
            "top_mainstats_by_slot": {
                "2": list(main_by_slot.get(2) or []),
                "4": list(main_by_slot.get(4) or []),
                "6": list(main_by_slot.get(6) or []),
            },
            "top_mainstat_combos_246": list(main_combos),
        }
        if "base_stars" in existing:
            payload["base_stars"] = int(existing.get("base_stars", 0) or 0)
        elif self._account:
            unit_obj = self._account.units_by_id.get(uid)
            if unit_obj is not None:
                payload["base_stars"] = int(getattr(unit_obj, "unit_class", 0) or 0)
        self._save_rune_pref_entry(master_id=master_id, payload=payload)

    def _apply_build_to_unit_controls(self, unit_id: int, build: Build) -> None:
        uid = int(unit_id or 0)
        if uid <= 0:
            return
        self._ensure_editor_page(int(uid))

        c1 = self._set1_combo.get(int(uid))
        c2 = self._set2_combo.get(int(uid))
        c3 = self._set3_combo.get(int(uid))
        slot1_ids, slot2_ids, slot3_ids = self._parse_set_options_to_slot_ids(list(build.set_options or []))
        if c1 is not None:
            c1.set_checked_ids(list(slot1_ids))
        if c2 is not None:
            c2.set_checked_ids(list(slot2_ids))
        if c3 is not None:
            c3.set_checked_ids(list(slot3_ids))
        self._sync_set_combo_constraints_for_unit(int(uid))

        mainstats = dict(getattr(build, "mainstats", {}) or {})
        ms2_vals = list(mainstats.get(2) or mainstats.get("2") or [])
        ms4_vals = list(mainstats.get(4) or mainstats.get("4") or [])
        ms6_vals = list(mainstats.get(6) or mainstats.get("6") or [])
        cmb2 = self._ms2_combo.get(int(uid))
        cmb4 = self._ms4_combo.get(int(uid))
        cmb6 = self._ms6_combo.get(int(uid))
        if cmb2 is not None:
            cmb2.set_checked_values([str(x) for x in ms2_vals if str(x) in MAINSTAT_KEYS])
        if cmb4 is not None:
            cmb4.set_checked_values([str(x) for x in ms4_vals if str(x) in MAINSTAT_KEYS])
        if cmb6 is not None:
            cmb6.set_checked_values([str(x) for x in ms6_vals if str(x) in MAINSTAT_KEYS])

        artifact_focus = dict(getattr(build, "artifact_focus", {}) or {})
        attr_focus_values = [str(x).upper() for x in (artifact_focus.get("attribute") or []) if str(x)]
        type_focus_values = [str(x).upper() for x in (artifact_focus.get("type") or []) if str(x)]
        art_attr_focus = self._art_attr_focus_combo.get(int(uid))
        art_type_focus = self._art_type_focus_combo.get(int(uid))
        if art_attr_focus is not None:
            idx_any = art_attr_focus.findData("")
            if idx_any >= 0:
                art_attr_focus.setCurrentIndex(int(idx_any))
            if attr_focus_values:
                self._set_art_focus_combo_value(art_attr_focus, attr_focus_values[0])
        if art_type_focus is not None:
            idx_any = art_type_focus.findData("")
            if idx_any >= 0:
                art_type_focus.setCurrentIndex(int(idx_any))
            if type_focus_values:
                self._set_art_focus_combo_value(art_type_focus, type_focus_values[0])

        artifact_substats = dict(getattr(build, "artifact_substats", {}) or {})
        attr_subs = [int(x) for x in (artifact_substats.get("attribute") or []) if int(x) > 0][:2]
        type_subs = [int(x) for x in (artifact_substats.get("type") or []) if int(x) > 0][:2]
        art_attr_sub1 = self._art_attr_sub1_combo.get(int(uid))
        art_attr_sub2 = self._art_attr_sub2_combo.get(int(uid))
        art_type_sub1 = self._art_type_sub1_combo.get(int(uid))
        art_type_sub2 = self._art_type_sub2_combo.get(int(uid))
        for cmb in (art_attr_sub1, art_attr_sub2, art_type_sub1, art_type_sub2):
            if cmb is None:
                continue
            idx_any = cmb.findData(0)
            if idx_any >= 0:
                cmb.setCurrentIndex(int(idx_any))
        if art_attr_sub1 is not None and len(attr_subs) >= 1:
            self._set_art_sub_combo_value(art_attr_sub1, int(attr_subs[0]))
        if art_attr_sub2 is not None and len(attr_subs) >= 2:
            self._set_art_sub_combo_value(art_attr_sub2, int(attr_subs[1]))
        if art_type_sub1 is not None and len(type_subs) >= 1:
            self._set_art_sub_combo_value(art_type_sub1, int(type_subs[0]))
        if art_type_sub2 is not None and len(type_subs) >= 2:
            self._set_art_sub_combo_value(art_type_sub2, int(type_subs[1]))

        current_min = dict(getattr(build, "min_stats", {}) or {})
        base_stats = self._unit_base_stats_for_min(int(uid))
        min_mode = self._min_mode_for_build(current_min)
        min_mode_combo = self._min_mode_combo.get(int(uid))
        if min_mode_combo is not None:
            idx = min_mode_combo.findData(str(min_mode))
            if idx >= 0:
                min_mode_combo.setCurrentIndex(int(idx))
        spin_by_key: Dict[str, QSpinBox | None] = {
            "SPD": self._min_spd_spin.get(int(uid)),
            "HP": self._min_hp_spin.get(int(uid)),
            "ATK": self._min_atk_spin.get(int(uid)),
            "DEF": self._min_def_spin.get(int(uid)),
            "CR": self._min_cr_spin.get(int(uid)),
            "CD": self._min_cd_spin.get(int(uid)),
            "RES": self._min_res_spin.get(int(uid)),
            "ACC": self._min_acc_spin.get(int(uid)),
        }
        for stat_key, spin in spin_by_key.items():
            if spin is None:
                continue
            spin.setValue(int(self._min_value_for_build(current_min, str(stat_key), str(min_mode), base_stats)))

        target_tick = int(getattr(build, "spd_tick", 0) or 0)
        for tick_cmb in list(self._team_spd_tick_combo_by_unit.get(int(uid), []) or []):
            idx = tick_cmb.findData(int(target_tick))
            tick_cmb.setCurrentIndex(int(idx) if idx >= 0 else 0)

    def _on_restore_saved_preset(self) -> None:
        self._ensure_all_editor_pages()
        for unit_id, build in self._initial_build_by_unit.items():
            self._apply_build_to_unit_controls(int(unit_id), copy.deepcopy(build))
        self._restore_unit_list_uid_order(list(self._initial_unit_list_order))

        for team_idx, cmb in self._team_speed_lead_combo_by_team.items():
            target_uid = int(self._initial_team_speed_lead_by_team.get(int(team_idx), 0) or 0)
            idx = cmb.findData(int(target_uid))
            cmb.setCurrentIndex(int(idx) if idx >= 0 else 0)
        for team_idx, spin in self._team_speed_lead_pct_spin_by_team.items():
            val = int(self._initial_team_speed_lead_pct_by_team.get(int(team_idx), int(spin.value())) or 0)
            spin.setValue(max(int(spin.minimum()), min(int(spin.maximum()), int(val))))
        for key, controls in self._team_effect_controls.items():
            team_idx = int(key[0])
            uid = int(key[1])
            raw = dict(self._initial_team_effect_control_state.get((team_idx, uid), {}) or {})
            spd_chk, atb_chk, atb_spin = controls
            spd_chk.setChecked(bool(raw.get("applies_spd_buff", False)))
            atb_chk.setChecked(bool(raw.get("atb_boost_enabled", False)))
            atb_val = int(raw.get("atb_boost_pct", 0) or 0)
            atb_spin.setValue(max(int(atb_spin.minimum()), min(int(atb_spin.maximum()), int(atb_val))))

        # Undo accidental "load current runes" so comparison snapshot is not carried over.
        self._loaded_current_runes = False
        self._loaded_current_runes_snapshot = {}

    def _on_load_current_runes(self) -> None:
        """Load currently equipped rune sets and mainstats for all units."""
        if not self._account:
            return
        # This action updates all units, so ensure all editors exist first.
        self._ensure_all_editor_pages()
        rune_mode = self._rune_mode_for_load_current_runes()
        for unit_id in list(self._set1_combo.keys()):
            equipped = self._account.equipped_runes_for(int(unit_id), rune_mode)
            if not equipped:
                continue
            # Count complete set instances (e.g. 6x Shield => 3 complete Shield sets).
            set_counts: Dict[int, int] = {}
            for r in equipped:
                sid = int(r.set_id or 0)
                if sid > 0:
                    set_counts[sid] = set_counts.get(sid, 0) + 1
            active_sets: List[int] = []
            for sid, cnt in set_counts.items():
                if sid not in SET_NAMES:
                    continue
                required = int(SET_SIZES.get(sid, 2))
                if required <= 0:
                    continue
                complete_count = int(cnt // required)
                for _ in range(max(0, complete_count)):
                    active_sets.append(int(sid))
            # Distribute into set slots by size: 4-sets first, then 2-sets
            active_sets.sort(key=lambda s: (-int(SET_SIZES.get(s, 2)), s))
            slot1_ids: List[int] = []
            slot2_ids: List[int] = []
            slot3_ids: List[int] = []
            for sid in active_sets:
                if not slot1_ids:
                    slot1_ids.append(sid)
                elif not slot2_ids:
                    slot2_ids.append(sid)
                else:
                    slot3_ids.append(sid)
            c1 = self._set1_combo.get(unit_id)
            c2 = self._set2_combo.get(unit_id)
            c3 = self._set3_combo.get(unit_id)
            if c1:
                c1.set_checked_ids(slot1_ids)
            if c2:
                c2.set_checked_ids(slot2_ids)
            if c3:
                c3.set_checked_ids(slot3_ids)
            self._sync_set_combo_constraints_for_unit(int(unit_id))
            # Load mainstats from slots 2, 4, 6
            for r in equipped:
                slot = int(r.slot_no or 0)
                if slot not in (2, 4, 6):
                    continue
                eff_id = int(r.pri_eff[0] or 0) if r.pri_eff else 0
                ms_key = EFFECT_ID_TO_MAINSTAT_KEY.get(eff_id, "")
                if not ms_key:
                    continue
                cmb = None
                if slot == 2:
                    cmb = self._ms2_combo.get(unit_id)
                elif slot == 4:
                    cmb = self._ms4_combo.get(unit_id)
                elif slot == 6:
                    cmb = self._ms6_combo.get(unit_id)
                if cmb:
                    cmb.set_checked_values([ms_key])
        self._loaded_current_runes = True
        self._loaded_current_runes_snapshot = self._capture_current_runes_snapshot(rune_mode)

    def _can_load_current_runes(self) -> bool:
        mode_key = str(self.mode or "").strip().lower()
        return bool(self._account) and mode_key in ("siege", "wgb", "rta", "arena_rush")

    def _rune_mode_for_load_current_runes(self) -> str:
        mode_key = str(self.mode or "").strip().lower()
        if mode_key == "rta":
            return "rta"
        if mode_key in ("siege", "wgb"):
            # PvP/Siege equips from guild_rune_equip.
            return "siege"
        if mode_key == "arena_rush":
            # Arena Rush preloads current PvE equips.
            return "pve"
        return "pve"

    def _capture_current_runes_snapshot(self, rune_mode: str) -> Dict[str, Any]:
        if not self._account:
            return {}
        runes_by_unit: Dict[int, Dict[int, int]] = {}
        artifacts_by_unit: Dict[int, Dict[int, int]] = {}
        for unit_id in [int(uid) for uid in self._unit_rows_by_uid.keys() if int(uid) > 0]:
            equipped = self._account.equipped_runes_for(int(unit_id), str(rune_mode))
            slot_map: Dict[int, int] = {}
            for rune in (equipped or []):
                slot = int(getattr(rune, "slot_no", 0) or 0)
                rid = int(getattr(rune, "rune_id", 0) or 0)
                if 1 <= slot <= 6 and rid > 0:
                    slot_map[int(slot)] = int(rid)
            if slot_map:
                runes_by_unit[int(unit_id)] = slot_map

            art_map = self._equipped_artifacts_for_unit(int(unit_id), str(rune_mode))
            if art_map:
                artifacts_by_unit[int(unit_id)] = art_map

        return {
            "mode": str(rune_mode),
            "runes_by_unit": runes_by_unit,
            "artifacts_by_unit": artifacts_by_unit,
        }

    def _equipped_artifacts_for_unit(self, unit_id: int, rune_mode: str) -> Dict[int, int]:
        if not self._account:
            return {}
        uid = int(unit_id or 0)
        if uid <= 0:
            return {}

        by_id = {int(a.artifact_id): a for a in (self._account.artifacts or [])}
        out: Dict[int, int] = {}

        if str(rune_mode).strip().lower() == "rta":
            for aid in (self._account.rta_artifact_equip.get(int(uid), []) or []):
                art = by_id.get(int(aid))
                if art is None:
                    continue
                art_type = int(getattr(art, "type_", 0) or 0)
                if art_type in (1, 2) and art_type not in out:
                    out[int(art_type)] = int(aid)
            if len(out) >= 2:
                return out

        for art in (self._account.artifacts or []):
            if int(getattr(art, "occupied_id", 0) or 0) != int(uid):
                continue
            art_type = int(getattr(art, "type_", 0) or 0)
            aid = int(getattr(art, "artifact_id", 0) or 0)
            if art_type in (1, 2) and aid > 0 and art_type not in out:
                out[int(art_type)] = int(aid)
        return out

    def loaded_current_runes_snapshot(self) -> Dict[str, Any] | None:
        if not bool(self._loaded_current_runes):
            return None
        snap = dict(self._loaded_current_runes_snapshot or {})
        if not snap:
            return None
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
        return {
            "mode": str(snap.get("mode", "")),
            "runes_by_unit": runes_by_unit,
            "artifacts_by_unit": artifacts_by_unit,
        }

    def _optimize_order_by_unit(self) -> Dict[int, int]:
        source = self._opt_order_list or self._unit_list
        if not source:
            return {}
        out: Dict[int, int] = {}
        for idx in range(source.count()):
            it = source.item(idx)
            uid = int(it.data(Qt.UserRole) or 0) if it else 0
            if uid:
                out[uid] = idx + 1
        return out

    def _team_turn_order_by_unit(self) -> Dict[int, int]:
        if not self._team_order_lists:
            return {}
        out: Dict[int, int] = {}
        for lw in self._team_order_lists:
            for idx in range(lw.count()):
                it = lw.item(idx)
                uid = int(it.data(Qt.UserRole) or 0)
                if uid:
                    out[uid] = idx + 1
        return out

    def _team_spd_tick_by_unit(self) -> Dict[int, int]:
        if not self._team_spd_tick_combo_by_unit:
            return {}
        out: Dict[int, int] = {}
        for uid, cmb_list in self._team_spd_tick_combo_by_unit.items():
            if not cmb_list:
                continue
            cmb0 = cmb_list[0]
            out[int(uid)] = int(cmb0.currentData() or 0)
        return out

    def _on_team_spd_tick_changed(self, uid: int, source_cmb: QComboBox) -> None:
        if self._syncing_team_spd_tick:
            return
        combos = list(self._team_spd_tick_combo_by_unit.get(int(uid), []) or [])
        if len(combos) <= 1:
            return
        target_tick = int(source_cmb.currentData() or 0)
        self._syncing_team_spd_tick = True
        try:
            for cmb in combos:
                if cmb is source_cmb:
                    continue
                idx = cmb.findData(int(target_tick))
                if idx >= 0 and cmb.currentIndex() != idx:
                    cmb.setCurrentIndex(idx)
        finally:
            self._syncing_team_spd_tick = False

    def _build_team_header_with_speed_lead(self, team_index: int, team_title: str, team_units: List[Tuple[int, str]]) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(QLabel(f"<b>{team_title}</b>"))
        row.addStretch(1)
        row.addWidget(QLabel("SPD Lead"))
        cmb = _NoScrollComboBox()
        cmb.setMinimumWidth(180)
        cmb.addItem("-", 0)
        for uid, label in team_units:
            pct = int(self._order_speed_lead_pct_by_unit.get(int(uid), 0) or 0)
            if pct <= 0:
                continue
            cmb.addItem(f"{label} (+{pct}%)", int(uid))
        preferred_uid = int(self._order_speed_leaders[int(team_index)]) if int(team_index) < len(self._order_speed_leaders) else 0
        idx = cmb.findData(int(preferred_uid))
        if idx < 0 and cmb.count() > 1:
            idx = 1
        cmb.setCurrentIndex(max(0, idx))
        cmb.setEnabled(bool(cmb.count() > 1))
        row.addWidget(cmb)
        pct_spin = QSpinBox()
        pct_spin.setMinimum(0)
        pct_spin.setMaximum(100)
        pct_spin.setSingleStep(1)
        pct_spin.setSuffix("%")
        pct_spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        pct_spin.setReadOnly(True)
        pct_spin.setMaximumWidth(64)
        preferred_pct = int(self._order_speed_lead_pct_by_team[int(team_index)]) if int(team_index) < len(self._order_speed_lead_pct_by_team) else 0
        if preferred_pct <= 0:
            selected_uid = int(cmb.currentData() or 0)
            preferred_pct = int(self._order_speed_lead_pct_by_unit.get(int(selected_uid), 0) or 0)
        pct_spin.setValue(max(0, min(100, int(preferred_pct))))
        row.addWidget(pct_spin)
        def _sync_pct_from_selected(_idx: int, _cmb=cmb, _spin=pct_spin) -> None:
            sel_uid = int(_cmb.currentData() or 0)
            known_pct = int(self._order_speed_lead_pct_by_unit.get(int(sel_uid), 0) or 0)
            _spin.setValue(max(0, min(100, int(known_pct))))
        cmb.currentIndexChanged.connect(_sync_pct_from_selected)
        self._team_speed_lead_combo_by_team[int(team_index)] = cmb
        self._team_speed_lead_pct_spin_by_team[int(team_index)] = pct_spin
        return row

    def team_order_by_lists(self) -> List[List[int]]:
        out: List[List[int]] = []
        for lw in self._team_order_lists:
            row: List[int] = []
            for idx in range(lw.count()):
                it = lw.item(idx)
                uid = int(it.data(Qt.UserRole) or 0) if it else 0
                if uid > 0:
                    row.append(uid)
            out.append(row)
        return out

    def team_speed_lead_by_lists(self) -> List[int]:
        out: List[int] = []
        for t, _lw in enumerate(self._team_order_lists):
            cmb = self._team_speed_lead_combo_by_team.get(int(t))
            out.append(int(cmb.currentData() or 0) if cmb is not None else 0)
        return out

    def team_speed_lead_pct_by_lists(self) -> List[int]:
        out: List[int] = []
        for t, _lw in enumerate(self._team_order_lists):
            spin = self._team_speed_lead_pct_spin_by_team.get(int(t))
            out.append(int(spin.value()) if spin is not None else 0)
        return out

    def team_turn_effects_by_lists(self) -> List[Dict[int, Dict[str, Any]]]:
        out: List[Dict[int, Dict[str, Any]]] = []
        for t, lw in enumerate(self._team_order_lists):
            row_cfg: Dict[int, Dict[str, Any]] = {}
            for idx in range(lw.count()):
                it = lw.item(idx)
                uid = int(it.data(Qt.UserRole) or 0) if it else 0
                if uid <= 0:
                    continue
                controls = self._team_effect_controls.get((int(t), int(uid)))
                if not controls:
                    continue
                spd_buff_chk, atb_boost_chk, atb_boost_spin = controls
                atb_boost_pct = float(atb_boost_spin.value()) if bool(atb_boost_chk.isChecked()) else 0.0
                applies_spd_buff = bool(spd_buff_chk.isChecked())
                if not applies_spd_buff and atb_boost_pct <= 0.0:
                    continue
                row_cfg[int(uid)] = {
                    "applies_spd_buff": bool(applies_spd_buff),
                    "atb_boost_pct": float(atb_boost_pct),
                    "include_caster": True,
                }
            out.append(row_cfg)
        return out

    def _team_title(self, team_index: int) -> str:
        if 0 <= int(team_index) < len(self._order_team_titles):
            title = str(self._order_team_titles[int(team_index)] or "").strip()
            if title:
                return title
        return f"Team {int(team_index) + 1}"

    def _has_spd_buff_before_turn(
        self,
        team_order: List[int],
        team_effect_cfg: Dict[int, Dict[str, Any]],
        target_uid: int,
    ) -> bool:
        order = [int(uid) for uid in (team_order or []) if int(uid) > 0]
        tu = int(target_uid or 0)
        if tu <= 0 or tu not in order:
            return False
        pos_target = order.index(int(tu))
        for pos, caster_uid in enumerate(order):
            if pos >= pos_target:
                break
            cfg = dict((team_effect_cfg or {}).get(int(caster_uid), {}) or {})
            if bool(cfg.get("applies_spd_buff", False)):
                return True
        return False

    def _atb_boost_before_turn_pct(
        self,
        team_order: List[int],
        team_effect_cfg: Dict[int, Dict[str, Any]],
        target_uid: int,
    ) -> float:
        order = [int(uid) for uid in (team_order or []) if int(uid) > 0]
        tu = int(target_uid or 0)
        if tu <= 0 or tu not in order:
            return 0.0
        pos_target = order.index(int(tu))
        total = 0.0
        for pos, caster_uid in enumerate(order):
            if pos >= pos_target:
                break
            cfg = dict((team_effect_cfg or {}).get(int(caster_uid), {}) or {})
            total += max(0.0, float(cfg.get("atb_boost_pct", 0.0) or 0.0))
        return max(0.0, min(95.0, float(total)))

    def _validate_order_tick_plausibility(self) -> None:
        if not bool(self._persist_order_fields):
            return
        if not self._team_order_lists:
            return

        team_orders = self.team_order_by_lists()
        tick_by_uid = self._team_spd_tick_by_unit()
        effect_teams = self.team_turn_effects_by_lists() if self._show_turn_effect_controls else []
        is_arena_rush = str(self.mode or "").strip().lower() == "arena_rush"

        for team_index, team_order in enumerate(team_orders):
            order = [int(uid) for uid in (team_order or []) if int(uid) > 0]
            if len(order) <= 1:
                continue
            team_title = self._team_title(int(team_index))
            effect_cfg = dict(effect_teams[int(team_index)]) if int(team_index) < len(effect_teams) else {}

            floor_by_uid: Dict[int, int] = {}
            cap_by_uid: Dict[int, int] = {}
            for uid in order:
                tick = int(tick_by_uid.get(int(uid), 0) or 0)
                if tick <= 0:
                    continue
                min_tick_spd = int(min_spd_for_tick(int(tick), self.mode) or 0)
                max_tick_spd = int(max_spd_for_tick(int(tick), self.mode) or 0)
                floor = int(min_tick_spd)
                if is_arena_rush and min_tick_spd > 0:
                    speed_factor = 1.0
                    if self._has_spd_buff_before_turn(order, effect_cfg, int(uid)):
                        speed_factor += 0.30
                    atb_before = self._atb_boost_before_turn_pct(order, effect_cfg, int(uid))
                    atb_factor = 1.0 - (max(0.0, float(atb_before)) / 100.0)
                    atb_factor = max(0.05, min(1.0, atb_factor))
                    floor = int(ceil((float(min_tick_spd) * float(atb_factor)) / max(1e-9, float(speed_factor))))
                if floor > 0:
                    floor_by_uid[int(uid)] = int(floor)
                if max_tick_spd > 0:
                    cap_by_uid[int(uid)] = int(max_tick_spd)

            for uid in order:
                ui = int(uid)
                floor = int(floor_by_uid.get(ui, 0) or 0)
                cap = int(cap_by_uid.get(ui, 0) or 0)
                if floor > 0 and cap > 0 and floor > cap:
                    label = self._unit_label_by_id.get(int(ui), str(ui))
                    tick = int(tick_by_uid.get(int(ui), 0) or 0)
                    raise ValueError(
                        f"Plausibilitaetsfehler ({team_title}): {label} hat ungueltigen Tick {tick} "
                        f"(minimale SPD {floor} > maximale SPD {cap})."
                    )

            for idx in range(1, len(order)):
                prev_uid = int(order[idx - 1])
                cur_uid = int(order[idx])
                prev_cap = int(cap_by_uid.get(int(prev_uid), 0) or 0)
                cur_floor = int(floor_by_uid.get(int(cur_uid), 0) or 0)
                if prev_cap > 0 and cur_floor > 0 and prev_cap <= cur_floor:
                    prev_label = self._unit_label_by_id.get(int(prev_uid), str(prev_uid))
                    cur_label = self._unit_label_by_id.get(int(cur_uid), str(cur_uid))
                    raise ValueError(
                        f"Plausibilitaetsfehler ({team_title}): Turnorder Position {idx}->{idx + 1} nicht stimmig. "
                        f"{prev_label} kann mit max. SPD {prev_cap} nicht vor {cur_label} "
                        f"(min. SPD {cur_floor}) ziehen."
                    )

    def _collect_artifact_substat_options_by_type(self, account: AccountData | None) -> Dict[int, List[int]]:
        out: Dict[int, Set[int]] = {
            1: set(ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE.get(1, [])),
            2: set(ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE.get(2, [])),
        }
        if not account:
            return {
                1: sorted(out[1]),
                2: sorted(out[2]),
            }
        for art in (account.artifacts or []):
            art_type = int(getattr(art, "type_", 0) or 0)
            if art_type not in (1, 2):
                continue
            for sec in (getattr(art, "sec_effects", []) or []):
                if not sec:
                    continue
                try:
                    eid = int(sec[0] or 0)
                except Exception:
                    continue
                if eid > 0:
                    out[art_type].add(eid)
        return {
            1: sorted(out[1]),
            2: sorted(out[2]),
        }

    def _artifact_substat_ids_for_unit(self, unit_id: int, kind: str) -> List[int]:
        if str(kind) == "attribute":
            c1 = self._art_attr_sub1_combo.get(int(unit_id))
            c2 = self._art_attr_sub2_combo.get(int(unit_id))
        else:
            c1 = self._art_type_sub1_combo.get(int(unit_id))
            c2 = self._art_type_sub2_combo.get(int(unit_id))
        vals: List[int] = []
        seen: Set[int] = set()
        for cmb in (c1, c2):
            if cmb is None:
                continue
            eid = int(cmb.currentData() or 0)
            if eid <= 0 or eid in seen:
                continue
            seen.add(eid)
            vals.append(eid)
            if len(vals) >= 2:
                break
        return vals

    def apply_to_store(self) -> None:
        # Persisting needs widget values for all units.
        self._ensure_all_editor_pages()
        self._validate_order_tick_plausibility()
        optimize_order_by_uid = self._optimize_order_by_unit()
        team_turn_order_by_uid = self._team_turn_order_by_unit() if self._persist_order_fields else {}
        team_spd_tick_by_uid = self._team_spd_tick_by_unit() if self._persist_order_fields else {}

        for unit_id in self._set1_combo.keys():
            self._sync_set_combo_constraints_for_unit(int(unit_id))

            set1_ids = [int(x) for x in self._set1_combo[unit_id].checked_ids()]
            set2_ids = [int(x) for x in self._set2_combo[unit_id].checked_ids()]
            set3_ids = [int(x) for x in self._set3_combo[unit_id].checked_ids()] if self._is_set3_allowed_for_unit(int(unit_id)) else []

            groups: List[List[int]] = []
            if set1_ids:
                groups.append(set1_ids)
            if set2_ids:
                groups.append(set2_ids)
            if set3_ids:
                groups.append(set3_ids)

            option_ids: List[List[int]] = []
            if groups:
                option_ids = [list(opt) for opt in product(*groups)]

            normalized_options: List[List[int]] = []
            seen_opts: Set[Tuple[int, ...]] = set()
            for opt in option_ids:
                cleaned: List[int] = []
                for sid in opt:
                    sid_i = int(sid)
                    if sid_i <= 0 or sid_i not in SET_NAMES:
                        continue
                    # Keep duplicates (e.g. Shield+Shield+Shield).
                    # Deduplicating here would collapse valid 2-set stacks to one set.
                    cleaned.append(sid_i)
                if not cleaned:
                    continue
                total_pieces = sum(int(SET_SIZES.get(sid, 2)) for sid in cleaned)
                if total_pieces > 6:
                    continue
                key = tuple(cleaned)
                if key in seen_opts:
                    continue
                seen_opts.add(key)
                normalized_options.append(cleaned)

            if option_ids and not normalized_options:
                unit_label = self._unit_label_by_id.get(unit_id, str(unit_id))
                raise ValueError(tr("val.set_invalid", unit=unit_label))

            ms2_values = [str(x) for x in self._ms2_combo[unit_id].checked_values()]
            ms4_values = [str(x) for x in self._ms4_combo[unit_id].checked_values()]
            ms6_values = [str(x) for x in self._ms6_combo[unit_id].checked_values()]
            art_attr_focus_value = str(self._art_attr_focus_combo[unit_id].currentData() or "").upper()
            art_type_focus_value = str(self._art_type_focus_combo[unit_id].currentData() or "").upper()
            art_attr_substats = self._artifact_substat_ids_for_unit(unit_id, "attribute")
            art_type_substats = self._artifact_substat_ids_for_unit(unit_id, "type")
            optimize_order = int(optimize_order_by_uid.get(unit_id, 0) or 0)
            existing_builds = self.preset_store.get_unit_builds(self.mode, int(unit_id))
            existing_build = existing_builds[0] if existing_builds else Build.default_any()
            turn_order = int(getattr(existing_build, "turn_order", 0) or 0)
            spd_tick = int(getattr(existing_build, "spd_tick", 0) or 0)
            if self._persist_order_fields:
                turn_order = int(team_turn_order_by_uid.get(unit_id, turn_order) or 0)
                spd_tick = int(team_spd_tick_by_uid.get(unit_id, spd_tick) or 0)
            min_mode = str(self._min_mode_combo[unit_id].currentData() or "with_base")
            base_stats = self._unit_base_stats_for_min(int(unit_id))
            min_stats: Dict[str, int] = {}
            if self._min_spd_spin[unit_id].value() > 0:
                bonus_val = int(self._min_spd_spin[unit_id].value())
                if min_mode == "without_base":
                    min_stats["SPD_NO_BASE"] = bonus_val
                else:
                    min_stats["SPD"] = int(base_stats.get("SPD", 0) or 0) + bonus_val
            if self._min_hp_spin[unit_id].value() > 0:
                bonus_val = int(self._min_hp_spin[unit_id].value())
                if min_mode == "without_base":
                    min_stats["HP_NO_BASE"] = bonus_val
                else:
                    min_stats["HP"] = int(base_stats.get("HP", 0) or 0) + bonus_val
            if self._min_atk_spin[unit_id].value() > 0:
                bonus_val = int(self._min_atk_spin[unit_id].value())
                if min_mode == "without_base":
                    min_stats["ATK_NO_BASE"] = bonus_val
                else:
                    min_stats["ATK"] = int(base_stats.get("ATK", 0) or 0) + bonus_val
            if self._min_def_spin[unit_id].value() > 0:
                bonus_val = int(self._min_def_spin[unit_id].value())
                if min_mode == "without_base":
                    min_stats["DEF_NO_BASE"] = bonus_val
                else:
                    min_stats["DEF"] = int(base_stats.get("DEF", 0) or 0) + bonus_val
            if self._min_cr_spin[unit_id].value() > 0:
                bonus_val = int(self._min_cr_spin[unit_id].value())
                min_stats["CR"] = (int(base_stats.get("CR", 0) or 0) + bonus_val) if min_mode == "with_base" else bonus_val
            if self._min_cd_spin[unit_id].value() > 0:
                bonus_val = int(self._min_cd_spin[unit_id].value())
                min_stats["CD"] = (int(base_stats.get("CD", 0) or 0) + bonus_val) if min_mode == "with_base" else bonus_val
            if self._min_res_spin[unit_id].value() > 0:
                bonus_val = int(self._min_res_spin[unit_id].value())
                min_stats["RES"] = (int(base_stats.get("RES", 0) or 0) + bonus_val) if min_mode == "with_base" else bonus_val
            if self._min_acc_spin[unit_id].value() > 0:
                bonus_val = int(self._min_acc_spin[unit_id].value())
                min_stats["ACC"] = (int(base_stats.get("ACC", 0) or 0) + bonus_val) if min_mode == "with_base" else bonus_val

            set_options = []
            for opt in normalized_options:
                names = [SET_NAMES[sid] for sid in opt if sid in SET_NAMES]
                if names:
                    set_options.append(names)

            mainstats: Dict[int, List[str]] = {}
            if ms2_values:
                mainstats[2] = ms2_values
            if ms4_values:
                mainstats[4] = ms4_values
            if ms6_values:
                mainstats[6] = ms6_values

            artifact_focus: Dict[str, List[str]] = {}
            if art_attr_focus_value in ("HP", "ATK", "DEF"):
                artifact_focus["attribute"] = [art_attr_focus_value]
            if art_type_focus_value in ("HP", "ATK", "DEF"):
                artifact_focus["type"] = [art_type_focus_value]

            artifact_substats: Dict[str, List[int]] = {}
            if art_attr_substats:
                artifact_substats["attribute"] = [int(x) for x in art_attr_substats[:2]]
            if art_type_substats:
                artifact_substats["type"] = [int(x) for x in art_type_substats[:2]]

            b = Build(
                id="default",
                name="Default",
                enabled=True,
                priority=1,
                optimize_order=optimize_order,
                turn_order=turn_order,
                spd_tick=spd_tick,
                set_options=set_options,
                mainstats=mainstats,
                min_stats=min_stats,
                artifact_focus=artifact_focus,
                artifact_substats=artifact_substats,
            )
            self.preset_store.set_unit_builds(self.mode, unit_id, [b])
