from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Set, Dict, Callable, Any

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QIcon, QPalette, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QLabel, QTableWidget, QTableWidgetItem,
    QMessageBox, QTabWidget, QGroupBox, QGridLayout, QComboBox, QSpacerItem,
    QSizePolicy, QDialog, QDialogButtonBox, QLineEdit, QListWidget,
    QListWidgetItem, QScrollArea, QFrame, QCheckBox, QAbstractItemView, QSpinBox, QAbstractSpinBox
)

from app.importer.sw_json_importer import load_account_from_data
from app.domain.models import AccountData, Rune
from app.domain.monster_db import MonsterDB, LeaderSkill
from app.domain.presets import (
    BuildStore,
    Build,
    SET_NAMES,
    SET_SIZES,
    SLOT2_DEFAULT,
    SLOT4_DEFAULT,
    SLOT6_DEFAULT,
    MAINSTAT_KEYS,
    EFFECT_ID_TO_MAINSTAT_KEY,
)
from app.engine.greedy_optimizer import optimize_greedy, GreedyRequest, GreedyUnitResult
from app.services.account_persistence import AccountPersistence
from app.services.license_service import (
    LicenseValidation,
    load_license_key,
    save_license_key,
    validate_license_key,
)
from app.domain.team_store import TeamStore, Team
from app.domain.optimization_store import OptimizationStore, SavedUnitResult
from app.ui.siege_cards_widget import SiegeDefCardsWidget
from app.ui.overview_widget import OverviewWidget
from app.ui.rta_overview_widget import RtaOverviewWidget


@dataclass
class TeamSelection:
    team_index: int
    unit_ids: List[int]


STAT_LABELS_DE: Dict[str, str] = {
    "HP": "LP",
    "ATK": "Angriff",
    "DEF": "Verteidigung",
    "SPD": "Tempo",
    "CR": "Krit.-Rate",
    "CD": "Krit.-Schaden",
    "RES": "Widerstand",
    "ACC": "Präzision",
}


class _NoScrollComboBox(QComboBox):
    """ComboBox that ignores mouse-wheel events to prevent accidental changes."""
    def wheelEvent(self, event):
        event.ignore()


class BuildDialog(QDialog):
    """
    Build editor for siege teams:
    - one build per unit (Default)
    - sets/mainstats per unit
    - optimization order via row reordering in the table
    """
    def __init__(
        self,
        parent: QWidget,
        title: str,
        unit_rows: List[Tuple[int, str]],
        preset_store: BuildStore,
        mode: str,
        unit_icon_fn: Callable[[int], QIcon],
        team_size: int = 3,
        show_order_sections: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1280, 760)

        self.preset_store = preset_store
        self.mode = mode
        self.team_size = max(1, int(team_size))
        self._unit_icon_fn = unit_icon_fn
        self._unit_rows = list(unit_rows)
        self._unit_rows_by_uid: Dict[int, Tuple[int, str]] = {int(uid): (int(uid), str(lbl)) for uid, lbl in self._unit_rows}

        layout = QVBoxLayout(self)

        self._opt_order_list: QListWidget | None = None
        self._team_order_lists: List[QListWidget] = []

        if show_order_sections:
            # Global optimization order (independent from team turn order)
            optimize_box = QGroupBox("Optimierungsreihenfolge (Drag & Drop)")
            optimize_layout = QVBoxLayout(optimize_box)
            self._opt_order_list = QListWidget()
            self._opt_order_list.setDragDropMode(QAbstractItemView.InternalMove)
            self._opt_order_list.setDefaultDropAction(Qt.MoveAction)
            self._opt_order_list.setSelectionMode(QAbstractItemView.SingleSelection)
            self._opt_order_list.setIconSize(QSize(32, 32))
            self._opt_order_list.setMinimumHeight(140)

            opt_sortable: List[Tuple[int, int, int, str]] = []
            for pos, (uid, label) in enumerate(self._unit_rows):
                builds = self.preset_store.get_unit_builds(self.mode, uid)
                b0 = builds[0] if builds else Build.default_any()
                opt = int(getattr(b0, "optimize_order", 0) or 0)
                key = opt if opt > 0 else 999
                opt_sortable.append((key, pos, int(uid), label))
            opt_sortable.sort(key=lambda x: (x[0], x[1]))
            for _, _, uid, label in opt_sortable:
                it = QListWidgetItem(label)
                it.setData(Qt.UserRole, int(uid))
                icon = self._unit_icon_fn(uid)
                if not icon.isNull():
                    it.setIcon(icon)
                self._opt_order_list.addItem(it)
            optimize_layout.addWidget(self._opt_order_list)
            layout.addWidget(optimize_box)

            # Team turn order (independent from optimization order)
            order_box = QGroupBox("Turn Order pro Team (Drag & Drop)")
            order_grid = QGridLayout(order_box)
            teams: List[List[Tuple[int, str]]] = [
                self._unit_rows[i:i + self.team_size]
                for i in range(0, len(self._unit_rows), self.team_size)
                if self._unit_rows[i:i + self.team_size]
            ]
            for t, team_units in enumerate(teams):
                order_grid.addWidget(QLabel(f"Team {t+1}"), 0, t)
                lw = QListWidget()
                lw.setDragDropMode(QAbstractItemView.InternalMove)
                lw.setDefaultDropAction(Qt.MoveAction)
                lw.setSelectionMode(QAbstractItemView.SingleSelection)
                lw.setIconSize(QSize(36, 36))
                lw.setMinimumHeight(140)
                sortable: List[Tuple[int, int, int, str]] = []
                for pos, (uid, label) in enumerate(team_units):
                    builds = self.preset_store.get_unit_builds(self.mode, uid)
                    b0 = builds[0] if builds else Build.default_any()
                    turn = int(getattr(b0, "turn_order", 0) or 0)
                    key = turn if turn > 0 else 999
                    sortable.append((key, pos, uid, label))
                sortable.sort(key=lambda x: (x[0], x[1]))
                for _, _, uid, label in sortable:
                    it = QListWidgetItem(label)
                    it.setData(Qt.UserRole, int(uid))
                    icon = self._unit_icon_fn(uid)
                    if not icon.isNull():
                        it.setIcon(icon)
                    lw.addItem(it)
                self._team_order_lists.append(lw)
                order_grid.addWidget(lw, 1, t)
            layout.addWidget(order_box)

        # Build details table (without unit_id column)
        self.table = QTableWidget(0, 12)
        self.table.setHorizontalHeaderLabels([
            "Monster", "Set 1", "Set 2", "Set 3",
            "Slot 2 Main", "Slot 4 Main", "Slot 6 Main",
            "Min SPD", "Min CR", "Min CD", "Min RES", "Min ACC"
        ])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setDragDropMode(QAbstractItemView.InternalMove)
        self.table.setDragEnabled(True)
        self.table.setAcceptDrops(True)
        self.table.viewport().setAcceptDrops(True)
        self.table.setDropIndicatorShown(True)
        self.table.setDefaultDropAction(Qt.MoveAction)
        self.table.setDragDropOverwriteMode(False)
        layout.addWidget(self.table, 1)

        self._set1_combo: Dict[int, QComboBox] = {}
        self._set2_combo: Dict[int, QComboBox] = {}
        self._set3_combo: Dict[int, QComboBox] = {}
        self._ms2_combo: Dict[int, QComboBox] = {}
        self._ms4_combo: Dict[int, QComboBox] = {}
        self._ms6_combo: Dict[int, QComboBox] = {}
        self._min_spd_spin: Dict[int, QSpinBox] = {}
        self._min_cr_spin: Dict[int, QSpinBox] = {}
        self._min_cd_spin: Dict[int, QSpinBox] = {}
        self._min_res_spin: Dict[int, QSpinBox] = {}
        self._min_acc_spin: Dict[int, QSpinBox] = {}
        self._row_unit_id: Dict[int, int] = {}
        self._unit_label_by_id: Dict[int, str] = {uid: lbl for uid, lbl in self._unit_rows}

        # table order should reflect stored optimize_order
        table_rows = list(self._unit_rows)
        table_rows.sort(
            key=lambda x: (
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0) <= 0,
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0),
                next((idx for idx, it in enumerate(self._unit_rows) if int(it[0]) == int(x[0])), 10_000),
            )
        )

        for unit_id, label in table_rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self._row_unit_id[r] = int(unit_id)

            monster_item = QTableWidgetItem(label)
            icon = self._unit_icon_fn(unit_id)
            if not icon.isNull():
                monster_item.setIcon(icon)
            monster_item.setData(Qt.UserRole, int(unit_id))
            self.table.setItem(r, 0, monster_item)

            cmb_set1 = _NoScrollComboBox()
            cmb_set2 = _NoScrollComboBox()
            cmb_set3 = _NoScrollComboBox()
            for cmb_set in (cmb_set1, cmb_set2, cmb_set3):
                cmb_set.addItem("—", 0)
                for sid in sorted(SET_NAMES.keys()):
                    cmb_set.addItem(f"{SET_NAMES[sid]} ({sid})", sid)

            builds = self.preset_store.get_unit_builds(self.mode, unit_id)
            b0 = builds[0] if builds else Build.default_any()

            req_set_ids: List[int] = []
            if b0.set_options:
                opt0 = b0.set_options[0]
                if isinstance(opt0, list):
                    for opt_name in opt0[:3]:
                        name = str(opt_name)
                        for sid, sname in SET_NAMES.items():
                            if sname == name:
                                req_set_ids.append(int(sid))
                                break
            for cmb_set, sid in zip((cmb_set1, cmb_set2, cmb_set3), req_set_ids):
                idx = cmb_set.findData(sid)
                cmb_set.setCurrentIndex(idx if idx >= 0 else 0)

            def _mk_ms_combo(defaults: List[str]) -> _NoScrollComboBox:
                cmb = _NoScrollComboBox()
                cmb.addItem("Any", "")
                for k in MAINSTAT_KEYS:
                    cmb.addItem(k, k)
                if defaults:
                    di = cmb.findData(defaults[0])
                    if di >= 0:
                        cmb.setCurrentIndex(di)
                return cmb

            cmb2 = _mk_ms_combo(SLOT2_DEFAULT)
            cmb4 = _mk_ms_combo(SLOT4_DEFAULT)
            cmb6 = _mk_ms_combo(SLOT6_DEFAULT)
            min_spd = QSpinBox()
            min_cr = QSpinBox()
            min_cd = QSpinBox()
            min_res = QSpinBox()
            min_acc = QSpinBox()
            for sp in (min_spd, min_cr, min_cd, min_res, min_acc):
                sp.setMinimum(0)
                sp.setMaximum(400)
                sp.setButtonSymbols(QAbstractSpinBox.NoButtons)

            current_min = dict(getattr(b0, "min_stats", {}) or {})
            min_spd.setValue(int(current_min.get("SPD", 0) or 0))
            min_cr.setValue(int(current_min.get("CR", 0) or 0))
            min_cd.setValue(int(current_min.get("CD", 0) or 0))
            min_res.setValue(int(current_min.get("RES", 0) or 0))
            min_acc.setValue(int(current_min.get("ACC", 0) or 0))

            if b0.mainstats:
                if 2 in b0.mainstats and b0.mainstats[2]:
                    di = cmb2.findData(b0.mainstats[2][0])
                    if di >= 0:
                        cmb2.setCurrentIndex(di)
                if 4 in b0.mainstats and b0.mainstats[4]:
                    di = cmb4.findData(b0.mainstats[4][0])
                    if di >= 0:
                        cmb4.setCurrentIndex(di)
                if 6 in b0.mainstats and b0.mainstats[6]:
                    di = cmb6.findData(b0.mainstats[6][0])
                    if di >= 0:
                        cmb6.setCurrentIndex(di)

            self.table.setCellWidget(r, 1, cmb_set1)
            self.table.setCellWidget(r, 2, cmb_set2)
            self.table.setCellWidget(r, 3, cmb_set3)
            self.table.setCellWidget(r, 4, cmb2)
            self.table.setCellWidget(r, 5, cmb4)
            self.table.setCellWidget(r, 6, cmb6)
            self.table.setCellWidget(r, 7, min_spd)
            self.table.setCellWidget(r, 8, min_cr)
            self.table.setCellWidget(r, 9, min_cd)
            self.table.setCellWidget(r, 10, min_res)
            self.table.setCellWidget(r, 11, min_acc)

            self._set1_combo[unit_id] = cmb_set1
            self._set2_combo[unit_id] = cmb_set2
            self._set3_combo[unit_id] = cmb_set3
            self._ms2_combo[unit_id] = cmb2
            self._ms4_combo[unit_id] = cmb4
            self._ms6_combo[unit_id] = cmb6
            self._min_spd_spin[unit_id] = min_spd
            self._min_cr_spin[unit_id] = min_cr
            self._min_cd_spin[unit_id] = min_cd
            self._min_res_spin[unit_id] = min_res
            self._min_acc_spin[unit_id] = min_acc

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _optimize_order_by_unit(self) -> Dict[int, int]:
        if not self._opt_order_list:
            return {}
        out: Dict[int, int] = {}
        for idx in range(self._opt_order_list.count()):
            it = self._opt_order_list.item(idx)
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

    def apply_to_store(self) -> None:
        optimize_order_by_uid = self._optimize_order_by_unit()
        team_turn_order_by_uid = self._team_turn_order_by_unit()

        for unit_id in self._set1_combo.keys():
            selected_set_ids = [
                int(self._set1_combo[unit_id].currentData() or 0),
                int(self._set2_combo[unit_id].currentData() or 0),
                int(self._set3_combo[unit_id].currentData() or 0),
            ]
            total_required_pieces = sum(int(SET_SIZES.get(sid, 2)) for sid in selected_set_ids if sid in SET_NAMES)
            if total_required_pieces > 6:
                unit_label = self._unit_label_by_id.get(unit_id, str(unit_id))
                raise ValueError(
                    f"Ungültige Set-Kombi für {unit_label}: "
                    f"{total_required_pieces} Pflicht-Teile (> 6)."
                )

            ms2 = str(self._ms2_combo[unit_id].currentData() or "")
            ms4 = str(self._ms4_combo[unit_id].currentData() or "")
            ms6 = str(self._ms6_combo[unit_id].currentData() or "")
            optimize_order = int(optimize_order_by_uid.get(unit_id, 0) or 0)
            turn_order = int(team_turn_order_by_uid.get(unit_id, 0) or 0)
            min_stats: Dict[str, int] = {}
            if self._min_spd_spin[unit_id].value() > 0:
                min_stats["SPD"] = int(self._min_spd_spin[unit_id].value())
            if self._min_cr_spin[unit_id].value() > 0:
                min_stats["CR"] = int(self._min_cr_spin[unit_id].value())
            if self._min_cd_spin[unit_id].value() > 0:
                min_stats["CD"] = int(self._min_cd_spin[unit_id].value())
            if self._min_res_spin[unit_id].value() > 0:
                min_stats["RES"] = int(self._min_res_spin[unit_id].value())
            if self._min_acc_spin[unit_id].value() > 0:
                min_stats["ACC"] = int(self._min_acc_spin[unit_id].value())

            set_options = []
            selected_names = [SET_NAMES[sid] for sid in selected_set_ids if sid in SET_NAMES]
            if selected_names:
                set_options = [selected_names]

            mainstats: Dict[int, List[str]] = {}
            if ms2:
                mainstats[2] = [ms2]
            if ms4:
                mainstats[4] = [ms4]
            if ms6:
                mainstats[6] = [ms6]

            b = Build(
                id="default",
                name="Default",
                enabled=True,
                priority=1,
                optimize_order=optimize_order,
                turn_order=turn_order,
                set_options=set_options,
                mainstats=mainstats,
                min_stats=min_stats,
            )
            self.preset_store.set_unit_builds(self.mode, unit_id, [b])


class TeamEditorDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        account: AccountData,
        unit_label_fn: Callable[[int], str],
        unit_icon_fn: Callable[[int], QIcon],
        team: Team | None = None,
        unit_combo_model: QStandardItemModel | None = None,
    ):
        super().__init__(parent)
        self.account = account
        self.unit_label_fn = unit_label_fn
        self.unit_icon_fn = unit_icon_fn
        self.team = team
        self._unit_combo_model = unit_combo_model

        title = "Team bearbeiten" if team else "Neues Team"
        self.setWindowTitle(title)
        self.resize(600, 420)

        layout = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Team-Name"))
        self.name_edit = QLineEdit(team.name if team else "")
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        control_row = QHBoxLayout()
        self.unit_combo = QComboBox()
        self.unit_combo.setIconSize(QSize(32, 32))
        control_row.addWidget(self.unit_combo, 1)
        self.btn_add_unit = QPushButton("Hinzufügen")
        self.btn_add_unit.clicked.connect(self._add_unit_from_combo)
        control_row.addWidget(self.btn_add_unit)
        self.btn_remove_unit = QPushButton("Entfernen")
        self.btn_remove_unit.clicked.connect(self._remove_selected_unit)
        control_row.addWidget(self.btn_remove_unit)
        layout.addLayout(control_row)

        self.unit_list = QListWidget()
        self.unit_list.setIconSize(QSize(32, 32))
        layout.addWidget(self.unit_list, 1)

        self._populate_unit_combo()
        if self.team:
            for uid in self.team.unit_ids:
                self._append_unit(uid)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_unit_combo(self) -> None:
        if self._unit_combo_model is not None:
            self.unit_combo.blockSignals(True)
            self.unit_combo.setModel(self._unit_combo_model)
            self.unit_combo.setModelColumn(0)
            self.unit_combo.setCurrentIndex(0)
            self.unit_combo.blockSignals(False)
            return
        self.unit_combo.clear()
        self.unit_combo.addItem("—", 0)
        if not self.account:
            return
        for uid in sorted(self.account.units_by_id.keys()):
            self.unit_combo.addItem(self.unit_icon_fn(uid), self.unit_label_fn(uid), uid)

    def _append_unit(self, uid: int) -> None:
        if uid == 0:
            return
        for idx in range(self.unit_list.count()):
            if int(self.unit_list.item(idx).data(Qt.UserRole) or 0) == uid:
                return
        label = self.unit_label_fn(uid)
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, uid)
        item.setIcon(self.unit_icon_fn(uid))
        self.unit_list.addItem(item)

    def _add_unit_from_combo(self) -> None:
        uid = int(self.unit_combo.currentData() or 0)
        if uid:
            self._append_unit(uid)

    def _remove_selected_unit(self) -> None:
        for item in list(self.unit_list.selectedItems()):
            self.unit_list.takeItem(self.unit_list.row(item))

    def _on_accept(self) -> None:
        if self.unit_list.count() == 0:
            QMessageBox.warning(self, "Team braucht Units", "Bitte füge mindestens ein Monster hinzu.")
            return
        self.accept()

    @property
    def team_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def unit_ids(self) -> List[int]:
        return [
            int(self.unit_list.item(idx).data(Qt.UserRole) or 0)
            for idx in range(self.unit_list.count())
        ]


class OptimizeResultDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        summary: str,
        results: List[GreedyUnitResult],
        rune_lookup: Dict[int, Rune],
        unit_label_fn: Callable[[int], str],
        unit_icon_fn: Callable[[int], QIcon],
        unit_spd_fn: Callable[[int, List[int], Dict[int, Dict[int, int]]], int],
        unit_stats_fn: Callable[[int, List[int], Dict[int, Dict[int, int]]], Dict[str, int]],
        set_icon_fn: Callable[[int], QIcon],
        unit_base_stats_fn: Callable[[int], Dict[str, int]],
        unit_leader_bonus_fn: Callable[[int, List[int]], Dict[str, int]],
        unit_team_index: Optional[Dict[int, int]] = None,
        unit_display_order: Optional[Dict[int, int]] = None,
        mode_rune_owner: Optional[Dict[int, int]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1440, 760)

        self._results = list(results)
        self._results_by_uid: Dict[int, GreedyUnitResult] = {r.unit_id: r for r in self._results}
        self._unit_label_fn = unit_label_fn
        self._unit_icon_fn = unit_icon_fn
        self._unit_spd_fn = unit_spd_fn
        self._unit_stats_fn = unit_stats_fn
        self._set_icon_fn = set_icon_fn
        self._unit_base_stats_fn = unit_base_stats_fn
        self._unit_leader_bonus_fn = unit_leader_bonus_fn
        self._unit_team_index = unit_team_index or {}
        self._unit_display_order = unit_display_order or {}
        self._rune_lookup = rune_lookup
        self._mode_rune_owner = mode_rune_owner or {}
        self.saved = False
        self._stats_detailed = True
        self._runes_detailed = True
        self._current_uid: Optional[int] = None

        root = QVBoxLayout(self)
        if summary:
            lbl = QLabel(summary)
            lbl.setWordWrap(True)
            root.addWidget(lbl)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        self.nav_list = QListWidget()
        self.nav_list.setMinimumWidth(280)
        self.nav_list.currentRowChanged.connect(self._on_nav_selected)
        body.addWidget(self.nav_list, 0)

        right = QVBoxLayout()
        body.addLayout(right, 1)

        self.team_icon_bar = QFrame()
        self.team_icon_bar.setFrameShape(QFrame.StyledPanel)
        self.team_icon_layout = QHBoxLayout(self.team_icon_bar)
        self.team_icon_layout.setContentsMargins(8, 8, 8, 8)
        self.team_icon_layout.setSpacing(10)
        right.addWidget(self.team_icon_bar)

        self.detail_container = QWidget()
        self.detail_layout = QHBoxLayout(self.detail_container)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(8)
        right.addWidget(self.detail_container, 1)

        self._populate_nav()

        btn_bar = QHBoxLayout()
        self.btn_save = QPushButton("Speichern")
        self.btn_save.clicked.connect(self._on_save)
        btn_bar.addWidget(self.btn_save)
        btn_bar.addStretch()
        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(self.reject)
        btn_bar.addWidget(btn_close)
        root.addLayout(btn_bar)

    def _populate_nav(self) -> None:
        self.nav_list.clear()
        has_selection = False
        for team_idx, team_results in self._grouped_results():
            header = QListWidgetItem(f"Team {team_idx + 1}")
            header.setData(Qt.UserRole, None)
            header.setFlags(Qt.NoItemFlags)
            self.nav_list.addItem(header)
            for result in team_results:
                label = self._unit_label_fn(result.unit_id)
                state = "OK" if result.ok else "Fehler"
                item = QListWidgetItem(f"{label} [{state}]")
                icon = self._unit_icon_fn(result.unit_id)
                if not icon.isNull():
                    item.setIcon(icon)
                item.setData(Qt.UserRole, result.unit_id)
                self.nav_list.addItem(item)
                if not has_selection:
                    self.nav_list.setCurrentItem(item)
                    has_selection = True

        if not has_selection:
            self._render_details(None)

    def _on_nav_selected(self, row: int) -> None:
        if row < 0:
            self._render_details(None)
            return
        item = self.nav_list.item(row)
        if not item:
            self._render_details(None)
            return
        uid = item.data(Qt.UserRole)
        if uid is None:
            self._render_details(None)
            return
        self._render_details(int(uid))

    def _render_team_icon_bar(self, selected_uid: int | None) -> None:
        while self.team_icon_layout.count():
            child = self.team_icon_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if selected_uid is None:
            return

        team_results: List[GreedyUnitResult] = []
        if self._unit_team_index:
            sel_team = self._unit_team_index.get(int(selected_uid), None)
            if sel_team is not None:
                team_results = [
                    r for r in self._results
                    if self._unit_team_index.get(int(r.unit_id), -1) == int(sel_team)
                ]
                team_results.sort(key=lambda r: self._unit_display_order.get(int(r.unit_id), 10_000))
        if not team_results:
            selected_index = 0
            for idx, result in enumerate(self._results):
                if result.unit_id == selected_uid:
                    selected_index = idx
                    break
            team_idx = selected_index // 3
            team_results = self._results[team_idx * 3:(team_idx + 1) * 3]

        for result in team_results:
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            card.setProperty("selected", result.unit_id == selected_uid)
            v = QVBoxLayout(card)
            v.setContentsMargins(6, 6, 6, 6)
            v.setSpacing(4)

            icon_lbl = QLabel()
            icon = self._unit_icon_fn(result.unit_id)
            if not icon.isNull():
                icon_lbl.setPixmap(icon.pixmap(72, 72))
            icon_lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(icon_lbl)

            runes_by_unit = {r.unit_id: (r.runes_by_slot or {}) for r in team_results}
            spd = self._unit_spd_fn(result.unit_id, [r.unit_id for r in team_results], runes_by_unit)
            spd_lbl = QLabel(str(spd))
            spd_lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(spd_lbl)

            self.team_icon_layout.addWidget(card)

        self.team_icon_layout.addStretch(1)

    def _grouped_results(self) -> List[Tuple[int, List[GreedyUnitResult]]]:
        if not self._unit_team_index:
            out: List[Tuple[int, List[GreedyUnitResult]]] = []
            team_count = (len(self._results) + 2) // 3
            for team_idx in range(team_count):
                out.append((team_idx, self._results[team_idx * 3:(team_idx + 1) * 3]))
            return out

        grouped: Dict[int, List[GreedyUnitResult]] = {}
        for r in self._results:
            t = int(self._unit_team_index.get(int(r.unit_id), 0))
            grouped.setdefault(t, []).append(r)
        out = []
        for team_idx in sorted(grouped.keys()):
            arr = grouped[team_idx]
            arr.sort(key=lambda rr: self._unit_display_order.get(int(rr.unit_id), 10_000))
            out.append((team_idx, arr))
        return out

    # ── detail rendering (tabs) ────────────────────────────

    def _team_unit_ids_for(self, unit_id: int) -> List[int]:
        if self._unit_team_index:
            team_idx = self._unit_team_index.get(int(unit_id))
            if team_idx is not None:
                ids = [
                    int(r.unit_id) for r in self._results
                    if self._unit_team_index.get(int(r.unit_id), -1) == int(team_idx)
                ]
                ids.sort(key=lambda uid: self._unit_display_order.get(uid, 10_000))
                return ids
        return [int(r.unit_id) for r in self._results]

    def _render_details(self, unit_id: int | None) -> None:
        self._render_team_icon_bar(unit_id)
        self._current_uid = unit_id

        while self.detail_layout.count():
            child = self.detail_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if unit_id is None:
            w = QWidget()
            QVBoxLayout(w).addWidget(QLabel("Bitte links ein Monster auswählen."))
            self.detail_layout.addWidget(w)
            return

        result = self._results_by_uid.get(unit_id)
        if not result:
            w = QWidget()
            QVBoxLayout(w).addWidget(QLabel("Kein Ergebnis gefunden."))
            self.detail_layout.addWidget(w)
            return

        team_unit_ids = self._team_unit_ids_for(unit_id)
        runes_by_unit = {int(r.unit_id): (r.runes_by_slot or {}) for r in self._results}
        total_stats = self._unit_stats_fn(int(unit_id), team_unit_ids, runes_by_unit)
        base_stats = self._unit_base_stats_fn(int(unit_id))
        leader_bonus = self._unit_leader_bonus_fn(int(unit_id), team_unit_ids)

        self.detail_layout.addWidget(
            self._build_stats_tab(unit_id, result, base_stats, total_stats, leader_bonus)
        )

        if result.ok and result.runes_by_slot:
            self.detail_layout.addWidget(
                self._build_runes_tab(result)
            )

    # ── Stats tab ──────────────────────────────────────────

    def _build_stats_tab(self, unit_id: int, result: GreedyUnitResult,
                         base_stats: Dict[str, int],
                         total_stats: Dict[str, int],
                         leader_bonus: Dict[str, int]) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)

        label = self._unit_label_fn(unit_id)
        title = QLabel(f"<b>{label}</b>" if result.ok else f"<b>{label} (Fehler)</b>")
        title.setTextFormat(Qt.RichText)
        v.addWidget(title)

        if not result.ok:
            msg = QLabel(result.message)
            msg.setWordWrap(True)
            v.addWidget(msg)
            v.addStretch()
            return w

        stat_keys = ["HP", "ATK", "DEF", "SPD", "CR", "CD", "RES", "ACC"]
        has_leader = any(leader_bonus.get(k, 0) != 0 for k in stat_keys)
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(stat_keys))

        if self._stats_detailed:
            if has_leader:
                table.setColumnCount(5)
                table.setHorizontalHeaderLabels(["Stat", "Basis", "Runen", "Leader", "Gesamt"])
            else:
                table.setColumnCount(4)
                table.setHorizontalHeaderLabels(["Stat", "Basis", "Runen", "Gesamt"])
            for i, key in enumerate(stat_keys):
                base = base_stats.get(key, 0)
                total = total_stats.get(key, 0)
                lead = leader_bonus.get(key, 0)
                rune_bonus = total - base - lead
                table.setItem(i, 0, QTableWidgetItem(STAT_LABELS_DE.get(key, key)))
                it_b = QTableWidgetItem(str(base))
                it_b.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 1, it_b)
                rune_str = f"+{rune_bonus}" if rune_bonus >= 0 else str(rune_bonus)
                it_r = QTableWidgetItem(rune_str)
                it_r.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 2, it_r)
                if has_leader:
                    lead_str = f"+{lead}" if lead > 0 else str(lead) if lead else ""
                    it_l = QTableWidgetItem(lead_str)
                    it_l.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, 3, it_l)
                    it_t = QTableWidgetItem(str(total))
                    it_t.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, 4, it_t)
                else:
                    it_t = QTableWidgetItem(str(total))
                    it_t.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, 3, it_t)
        else:
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels(["Stat", "Wert"])
            for i, key in enumerate(stat_keys):
                table.setItem(i, 0, QTableWidgetItem(STAT_LABELS_DE.get(key, key)))
                it_v = QTableWidgetItem(str(total_stats.get(key, 0)))
                it_v.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 1, it_v)

        table.resizeColumnsToContents()
        table.setMaximumHeight(
            table.verticalHeader().length() + table.horizontalHeader().height() + 4
        )
        v.addWidget(table)
        v.addStretch()
        return w

    # ── Runes tab ──────────────────────────────────────────

    def _build_runes_tab(self, result: GreedyUnitResult) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)

        grid = QGridLayout()
        grid.setSpacing(6)
        slots = sorted((result.runes_by_slot or {}).items())
        for idx, (slot, rune_id) in enumerate(slots):
            rune = self._rune_lookup.get(rune_id)
            if not rune:
                continue
            row, col = divmod(idx, 2)
            grid.addWidget(self._build_rune_frame(rune, slot), row, col)
        v.addLayout(grid)
        v.addStretch()
        return w

    def _build_rune_frame(self, rune: Rune, slot: int) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 3px; padding: 2px; }")
        main_v = QVBoxLayout(frame)
        main_v.setSpacing(2)
        main_v.setContentsMargins(6, 4, 6, 4)

        header = QHBoxLayout()
        header.setSpacing(4)
        set_icon = self._set_icon_fn(rune.set_id)
        icon_lbl = QLabel()
        if not set_icon.isNull():
            icon_lbl.setPixmap(set_icon.pixmap(28, 28))
        else:
            icon_lbl.setFixedSize(28, 28)
        header.addWidget(icon_lbl)
        set_name = SET_NAMES.get(rune.set_id, f"Set {rune.set_id}")
        header.addWidget(QLabel(f"<b>Slot {slot}</b> | {set_name} | +{rune.upgrade_curr}"))
        header.addStretch()
        main_v.addLayout(header)

        # Show current rune owner: prefer mode-specific assignment, fallback to PvE
        owner_uid = self._mode_rune_owner.get(rune.rune_id)
        if not owner_uid and rune.occupied_type == 1 and rune.occupied_id:
            owner_uid = int(rune.occupied_id)
        if owner_uid:
            owner = self._unit_label_fn(owner_uid)
            src = QLabel(f"aktuell auf: {owner}")
            src.setStyleSheet("color: #888; font-size: 7pt;")
            main_v.addWidget(src)

        main_v.addWidget(QLabel(f"Main: {self._stat_label(rune.pri_eff)}"))
        pfx = self._prefix_text(rune.prefix_eff)
        if pfx != "—":
            main_v.addWidget(QLabel(f"Prefix: {pfx}"))

        for sec in (rune.sec_eff or []):
            if not sec:
                continue
            eff_id = int(sec[0] or 0)
            value = int(sec[1] or 0)
            gem_flag = int(sec[2] or 0) if len(sec) >= 3 else 0
            grind = int(sec[3] or 0) if len(sec) >= 4 else 0
            key = EFFECT_ID_TO_MAINSTAT_KEY.get(eff_id, f"Effect {eff_id}")
            total = value + grind
            if self._runes_detailed:
                if grind:
                    text = f"{key} {total} <span style='color: #FFD700;'>({value}+{grind})</span>"
                else:
                    text = f"{key} {value}"
            else:
                text = f"{key} {total}"
            if gem_flag:
                text = f"<span style='color:#1abc9c'>{text} [Gem]</span>"
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet("font-size: 8pt;")
            main_v.addWidget(lbl)

        return frame

    # ── helpers ────────────────────────────────────────────

    def _stat_label(self, stat: Tuple[int, int]) -> str:
        eff_id, value = stat
        key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"Effect {eff_id}")
        return f"{key} {self._fmt(value)}"

    def _prefix_text(self, prefix: Tuple[int, int]) -> str:
        if not prefix or prefix[0] == 0:
            return "—"
        return self._stat_label(prefix)

    def _fmt(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    def _on_save(self):
        self.saved = True
        self.btn_save.setEnabled(False)
        self.btn_save.setText("Gespeichert")

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SW Team Optimizer")
        self.resize(1600, 980)
        self.setMinimumSize(1360, 820)

        self.account: Optional[AccountData] = None
        self._icon_cache: Dict[int, QIcon] = {}
        self._unit_combo_model: Optional[QStandardItemModel] = None
        self._unit_combo_index_by_uid: Dict[int, int] = {}
        self._unit_text_cache_by_uid: Dict[int, str] = {}

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

        top = QHBoxLayout()
        layout.addLayout(top)

        self.btn_import = QPushButton("JSON importieren")
        self.btn_import.clicked.connect(self.on_import)
        top.addWidget(self.btn_import)

        self.lbl_status = QLabel("Kein Import geladen.")
        self.lbl_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        top.addWidget(self.lbl_status, 1)

        btn_help = QPushButton("?")
        btn_help.setFixedSize(32, 32)
        btn_help.setStyleSheet(
            "QPushButton { background: #2b2b2b; color: #ddd; border: 1px solid #3a3a3a;"
            " border-radius: 16px; font-size: 14pt; font-weight: bold; }"
            "QPushButton:hover { background: #3498db; color: #fff; }"
        )
        btn_help.clicked.connect(self._show_help_dialog)
        top.addWidget(btn_help)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setElideMode(Qt.ElideRight)
        self._apply_tab_style()
        layout.addWidget(self.tabs, 1)

        # Overview
        self.tab_overview = QWidget()
        self.tabs.addTab(self.tab_overview, "Übersicht")
        ov = QVBoxLayout(self.tab_overview)
        ov.setContentsMargins(0, 0, 0, 0)
        self.overview_widget = OverviewWidget()
        ov.addWidget(self.overview_widget)

        # Raw Siege – card-based layout
        self.tab_siege_raw = QWidget()
        self.tabs.addTab(self.tab_siege_raw, "Siege Verteidigungen (aktuell)")
        sv = QVBoxLayout(self.tab_siege_raw)
        self.siege_cards = SiegeDefCardsWidget()
        sv.addWidget(self.siege_cards)

        # RTA (aktuell) – card-based overview of current RTA monsters
        self.tab_rta_overview = QWidget()
        self.tabs.addTab(self.tab_rta_overview, "RTA (aktuell)")
        rv = QVBoxLayout(self.tab_rta_overview)
        self.rta_overview = RtaOverviewWidget()
        rv.addWidget(self.rta_overview)

        # Siege Builder
        self.tab_siege_builder = QWidget()
        self.tabs.addTab(self.tab_siege_builder, "Siege Builder (Custom)")
        self._init_siege_builder_ui()

        # Saved Siege Optimizations
        self.tab_saved_siege = QWidget()
        self.tabs.addTab(self.tab_saved_siege, "Siege Optimierungen (gespeichert)")
        self._init_saved_siege_tab()

        # WGB Builder (nur Validierung)
        self.tab_wgb_builder = QWidget()
        self.tabs.addTab(self.tab_wgb_builder, "WGB Builder (Custom)")
        self._init_wgb_builder_ui()

        # Saved WGB Optimizations
        self.tab_saved_wgb = QWidget()
        self.tabs.addTab(self.tab_saved_wgb, "WGB Optimierungen (gespeichert)")
        self._init_saved_wgb_tab()

        # RTA Builder
        self.tab_rta_builder = QWidget()
        self.tabs.addTab(self.tab_rta_builder, "RTA Builder (Custom)")
        self._init_rta_builder_ui()

        # Saved RTA Optimizations
        self.tab_saved_rta = QWidget()
        self.tabs.addTab(self.tab_saved_rta, "RTA Optimierungen (gespeichert)")
        self._init_saved_rta_tab()

        # Team Manager (fixed + custom teams)
        self.tab_team_builder = QWidget()
        self._init_team_tab_ui()
        self._unit_dropdowns_populated = False
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self._try_restore_snapshot()

    def _apply_tab_style(self) -> None:
        self.tabs.setStyleSheet(
            """
            QTabWidget::pane {
                border: 1px solid #35383d;
                border-top: none;
                background: #1f2126;
                top: -1px;
            }
            QTabBar::tab {
                background: #262a30;
                color: #b7bec8;
                border: 1px solid #35383d;
                border-bottom: none;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                padding: 8px 14px;
                margin-right: 6px;
                min-height: 18px;
                font-size: 9pt;
                font-weight: 600;
            }
            QTabBar::tab:hover {
                background: #2f353d;
                color: #e1e6ec;
            }
            QTabBar::tab:selected {
                background: #1f2126;
                color: #eaf5ff;
                border-color: #3f74a8;
            }
            QTabBar::tab:!selected {
                margin-top: 3px;
            }
            QTabBar::scroller {
                width: 22px;
            }
            QTabBar QToolButton {
                background: #262a30;
                border: 1px solid #35383d;
                color: #b7bec8;
                border-radius: 6px;
                padding: 2px;
            }
            QTabBar QToolButton:hover {
                background: #2f353d;
                color: #e1e6ec;
            }
            """
        )

    # ============================================================
    # Help dialog
    # ============================================================
    def _show_help_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Anleitung")
        dlg.resize(620, 520)
        layout = QVBoxLayout(dlg)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        layout.addWidget(scroll)

        content = QLabel()
        content.setTextFormat(Qt.RichText)
        content.setWordWrap(True)
        content.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        content.setContentsMargins(16, 12, 16, 12)
        content.setStyleSheet("font-size: 10pt; line-height: 1.5;")
        content.setText(
            "<h2>SW Team Optimizer – Kurzanleitung</h2>"

            "<h3>1. JSON importieren</h3>"
            "<p>Klicke auf <b>JSON importieren</b> und wähle deinen "
            "Summoners War JSON-Export aus. Nach dem Import siehst du "
            "auf dem <b>Übersicht</b>-Tab deine Account-Statistiken, "
            "Runen-Effizienz-Charts und die Set-Verteilung.</p>"

            "<h3>2. Aktuelle Aufstellungen ansehen</h3>"
            "<p><b>Siege Verteidigungen (aktuell)</b> – Zeigt deine im Spiel "
            "eingestellten Siege-Verteidigungen als Karten mit Runen-Details.<br>"
            "<b>RTA (aktuell)</b> – Zeigt deine aktuell für RTA gerüsteten Monster.</p>"

            "<h3>3. Teams zusammenstellen</h3>"
            "<p>In den <b>Builder</b>-Tabs (Siege / WGB / RTA) kannst du "
            "eigene Team-Aufstellungen erstellen:</p>"
            "<ul>"
            "<li><b>Monster wählen</b> – Über die Dropdowns je Verteidigung (Siege/WGB) "
            "oder per Hinzufügen-Button (RTA).</li>"
            "<li><b>Aktuelle übernehmen</b> – Übernimmt die im Spiel eingestellten Teams.</li>"
            "<li><b>Validieren</b> – Prüft ob Runen-Pools kollidieren und zeigt Warnungen.</li>"
            "</ul>"

            "<h3>4. Builds definieren</h3>"
            "<p>Klicke auf <b>Builds (Sets+Mainstats)…</b> um je Monster "
            "die gewünschten Runen-Sets und Slot-2/4/6-Hauptstats festzulegen. "
            "Hier kannst du auch Mindest-Werte (z.B. min SPD) definieren.</p>"

            "<h3>5. Optimieren</h3>"
            "<p>Klicke auf <b>Optimieren (Runen)</b> um die automatische "
            "Runen-Verteilung zu starten. Der Optimizer verteilt deine Runen "
            "so, dass die Vorgaben möglichst effizient erfüllt werden. "
            "Das Ergebnis kannst du als Karten mit allen Stats und Runen-Details sehen.</p>"

            "<h3>6. Ergebnisse speichern</h3>"
            "<p>Optimierungen werden automatisch gespeichert und können "
            "in den <b>Optimierungen (gespeichert)</b>-Tabs jederzeit "
            "wieder aufgerufen oder gelöscht werden.</p>"

            "<h3>Tipps</h3>"
            "<ul>"
            "<li>Im Runen-Chart kannst du mit <b>Strg+Mausrad</b> die Anzahl "
            "der angezeigten Top-Runen ändern.</li>"
            "<li>Fahre mit der Maus über einen Datenpunkt im Chart, um "
            "Runen-Details inkl. Subs und Grinds zu sehen.</li>"
            "<li>Subs die mit einem <span style='color:#1abc9c'><b>Gem</b></span> "
            "getauscht wurden, werden farblich hervorgehoben.</li>"
            "</ul>"
        )
        scroll.setWidget(content)

        btn_close = QPushButton("Schließen")
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

        dlg.exec()

    # ============================================================
    # Import
    # ============================================================
    def on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Summoners War JSON auswählen",
            str(Path.home()),
            "JSON (*.json);;Alle Dateien (*.*)",
        )
        if not path:
            return
        try:
            raw_json = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
            self.account_persistence.save(raw_json, source_name=Path(path).name)
            account = load_account_from_data(raw_json)
        except Exception as e:
            QMessageBox.critical(self, "Import fehlgeschlagen", str(e))
            return

        self._apply_saved_account(account, Path(path).name)

    def _apply_saved_account(self, account: AccountData, source_label: str) -> None:
        self.account = account
        self.monster_db.load()
        self._unit_dropdowns_populated = False
        self._icon_cache = {}
        self._unit_combo_model = None
        self._unit_combo_index_by_uid = {}
        self._unit_text_cache_by_uid = {}

        self.lbl_status.setText(f"Import: {source_label}")
        self.overview_widget.set_data(account)

        self._render_siege_raw()
        self.rta_overview.set_context(account, self.monster_db, self.assets_dir)
        self._on_tab_changed(self.tabs.currentIndex())

        self.btn_take_current_siege.setEnabled(True)
        self.btn_validate_siege.setEnabled(True)
        self.btn_edit_presets_siege.setEnabled(True)
        self.btn_optimize_siege.setEnabled(True)

        self.btn_validate_wgb.setEnabled(True)
        self.btn_edit_presets_wgb.setEnabled(True)
        self.btn_optimize_wgb.setEnabled(True)

        self.btn_take_current_rta.setEnabled(True)
        self.btn_validate_rta.setEnabled(True)
        self.btn_edit_presets_rta.setEnabled(True)
        self.btn_optimize_rta.setEnabled(True)

        self.lbl_siege_validate.setText("Bereit. Siege auswählen/übernehmen -> Validieren -> Builds -> Optimieren.")
        self.lbl_wgb_validate.setText("Bereit. (WGB) Teams auswählen.")

        self._ensure_siege_team_defaults()
        self._refresh_team_combo()
        self._set_team_controls_enabled(True)

    def _try_restore_snapshot(self) -> None:
        if not self.account_persistence.exists():
            return
        raw = self.account_persistence.load()
        if not raw:
            return
        try:
            account = load_account_from_data(raw)
        except Exception as exc:
            QMessageBox.warning(self, "Snapshot laden", f"Snapshot konnte nicht geladen werden:\n{exc}")
            return
        meta = self.account_persistence.load_meta()
        source_name = str(meta.get("source_name", "")).strip() or "Originalname unbekannt"
        imported_at_raw = str(meta.get("imported_at", "")).strip()
        imported_at = None
        if imported_at_raw:
            try:
                imported_at = datetime.fromisoformat(imported_at_raw)
            except ValueError:
                imported_at = None
        if imported_at is None:
            try:
                imported_at = datetime.fromtimestamp(self.account_persistence.snapshot_path.stat().st_mtime)
            except OSError:
                imported_at = None

        if imported_at is not None:
            source_label = f"{source_name} ({imported_at.strftime('%d.%m.%Y %H:%M')})"
        else:
            source_label = source_name
        self._apply_saved_account(account, source_label)
    # ============================================================
    # Helpers: names+icons
    # ============================================================
    def _icon_for_master_id(self, master_id: int) -> QIcon:
        cached = self._icon_cache.get(int(master_id))
        if cached is not None:
            return cached
        rel = self.monster_db.icon_path_for(master_id)
        if not rel:
            icon = QIcon()
            self._icon_cache[int(master_id)] = icon
            return icon
        p = (self.assets_dir / rel).resolve()
        icon = QIcon(str(p)) if p.exists() else QIcon()
        self._icon_cache[int(master_id)] = icon
        return icon

    def _rune_set_icon(self, set_id: int) -> QIcon:
        name = SET_NAMES.get(set_id, "")
        slug = name.lower().replace(" ", "_") if name else str(set_id)
        filename = f"{set_id}_{slug}.png"
        icon_path = self.assets_dir / "runes" / "sets" / filename
        return QIcon(str(icon_path)) if icon_path.exists() else QIcon()

    def _unit_text(self, unit_id: int) -> str:
        if not self.account:
            return str(unit_id)
        u = self.account.units_by_id.get(unit_id)
        if not u:
            return f"{unit_id} (—)"
        name = self.monster_db.name_for(u.unit_master_id)
        elem = self.monster_db.element_for(u.unit_master_id)
        return f"{name} ({elem}) | lvl {u.unit_level}"

    def _unit_text_cached(self, unit_id: int) -> str:
        uid = int(unit_id)
        cached = self._unit_text_cache_by_uid.get(uid)
        if cached is not None:
            return cached
        txt = self._unit_text(uid)
        self._unit_text_cache_by_uid[uid] = txt
        return txt

    def _populate_combo_with_units(self, cmb: QComboBox):
        if not self.account:
            return
        model = self._ensure_unit_combo_model()
        prev_uid = int(cmb.currentData() or 0)

        cmb.blockSignals(True)
        cmb.setModel(model)
        cmb.setModelColumn(0)
        cmb.setIconSize(QSize(40, 40))
        cmb.setCurrentIndex(self._unit_combo_index_by_uid.get(prev_uid, 0))
        cmb.blockSignals(False)

    def _build_unit_combo_model(self) -> QStandardItemModel:
        model = QStandardItemModel()
        index_by_uid: Dict[int, int] = {}

        placeholder = QStandardItem("—")
        placeholder.setData(0, Qt.UserRole)
        model.appendRow(placeholder)
        index_by_uid[0] = 0

        if self.account:
            for uid in sorted(self.account.units_by_id.keys()):
                u = self.account.units_by_id[uid]
                name = self.monster_db.name_for(u.unit_master_id)
                elem = self.monster_db.element_for(u.unit_master_id)
                self._unit_text_cache_by_uid[int(uid)] = f"{name} ({elem}) | lvl {u.unit_level}"
                item = QStandardItem(f"{name} ({elem})")
                item.setIcon(self._icon_for_master_id(u.unit_master_id))
                item.setData(int(uid), Qt.UserRole)
                model.appendRow(item)
                index_by_uid[int(uid)] = model.rowCount() - 1

        self._unit_combo_index_by_uid = index_by_uid
        return model

    def _ensure_unit_combo_model(self) -> QStandardItemModel:
        if self._unit_combo_model is None:
            self._unit_combo_model = self._build_unit_combo_model()
        return self._unit_combo_model

    def _populate_all_dropdowns(self):
        for cmb in getattr(self, "_all_unit_combos", []):
            self._populate_combo_with_units(cmb)

    def _tab_needs_unit_dropdowns(self, tab: QWidget | None) -> bool:
        return tab in (self.tab_siege_builder, self.tab_wgb_builder, self.tab_rta_builder)

    def _on_tab_changed(self, index: int) -> None:
        if not self.account:
            return
        tab = self.tabs.widget(index)
        if self._tab_needs_unit_dropdowns(tab):
            self._ensure_unit_dropdowns_populated()

    def _ensure_unit_dropdowns_populated(self) -> None:
        if self._unit_dropdowns_populated or not self.account:
            return
        self._populate_all_dropdowns()
        self._unit_dropdowns_populated = True

    # ============================================================
    # Saved Optimization Tabs
    # ============================================================
    def _init_saved_siege_tab(self):
        v = QVBoxLayout(self.tab_saved_siege)
        top = QHBoxLayout()
        top.addWidget(QLabel("Gespeicherte Optimierung:"))
        self.saved_siege_combo = QComboBox()
        self.saved_siege_combo.currentIndexChanged.connect(lambda: self._on_saved_opt_changed("siege"))
        top.addWidget(self.saved_siege_combo, 1)
        self.btn_delete_saved_siege = QPushButton("Löschen")
        self.btn_delete_saved_siege.clicked.connect(lambda: self._on_delete_saved_opt("siege"))
        top.addWidget(self.btn_delete_saved_siege)
        v.addLayout(top)
        self.saved_siege_cards = SiegeDefCardsWidget()
        v.addWidget(self.saved_siege_cards, 1)
        self._refresh_saved_opt_combo("siege")

    def _init_saved_wgb_tab(self):
        v = QVBoxLayout(self.tab_saved_wgb)
        top = QHBoxLayout()
        top.addWidget(QLabel("Gespeicherte Optimierung:"))
        self.saved_wgb_combo = QComboBox()
        self.saved_wgb_combo.currentIndexChanged.connect(lambda: self._on_saved_opt_changed("wgb"))
        top.addWidget(self.saved_wgb_combo, 1)
        self.btn_delete_saved_wgb = QPushButton("Löschen")
        self.btn_delete_saved_wgb.clicked.connect(lambda: self._on_delete_saved_opt("wgb"))
        top.addWidget(self.btn_delete_saved_wgb)
        v.addLayout(top)
        self.saved_wgb_cards = SiegeDefCardsWidget()
        v.addWidget(self.saved_wgb_cards, 1)
        self._refresh_saved_opt_combo("wgb")

    def _init_saved_rta_tab(self):
        v = QVBoxLayout(self.tab_saved_rta)
        top = QHBoxLayout()
        top.addWidget(QLabel("Gespeicherte Optimierung:"))
        self.saved_rta_combo = QComboBox()
        self.saved_rta_combo.currentIndexChanged.connect(lambda: self._on_saved_opt_changed("rta"))
        top.addWidget(self.saved_rta_combo, 1)
        self.btn_delete_saved_rta = QPushButton("Löschen")
        self.btn_delete_saved_rta.clicked.connect(lambda: self._on_delete_saved_opt("rta"))
        top.addWidget(self.btn_delete_saved_rta)
        v.addLayout(top)
        self.saved_rta_cards = SiegeDefCardsWidget()
        v.addWidget(self.saved_rta_cards, 1)
        self._refresh_saved_opt_combo("rta")

    def _saved_opt_widgets(self, mode: str):
        """Return (combo, cards) for the given mode."""
        if mode == "siege":
            return self.saved_siege_combo, self.saved_siege_cards
        if mode == "rta":
            return self.saved_rta_combo, self.saved_rta_cards
        return self.saved_wgb_combo, self.saved_wgb_cards

    def _refresh_saved_opt_combo(self, mode: str):
        combo, _ = self._saved_opt_widgets(mode)
        combo.blockSignals(True)
        current_id = str(combo.currentData() or "")
        combo.clear()
        items = self.opt_store.get_by_mode(mode)
        for opt in items:
            display_name = str(opt.name)
            display_name = display_name.replace(" Opt ", " Optimierung ")
            display_name = display_name.replace(" Optimizer ", " Optimierung ")
            display_name = display_name.replace("SIEGE Opt", "SIEGE Optimierung")
            display_name = display_name.replace("WGB Opt", "WGB Optimierung")
            display_name = display_name.replace("RTA Opt", "RTA Optimierung")
            display_name = display_name.replace("SIEGE Optimizer", "SIEGE Optimierung")
            display_name = display_name.replace("WGB Optimizer", "WGB Optimierung")
            display_name = display_name.replace("RTA Optimizer", "RTA Optimierung")
            combo.addItem(f"{display_name}  ({opt.timestamp})", opt.id)
        if current_id:
            idx = combo.findData(current_id)
            if idx >= 0:
                combo.setCurrentIndex(idx)
        combo.blockSignals(False)
        self._on_saved_opt_changed(mode)

    def _on_saved_opt_changed(self, mode: str):
        combo, cards = self._saved_opt_widgets(mode)
        oid = str(combo.currentData() or "")
        if not oid or not self.account:
            cards._clear()
            return
        opt = self.opt_store.optimizations.get(oid)
        if not opt:
            cards._clear()
            return
        rune_mode = "rta" if mode == "rta" else "siege"
        cards.render_saved_optimization(opt, self.account, self.monster_db, self.assets_dir,
                                        rune_mode=rune_mode)

    def _on_delete_saved_opt(self, mode: str):
        combo, _ = self._saved_opt_widgets(mode)
        oid = str(combo.currentData() or "")
        if not oid:
            return
        opt = self.opt_store.optimizations.get(oid)
        name = opt.name if opt else oid
        reply = QMessageBox.question(
            self, "Löschen", f"'{name}' wirklich löschen?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.opt_store.remove(oid)
        self.opt_store.save(self.opt_store_path)
        self._refresh_saved_opt_combo(mode)

    # ============================================================
    # Siege raw view
    # ============================================================
    def _render_siege_raw(self):
        if not self.account:
            return
        self.siege_cards.render(self.account, self.monster_db, self.assets_dir)

    # ============================================================
    # Custom Builders UI
    # ============================================================
    def _init_siege_builder_ui(self):
        v = QVBoxLayout(self.tab_siege_builder)

        box = QGroupBox("Siege-Teams auswählen (bis zu 10 Verteidigungen × 3 Monster)")
        v.addWidget(box, 1)
        box_layout = QVBoxLayout(box)
        siege_scroll = QScrollArea()
        siege_scroll.setWidgetResizable(True)
        box_layout.addWidget(siege_scroll)
        siege_inner = QWidget()
        grid = QGridLayout(siege_inner)
        siege_scroll.setWidget(siege_inner)

        self._all_unit_combos: List[QComboBox] = []

        self.siege_team_combos: List[List[QComboBox]] = []
        for t in range(10):
            grid.addWidget(QLabel(f"Verteidigung {t+1}"), t, 0)
            row: List[QComboBox] = []
            for s in range(3):
                cmb = _NoScrollComboBox()
                cmb.setMinimumWidth(300)
                self._all_unit_combos.append(cmb)
                grid.addWidget(cmb, t, 1 + s)
                row.append(cmb)
            self.siege_team_combos.append(row)

        btn_row = QHBoxLayout()
        v.addLayout(btn_row)

        self.btn_take_current_siege = QPushButton("Aktuelle Siege-Verteidigungen übernehmen")
        self.btn_take_current_siege.setEnabled(False)
        self.btn_take_current_siege.clicked.connect(self.on_take_current_siege)
        btn_row.addWidget(self.btn_take_current_siege)

        self.btn_validate_siege = QPushButton("Validieren (Pools/Teams)")
        self.btn_validate_siege.setEnabled(False)
        self.btn_validate_siege.clicked.connect(self.on_validate_siege)
        btn_row.addWidget(self.btn_validate_siege)

        self.btn_edit_presets_siege = QPushButton("Builds (Sets+Mainstats)…")
        self.btn_edit_presets_siege.setEnabled(False)
        self.btn_edit_presets_siege.clicked.connect(self.on_edit_presets_siege)
        btn_row.addWidget(self.btn_edit_presets_siege)

        self.btn_optimize_siege = QPushButton("Optimieren (Runen)")
        self.btn_optimize_siege.setEnabled(False)
        self.btn_optimize_siege.clicked.connect(self.on_optimize_siege)
        btn_row.addWidget(self.btn_optimize_siege)

        self.chk_turn_order_siege = QCheckBox("Turn Order erzwingen")
        self.chk_turn_order_siege.setChecked(False)
        btn_row.addWidget(self.chk_turn_order_siege)

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.lbl_siege_validate = QLabel("—")
        v.addWidget(self.lbl_siege_validate)

    def _init_wgb_builder_ui(self):
        v = QVBoxLayout(self.tab_wgb_builder)

        # ── team selection grid (5 defs x 3 monsters) ────────
        box = QGroupBox("WGB-Teams auswählen (5 Verteidigungen × 3 Monster)")
        v.addWidget(box)
        grid = QGridLayout(box)

        self.wgb_team_combos: List[List[QComboBox]] = []
        for t in range(5):
            grid.addWidget(QLabel(f"Verteidigung {t+1}"), t, 0)
            row: List[QComboBox] = []
            for s in range(3):
                cmb = _NoScrollComboBox()
                cmb.setMinimumWidth(300)
                self._all_unit_combos.append(cmb)
                grid.addWidget(cmb, t, 1 + s)
                row.append(cmb)
            self.wgb_team_combos.append(row)

        # ── buttons ──────────────────────────────────────────
        btn_row = QHBoxLayout()
        v.addLayout(btn_row)

        self.btn_validate_wgb = QPushButton("Validieren (Pools/Teams)")
        self.btn_validate_wgb.setEnabled(False)
        self.btn_validate_wgb.clicked.connect(self.on_validate_wgb)
        btn_row.addWidget(self.btn_validate_wgb)

        self.btn_edit_presets_wgb = QPushButton("Builds (Sets+Mainstats)…")
        self.btn_edit_presets_wgb.setEnabled(False)
        self.btn_edit_presets_wgb.clicked.connect(self.on_edit_presets_wgb)
        btn_row.addWidget(self.btn_edit_presets_wgb)

        self.btn_optimize_wgb = QPushButton("Optimieren (Runen)")
        self.btn_optimize_wgb.setEnabled(False)
        self.btn_optimize_wgb.clicked.connect(self.on_optimize_wgb)
        btn_row.addWidget(self.btn_optimize_wgb)

        self.chk_turn_order_wgb = QCheckBox("Turn Order erzwingen")
        self.chk_turn_order_wgb.setChecked(False)
        btn_row.addWidget(self.chk_turn_order_wgb)

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.lbl_wgb_validate = QLabel("—")
        v.addWidget(self.lbl_wgb_validate)

        # ── preview cards ────────────────────────────────────
        self.wgb_preview_cards = SiegeDefCardsWidget()
        v.addWidget(self.wgb_preview_cards, 1)

    def _init_rta_builder_ui(self):
        v = QVBoxLayout(self.tab_rta_builder)

        box = QGroupBox("RTA Monster auswählen (bis zu 15 – Reihenfolge per Drag & Drop)")
        v.addWidget(box, 1)
        box_layout = QVBoxLayout(box)

        # Top row: combo selector + add/remove + load current
        top_row = QHBoxLayout()
        self.rta_add_combo = _NoScrollComboBox()
        self.rta_add_combo.setMinimumWidth(350)
        self._all_unit_combos.append(self.rta_add_combo)
        top_row.addWidget(self.rta_add_combo, 1)

        btn_add = QPushButton("Hinzufügen")
        btn_add.clicked.connect(self._on_rta_add_monster)
        top_row.addWidget(btn_add)

        btn_remove = QPushButton("Entfernen")
        btn_remove.clicked.connect(self._on_rta_remove_monster)
        top_row.addWidget(btn_remove)

        self.btn_take_current_rta = QPushButton("Aktuelle RTA Monster übernehmen")
        self.btn_take_current_rta.setEnabled(False)
        self.btn_take_current_rta.clicked.connect(self.on_take_current_rta)
        top_row.addWidget(self.btn_take_current_rta)

        box_layout.addLayout(top_row)

        # Selected monsters list with drag-and-drop reordering
        self.rta_selected_list = QListWidget()
        self.rta_selected_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.rta_selected_list.setDefaultDropAction(Qt.MoveAction)
        self.rta_selected_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.rta_selected_list.setIconSize(QSize(40, 40))
        box_layout.addWidget(self.rta_selected_list)

        # Action buttons
        btn_row = QHBoxLayout()
        v.addLayout(btn_row)

        self.btn_validate_rta = QPushButton("Validieren")
        self.btn_validate_rta.setEnabled(False)
        self.btn_validate_rta.clicked.connect(self.on_validate_rta)
        btn_row.addWidget(self.btn_validate_rta)

        self.btn_edit_presets_rta = QPushButton("Builds (Sets+Mainstats)…")
        self.btn_edit_presets_rta.setEnabled(False)
        self.btn_edit_presets_rta.clicked.connect(self.on_edit_presets_rta)
        btn_row.addWidget(self.btn_edit_presets_rta)

        self.btn_optimize_rta = QPushButton("Optimieren (Runen)")
        self.btn_optimize_rta.setEnabled(False)
        self.btn_optimize_rta.clicked.connect(self.on_optimize_rta)
        btn_row.addWidget(self.btn_optimize_rta)

        self.chk_turn_order_rta = QCheckBox("Turn Order erzwingen")
        self.chk_turn_order_rta.setChecked(False)
        btn_row.addWidget(self.chk_turn_order_rta)

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.lbl_rta_validate = QLabel("—")
        v.addWidget(self.lbl_rta_validate)

    def _init_team_tab_ui(self):
        layout = QVBoxLayout(self.tab_team_builder)

        row = QHBoxLayout()
        row.addWidget(QLabel("Team"))
        self.team_combo = QComboBox()
        self.team_combo.currentIndexChanged.connect(self._on_team_selected)
        row.addWidget(self.team_combo, 1)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.btn_new_team = QPushButton("Neues Team")
        self.btn_new_team.clicked.connect(self._on_new_team)
        btn_row.addWidget(self.btn_new_team)
        self.btn_edit_team = QPushButton("Team bearbeiten")
        self.btn_edit_team.clicked.connect(self._on_edit_team)
        btn_row.addWidget(self.btn_edit_team)
        self.btn_remove_team = QPushButton("Team löschen")
        self.btn_remove_team.clicked.connect(self._on_remove_team)
        btn_row.addWidget(self.btn_remove_team)
        layout.addLayout(btn_row)

        self.btn_optimize_team = QPushButton("Team optimieren")
        self.btn_optimize_team.clicked.connect(self._optimize_team)
        layout.addWidget(self.btn_optimize_team)

        self.chk_turn_order_team = QCheckBox("Turn Order erzwingen")
        self.chk_turn_order_team.setChecked(False)
        layout.addWidget(self.chk_turn_order_team)

        self.lbl_team_units = QLabel("Importiere zuerst ein Konto.")
        layout.addWidget(self.lbl_team_units)

        self._refresh_team_combo()
        self._set_team_controls_enabled(False)

    def _current_team(self) -> Team | None:
        tid = str(self.team_combo.currentData() or "")
        if not tid:
            return None
        return self.team_store.teams.get(tid)

    def _refresh_team_combo(self) -> None:
        current_id = str(self.team_combo.currentData() or "")
        self.team_combo.blockSignals(True)
        self.team_combo.clear()
        teams = sorted(self.team_store.teams.values(), key=lambda t: t.name)
        for team in teams:
            self.team_combo.addItem(f"{team.name} ({len(team.unit_ids)} Units)", team.id)
        self.team_combo.blockSignals(False)
        if not teams:
            self.lbl_team_units.setText("Keine Teams definiert.")
            self._set_team_controls_enabled(False)
            return
        self._select_team_by_id(current_id or teams[0].id)
        self._on_team_selected()

    def _select_team_by_id(self, tid: str) -> None:
        idx = self.team_combo.findData(tid)
        if idx >= 0:
            self.team_combo.setCurrentIndex(idx)

    def _set_team_controls_enabled(self, has_account: bool) -> None:
        team_exists = self._current_team() is not None
        self.btn_new_team.setEnabled(has_account)
        self.btn_edit_team.setEnabled(has_account and team_exists)
        self.btn_remove_team.setEnabled(has_account and team_exists)
        self.btn_optimize_team.setEnabled(has_account and team_exists)
        self.team_combo.setEnabled(bool(self.team_store.teams))

    def _on_team_selected(self) -> None:
        team = self._current_team()
        if not team:
            if not self.team_store.teams:
                self.lbl_team_units.setText("Keine Teams definiert.")
            else:
                self.lbl_team_units.setText("Kein Team ausgewählt.")
            self._set_team_controls_enabled(bool(self.account))
            return
        self.lbl_team_units.setText(self._team_units_text(team))
        self._set_team_controls_enabled(bool(self.account))
        if not self.account:
            return

    def _team_units_text(self, team: Team) -> str:
        if not team.unit_ids:
            return "Keine Units."
        return "\n".join(self._unit_text_cached(uid) for uid in team.unit_ids)

    def _on_new_team(self) -> None:
        if not self.account:
            QMessageBox.warning(self, "Team", "Bitte zuerst einen Import laden.")
            return
        dlg = TeamEditorDialog(
            self,
            self.account,
            self._unit_text_cached,
            self._icon_for_master_id,
            unit_combo_model=self._ensure_unit_combo_model(),
        )
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            team = self.team_store.upsert(dlg.team_name or "Team", dlg.unit_ids)
        except ValueError as exc:
            QMessageBox.warning(self, "Team", str(exc))
            return
        self.team_store.save(self.team_config_path)
        self._refresh_team_combo()
        self._select_team_by_id(team.id)

    def _on_edit_team(self) -> None:
        if not self.account:
            QMessageBox.warning(self, "Team", "Bitte zuerst einen Import laden.")
            return
        team = self._current_team()
        if not team:
            return
        dlg = TeamEditorDialog(
            self,
            self.account,
            self._unit_text_cached,
            self._icon_for_master_id,
            team=team,
            unit_combo_model=self._ensure_unit_combo_model(),
        )
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            self.team_store.upsert(dlg.team_name or team.name, dlg.unit_ids, tid=team.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Team", str(exc))
            return
        self.team_store.save(self.team_config_path)
        self._refresh_team_combo()
        self._select_team_by_id(team.id)

    def _on_remove_team(self) -> None:
        team = self._current_team()
        if not team:
            return
        self.team_store.remove(team.id)
        self.team_store.save(self.team_config_path)
        self._refresh_team_combo()

    def _optimize_team(self) -> None:
        team = self._current_team()
        if not self.account or not team:
            QMessageBox.warning(self, "Team", "Bitte zuerst einen Import laden und ein Team auswählen.")
            return
        ordered_unit_ids = self._units_by_turn_order("siege", team.unit_ids)
        team_idx_by_uid: Dict[int, int] = {int(uid): 0 for uid in team.unit_ids}
        team_turn_by_uid: Dict[int, int] = {}
        for uid in team.unit_ids:
            builds = self.presets.get_unit_builds("siege", int(uid))
            b0 = builds[0] if builds else Build.default_any()
            team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
        res = optimize_greedy(
            self.account,
            self.presets,
            GreedyRequest(
                mode="siege",
                unit_ids_in_order=ordered_unit_ids,
                time_limit_per_unit_s=5.0,
                workers=8,
                enforce_turn_order=bool(self.chk_turn_order_team.isChecked()),
                unit_team_index=team_idx_by_uid,
                unit_team_turn_order=team_turn_by_uid,
            ),
        )
        self._show_optimize_results(
            f"Team Optimierung: {team.name}", res.message, res.results,
            mode="siege", teams=[team.unit_ids],
        )

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
            QMessageBox.warning(self, "Optimierung", "Bitte zuerst einen Import laden.")
            return
        rune_lookup: Dict[int, Rune] = {r.rune_id: r for r in self.account.runes}
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
            self._unit_text,
            self._unit_icon_for_unit_id,
            self._unit_final_spd_value,
            self._unit_final_stats_values,
            self._rune_set_icon,
            self._unit_base_stats,
            self._unit_leader_bonus,
            unit_team_index=unit_team_index,
            unit_display_order=unit_display_order,
            mode_rune_owner=mode_rune_owner,
        )
        dlg.exec()

        if dlg.saved and mode and teams:
            from datetime import datetime
            ts = datetime.now().strftime("%d.%m.%Y %H:%M")
            name = f"{mode.upper()} Optimierung {ts}"
            saved_results: List[SavedUnitResult] = []
            for r in results:
                if r.ok and r.runes_by_slot:
                    saved_results.append(SavedUnitResult(
                        unit_id=r.unit_id,
                        runes_by_slot=dict(r.runes_by_slot),
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
        if not self.account:
            return {}
        u = self.account.units_by_id.get(unit_id)
        if not u:
            return {}
        return {
            "HP": int((u.base_con or 0) * 15),
            "ATK": int(u.base_atk or 0),
            "DEF": int(u.base_def or 0),
            "SPD": int(u.base_spd or 0),
            "CR": int(u.crit_rate or 15),
            "CD": int(u.crit_dmg or 50),
            "RES": int(u.base_res or 15),
            "ACC": int(u.base_acc or 0),
        }

    def _unit_leader_bonus(self, unit_id: int, team_unit_ids: List[int]) -> Dict[str, int]:
        """Return the leader skill bonus for *unit_id* given the team.

        Monster 1 (team_unit_ids[0]) provides the leader skill.
        """
        out: Dict[str, int] = {}
        if not self.account:
            return out
        u = self.account.units_by_id.get(unit_id)
        if not u:
            return out
        ls = self._team_leader_skill(team_unit_ids)
        if not ls:
            return out
        base_hp = int((u.base_con or 0) * 15)
        base_atk = int(u.base_atk or 0)
        base_def = int(u.base_def or 0)
        base_spd = int(u.base_spd or 0)
        s, a = ls.stat, ls.amount
        if s == "HP%":
            out["HP"] = int(base_hp * a / 100)
        elif s == "ATK%":
            out["ATK"] = int(base_atk * a / 100)
        elif s == "DEF%":
            out["DEF"] = int(base_def * a / 100)
        elif s == "SPD%":
            out["SPD"] = int(base_spd * a / 100)
        elif s == "CR%":
            out["CR"] = a
        elif s == "CD%":
            out["CD"] = a
        elif s == "RES%":
            out["RES"] = a
        elif s == "ACC%":
            out["ACC"] = a
        return out

    def _unit_final_spd_value(
        self,
        unit_id: int,
        team_unit_ids: List[int],
        runes_by_unit: Dict[int, Dict[int, int]],
    ) -> int:
        if not self.account:
            return 0
        u = self.account.units_by_id.get(unit_id)
        if not u:
            return 0
        base_spd = int(u.base_spd or 0)
        rune_lookup: Dict[int, Rune] = {r.rune_id: r for r in self.account.runes}
        rune_ids = list((runes_by_unit.get(unit_id) or {}).values())

        rune_spd_flat = 0
        rune_set_ids: List[int] = []
        for rid in rune_ids:
            rune = rune_lookup.get(int(rid))
            if not rune:
                continue
            rune_set_ids.append(int(rune.set_id or 0))
            rune_spd_flat += self._spd_from_stat_tuple(rune.pri_eff)
            rune_spd_flat += self._spd_from_stat_tuple(rune.prefix_eff)
            rune_spd_flat += self._spd_from_substats(rune.sec_eff)

        swift_sets = rune_set_ids.count(3) // 4
        set_spd_pct = 25 * swift_sets
        set_spd_bonus = int(base_spd * set_spd_pct / 100)

        ls = self._team_leader_skill(team_unit_ids)
        lead_spd_bonus = int(base_spd * ls.amount / 100) if ls and ls.stat == "SPD%" else 0

        return int(base_spd + rune_spd_flat + set_spd_bonus + lead_spd_bonus)

    def _unit_final_stats_values(
        self,
        unit_id: int,
        team_unit_ids: List[int],
        runes_by_unit: Dict[int, Dict[int, int]],
    ) -> Dict[str, int]:
        if not self.account:
            return {}
        u = self.account.units_by_id.get(unit_id)
        if not u:
            return {}

        base_hp = int((u.base_con or 0) * 15)
        base_atk = int(u.base_atk or 0)
        base_def = int(u.base_def or 0)
        base_spd = int(u.base_spd or 0)
        base_cr = int(u.crit_rate or 15)
        base_cd = int(u.crit_dmg or 50)
        base_res = int(u.base_res or 15)
        base_acc = int(u.base_acc or 0)

        flat_hp = flat_atk = flat_def = 0
        pct_hp = pct_atk = pct_def = 0
        add_spd = add_cr = add_cd = add_res = add_acc = 0

        rune_lookup: Dict[int, Rune] = {r.rune_id: r for r in self.account.runes}
        rune_ids = list((runes_by_unit.get(unit_id) or {}).values())
        rune_set_ids: List[int] = []

        def _acc_stat(eff_id: int, value: int) -> None:
            nonlocal flat_hp, flat_atk, flat_def, pct_hp, pct_atk, pct_def
            nonlocal add_spd, add_cr, add_cd, add_res, add_acc
            if eff_id == 1:
                flat_hp += int(value or 0)
            elif eff_id == 2:
                pct_hp += int(value or 0)
            elif eff_id == 3:
                flat_atk += int(value or 0)
            elif eff_id == 4:
                pct_atk += int(value or 0)
            elif eff_id == 5:
                flat_def += int(value or 0)
            elif eff_id == 6:
                pct_def += int(value or 0)
            elif eff_id == 8:
                add_spd += int(value or 0)
            elif eff_id == 9:
                add_cr += int(value or 0)
            elif eff_id == 10:
                add_cd += int(value or 0)
            elif eff_id == 11:
                add_res += int(value or 0)
            elif eff_id == 12:
                add_acc += int(value or 0)

        for rid in rune_ids:
            rune = rune_lookup.get(int(rid))
            if not rune:
                continue
            rune_set_ids.append(int(rune.set_id or 0))
            try:
                _acc_stat(int(rune.pri_eff[0] or 0), int(rune.pri_eff[1] or 0))
            except Exception:
                pass
            try:
                _acc_stat(int(rune.prefix_eff[0] or 0), int(rune.prefix_eff[1] or 0))
            except Exception:
                pass
            for sec in (rune.sec_eff or []):
                if not sec:
                    continue
                try:
                    eff = int(sec[0] or 0)
                    val = int(sec[1] or 0)
                    grind = int(sec[3] or 0) if len(sec) >= 4 else 0
                    _acc_stat(eff, val + grind)
                except Exception:
                    continue

        swift_sets = rune_set_ids.count(3) // 4
        spd_from_swift = int(base_spd * (25 * swift_sets) / 100)

        # Leader skill from monster 1 (first in team)
        ls = self._team_leader_skill(team_unit_ids)
        lead_hp = lead_atk = lead_def = lead_spd = 0
        lead_cr = lead_cd = lead_res = lead_acc = 0
        if ls:
            s, a = ls.stat, ls.amount
            if s == "HP%":
                lead_hp = int(base_hp * a / 100)
            elif s == "ATK%":
                lead_atk = int(base_atk * a / 100)
            elif s == "DEF%":
                lead_def = int(base_def * a / 100)
            elif s == "SPD%":
                lead_spd = int(base_spd * a / 100)
            elif s == "CR%":
                lead_cr = a
            elif s == "CD%":
                lead_cd = a
            elif s == "RES%":
                lead_res = a
            elif s == "ACC%":
                lead_acc = a

        hp = base_hp + flat_hp + int(base_hp * pct_hp / 100) + lead_hp
        atk = base_atk + flat_atk + int(base_atk * pct_atk / 100) + lead_atk
        deff = base_def + flat_def + int(base_def * pct_def / 100) + lead_def
        spd = base_spd + add_spd + spd_from_swift + lead_spd

        return {
            "HP": int(hp),
            "ATK": int(atk),
            "DEF": int(deff),
            "SPD": int(spd),
            "CR": int(base_cr + add_cr + lead_cr),
            "CD": int(base_cd + add_cd + lead_cd),
            "RES": int(base_res + add_res + lead_res),
            "ACC": int(base_acc + add_acc + lead_acc),
        }

    def _team_leader_skill(self, team_unit_ids: List[int]) -> Optional[LeaderSkill]:
        """Return the applicable leader skill for the team.

        The leader is the first unit (monster 1). Only Guild and General
        area leader skills apply (for siege / WGB).
        """
        if not self.account or not team_unit_ids:
            return None
        leader_uid = team_unit_ids[0]
        u = self.account.units_by_id.get(int(leader_uid))
        if not u:
            return None
        ls = self.monster_db.leader_skill_for(u.unit_master_id)
        if ls and ls.area in ("Guild", "General"):
            return ls
        return None

    def _spd_from_stat_tuple(self, stat: Tuple[int, int] | Tuple[int, int, int, int]) -> int:
        if not stat:
            return 0
        try:
            if int(stat[0] or 0) != 8:
                return 0
            return int(stat[1] or 0)
        except Exception:
            return 0

    def _spd_from_substats(self, subs: List[Tuple[int, int, int, int]]) -> int:
        total = 0
        for sec in subs or []:
            try:
                if int(sec[0] or 0) != 8:
                    continue
                total += int(sec[1] or 0)
                if len(sec) >= 4:
                    total += int(sec[3] or 0)
            except Exception:
                continue
        return total

    def _ensure_siege_team_defaults(self) -> None:
        if not self.account:
            return
        existing_names = {team.name for team in self.team_store.teams.values()}
        added = False
        for idx, units in enumerate(self.account.siege_def_teams(), start=1):
            if not units:
                continue
            name = f"Siege Verteidigung {idx}"
            if name in existing_names:
                continue
            try:
                self.team_store.upsert(name, units)
            except ValueError:
                continue
            existing_names.add(name)
            added = True
        if added:
            self.team_store.save(self.team_config_path)

    # ============================================================
    # Siege actions
    # ============================================================
    def on_take_current_siege(self):
        if not self.account:
            return
        teams = self.account.siege_def_teams()
        for t in range(min(len(teams), len(self.siege_team_combos))):
            team = teams[t]
            for s in range(min(3, len(team))):
                uid = team[s]
                cmb = self.siege_team_combos[t][s]
                idx = cmb.findData(uid)
                cmb.setCurrentIndex(idx if idx >= 0 else 0)

        self.lbl_siege_validate.setText("Aktuelle Verteidigungen übernommen. Bitte validieren.")

    def _collect_siege_selections(self) -> List[TeamSelection]:
        self._ensure_unit_dropdowns_populated()
        selections: List[TeamSelection] = []
        for t, row in enumerate(self.siege_team_combos):
            ids = []
            for cmb in row:
                uid = int(cmb.currentData() or 0)
                if uid != 0:
                    ids.append(uid)
            selections.append(TeamSelection(team_index=t, unit_ids=ids))
        return selections

    def _validate_team_structure(self, label: str, selections: List[TeamSelection], must_have_team_size: int) -> Tuple[bool, str, List[int]]:
        """Validate team structure.  Checks per-team completeness and
        intra-team uniqueness (no duplicate unit within the same team).
        Cross-team uniqueness is NOT enforced here – use
        ``_validate_unique_monsters`` for that (WGB requirement).
        """
        all_units: List[int] = []

        for sel in selections:
            if not sel.unit_ids:
                continue
            if len(sel.unit_ids) != must_have_team_size:
                return False, f"{label}: Team {sel.team_index+1} ist unvollständig ({len(sel.unit_ids)}/{must_have_team_size}).", []
            # intra-team duplicate check
            team_set: Set[int] = set()
            for uid in sel.unit_ids:
                if uid in team_set:
                    name = self._unit_text(uid) if self.account else str(uid)
                    return False, f"{label}: Team {sel.team_index+1} enthält '{name}' doppelt.", []
                team_set.add(uid)
            all_units.extend(sel.unit_ids)

        if not all_units:
            return False, f"{label}: Keine Teams ausgewählt.", []

        return True, f"{label}: OK ({len(all_units)} Units).", all_units

    def on_validate_siege(self):
        if not self.account:
            return
        selections = self._collect_siege_selections()
        ok, msg, all_units = self._validate_team_structure("Siege", selections, must_have_team_size=3)
        if not ok:
            self.lbl_siege_validate.setText(msg)
            QMessageBox.critical(self, "Siege Validierung", msg)
            return
        self.lbl_siege_validate.setText(msg)
        QMessageBox.information(self, "Siege Validierung OK", msg)

    def on_edit_presets_siege(self):
        if not self.account:
            return
        selections = self._collect_siege_selections()
        ok, msg, all_units = self._validate_team_structure("Siege", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(self, "Siege", f"Bitte erst validieren.\n\n{msg}")
            return

        unit_rows: List[Tuple[int, str]] = [(uid, self._unit_text(uid)) for uid in all_units]

        dlg = BuildDialog(self, "Siege Builds", unit_rows, self.presets, "siege", self._unit_icon_for_unit_id, team_size=3)
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.apply_to_store()
            except ValueError as exc:
                QMessageBox.critical(self, "Builds", str(exc))
                return
            self.presets.save(self.presets_path)
            QMessageBox.information(self, "Builds gespeichert", f"Gespeichert in {self.presets_path}")

    def on_optimize_siege(self):
        if not self.account:
            return
        selections = self._collect_siege_selections()
        ok, msg, all_units = self._validate_team_structure("Siege", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(self, "Siege", f"Bitte erst validieren.\n\n{msg}")
            return

        ordered_unit_ids = self._units_by_turn_order("siege", all_units)
        team_idx_by_uid: Dict[int, int] = {}
        for idx, sel in enumerate(selections):
            for uid in sel.unit_ids:
                team_idx_by_uid[int(uid)] = int(idx)
        team_turn_by_uid: Dict[int, int] = {}
        for uid in all_units:
            builds = self.presets.get_unit_builds("siege", int(uid))
            b0 = builds[0] if builds else Build.default_any()
            team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
        res = optimize_greedy(
            self.account,
            self.presets,
            GreedyRequest(
                mode="siege",
                unit_ids_in_order=ordered_unit_ids,
                time_limit_per_unit_s=5.0,
                workers=8,
                enforce_turn_order=bool(self.chk_turn_order_siege.isChecked()),
                unit_team_index=team_idx_by_uid,
                unit_team_turn_order=team_turn_by_uid,
            ),
        )
        unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(all_units)}
        siege_teams = [sel.unit_ids for sel in selections if sel.unit_ids]
        self._show_optimize_results(
            "Greedy Optimierung",
            res.message,
            res.results,
            unit_team_index=team_idx_by_uid,
            unit_display_order=unit_display_order,
            mode="siege",
            teams=siege_teams,
        )

    def _units_by_turn_order(self, mode: str, unit_ids: List[int]) -> List[int]:
        indexed: List[Tuple[int, int, int]] = []
        for pos, uid in enumerate(unit_ids):
            builds = self.presets.get_unit_builds(mode, int(uid))
            b0 = builds[0] if builds else Build.default_any()
            opt = int(getattr(b0, "optimize_order", 0) or 0)
            indexed.append((opt, pos, int(uid)))
        with_order = [x for x in indexed if x[0] > 0]
        without_order = [x for x in indexed if x[0] <= 0]
        with_order.sort(key=lambda t: (t[0], t[1]))
        without_order.sort(key=lambda t: t[1])
        return [uid for _, _, uid in (with_order + without_order)]

    def _units_by_turn_order_grouped(self, mode: str, unit_ids: List[int], group_size: int) -> List[int]:
        if group_size <= 0:
            return self._units_by_turn_order(mode, unit_ids)
        out: List[int] = []
        for i in range(0, len(unit_ids), group_size):
            group = unit_ids[i:i + group_size]
            out.extend(self._units_by_turn_order(mode, group))
        return out

    # ============================================================
    # WGB Builder
    # ============================================================
    def _collect_wgb_selections(self) -> List[TeamSelection]:
        self._ensure_unit_dropdowns_populated()
        selections: List[TeamSelection] = []
        for t, row in enumerate(self.wgb_team_combos):
            ids = []
            for cmb in row:
                uid = int(cmb.currentData() or 0)
                if uid != 0:
                    ids.append(uid)
            selections.append(TeamSelection(team_index=t, unit_ids=ids))
        return selections

    def _validate_unique_monsters(self, all_unit_ids: List[int]) -> Tuple[bool, str]:
        """Check that no unit_master_id appears more than once."""
        if not self.account:
            return False, "Kein Account geladen."
        seen: Dict[int, str] = {}  # master_id -> first unit name
        for uid in all_unit_ids:
            u = self.account.units_by_id.get(uid)
            if not u:
                continue
            mid = u.unit_master_id
            name = self.monster_db.name_for(mid)
            if mid in seen:
                return False, f"Monster '{name}' kommt mehrfach vor (WGB erlaubt jedes Monster nur 1×)."
            seen[mid] = name
        return True, ""

    def on_validate_wgb(self):
        if not self.account:
            return
        selections = self._collect_wgb_selections()
        ok, msg, all_units = self._validate_team_structure("WGB", selections, must_have_team_size=3)
        if not ok:
            self.lbl_wgb_validate.setText(msg)
            QMessageBox.critical(self, "WGB Validierung", msg)
            return
        # unique monster check
        ok2, msg2 = self._validate_unique_monsters(all_units)
        if not ok2:
            self.lbl_wgb_validate.setText(msg2)
            QMessageBox.critical(self, "WGB Validierung", msg2)
            return
        self.lbl_wgb_validate.setText(msg)
        QMessageBox.information(self, "WGB Validierung OK", msg)
        # update preview cards
        self._render_wgb_preview(selections)

    def on_edit_presets_wgb(self):
        if not self.account:
            return
        selections = self._collect_wgb_selections()
        ok, msg, all_units = self._validate_team_structure("WGB", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(self, "WGB", f"Bitte erst validieren.\n\n{msg}")
            return
        ok2, msg2 = self._validate_unique_monsters(all_units)
        if not ok2:
            QMessageBox.critical(self, "WGB", msg2)
            return

        unit_rows: List[Tuple[int, str]] = [(uid, self._unit_text(uid)) for uid in all_units]
        dlg = BuildDialog(self, "WGB Builds", unit_rows, self.presets, "wgb", self._unit_icon_for_unit_id, team_size=3)
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.apply_to_store()
            except ValueError as exc:
                QMessageBox.critical(self, "Builds", str(exc))
                return
            self.presets.save(self.presets_path)
            QMessageBox.information(self, "Builds gespeichert", f"Gespeichert in {self.presets_path}")

    def on_optimize_wgb(self):
        if not self.account:
            return
        selections = self._collect_wgb_selections()
        ok, msg, all_units = self._validate_team_structure("WGB", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(self, "WGB", f"Bitte erst validieren.\n\n{msg}")
            return
        ok2, msg2 = self._validate_unique_monsters(all_units)
        if not ok2:
            QMessageBox.critical(self, "WGB", msg2)
            return

        ordered_unit_ids = self._units_by_turn_order("wgb", all_units)
        team_idx_by_uid: Dict[int, int] = {}
        for idx, sel in enumerate(selections):
            for uid in sel.unit_ids:
                team_idx_by_uid[int(uid)] = int(idx)
        team_turn_by_uid: Dict[int, int] = {}
        for uid in all_units:
            builds = self.presets.get_unit_builds("wgb", int(uid))
            b0 = builds[0] if builds else Build.default_any()
            team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
        res = optimize_greedy(
            self.account,
            self.presets,
            GreedyRequest(
                mode="wgb",
                unit_ids_in_order=ordered_unit_ids,
                time_limit_per_unit_s=5.0,
                workers=8,
                enforce_turn_order=bool(self.chk_turn_order_wgb.isChecked()),
                unit_team_index=team_idx_by_uid,
                unit_team_turn_order=team_turn_by_uid,
            ),
        )
        unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(all_units)}
        wgb_teams = [sel.unit_ids for sel in selections if sel.unit_ids]
        self._show_optimize_results(
            "WGB Greedy Optimierung",
            res.message,
            res.results,
            unit_team_index=team_idx_by_uid,
            unit_display_order=unit_display_order,
            mode="wgb",
            teams=wgb_teams,
        )

    def _render_wgb_preview(self, selections: List[TeamSelection] | None = None):
        if not self.account:
            return
        if selections is None:
            selections = self._collect_wgb_selections()
        teams = [sel.unit_ids for sel in selections if sel.unit_ids]
        self.wgb_preview_cards.render_from_selections(
            teams, self.account, self.monster_db, self.assets_dir, rune_mode="siege",
        )

    # ============================================================
    # RTA Builder
    # ============================================================
    def _on_rta_add_monster(self):
        self._ensure_unit_dropdowns_populated()
        uid = int(self.rta_add_combo.currentData() or 0)
        if uid == 0:
            return
        if self.rta_selected_list.count() >= 15:
            QMessageBox.warning(self, "RTA", "Maximal 15 Monster erlaubt.")
            return
        for i in range(self.rta_selected_list.count()):
            if int(self.rta_selected_list.item(i).data(Qt.UserRole) or 0) == uid:
                return
        item = QListWidgetItem(self._unit_text(uid))
        item.setData(Qt.UserRole, uid)
        item.setIcon(self._unit_icon_for_unit_id(uid))
        self.rta_selected_list.addItem(item)

    def _on_rta_remove_monster(self):
        for item in list(self.rta_selected_list.selectedItems()):
            self.rta_selected_list.takeItem(self.rta_selected_list.row(item))

    def on_take_current_rta(self):
        if not self.account:
            return
        active_uids = self.account.rta_active_unit_ids()
        self.rta_selected_list.clear()
        for uid in active_uids[:15]:
            item = QListWidgetItem(self._unit_text(uid))
            item.setData(Qt.UserRole, uid)
            item.setIcon(self._unit_icon_for_unit_id(uid))
            self.rta_selected_list.addItem(item)
        self.lbl_rta_validate.setText(
            f"{min(len(active_uids), 15)} aktive RTA Monster übernommen."
        )

    def _collect_rta_unit_ids(self) -> List[int]:
        """Return selected unit IDs in the current drag-and-drop order."""
        ids: List[int] = []
        for i in range(self.rta_selected_list.count()):
            uid = int(self.rta_selected_list.item(i).data(Qt.UserRole) or 0)
            if uid != 0:
                ids.append(uid)
        return ids

    def on_validate_rta(self):
        if not self.account:
            return
        ids = self._collect_rta_unit_ids()
        if not ids:
            msg = "RTA: Keine Monster ausgewählt."
            self.lbl_rta_validate.setText(msg)
            QMessageBox.critical(self, "RTA Validierung", msg)
            return
        seen: Set[int] = set()
        for uid in ids:
            if uid in seen:
                name = self._unit_text(uid)
                msg = f"RTA: '{name}' ist doppelt ausgewählt."
                self.lbl_rta_validate.setText(msg)
                QMessageBox.critical(self, "RTA Validierung", msg)
                return
            seen.add(uid)
        msg = f"RTA: OK ({len(ids)} Monster)."
        self.lbl_rta_validate.setText(msg)
        QMessageBox.information(self, "RTA Validierung OK", msg)

    def on_edit_presets_rta(self):
        if not self.account:
            return
        ids = self._collect_rta_unit_ids()
        if not ids:
            QMessageBox.critical(self, "RTA", "Bitte erst Monster auswählen.")
            return
        if len(ids) != len(set(ids)):
            QMessageBox.critical(self, "RTA", "Duplikate gefunden. Bitte erst validieren.")
            return

        unit_rows: List[Tuple[int, str]] = [(uid, self._unit_text(uid)) for uid in ids]
        dlg = BuildDialog(
            self, "RTA Builds", unit_rows, self.presets, "rta",
            self._unit_icon_for_unit_id, team_size=len(ids),
            show_order_sections=False,
        )
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.apply_to_store()
            except ValueError as exc:
                QMessageBox.critical(self, "Builds", str(exc))
                return
            self.presets.save(self.presets_path)
            QMessageBox.information(self, "Builds gespeichert", f"Gespeichert in {self.presets_path}")

    def on_optimize_rta(self):
        if not self.account:
            return
        ids = self._collect_rta_unit_ids()
        if not ids:
            QMessageBox.critical(self, "RTA", "Bitte erst Monster auswählen.")
            return
        if len(ids) != len(set(ids)):
            QMessageBox.critical(self, "RTA", "Duplikate gefunden. Bitte erst validieren.")
            return

        # List order = optimization order = turn order
        team_idx_by_uid: Dict[int, int] = {int(uid): 0 for uid in ids}
        team_turn_by_uid: Dict[int, int] = {int(uid): pos + 1 for pos, uid in enumerate(ids)}
        res = optimize_greedy(
            self.account,
            self.presets,
            GreedyRequest(
                mode="rta",
                unit_ids_in_order=ids,
                time_limit_per_unit_s=5.0,
                workers=8,
                enforce_turn_order=bool(self.chk_turn_order_rta.isChecked()),
                unit_team_index=team_idx_by_uid,
                unit_team_turn_order=team_turn_by_uid,
            ),
        )
        unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(ids)}
        rta_teams = [ids]
        self._show_optimize_results(
            "RTA Greedy Optimierung",
            res.message,
            res.results,
            unit_team_index=team_idx_by_uid,
            unit_display_order=unit_display_order,
            mode="rta",
            teams=rta_teams,
        )


def _apply_dark_palette(app: QApplication) -> None:
    """Force a dark colour palette so the app looks correct on any OS theme."""
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#1e1e1e"))
    p.setColor(QPalette.WindowText, QColor("#dddddd"))
    p.setColor(QPalette.Base, QColor("#2b2b2b"))
    p.setColor(QPalette.AlternateBase, QColor("#333333"))
    p.setColor(QPalette.ToolTipBase, QColor("#1f242a"))
    p.setColor(QPalette.ToolTipText, QColor("#e6edf3"))
    p.setColor(QPalette.Text, QColor("#dddddd"))
    p.setColor(QPalette.Button, QColor("#2b2b2b"))
    p.setColor(QPalette.ButtonText, QColor("#dddddd"))
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.Link, QColor("#3498db"))
    p.setColor(QPalette.Highlight, QColor("#3498db"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#666666"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#666666"))
    app.setPalette(p)
    app.setStyleSheet("QToolTip { color: #e6edf3; background: #1f242a; border: 1px solid #3a3f46; }")


def run_app():
    app = QApplication(sys.argv)
    _apply_dark_palette(app)
    license_info = _ensure_license_accepted()
    if not license_info:
        sys.exit(1)
    w = MainWindow()
    _apply_license_title(w, license_info)
    w.show()
    sys.exit(app.exec())


class LicenseDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial_key: str = ""):
        super().__init__(parent)
        self.validation_result: LicenseValidation | None = None
        self.setWindowTitle("Lizenz Aktivierung")
        self.resize(520, 180)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Bitte gib deinen Serial Key ein."))

        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("SWTO-...")
        self.edit_key.setText(initial_key)
        layout.addWidget(self.edit_key)

        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)

        buttons = QDialogButtonBox()
        self.btn_validate = buttons.addButton("Aktivieren", QDialogButtonBox.AcceptRole)
        self.btn_cancel = buttons.addButton("Beenden", QDialogButtonBox.RejectRole)
        self.btn_validate.clicked.connect(self._on_validate)
        self.btn_cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def key_text(self) -> str:
        return self.edit_key.text().strip()

    def _on_validate(self) -> None:
        result = validate_license_key(self.key_text)
        if result.valid:
            save_license_key(self.key_text)
            self.validation_result = result
            self.accept()
            return
        self.lbl_status.setText(result.message)


def _format_trial_remaining(expires_at: int, now_ts: int | None = None) -> str:
    now = int(now_ts if now_ts is not None else datetime.now().timestamp())
    remaining_s = max(0, int(expires_at) - now)
    if remaining_s >= 24 * 60 * 60:
        days = max(1, remaining_s // (24 * 60 * 60))
        return f"{days} Tage"
    if remaining_s >= 60 * 60:
        hours = max(1, remaining_s // (60 * 60))
        return f"{hours} Stunden"
    minutes = max(1, remaining_s // 60)
    return f"{minutes} Minuten"


def _apply_license_title(window: QMainWindow, result: LicenseValidation) -> None:
    base_title = "SW Team Optimizer"
    license_type = (result.license_type or "").strip().lower()
    if "trial" not in license_type:
        return
    if result.expires_at:
        remaining = _format_trial_remaining(result.expires_at)
        window.setWindowTitle(f"{base_title} - Trial ({remaining} gültig)")
        return
    window.setWindowTitle(f"{base_title} - Trial")


def _ensure_license_accepted() -> LicenseValidation | None:
    existing = load_license_key()
    if existing:
        check = validate_license_key(existing)
        if check.valid:
            return check

    dlg = LicenseDialog(initial_key=existing or "")
    if dlg.exec() == QDialog.Accepted:
        return dlg.validation_result
    return None
