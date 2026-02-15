from __future__ import annotations

import json
import os
import subprocess
import sys
import webbrowser
import threading
from itertools import product
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Set, Dict, Callable, Any

from PySide6.QtCore import Qt, QSize, QTimer, QSortFilterProxyModel, QRegularExpression, Signal, QObject, QRunnable, QThreadPool, QEventLoop
from PySide6.QtGui import QColor, QIcon, QPalette, QStandardItem, QStandardItemModel, QKeyEvent
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QFileDialog, QLabel, QTableWidget, QTableWidgetItem,
    QMessageBox, QTabWidget, QGroupBox, QGridLayout, QComboBox, QSpacerItem,
    QSizePolicy, QDialog, QDialogButtonBox, QLineEdit, QListWidget,
    QListWidgetItem, QScrollArea, QFrame, QAbstractItemView, QSpinBox, QAbstractSpinBox, QCompleter,
    QHeaderView, QProgressDialog
)

from app.importer.sw_json_importer import load_account_from_data
from app.domain.models import AccountData, Rune, Artifact
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
    ARTIFACT_MAIN_KEYS,
    EFFECT_ID_TO_MAINSTAT_KEY,
)
from app.domain.speed_ticks import allowed_spd_ticks, min_spd_for_tick
from app.engine.greedy_optimizer import optimize_greedy, GreedyRequest, GreedyUnitResult
from app.engine.efficiency import rune_efficiency
from app.services.account_persistence import AccountPersistence
from app.services.license_service import (
    LicenseValidation,
    load_license_keys,
    save_license_key,
    validate_license_key,
)
from app.services.update_service import check_latest_release, UpdateCheckResult
from app.domain.team_store import TeamStore, Team
from app.domain.optimization_store import OptimizationStore, SavedUnitResult
from app.domain.artifact_effects import (
    ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID,
    ARTIFACT_EFFECT_IDS_BY_ARTIFACT_TYPE,
    artifact_effect_label,
    artifact_effect_text,
    artifact_effect_is_legacy,
)
from app.ui.siege_cards_widget import SiegeDefCardsWidget
from app.ui.overview_widget import OverviewWidget
from app.ui.rta_overview_widget import RtaOverviewWidget
from app.i18n import tr


@dataclass
class TeamSelection:
    team_index: int
    unit_ids: List[int]


def _stat_label_tr(key: str) -> str:
    return tr("stat." + key)


def _artifact_kind_label(type_id: int) -> str:
    if type_id == 1:
        return tr("artifact.attribute")
    if type_id == 2:
        return tr("artifact.type")
    return str(type_id)

ARTIFACT_FOCUS_BY_EFFECT_ID: Dict[int, str] = dict(ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID)


def _artifact_focus_key_from_effect_id(effect_id: int) -> str:
    return str(ARTIFACT_FOCUS_BY_EFFECT_ID.get(int(effect_id or 0), ""))


def _artifact_effect_label(effect_id: int) -> str:
    return artifact_effect_label(effect_id, fallback_prefix="Effekt")


def _artifact_effect_text(effect_id: int, value: int | float | str) -> str:
    return artifact_effect_text(effect_id, value, fallback_prefix="Effekt")


class _TaskWorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)


class _TaskWorker(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.signals = _TaskWorkerSignals()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.finished.emit(result)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class _NoScrollComboBox(QComboBox):
    """ComboBox that ignores mouse-wheel events to prevent accidental changes."""
    def wheelEvent(self, event):
        event.ignore()


class _UnitSearchComboBox(_NoScrollComboBox):
    """Unit combo with in-popup text filtering."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._suspend_filter: bool = False
        self._proxy_model = QSortFilterProxyModel(self)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy_model.setFilterKeyColumn(0)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self._completer = QCompleter(self._proxy_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.activated.connect(self._on_completer_activated)
        self.setCompleter(self._completer)
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setClearButtonEnabled(False)
            line_edit.setPlaceholderText(tr("main.search_placeholder"))
            line_edit.textChanged.connect(self._on_filter_text_edited)
        self.activated.connect(self._on_item_activated)

    def set_filter_suspended(self, suspended: bool) -> None:
        self._suspend_filter = bool(suspended)

    def set_source_model(self, model: QStandardItemModel) -> None:
        self._proxy_model.setSourceModel(model)
        self.setModel(model)
        self._completer.setModel(self._proxy_model)

    def showPopup(self) -> None:
        super().showPopup()
        QTimer.singleShot(0, self._focus_search_field)

    def hidePopup(self) -> None:
        super().hidePopup()
        self._reset_search_field()

    def _on_filter_text_edited(self, text: str) -> None:
        if self._suspend_filter:
            return
        query = (text or "").strip()
        if not query:
            self._proxy_model.setFilterRegularExpression(QRegularExpression())
            self._completer.popup().hide()
            return
        escaped = QRegularExpression.escape(query)
        self._proxy_model.setFilterRegularExpression(
            QRegularExpression(f".*{escaped}.*", QRegularExpression.CaseInsensitiveOption)
        )
        self._completer.complete()

    def _focus_search_field(self) -> None:
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        line_edit.setFocus(Qt.PopupFocusReason)
        line_edit.selectAll()

    def _reset_search_field(self, *_args) -> None:
        if self._suspend_filter:
            return
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        line_edit.blockSignals(True)
        line_edit.clear()
        line_edit.blockSignals(False)

    def _on_item_activated(self, _index: int) -> None:
        self._reset_search_field()

    def _on_completer_activated(self, _text: str) -> None:
        idx = self._completer.currentIndex()
        if not idx.isValid():
            return
        src_idx = self._proxy_model.mapToSource(idx)
        if not src_idx.isValid():
            return
        self.setCurrentIndex(src_idx.row())
        self._reset_search_field()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        line_edit = self.lineEdit()
        if line_edit is not None:
            key = event.key()
            if key == Qt.Key_Backspace:
                line_edit.backspace()
                event.accept()
                return
            if key == Qt.Key_Delete:
                line_edit.del_()
                event.accept()
                return
            text = event.text()
            if text and not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
                line_edit.insert(text)
                event.accept()
                return
        super().keyPressEvent(event)


class _SetMultiCombo(_NoScrollComboBox):
    """Checkable multi-select combo for rune sets with optional size enforcement."""

    selection_changed = Signal()

    ROLE_SET_ID = Qt.UserRole
    ROLE_SET_SIZE = Qt.UserRole + 1
    EXCLUDED_SET_IDS = {25}  # Intangible is handled automatically by the optimizer.

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._block_hide_once = False
        self._enforced_size: int | None = None
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        le = self.lineEdit()
        if le is not None:
            le.setReadOnly(True)
            le.setPlaceholderText("—")
        model = QStandardItemModel(self)
        self.setModel(model)
        for sid in sorted(SET_NAMES.keys()):
            if int(sid) in self.EXCLUDED_SET_IDS:
                continue
            name = str(SET_NAMES[sid])
            ssize = int(SET_SIZES.get(int(sid), 2))
            item = QStandardItem(f"{name} ({sid})")
            item.setData(int(sid), self.ROLE_SET_ID)
            item.setData(int(ssize), self.ROLE_SET_SIZE)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked, Qt.CheckStateRole)
            model.appendRow(item)
        self.view().pressed.connect(self._on_item_pressed)
        self._apply_size_constraints()
        self._refresh_text()

    def _on_item_pressed(self, index) -> None:
        if not index.isValid():
            return
        item = self.model().item(index.row())
        if item is None or not item.isEnabled():
            return
        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
        item.setCheckState(new_state)
        self._block_hide_once = True
        self._apply_size_constraints()
        self._refresh_text()
        self.selection_changed.emit()

    def hidePopup(self) -> None:
        if self._block_hide_once:
            self._block_hide_once = False
            return
        super().hidePopup()

    def checked_ids(self) -> List[int]:
        out: List[int] = []
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            if item.checkState() == Qt.Checked:
                out.append(int(item.data(self.ROLE_SET_ID) or 0))
        return [x for x in out if x > 0]

    def checked_sizes(self) -> Set[int]:
        out: Set[int] = set()
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            if item.checkState() == Qt.Checked:
                out.add(int(item.data(self.ROLE_SET_SIZE) or 0))
        return out

    def selected_size(self) -> int | None:
        sizes = self.checked_sizes()
        if len(sizes) == 1:
            return int(next(iter(sizes)))
        return None

    def set_enforced_size(self, size: int | None) -> None:
        self._enforced_size = int(size) if size in (2, 4) else None
        self._apply_size_constraints()
        self._refresh_text()

    def clear_checked(self) -> None:
        self.set_checked_ids([])

    def set_checked_ids(self, set_ids: List[int]) -> None:
        selected = [int(x) for x in (set_ids or []) if int(x) > 0]
        selected_set = set(selected)
        size_by_id = {int(sid): int(SET_SIZES.get(int(sid), 2)) for sid in selected}
        target_size = self._enforced_size
        if target_size is None and selected:
            first_id = int(selected[0])
            target_size = int(size_by_id.get(first_id, 0) or 0) or None

        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            sid = int(item.data(self.ROLE_SET_ID) or 0)
            ssize = int(item.data(self.ROLE_SET_SIZE) or 0)
            should_check = sid in selected_set and (target_size is None or ssize == int(target_size))
            item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
        self._apply_size_constraints()
        self._refresh_text()

    def _effective_size(self) -> int | None:
        if self._enforced_size in (2, 4):
            return int(self._enforced_size)
        sizes = self.checked_sizes()
        if len(sizes) == 1:
            return int(next(iter(sizes)))
        return None

    def _apply_size_constraints(self) -> None:
        eff_size = self._effective_size()
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            ssize = int(item.data(self.ROLE_SET_SIZE) or 0)
            allowed = eff_size is None or ssize == int(eff_size)
            item.setEnabled(bool(allowed))
            if not allowed and item.checkState() == Qt.Checked:
                item.setCheckState(Qt.Unchecked)

    def _refresh_text(self) -> None:
        ids = self.checked_ids()
        if not ids:
            text = "—"
        else:
            names = [str(SET_NAMES.get(int(sid), sid)) for sid in ids]
            text = ", ".join(names)
        le = self.lineEdit()
        if le is not None:
            le.setText(text)


class _MainstatMultiCombo(_NoScrollComboBox):
    """Checkable multi-select combo for allowed mainstats."""

    def __init__(self, options: List[str], parent: QWidget | None = None):
        super().__init__(parent)
        self._block_hide_once = False
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        le = self.lineEdit()
        if le is not None:
            le.setReadOnly(True)
            le.setPlaceholderText("Any")
        model = QStandardItemModel(self)
        self.setModel(model)
        for key in options:
            item = QStandardItem(str(key))
            item.setData(str(key), Qt.UserRole)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked, Qt.CheckStateRole)
            model.appendRow(item)
        self.view().pressed.connect(self._on_item_pressed)
        self._refresh_text()

    def _on_item_pressed(self, index) -> None:
        if not index.isValid():
            return
        item = self.model().item(index.row())
        if item is None:
            return
        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
        item.setCheckState(new_state)
        self._block_hide_once = True
        self._refresh_text()

    def hidePopup(self) -> None:
        if self._block_hide_once:
            self._block_hide_once = False
            return
        super().hidePopup()

    def checked_values(self) -> List[str]:
        out: List[str] = []
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            if item.checkState() == Qt.Checked:
                out.append(str(item.data(Qt.UserRole) or item.text() or ""))
        return [x for x in out if x]

    def set_checked_values(self, values: List[str]) -> None:
        selected = {str(v) for v in (values or []) if str(v)}
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            key = str(item.data(Qt.UserRole) or item.text() or "")
            item.setCheckState(Qt.Checked if key in selected else Qt.Unchecked)
        self._refresh_text()

    def _refresh_text(self) -> None:
        vals = self.checked_values()
        text = "Any" if not vals else ", ".join(vals)
        le = self.lineEdit()
        if le is not None:
            le.setText(text)


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
        account: AccountData | None,
        unit_icon_fn: Callable[[int], QIcon],
        team_size: int = 3,
        show_order_sections: bool = True,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        screen = QApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            w = min(max(1680, int(avail.width() * 0.92)), int(avail.width()))
            h = min(max(860, int(avail.height() * 0.90)), int(avail.height()))
            self.resize(w, h)
            self.setMinimumSize(min(1400, w), min(760, h))
        else:
            self.resize(1840, 900)
            self.setMinimumSize(1400, 760)

        self.preset_store = preset_store
        self.mode = mode
        self._account = account
        self.team_size = max(1, int(team_size))
        self._unit_icon_fn = unit_icon_fn
        self._unit_rows = list(unit_rows)
        self._unit_rows_by_uid: Dict[int, Tuple[int, str]] = {int(uid): (int(uid), str(lbl)) for uid, lbl in self._unit_rows}
        self._artifact_substat_options_by_type = self._collect_artifact_substat_options_by_type(self._account)

        layout = QVBoxLayout(self)

        self._opt_order_list: QListWidget | None = None
        self._team_order_lists: List[QListWidget] = []
        self._team_spd_tick_combo_by_unit: Dict[int, QComboBox] = {}

        if show_order_sections:
            # Global optimization order (independent from team turn order)
            optimize_box = QGroupBox(tr("group.opt_order"))
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
            order_box = QGroupBox(tr("group.turn_order"))
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
                sortable: List[Tuple[int, int, int, str, int]] = []
                for pos, (uid, label) in enumerate(team_units):
                    builds = self.preset_store.get_unit_builds(self.mode, uid)
                    b0 = builds[0] if builds else Build.default_any()
                    turn = int(getattr(b0, "turn_order", 0) or 0)
                    key = turn if turn > 0 else 999
                    spd_tick = int(getattr(b0, "spd_tick", 0) or 0)
                    sortable.append((key, pos, uid, label, spd_tick))
                sortable.sort(key=lambda x: (x[0], x[1]))
                for _, _, uid, label, spd_tick in sortable:
                    it = QListWidgetItem()
                    it.setData(Qt.UserRole, int(uid))
                    lw.addItem(it)

                    row_widget = QWidget()
                    row_layout = QHBoxLayout(row_widget)
                    row_layout.setContentsMargins(2, 2, 2, 2)
                    row_layout.setSpacing(6)

                    icon_lbl = QLabel()
                    icon = self._unit_icon_fn(uid)
                    if not icon.isNull():
                        icon_lbl.setPixmap(icon.pixmap(28, 28))
                    row_layout.addWidget(icon_lbl)

                    txt_lbl = QLabel(label)
                    row_layout.addWidget(txt_lbl, 1)

                    tick_lbl = QLabel(tr("label.spd_tick_short"))
                    row_layout.addWidget(tick_lbl)

                    tick_cmb = _NoScrollComboBox()
                    tick_cmb.setMinimumWidth(72)
                    tick_cmb.addItem("—", 0)
                    for tick in allowed_spd_ticks():
                        req_spd = int(min_spd_for_tick(tick))
                        tick_cmb.addItem(f"{tick} (>= {req_spd})", int(tick))
                    idx = tick_cmb.findData(int(spd_tick))
                    tick_cmb.setCurrentIndex(idx if idx >= 0 else 0)
                    tick_cmb.setToolTip(tr("tooltip.spd_tick"))
                    row_layout.addWidget(tick_cmb)

                    self._team_spd_tick_combo_by_unit[int(uid)] = tick_cmb
                    it.setSizeHint(row_widget.sizeHint())
                    lw.setItemWidget(it, row_widget)
                self._team_order_lists.append(lw)
                order_grid.addWidget(lw, 1, t)
            layout.addWidget(order_box)

        # Build details table (without unit_id column)
        self.table = QTableWidget(0, 18)
        self.table.setHorizontalHeaderLabels([
            tr("header.monster"), tr("header.set1"), tr("header.set2"), tr("header.set3"),
            tr("header.slot2_main"), tr("header.slot4_main"), tr("header.slot6_main"),
            tr("header.attr_main"), tr("header.attr_sub1"), tr("header.attr_sub2"),
            tr("header.type_main"), tr("header.type_sub1"), tr("header.type_sub2"),
            tr("header.min_spd"), tr("header.min_cr"), tr("header.min_cd"), tr("header.min_res"), tr("header.min_acc")
        ])
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        # Keep monster column flexible, but reserve readable width for set/mainstat columns.
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3, 4, 5, 6, 7, 10):
            header.setSectionResizeMode(col, QHeaderView.Interactive)

        # Compact columns (artifact substats + stat thresholds).
        for col in (8, 9, 11, 12, 13, 14, 15, 16, 17):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)

        # Default widths to avoid clipped labels/values in Builder table.
        for col in (1, 2, 3):
            self.table.setColumnWidth(col, 110)
        for col in (4, 5, 6):
            self.table.setColumnWidth(col, 120)
        self.table.setColumnWidth(7, 95)
        self.table.setColumnWidth(10, 95)
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

        self._set1_combo: Dict[int, _SetMultiCombo] = {}
        self._set2_combo: Dict[int, _SetMultiCombo] = {}
        self._set3_combo: Dict[int, _SetMultiCombo] = {}
        self._ms2_combo: Dict[int, _MainstatMultiCombo] = {}
        self._ms4_combo: Dict[int, _MainstatMultiCombo] = {}
        self._ms6_combo: Dict[int, _MainstatMultiCombo] = {}
        self._art_attr_focus_combo: Dict[int, _MainstatMultiCombo] = {}
        self._art_type_focus_combo: Dict[int, _MainstatMultiCombo] = {}
        self._art_attr_sub1_combo: Dict[int, QComboBox] = {}
        self._art_attr_sub2_combo: Dict[int, QComboBox] = {}
        self._art_type_sub1_combo: Dict[int, QComboBox] = {}
        self._art_type_sub2_combo: Dict[int, QComboBox] = {}
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

            cmb_set1 = _SetMultiCombo()
            cmb_set2 = _SetMultiCombo()
            cmb_set3 = _SetMultiCombo()
            cmb_set1.setToolTip(tr("tooltip.set_multi"))
            cmb_set2.setToolTip(tr("tooltip.set_multi"))
            cmb_set3.setToolTip(tr("tooltip.set3"))

            builds = self.preset_store.get_unit_builds(self.mode, unit_id)
            b0 = builds[0] if builds else Build.default_any()

            slot1_ids, slot2_ids, slot3_ids = self._parse_set_options_to_slot_ids(b0.set_options or [])
            cmb_set1.set_checked_ids(slot1_ids)
            cmb_set2.set_checked_ids(slot2_ids)
            cmb_set3.set_checked_ids(slot3_ids)
            cmb_set1.selection_changed.connect(lambda _uid=int(unit_id): self._sync_set_combo_constraints_for_unit(_uid))
            cmb_set2.selection_changed.connect(lambda _uid=int(unit_id): self._sync_set_combo_constraints_for_unit(_uid))
            cmb_set3.selection_changed.connect(lambda _uid=int(unit_id): self._sync_set_combo_constraints_for_unit(_uid))

            def _mk_ms_combo(defaults: List[str]) -> _MainstatMultiCombo:
                cmb = _MainstatMultiCombo(MAINSTAT_KEYS)
                if defaults:
                    cmb.set_checked_values([str(defaults[0])])
                cmb.setToolTip(tr("tooltip.mainstat_multi"))
                return cmb

            cmb2 = _mk_ms_combo(SLOT2_DEFAULT)
            cmb4 = _mk_ms_combo(SLOT4_DEFAULT)
            cmb6 = _mk_ms_combo(SLOT6_DEFAULT)
            art_attr_focus = _MainstatMultiCombo(ARTIFACT_MAIN_KEYS)
            art_type_focus = _MainstatMultiCombo(ARTIFACT_MAIN_KEYS)
            art_attr_focus.setToolTip(tr("tooltip.art_attr_focus"))
            art_type_focus.setToolTip(tr("tooltip.art_type_focus"))

            def _mk_art_sub_combo(artifact_type: int) -> QComboBox:
                cmb = _NoScrollComboBox()
                cmb.addItem("Any", 0)
                eids = list(self._artifact_substat_options_by_type.get(int(artifact_type), []))
                eids.sort(key=lambda x: (artifact_effect_is_legacy(int(x)), int(x)))
                for eid in eids:
                    cmb.addItem(_artifact_effect_label(int(eid)), int(eid))
                cmb.setToolTip(
                    tr("tooltip.art_sub", kind=_artifact_kind_label(int(artifact_type)))
                )
                return cmb

            art_attr_sub1 = _mk_art_sub_combo(1)
            art_attr_sub2 = _mk_art_sub_combo(1)
            art_type_sub1 = _mk_art_sub_combo(2)
            art_type_sub2 = _mk_art_sub_combo(2)

            def _set_art_sub_combo_value(cmb: QComboBox, eid: int) -> None:
                effect_id = int(eid or 0)
                if effect_id <= 0:
                    return
                idx_local = cmb.findData(effect_id)
                if idx_local < 0:
                    cmb.addItem(_artifact_effect_label(effect_id), effect_id)
                    idx_local = cmb.findData(effect_id)
                if idx_local >= 0:
                    cmb.setCurrentIndex(idx_local)

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
                    cmb2.set_checked_values([str(x) for x in (b0.mainstats[2] or [])])
                if 4 in b0.mainstats and b0.mainstats[4]:
                    cmb4.set_checked_values([str(x) for x in (b0.mainstats[4] or [])])
                if 6 in b0.mainstats and b0.mainstats[6]:
                    cmb6.set_checked_values([str(x) for x in (b0.mainstats[6] or [])])

            artifact_focus = dict(getattr(b0, "artifact_focus", {}) or {})
            attr_focus_values = [str(x).upper() for x in (artifact_focus.get("attribute") or []) if str(x)]
            type_focus_values = [str(x).upper() for x in (artifact_focus.get("type") or []) if str(x)]
            if attr_focus_values:
                art_attr_focus.set_checked_values(attr_focus_values)
            if type_focus_values:
                art_type_focus.set_checked_values(type_focus_values)

            artifact_substats = dict(getattr(b0, "artifact_substats", {}) or {})
            attr_subs = [int(x) for x in (artifact_substats.get("attribute") or []) if int(x) > 0][:2]
            type_subs = [int(x) for x in (artifact_substats.get("type") or []) if int(x) > 0][:2]
            if attr_subs:
                _set_art_sub_combo_value(art_attr_sub1, attr_subs[0])
            if len(attr_subs) > 1:
                _set_art_sub_combo_value(art_attr_sub2, attr_subs[1])
            if type_subs:
                _set_art_sub_combo_value(art_type_sub1, type_subs[0])
            if len(type_subs) > 1:
                _set_art_sub_combo_value(art_type_sub2, type_subs[1])

            self.table.setCellWidget(r, 1, cmb_set1)
            self.table.setCellWidget(r, 2, cmb_set2)
            self.table.setCellWidget(r, 3, cmb_set3)
            self.table.setCellWidget(r, 4, cmb2)
            self.table.setCellWidget(r, 5, cmb4)
            self.table.setCellWidget(r, 6, cmb6)
            self.table.setCellWidget(r, 7, art_attr_focus)
            self.table.setCellWidget(r, 8, art_attr_sub1)
            self.table.setCellWidget(r, 9, art_attr_sub2)
            self.table.setCellWidget(r, 10, art_type_focus)
            self.table.setCellWidget(r, 11, art_type_sub1)
            self.table.setCellWidget(r, 12, art_type_sub2)
            self.table.setCellWidget(r, 13, min_spd)
            self.table.setCellWidget(r, 14, min_cr)
            self.table.setCellWidget(r, 15, min_cd)
            self.table.setCellWidget(r, 16, min_res)
            self.table.setCellWidget(r, 17, min_acc)

            self._set1_combo[unit_id] = cmb_set1
            self._set2_combo[unit_id] = cmb_set2
            self._set3_combo[unit_id] = cmb_set3
            self._sync_set_combo_constraints_for_unit(int(unit_id))
            self._ms2_combo[unit_id] = cmb2
            self._ms4_combo[unit_id] = cmb4
            self._ms6_combo[unit_id] = cmb6
            self._art_attr_focus_combo[unit_id] = art_attr_focus
            self._art_type_focus_combo[unit_id] = art_type_focus
            self._art_attr_sub1_combo[unit_id] = art_attr_sub1
            self._art_attr_sub2_combo[unit_id] = art_attr_sub2
            self._art_type_sub1_combo[unit_id] = art_type_sub1
            self._art_type_sub2_combo[unit_id] = art_type_sub2
            self._min_spd_spin[unit_id] = min_spd
            self._min_cr_spin[unit_id] = min_cr
            self._min_cd_spin[unit_id] = min_cd
            self._min_res_spin[unit_id] = min_res
            self._min_acc_spin[unit_id] = min_acc

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

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

        # Set 1/2: internal size lock based on current selection.
        c1.set_enforced_size(None)
        c2.set_enforced_size(None)

        # Set 3 is only available for 2-set + 2-set setups.
        allow_set3 = self._is_set3_allowed_for_unit(int(unit_id))
        if allow_set3:
            c3.setEnabled(True)
            c3.set_enforced_size(2)
        else:
            c3.clear_checked()
            c3.set_enforced_size(None)
            c3.setEnabled(False)

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

    def _team_spd_tick_by_unit(self) -> Dict[int, int]:
        if not self._team_spd_tick_combo_by_unit:
            return {}
        out: Dict[int, int] = {}
        for uid, cmb in self._team_spd_tick_combo_by_unit.items():
            if cmb is None:
                continue
            out[int(uid)] = int(cmb.currentData() or 0)
        return out

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
                    # Keep observed in-game association for this artifact type.
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
        optimize_order_by_uid = self._optimize_order_by_unit()
        team_turn_order_by_uid = self._team_turn_order_by_unit()
        team_spd_tick_by_uid = self._team_spd_tick_by_unit()

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

            # Normalize (dedupe within each option) and keep only feasible options (<= 6 pieces).
            normalized_options: List[List[int]] = []
            seen_opts: Set[Tuple[int, ...]] = set()
            for opt in option_ids:
                cleaned: List[int] = []
                seen_local: Set[int] = set()
                for sid in opt:
                    sid_i = int(sid)
                    if sid_i <= 0 or sid_i not in SET_NAMES or sid_i in seen_local:
                        continue
                    seen_local.add(sid_i)
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
                raise ValueError(
                    tr("val.set_invalid", unit=unit_label)
                )

            ms2_values = [str(x) for x in self._ms2_combo[unit_id].checked_values()]
            ms4_values = [str(x) for x in self._ms4_combo[unit_id].checked_values()]
            ms6_values = [str(x) for x in self._ms6_combo[unit_id].checked_values()]
            art_attr_focus_values = [str(x).upper() for x in self._art_attr_focus_combo[unit_id].checked_values()]
            art_type_focus_values = [str(x).upper() for x in self._art_type_focus_combo[unit_id].checked_values()]
            art_attr_substats = self._artifact_substat_ids_for_unit(unit_id, "attribute")
            art_type_substats = self._artifact_substat_ids_for_unit(unit_id, "type")
            optimize_order = int(optimize_order_by_uid.get(unit_id, 0) or 0)
            turn_order = int(team_turn_order_by_uid.get(unit_id, 0) or 0)
            spd_tick = int(team_spd_tick_by_uid.get(unit_id, 0) or 0)
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
            if art_attr_focus_values:
                artifact_focus["attribute"] = [v for v in art_attr_focus_values if v in ("HP", "ATK", "DEF")]
            if art_type_focus_values:
                artifact_focus["type"] = [v for v in art_type_focus_values if v in ("HP", "ATK", "DEF")]

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

        title = tr("btn.edit_team") if team else tr("btn.new_team")
        self.setWindowTitle(title)
        self.resize(600, 420)

        layout = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("label.team_name")))
        self.name_edit = QLineEdit(team.name if team else "")
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        control_row = QHBoxLayout()
        self.unit_combo = QComboBox()
        self.unit_combo.setIconSize(QSize(32, 32))
        control_row.addWidget(self.unit_combo, 1)
        self.btn_add_unit = QPushButton(tr("btn.add"))
        self.btn_add_unit.clicked.connect(self._add_unit_from_combo)
        control_row.addWidget(self.btn_add_unit)
        self.btn_remove_unit = QPushButton(tr("btn.remove"))
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
            QMessageBox.warning(self, tr("dlg.team_needs_units_title"), tr("dlg.team_needs_units"))
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
        artifact_lookup: Dict[int, Artifact],
        unit_label_fn: Callable[[int], str],
        unit_icon_fn: Callable[[int], QIcon],
        unit_spd_fn: Callable[[int, List[int], Dict[int, Dict[int, int]]], int],
        unit_stats_fn: Callable[[int, List[int], Dict[int, Dict[int, int]]], Dict[str, int]],
        set_icon_fn: Callable[[int], QIcon],
        unit_base_stats_fn: Callable[[int], Dict[str, int]],
        unit_leader_bonus_fn: Callable[[int, List[int]], Dict[str, int]],
        unit_totem_bonus_fn: Callable[[int], Dict[str, int]],
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
        self._unit_totem_bonus_fn = unit_totem_bonus_fn
        self._unit_team_index = unit_team_index or {}
        self._unit_display_order = unit_display_order or {}
        self._rune_lookup = rune_lookup
        self._artifact_lookup = artifact_lookup
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
        self.btn_save = QPushButton(tr("btn.save"))
        self.btn_save.clicked.connect(self._on_save)
        btn_bar.addWidget(self.btn_save)
        btn_bar.addStretch()
        btn_close = QPushButton(tr("btn.close"))
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
                state = "OK" if result.ok else tr("label.error")
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

    # -- detail rendering (tabs) ----------------------------

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
            QVBoxLayout(w).addWidget(QLabel(tr("dlg.select_left")))
            self.detail_layout.addWidget(w)
            return

        result = self._results_by_uid.get(unit_id)
        if not result:
            w = QWidget()
            QVBoxLayout(w).addWidget(QLabel(tr("dlg.no_result")))
            self.detail_layout.addWidget(w)
            return

        team_unit_ids = self._team_unit_ids_for(unit_id)
        runes_by_unit = {int(r.unit_id): (r.runes_by_slot or {}) for r in self._results}
        total_stats = self._unit_stats_fn(int(unit_id), team_unit_ids, runes_by_unit)
        base_stats = self._unit_base_stats_fn(int(unit_id))
        leader_bonus = self._unit_leader_bonus_fn(int(unit_id), team_unit_ids)
        totem_bonus = self._unit_totem_bonus_fn(int(unit_id))

        self.detail_layout.addWidget(
            self._build_stats_tab(unit_id, result, base_stats, total_stats, leader_bonus, totem_bonus)
        )

        if result.ok and result.runes_by_slot:
            self.detail_layout.addWidget(
                self._build_runes_tab(result)
            )
        if result.ok and result.artifacts_by_type:
            self.detail_layout.addWidget(
                self._build_artifacts_tab(result)
            )

    # -- Stats tab ------------------------------------------

    def _build_stats_tab(self, unit_id: int, result: GreedyUnitResult,
                         base_stats: Dict[str, int],
                         total_stats: Dict[str, int],
                         leader_bonus: Dict[str, int],
                         totem_bonus: Dict[str, int]) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)

        label = self._unit_label_fn(unit_id)
        title = QLabel(f"<b>{label}</b>" if result.ok else f"<b>{label} ({tr('label.error')})</b>")
        title.setTextFormat(Qt.RichText)
        v.addWidget(title)

        rune_ids = list((result.runes_by_slot or {}).values())
        eff_values = [rune_efficiency(r) for rid in rune_ids if (r := self._rune_lookup.get(int(rid)))]
        if eff_values:
            avg_eff = sum(eff_values) / len(eff_values)
            eff_lbl = QLabel(tr("result.avg_rune_eff", eff=f"{avg_eff:.2f}"))
        else:
            eff_lbl = QLabel(tr("result.avg_rune_eff_none"))
        eff_lbl.setTextFormat(Qt.RichText)
        eff_lbl.setStyleSheet("color: #bbb;")
        v.addWidget(eff_lbl)

        if not result.ok:
            msg = QLabel(result.message)
            msg.setWordWrap(True)
            v.addWidget(msg)
            v.addStretch()
            return w

        stat_keys = ["HP", "ATK", "DEF", "SPD", "CR", "CD", "RES", "ACC"]
        has_leader = any(leader_bonus.get(k, 0) != 0 for k in stat_keys)
        has_totem = any(totem_bonus.get(k, 0) != 0 for k in stat_keys)
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(stat_keys))

        if self._stats_detailed:
            headers = [tr("header.stat"), tr("header.base"), tr("header.runes")]
            if has_totem:
                headers.append(tr("header.totem"))
            if has_leader:
                headers.append(tr("header.leader"))
            headers.append(tr("header.total"))
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)

            total_col = len(headers) - 1
            leader_col = total_col - 1 if has_leader else -1
            totem_col = (3 if has_totem else -1)
            runes_col = 2

            for i, key in enumerate(stat_keys):
                base = base_stats.get(key, 0)
                total = total_stats.get(key, 0)
                lead = leader_bonus.get(key, 0)
                totem = totem_bonus.get(key, 0)
                rune_bonus = total - base - lead - totem
                table.setItem(i, 0, QTableWidgetItem(_stat_label_tr(key)))
                it_b = QTableWidgetItem(str(base))
                it_b.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 1, it_b)
                rune_str = f"+{rune_bonus}" if rune_bonus >= 0 else str(rune_bonus)
                it_r = QTableWidgetItem(rune_str)
                it_r.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, runes_col, it_r)
                if has_totem and totem_col >= 0:
                    totem_str = f"+{totem}" if totem > 0 else str(totem) if totem else ""
                    it_tt = QTableWidgetItem(totem_str)
                    it_tt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, totem_col, it_tt)
                if has_leader and leader_col >= 0:
                    lead_str = f"+{lead}" if lead > 0 else str(lead) if lead else ""
                    it_l = QTableWidgetItem(lead_str)
                    it_l.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, leader_col, it_l)
                it_t = QTableWidgetItem(str(total))
                it_t.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, total_col, it_t)
        else:
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels([tr("header.stat"), tr("header.value")])
            for i, key in enumerate(stat_keys):
                table.setItem(i, 0, QTableWidgetItem(_stat_label_tr(key)))
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

    # -- Runes tab ------------------------------------------

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

    def _build_artifacts_tab(self, result: GreedyUnitResult) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        v.addWidget(QLabel(f"<b>{tr('ui.artifacts_title')}</b>"))

        for art_type in (1, 2):
            aid = int((result.artifacts_by_type or {}).get(art_type, 0) or 0)
            if aid <= 0:
                continue
            art = self._artifact_lookup.get(aid)
            if art is None:
                v.addWidget(QLabel(f"{_artifact_kind_label(art_type)}: {aid}"))
                continue

            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 3px; padding: 4px; }")
            fv = QVBoxLayout(frame)
            fv.setContentsMargins(6, 4, 6, 4)
            fv.setSpacing(2)

            kind = _artifact_kind_label(art_type)
            fv.addWidget(
                QLabel(
                    f"<b>{kind}</b> | +{int(art.level or 0)}"
                )
            )

            owner_uid = int(art.occupied_id or 0)
            if owner_uid > 0:
                owner = self._unit_label_fn(owner_uid)
                owner_lbl = QLabel(tr("ui.current_on", owner=owner))
                owner_lbl.setStyleSheet("color: #888; font-size: 7pt;")
                fv.addWidget(owner_lbl)

            sec_lines: List[str] = []
            for sec in (art.sec_effects or []):
                if not sec:
                    continue
                try:
                    eid = int(sec[0] or 0)
                    val = sec[1] if len(sec) > 1 else 0
                except Exception:
                    continue
                sec_lines.append(f"• {_artifact_effect_text(eid, val)}")
            if sec_lines:
                for line in sec_lines:
                    lbl = QLabel(line)
                    lbl.setStyleSheet("font-size: 8pt;")
                    fv.addWidget(lbl)

            v.addWidget(frame)

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
        header.addWidget(QLabel(f"<b>{tr('ui.slot')} {slot}</b> | {set_name} | +{rune.upgrade_curr}"))
        header.addStretch()
        main_v.addLayout(header)

        # Show current rune owner: prefer mode-specific assignment, fallback to PvE
        owner_uid = self._mode_rune_owner.get(rune.rune_id)
        if not owner_uid and rune.occupied_type == 1 and rune.occupied_id:
            owner_uid = int(rune.occupied_id)
        if owner_uid:
            owner = self._unit_label_fn(owner_uid)
            src = QLabel(tr("ui.current_on", owner=owner))
            src.setStyleSheet("color: #888; font-size: 7pt;")
            main_v.addWidget(src)

        main_v.addWidget(QLabel(f"{tr('ui.main')}: {self._stat_label(rune.pri_eff)}"))
        pfx = self._prefix_text(rune.prefix_eff)
        if pfx != "—":
            main_v.addWidget(QLabel(f"{tr('ui.prefix')}: {pfx}"))

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

    # -- helpers --------------------------------------------

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
        self.btn_save.setText(tr("btn.saved"))

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
        _apply("combo_quality_profile_team", "combo_workers_team")

    def __init__(self):
        super().__init__()
        self.setWindowTitle(tr("main.title"))
        self.resize(1600, 980)
        self.setMinimumSize(1360, 820)

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

        top = QHBoxLayout()
        layout.addLayout(top)

        self.btn_import = QPushButton(tr("main.import_btn"))
        self.btn_import.clicked.connect(self.on_import)
        top.addWidget(self.btn_import)

        self.lbl_status = QLabel(tr("main.no_import"))
        self.lbl_status.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        top.addWidget(self.lbl_status, 1)

        import app.i18n as i18n
        self.lang_combo = QComboBox()
        self.lang_combo.setFixedWidth(100)
        for code, name in i18n.available_languages().items():
            self.lang_combo.addItem(name, code)
        idx = self.lang_combo.findData(i18n.get_language())
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        top.addWidget(self.lang_combo)

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
        dlg.setWindowTitle(tr("help.title"))
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
        content.setText(tr("help.content"))
        scroll.setWidget(content)

        btn_close = QPushButton(tr("btn.close"))
        btn_close.clicked.connect(dlg.accept)
        layout.addWidget(btn_close, 0, Qt.AlignRight)

        dlg.exec()

    # ============================================================
    # Import
    # ============================================================
    def on_import(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("main.file_dialog_title"),
            str(Path.home()),
            tr("main.file_dialog_filter"),
        )
        if not path:
            return
        try:
            raw_json = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
            self.account_persistence.save(raw_json, source_name=Path(path).name)
            account = load_account_from_data(raw_json)
        except Exception as e:
            QMessageBox.critical(self, tr("main.import_failed"), str(e))
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

        self.lbl_status.setText(tr("main.import_label", source=source_label))
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

        self.lbl_siege_validate.setText(tr("status.siege_ready"))
        self.lbl_wgb_validate.setText(tr("status.wgb_ready"))

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
            QMessageBox.warning(self, tr("main.snapshot_title"), tr("main.snapshot_failed", exc=exc))
            return
        meta = self.account_persistence.load_meta()
        source_name = str(meta.get("source_name", "")).strip() or tr("main.source_unknown")
        imported_at_raw = str(meta.get("imported_at", "")).strip()
        imported_at = None
        if imported_at_raw:
            try:
                imported_at = datetime.fromisoformat(imported_at_raw)
            except ValueError:
                imported_at = None
        if imported_at is None:
            try:
                imported_at = datetime.fromtimestamp(self.account_persistence.active_snapshot_path().stat().st_mtime)
            except OSError:
                imported_at = None

        if imported_at is not None:
            source_label = f"{source_name} ({imported_at.strftime('%d.%m.%Y %H:%M')})"
        else:
            source_label = source_name
        self._apply_saved_account(account, source_label)

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
        if isinstance(cmb, _UnitSearchComboBox):
            cmb.set_filter_suspended(True)
            cmb.set_source_model(model)
        else:
            cmb.setModel(model)
        cmb.setModelColumn(0)
        cmb.setIconSize(QSize(40, 40))
        idx = cmb.findData(prev_uid, role=Qt.UserRole)
        cmb.setCurrentIndex(idx if idx >= 0 else 0)
        if isinstance(cmb, _UnitSearchComboBox):
            cmb.set_filter_suspended(False)
            cmb._reset_search_field()
        cmb.blockSignals(False)

    def _build_unit_combo_model(self) -> QStandardItemModel:
        model = QStandardItemModel()
        index_by_uid: Dict[int, int] = {}

        placeholder = QStandardItem("—")
        placeholder.setData(0, Qt.UserRole)
        model.appendRow(placeholder)
        index_by_uid[0] = 0

        if self.account:
            unit_rows: List[Tuple[str, str, int, Any]] = []
            for uid, u in self.account.units_by_id.items():
                name = self.monster_db.name_for(u.unit_master_id)
                elem = self.monster_db.element_for(u.unit_master_id)
                unit_rows.append((name.lower(), elem.lower(), int(uid), u))

            for _, _, uid, u in sorted(unit_rows, key=lambda x: (x[0], x[1], x[2])):
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
        self.lbl_saved_siege = QLabel(tr("label.saved_opt"))
        top.addWidget(self.lbl_saved_siege)
        self.saved_siege_combo = QComboBox()
        self.saved_siege_combo.currentIndexChanged.connect(lambda: self._on_saved_opt_changed("siege"))
        top.addWidget(self.saved_siege_combo, 1)
        self.btn_delete_saved_siege = QPushButton(tr("btn.delete"))
        self.btn_delete_saved_siege.clicked.connect(lambda: self._on_delete_saved_opt("siege"))
        top.addWidget(self.btn_delete_saved_siege)
        v.addLayout(top)
        self.saved_siege_cards = SiegeDefCardsWidget()
        v.addWidget(self.saved_siege_cards, 1)
        self._refresh_saved_opt_combo("siege")

    def _init_saved_wgb_tab(self):
        v = QVBoxLayout(self.tab_saved_wgb)
        top = QHBoxLayout()
        self.lbl_saved_wgb = QLabel(tr("label.saved_opt"))
        top.addWidget(self.lbl_saved_wgb)
        self.saved_wgb_combo = QComboBox()
        self.saved_wgb_combo.currentIndexChanged.connect(lambda: self._on_saved_opt_changed("wgb"))
        top.addWidget(self.saved_wgb_combo, 1)
        self.btn_delete_saved_wgb = QPushButton(tr("btn.delete"))
        self.btn_delete_saved_wgb.clicked.connect(lambda: self._on_delete_saved_opt("wgb"))
        top.addWidget(self.btn_delete_saved_wgb)
        v.addLayout(top)
        self.saved_wgb_cards = SiegeDefCardsWidget()
        v.addWidget(self.saved_wgb_cards, 1)
        self._refresh_saved_opt_combo("wgb")

    def _init_saved_rta_tab(self):
        v = QVBoxLayout(self.tab_saved_rta)
        top = QHBoxLayout()
        self.lbl_saved_rta = QLabel(tr("label.saved_opt"))
        top.addWidget(self.lbl_saved_rta)
        self.saved_rta_combo = QComboBox()
        self.saved_rta_combo.currentIndexChanged.connect(lambda: self._on_saved_opt_changed("rta"))
        top.addWidget(self.saved_rta_combo, 1)
        self.btn_delete_saved_rta = QPushButton(tr("btn.delete"))
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
            display_name = display_name.replace(" Opt ", tr("saved.opt_replace"))
            display_name = display_name.replace(" Optimizer ", tr("saved.opt_replace"))
            display_name = display_name.replace("SIEGE Opt", tr("saved.siege_opt"))
            display_name = display_name.replace("WGB Opt", tr("saved.wgb_opt"))
            display_name = display_name.replace("RTA Opt", tr("saved.rta_opt"))
            display_name = display_name.replace("SIEGE Optimizer", tr("saved.siege_opt"))
            display_name = display_name.replace("WGB Optimizer", tr("saved.wgb_opt"))
            display_name = display_name.replace("RTA Optimizer", tr("saved.rta_opt"))
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
            self, tr("btn.delete"), tr("dlg.delete_confirm", name=name),
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

        self.box_siege_select = QGroupBox(tr("group.siege_select"))
        v.addWidget(self.box_siege_select, 1)
        box_layout = QVBoxLayout(self.box_siege_select)
        siege_scroll = QScrollArea()
        siege_scroll.setWidgetResizable(True)
        box_layout.addWidget(siege_scroll)
        siege_inner = QWidget()
        grid = QGridLayout(siege_inner)
        siege_scroll.setWidget(siege_inner)

        self._all_unit_combos: List[QComboBox] = []
        self.lbl_siege_defense: List[QLabel] = []

        self.siege_team_combos: List[List[QComboBox]] = []
        for t in range(10):
            lbl = QLabel(tr("label.defense", n=t+1))
            self.lbl_siege_defense.append(lbl)
            grid.addWidget(lbl, t, 0)
            row: List[QComboBox] = []
            for s in range(3):
                cmb = _UnitSearchComboBox()
                cmb.setMinimumWidth(300)
                self._all_unit_combos.append(cmb)
                grid.addWidget(cmb, t, 1 + s)
                row.append(cmb)
            self.siege_team_combos.append(row)

        btn_row = QHBoxLayout()
        v.addLayout(btn_row)

        self.btn_take_current_siege = QPushButton(tr("btn.take_siege"))
        self.btn_take_current_siege.setEnabled(False)
        self.btn_take_current_siege.clicked.connect(self.on_take_current_siege)
        btn_row.addWidget(self.btn_take_current_siege)

        self.btn_validate_siege = QPushButton(tr("btn.validate_pools"))
        self.btn_validate_siege.setEnabled(False)
        self.btn_validate_siege.clicked.connect(self.on_validate_siege)
        btn_row.addWidget(self.btn_validate_siege)

        self.btn_edit_presets_siege = QPushButton(tr("btn.builds"))
        self.btn_edit_presets_siege.setEnabled(False)
        self.btn_edit_presets_siege.clicked.connect(self.on_edit_presets_siege)
        btn_row.addWidget(self.btn_edit_presets_siege)

        self.btn_optimize_siege = QPushButton(tr("btn.optimize"))
        self.btn_optimize_siege.setEnabled(False)
        self.btn_optimize_siege.clicked.connect(self.on_optimize_siege)
        btn_row.addWidget(self.btn_optimize_siege)

        self.lbl_siege_passes = QLabel(tr("label.passes"))
        btn_row.addWidget(self.lbl_siege_passes)
        self.spin_multi_pass_siege = QSpinBox()
        self.spin_multi_pass_siege.setRange(1, 10)
        self.spin_multi_pass_siege.setValue(3)
        self.spin_multi_pass_siege.setToolTip(tr("tooltip.passes"))
        self.spin_multi_pass_siege.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        btn_row.addWidget(self.spin_multi_pass_siege)
        self.lbl_siege_workers = QLabel(tr("label.workers"))
        btn_row.addWidget(self.lbl_siege_workers)
        self.combo_workers_siege = QComboBox()
        self._populate_worker_combo(self.combo_workers_siege)
        btn_row.addWidget(self.combo_workers_siege)
        self.lbl_siege_profile = QLabel("Profil")
        btn_row.addWidget(self.lbl_siege_profile)
        self.combo_quality_profile_siege = QComboBox()
        self.combo_quality_profile_siege.addItem("Fast", "fast")
        self.combo_quality_profile_siege.addItem("Balanced", "balanced")
        self.combo_quality_profile_siege.addItem("Max Qualität", "max_quality")
        if self._gpu_search_available():
            self.combo_quality_profile_siege.addItem("GPU Fast", "gpu_search_fast")
            self.combo_quality_profile_siege.addItem("GPU Balanced", "gpu_search_balanced")
            self.combo_quality_profile_siege.addItem("GPU Max", "gpu_search_max")
        self.combo_quality_profile_siege.setCurrentIndex(1)
        self.combo_quality_profile_siege.currentIndexChanged.connect(self._sync_worker_controls)
        btn_row.addWidget(self.combo_quality_profile_siege)
        self._sync_worker_controls()

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.lbl_siege_validate = QLabel("—")
        v.addWidget(self.lbl_siege_validate)

    def _init_wgb_builder_ui(self):
        v = QVBoxLayout(self.tab_wgb_builder)

        # -- team selection grid (5 defs x 3 monsters) --------
        self.box_wgb_select = QGroupBox(tr("group.wgb_select"))
        v.addWidget(self.box_wgb_select)
        grid = QGridLayout(self.box_wgb_select)

        self.wgb_team_combos: List[List[QComboBox]] = []
        self.lbl_wgb_defense: List[QLabel] = []
        for t in range(5):
            lbl = QLabel(tr("label.defense", n=t+1))
            self.lbl_wgb_defense.append(lbl)
            grid.addWidget(lbl, t, 0)
            row: List[QComboBox] = []
            for s in range(3):
                cmb = _UnitSearchComboBox()
                cmb.setMinimumWidth(300)
                self._all_unit_combos.append(cmb)
                grid.addWidget(cmb, t, 1 + s)
                row.append(cmb)
            self.wgb_team_combos.append(row)

        # -- buttons ------------------------------------------
        btn_row = QHBoxLayout()
        v.addLayout(btn_row)

        self.btn_validate_wgb = QPushButton(tr("btn.validate_pools"))
        self.btn_validate_wgb.setEnabled(False)
        self.btn_validate_wgb.clicked.connect(self.on_validate_wgb)
        btn_row.addWidget(self.btn_validate_wgb)

        self.btn_edit_presets_wgb = QPushButton(tr("btn.builds"))
        self.btn_edit_presets_wgb.setEnabled(False)
        self.btn_edit_presets_wgb.clicked.connect(self.on_edit_presets_wgb)
        btn_row.addWidget(self.btn_edit_presets_wgb)

        self.btn_optimize_wgb = QPushButton(tr("btn.optimize"))
        self.btn_optimize_wgb.setEnabled(False)
        self.btn_optimize_wgb.clicked.connect(self.on_optimize_wgb)
        btn_row.addWidget(self.btn_optimize_wgb)

        self.lbl_wgb_passes = QLabel(tr("label.passes"))
        btn_row.addWidget(self.lbl_wgb_passes)
        self.spin_multi_pass_wgb = QSpinBox()
        self.spin_multi_pass_wgb.setRange(1, 10)
        self.spin_multi_pass_wgb.setValue(3)
        self.spin_multi_pass_wgb.setToolTip(tr("tooltip.passes"))
        self.spin_multi_pass_wgb.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        btn_row.addWidget(self.spin_multi_pass_wgb)
        self.lbl_wgb_workers = QLabel(tr("label.workers"))
        btn_row.addWidget(self.lbl_wgb_workers)
        self.combo_workers_wgb = QComboBox()
        self._populate_worker_combo(self.combo_workers_wgb)
        btn_row.addWidget(self.combo_workers_wgb)
        self.lbl_wgb_profile = QLabel("Profil")
        btn_row.addWidget(self.lbl_wgb_profile)
        self.combo_quality_profile_wgb = QComboBox()
        self.combo_quality_profile_wgb.addItem("Fast", "fast")
        self.combo_quality_profile_wgb.addItem("Balanced", "balanced")
        self.combo_quality_profile_wgb.addItem("Max Qualität", "max_quality")
        if self._gpu_search_available():
            self.combo_quality_profile_wgb.addItem("GPU Fast", "gpu_search_fast")
            self.combo_quality_profile_wgb.addItem("GPU Balanced", "gpu_search_balanced")
            self.combo_quality_profile_wgb.addItem("GPU Max", "gpu_search_max")
        self.combo_quality_profile_wgb.setCurrentIndex(1)
        self.combo_quality_profile_wgb.currentIndexChanged.connect(self._sync_worker_controls)
        btn_row.addWidget(self.combo_quality_profile_wgb)
        self._sync_worker_controls()

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.lbl_wgb_validate = QLabel("—")
        v.addWidget(self.lbl_wgb_validate)

        # -- preview cards ------------------------------------
        self.wgb_preview_cards = SiegeDefCardsWidget()
        v.addWidget(self.wgb_preview_cards, 1)

    def _init_rta_builder_ui(self):
        v = QVBoxLayout(self.tab_rta_builder)

        self.box_rta_select = QGroupBox(tr("group.rta_select"))
        v.addWidget(self.box_rta_select, 1)
        box_layout = QVBoxLayout(self.box_rta_select)

        # Top row: combo selector + add/remove + load current
        top_row = QHBoxLayout()
        self.rta_add_combo = _UnitSearchComboBox()
        self.rta_add_combo.setMinimumWidth(350)
        self._all_unit_combos.append(self.rta_add_combo)
        top_row.addWidget(self.rta_add_combo, 1)

        self.btn_rta_add = QPushButton(tr("btn.add"))
        self.btn_rta_add.clicked.connect(self._on_rta_add_monster)
        top_row.addWidget(self.btn_rta_add)

        self.btn_rta_remove = QPushButton(tr("btn.remove"))
        self.btn_rta_remove.clicked.connect(self._on_rta_remove_monster)
        top_row.addWidget(self.btn_rta_remove)

        self.btn_take_current_rta = QPushButton(tr("btn.take_rta"))
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

        self.btn_validate_rta = QPushButton(tr("btn.validate"))
        self.btn_validate_rta.setEnabled(False)
        self.btn_validate_rta.clicked.connect(self.on_validate_rta)
        btn_row.addWidget(self.btn_validate_rta)

        self.btn_edit_presets_rta = QPushButton(tr("btn.builds"))
        self.btn_edit_presets_rta.setEnabled(False)
        self.btn_edit_presets_rta.clicked.connect(self.on_edit_presets_rta)
        btn_row.addWidget(self.btn_edit_presets_rta)

        self.btn_optimize_rta = QPushButton(tr("btn.optimize"))
        self.btn_optimize_rta.setEnabled(False)
        self.btn_optimize_rta.clicked.connect(self.on_optimize_rta)
        btn_row.addWidget(self.btn_optimize_rta)

        self.lbl_rta_passes = QLabel(tr("label.passes"))
        btn_row.addWidget(self.lbl_rta_passes)
        self.spin_multi_pass_rta = QSpinBox()
        self.spin_multi_pass_rta.setRange(1, 10)
        self.spin_multi_pass_rta.setValue(3)
        self.spin_multi_pass_rta.setToolTip(tr("tooltip.passes"))
        self.spin_multi_pass_rta.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        btn_row.addWidget(self.spin_multi_pass_rta)
        self.lbl_rta_workers = QLabel(tr("label.workers"))
        btn_row.addWidget(self.lbl_rta_workers)
        self.combo_workers_rta = QComboBox()
        self._populate_worker_combo(self.combo_workers_rta)
        btn_row.addWidget(self.combo_workers_rta)
        self.lbl_rta_profile = QLabel("Profil")
        btn_row.addWidget(self.lbl_rta_profile)
        self.combo_quality_profile_rta = QComboBox()
        self.combo_quality_profile_rta.addItem("Fast", "fast")
        self.combo_quality_profile_rta.addItem("Balanced", "balanced")
        self.combo_quality_profile_rta.addItem("Max Qualität", "max_quality")
        if self._gpu_search_available():
            self.combo_quality_profile_rta.addItem("GPU Fast", "gpu_search_fast")
            self.combo_quality_profile_rta.addItem("GPU Balanced", "gpu_search_balanced")
            self.combo_quality_profile_rta.addItem("GPU Max", "gpu_search_max")
        self.combo_quality_profile_rta.setCurrentIndex(1)
        self.combo_quality_profile_rta.currentIndexChanged.connect(self._sync_worker_controls)
        btn_row.addWidget(self.combo_quality_profile_rta)
        self._sync_worker_controls()

        btn_row.addItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.lbl_rta_validate = QLabel("—")
        v.addWidget(self.lbl_rta_validate)

    def _init_team_tab_ui(self):
        layout = QVBoxLayout(self.tab_team_builder)

        row = QHBoxLayout()
        self.lbl_team = QLabel(tr("label.team"))
        row.addWidget(self.lbl_team)
        self.team_combo = QComboBox()
        self.team_combo.currentIndexChanged.connect(self._on_team_selected)
        row.addWidget(self.team_combo, 1)
        layout.addLayout(row)

        btn_row = QHBoxLayout()
        self.btn_new_team = QPushButton(tr("btn.new_team"))
        self.btn_new_team.clicked.connect(self._on_new_team)
        btn_row.addWidget(self.btn_new_team)
        self.btn_edit_team = QPushButton(tr("btn.edit_team"))
        self.btn_edit_team.clicked.connect(self._on_edit_team)
        btn_row.addWidget(self.btn_edit_team)
        self.btn_remove_team = QPushButton(tr("btn.delete_team"))
        self.btn_remove_team.clicked.connect(self._on_remove_team)
        btn_row.addWidget(self.btn_remove_team)
        layout.addLayout(btn_row)

        self.btn_optimize_team = QPushButton(tr("btn.optimize_team"))
        self.btn_optimize_team.clicked.connect(self._optimize_team)
        layout.addWidget(self.btn_optimize_team)

        pass_row = QHBoxLayout()
        self.lbl_team_passes = QLabel(tr("label.passes"))
        pass_row.addWidget(self.lbl_team_passes)
        self.spin_multi_pass_team = QSpinBox()
        self.spin_multi_pass_team.setRange(1, 10)
        self.spin_multi_pass_team.setValue(3)
        self.spin_multi_pass_team.setToolTip(tr("tooltip.passes"))
        self.spin_multi_pass_team.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        pass_row.addWidget(self.spin_multi_pass_team)
        self.lbl_team_workers = QLabel(tr("label.workers"))
        pass_row.addWidget(self.lbl_team_workers)
        self.combo_workers_team = QComboBox()
        self._populate_worker_combo(self.combo_workers_team)
        pass_row.addWidget(self.combo_workers_team)
        self.lbl_team_profile = QLabel("Profil")
        pass_row.addWidget(self.lbl_team_profile)
        self.combo_quality_profile_team = QComboBox()
        self.combo_quality_profile_team.addItem("Fast", "fast")
        self.combo_quality_profile_team.addItem("Balanced", "balanced")
        self.combo_quality_profile_team.addItem("Max Qualität", "max_quality")
        if self._gpu_search_available():
            self.combo_quality_profile_team.addItem("GPU Fast", "gpu_search_fast")
            self.combo_quality_profile_team.addItem("GPU Balanced", "gpu_search_balanced")
            self.combo_quality_profile_team.addItem("GPU Max", "gpu_search_max")
        self.combo_quality_profile_team.setCurrentIndex(1)
        self.combo_quality_profile_team.currentIndexChanged.connect(self._sync_worker_controls)
        pass_row.addWidget(self.combo_quality_profile_team)
        self._sync_worker_controls()
        pass_row.addStretch(1)
        layout.addLayout(pass_row)

        self.lbl_team_opt_status = QLabel("—")
        layout.addWidget(self.lbl_team_opt_status)

        self.lbl_team_units = QLabel(tr("label.import_account_first"))
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
            self.team_combo.addItem(f"{team.name} ({len(team.unit_ids)} {tr('label.units')})", team.id)
        self.team_combo.blockSignals(False)
        if not teams:
            self.lbl_team_units.setText(tr("label.no_teams"))
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
                self.lbl_team_units.setText(tr("label.no_teams"))
            else:
                self.lbl_team_units.setText(tr("label.no_team_selected"))
            self._set_team_controls_enabled(bool(self.account))
            return
        self.lbl_team_units.setText(self._team_units_text(team))
        self._set_team_controls_enabled(bool(self.account))
        if not self.account:
            return

    def _team_units_text(self, team: Team) -> str:
        if not team.unit_ids:
            return tr("label.no_units")
        return "\n".join(self._unit_text_cached(uid) for uid in team.unit_ids)

    def _on_new_team(self) -> None:
        if not self.account:
            QMessageBox.warning(self, tr("label.team"), tr("dlg.load_import_first"))
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
            QMessageBox.warning(self, tr("label.team"), str(exc))
            return
        self.team_store.save(self.team_config_path)
        self._refresh_team_combo()
        self._select_team_by_id(team.id)

    def _on_edit_team(self) -> None:
        if not self.account:
            QMessageBox.warning(self, tr("label.team"), tr("dlg.load_import_first"))
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
            QMessageBox.warning(self, tr("label.team"), str(exc))
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
            QMessageBox.warning(self, tr("label.team"), tr("dlg.load_import_and_team"))
            return
        pass_count = int(self.spin_multi_pass_team.value())
        quality_profile = str(self.combo_quality_profile_team.currentData() or "balanced")
        workers = self._effective_workers(quality_profile, self.combo_workers_team)
        running_text = tr("result.team_opt_running", name=team.name)
        self.lbl_team_opt_status.setText(running_text)
        self.statusBar().showMessage(running_text)
        ordered_unit_ids = self._units_by_turn_order("siege", team.unit_ids)
        team_idx_by_uid: Dict[int, int] = {int(uid): 0 for uid in team.unit_ids}
        leader_spd_bonus_by_uid = self._leader_spd_bonus_map([team.unit_ids])
        team_turn_by_uid: Dict[int, int] = {}
        for uid in team.unit_ids:
            builds = self.presets.get_unit_builds("siege", int(uid))
            b0 = builds[0] if builds else Build.default_any()
            team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
        res = self._run_with_busy_progress(
            running_text,
            lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
                self.account,
                self.presets,
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
        self.lbl_team_opt_status.setText(res.message)
        self.statusBar().showMessage(res.message, 7000)
        self._show_optimize_results(
            tr("result.title_team", name=team.name), res.message, res.results,
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

    def _unit_totem_bonus(self, unit_id: int) -> Dict[str, int]:
        out: Dict[str, int] = {}
        if not self.account:
            return out
        u = self.account.units_by_id.get(unit_id)
        if not u:
            return out
        pct = int(self.account.sky_tribe_totem_spd_pct or 0)
        if pct > 0:
            out["SPD"] = int(int(u.base_spd or 0) * pct / 100)
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
        totem_spd_bonus = int(base_spd * int(self.account.sky_tribe_totem_spd_pct or 0) / 100)

        ls = self._team_leader_skill(team_unit_ids)
        lead_spd_bonus = int(base_spd * ls.amount / 100) if ls and ls.stat == "SPD%" else 0

        return int(base_spd + rune_spd_flat + set_spd_bonus + totem_spd_bonus + lead_spd_bonus)

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
        spd_from_totem = int(base_spd * int(self.account.sky_tribe_totem_spd_pct or 0) / 100)

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
        spd = base_spd + add_spd + spd_from_swift + spd_from_totem + lead_spd

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
            name = tr("label.defense", n=idx)
            legacy_name = f"Siege Verteidigung {idx}"
            if name in existing_names or legacy_name in existing_names:
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

        self.lbl_siege_validate.setText(tr("status.siege_taken"))

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
                return False, tr("val.incomplete_team", label=label, team=sel.team_index+1, have=len(sel.unit_ids), need=must_have_team_size), []
            # intra-team duplicate check
            team_set: Set[int] = set()
            for uid in sel.unit_ids:
                if uid in team_set:
                    name = self._unit_text(uid) if self.account else str(uid)
                    return False, tr("val.duplicate_in_team", label=label, team=sel.team_index+1, name=name), []
                team_set.add(uid)
            all_units.extend(sel.unit_ids)

        if not all_units:
            return False, tr("val.no_teams", label=label), []

        return True, tr("val.ok", label=label, count=len(all_units)), all_units

    def on_validate_siege(self):
        if not self.account:
            return
        selections = self._collect_siege_selections()
        ok, msg, all_units = self._validate_team_structure("Siege", selections, must_have_team_size=3)
        if not ok:
            self.lbl_siege_validate.setText(msg)
            QMessageBox.critical(self, tr("val.title_siege"), msg)
            return
        self.lbl_siege_validate.setText(msg)
        QMessageBox.information(self, tr("val.title_siege_ok"), msg)

    def on_edit_presets_siege(self):
        if not self.account:
            return
        selections = self._collect_siege_selections()
        ok, msg, all_units = self._validate_team_structure("Siege", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(self, "Siege", tr("dlg.validate_first", msg=msg))
            return

        unit_rows: List[Tuple[int, str]] = [(uid, self._unit_text(uid)) for uid in all_units]

        dlg = BuildDialog(
            self,
            "Siege Builds",
            unit_rows,
            self.presets,
            "siege",
            self.account,
            self._unit_icon_for_unit_id,
            team_size=3,
        )
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.apply_to_store()
            except ValueError as exc:
                QMessageBox.critical(self, "Builds", str(exc))
                return
            self.presets.save(self.presets_path)
            QMessageBox.information(self, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=self.presets_path))

    def on_optimize_siege(self):
        if not self.account:
            return
        if self._siege_optimization_running:
            return
        self._siege_optimization_running = True
        self.btn_optimize_siege.setEnabled(False)
        try:
            pass_count = int(self.spin_multi_pass_siege.value())
            quality_profile = str(self.combo_quality_profile_siege.currentData() or "balanced")
            workers = self._effective_workers(quality_profile, self.combo_workers_siege)
            running_text = tr("result.opt_running", mode="Siege")
            self.lbl_siege_validate.setText(running_text)
            self.statusBar().showMessage(running_text)
            selections = self._collect_siege_selections()
            ok, msg, all_units = self._validate_team_structure("Siege", selections, must_have_team_size=3)
            if not ok:
                QMessageBox.critical(self, "Siege", tr("dlg.validate_first", msg=msg))
                return

            ordered_unit_ids = self._units_by_turn_order("siege", all_units)
            team_idx_by_uid: Dict[int, int] = {}
            for idx, sel in enumerate(selections):
                for uid in sel.unit_ids:
                    team_idx_by_uid[int(uid)] = int(idx)
            leader_spd_bonus_by_uid = self._leader_spd_bonus_map([sel.unit_ids for sel in selections if sel.unit_ids])
            team_turn_by_uid: Dict[int, int] = {}
            for uid in all_units:
                builds = self.presets.get_unit_builds("siege", int(uid))
                b0 = builds[0] if builds else Build.default_any()
                team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
            res = self._run_with_busy_progress(
                running_text,
                lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
                    self.account,
                    self.presets,
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
            self.lbl_siege_validate.setText(res.message)
            self.statusBar().showMessage(res.message, 7000)
            unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(all_units)}
            siege_teams = [sel.unit_ids for sel in selections if sel.unit_ids]
            self._show_optimize_results(
                tr("result.title_siege"),
                res.message,
                res.results,
                unit_team_index=team_idx_by_uid,
                unit_display_order=unit_display_order,
                mode="siege",
                teams=siege_teams,
            )
        finally:
            self._siege_optimization_running = False
            self.btn_optimize_siege.setEnabled(bool(self.account))

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

    def _leader_spd_bonus_map(self, teams: List[List[int]]) -> Dict[int, int]:
        out: Dict[int, int] = {}
        if not self.account:
            return out
        for team in teams:
            ids = [int(uid) for uid in (team or []) if int(uid) != 0]
            if not ids:
                continue
            for uid in ids:
                out[int(uid)] = int(self._unit_leader_bonus(int(uid), ids).get("SPD", 0) or 0)
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
            return False, tr("val.no_account")
        seen: Dict[int, str] = {}  # master_id -> first unit name
        for uid in all_unit_ids:
            u = self.account.units_by_id.get(uid)
            if not u:
                continue
            mid = u.unit_master_id
            name = self.monster_db.name_for(mid)
            if mid in seen:
                return False, tr("val.duplicate_monster_wgb", name=name)
            seen[mid] = name
        return True, ""

    def on_validate_wgb(self):
        if not self.account:
            return
        selections = self._collect_wgb_selections()
        ok, msg, all_units = self._validate_team_structure("WGB", selections, must_have_team_size=3)
        if not ok:
            self.lbl_wgb_validate.setText(msg)
            QMessageBox.critical(self, tr("val.title_wgb"), msg)
            return
        # unique monster check
        ok2, msg2 = self._validate_unique_monsters(all_units)
        if not ok2:
            self.lbl_wgb_validate.setText(msg2)
            QMessageBox.critical(self, tr("val.title_wgb"), msg2)
            return
        self.lbl_wgb_validate.setText(msg)
        QMessageBox.information(self, tr("val.title_wgb_ok"), msg)
        # update preview cards
        self._render_wgb_preview(selections)

    def on_edit_presets_wgb(self):
        if not self.account:
            return
        selections = self._collect_wgb_selections()
        ok, msg, all_units = self._validate_team_structure("WGB", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(self, "WGB", tr("dlg.validate_first", msg=msg))
            return
        ok2, msg2 = self._validate_unique_monsters(all_units)
        if not ok2:
            QMessageBox.critical(self, "WGB", msg2)
            return

        unit_rows: List[Tuple[int, str]] = [(uid, self._unit_text(uid)) for uid in all_units]
        dlg = BuildDialog(
            self,
            "WGB Builds",
            unit_rows,
            self.presets,
            "wgb",
            self.account,
            self._unit_icon_for_unit_id,
            team_size=3,
        )
        if dlg.exec() == QDialog.Accepted:
            try:
                dlg.apply_to_store()
            except ValueError as exc:
                QMessageBox.critical(self, "Builds", str(exc))
                return
            self.presets.save(self.presets_path)
            QMessageBox.information(self, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=self.presets_path))

    def on_optimize_wgb(self):
        if not self.account:
            return
        pass_count = int(self.spin_multi_pass_wgb.value())
        quality_profile = str(self.combo_quality_profile_wgb.currentData() or "balanced")
        workers = self._effective_workers(quality_profile, self.combo_workers_wgb)
        running_text = tr("result.opt_running", mode="WGB")
        self.lbl_wgb_validate.setText(running_text)
        self.statusBar().showMessage(running_text)
        selections = self._collect_wgb_selections()
        ok, msg, all_units = self._validate_team_structure("WGB", selections, must_have_team_size=3)
        if not ok:
            QMessageBox.critical(self, "WGB", tr("dlg.validate_first", msg=msg))
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
        leader_spd_bonus_by_uid = self._leader_spd_bonus_map([sel.unit_ids for sel in selections if sel.unit_ids])
        team_turn_by_uid: Dict[int, int] = {}
        for uid in all_units:
            builds = self.presets.get_unit_builds("wgb", int(uid))
            b0 = builds[0] if builds else Build.default_any()
            team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
        res = self._run_with_busy_progress(
            running_text,
            lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
                self.account,
                self.presets,
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
        self.lbl_wgb_validate.setText(res.message)
        self.statusBar().showMessage(res.message, 7000)
        unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(all_units)}
        wgb_teams = [sel.unit_ids for sel in selections if sel.unit_ids]
        self._show_optimize_results(
            tr("result.title_wgb"),
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
            QMessageBox.warning(self, "RTA", tr("dlg.max_15_rta"))
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
            tr("status.rta_taken", count=min(len(active_uids), 15))
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
            msg = tr("rta.no_monsters")
            self.lbl_rta_validate.setText(msg)
            QMessageBox.critical(self, tr("val.title_rta"), msg)
            return
        seen: Set[int] = set()
        for uid in ids:
            if uid in seen:
                name = self._unit_text(uid)
                msg = tr("rta.duplicate", name=name)
                self.lbl_rta_validate.setText(msg)
                QMessageBox.critical(self, tr("val.title_rta"), msg)
                return
            seen.add(uid)
        msg = tr("rta.ok", count=len(ids))
        self.lbl_rta_validate.setText(msg)
        QMessageBox.information(self, tr("val.title_rta_ok"), msg)

    def on_edit_presets_rta(self):
        if not self.account:
            return
        ids = self._collect_rta_unit_ids()
        if not ids:
            QMessageBox.critical(self, "RTA", tr("dlg.select_monsters_first"))
            return
        if len(ids) != len(set(ids)):
            QMessageBox.critical(self, "RTA", tr("dlg.duplicates_found"))
            return

        unit_rows: List[Tuple[int, str]] = [(uid, self._unit_text(uid)) for uid in ids]
        dlg = BuildDialog(
            self, "RTA Builds", unit_rows, self.presets, "rta", self.account,
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
            QMessageBox.information(self, tr("dlg.builds_saved_title"), tr("dlg.builds_saved", path=self.presets_path))

    def on_optimize_rta(self):
        if not self.account:
            return
        pass_count = int(self.spin_multi_pass_rta.value())
        quality_profile = str(self.combo_quality_profile_rta.currentData() or "balanced")
        workers = self._effective_workers(quality_profile, self.combo_workers_rta)
        running_text = tr("result.opt_running", mode="RTA")
        self.lbl_rta_validate.setText(running_text)
        self.statusBar().showMessage(running_text)
        ids = self._collect_rta_unit_ids()
        if not ids:
            QMessageBox.critical(self, "RTA", tr("dlg.select_monsters_first"))
            return
        if len(ids) != len(set(ids)):
            QMessageBox.critical(self, "RTA", tr("dlg.duplicates_found"))
            return

        # List order = optimization order = turn order
        team_idx_by_uid: Dict[int, int] = {int(uid): 0 for uid in ids}
        team_turn_by_uid: Dict[int, int] = {int(uid): pos + 1 for pos, uid in enumerate(ids)}
        res = self._run_with_busy_progress(
            running_text,
            lambda is_cancelled, register_solver, progress_cb: optimize_greedy(
                self.account,
                self.presets,
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
        self.lbl_rta_validate.setText(res.message)
        self.statusBar().showMessage(res.message, 7000)
        unit_display_order: Dict[int, int] = {int(uid): idx for idx, uid in enumerate(ids)}
        rta_teams = [ids]
        self._show_optimize_results(
            tr("result.title_rta"),
            res.message,
            res.results,
            unit_team_index=team_idx_by_uid,
            unit_display_order=unit_display_order,
            mode="rta",
            teams=rta_teams,
        )

    def _on_language_changed(self, index: int) -> None:
        import app.i18n as i18n
        code = self.lang_combo.itemData(index)
        if code and code != i18n.get_language():
            i18n.set_language(code)
            self._retranslate_ui()

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(tr("main.title"))
        self.btn_import.setText(tr("main.import_btn"))
        if not self.account:
            self.lbl_status.setText(tr("main.no_import"))
        self.tabs.setTabText(0, tr("tab.overview"))
        self.tabs.setTabText(1, tr("tab.siege_current"))
        self.tabs.setTabText(2, tr("tab.rta_current"))
        self.tabs.setTabText(3, tr("tab.siege_builder"))
        self.tabs.setTabText(4, tr("tab.siege_saved"))
        self.tabs.setTabText(5, tr("tab.wgb_builder"))
        self.tabs.setTabText(6, tr("tab.wgb_saved"))
        self.tabs.setTabText(7, tr("tab.rta_builder"))
        self.tabs.setTabText(8, tr("tab.rta_saved"))

        # Saved optimization tabs
        self.lbl_saved_siege.setText(tr("label.saved_opt"))
        self.lbl_saved_wgb.setText(tr("label.saved_opt"))
        self.lbl_saved_rta.setText(tr("label.saved_opt"))
        self.btn_delete_saved_siege.setText(tr("btn.delete"))
        self.btn_delete_saved_wgb.setText(tr("btn.delete"))
        self.btn_delete_saved_rta.setText(tr("btn.delete"))

        # Siege builder
        self.box_siege_select.setTitle(tr("group.siege_select"))
        for idx, lbl in enumerate(self.lbl_siege_defense, start=1):
            lbl.setText(tr("label.defense", n=idx))
        self.btn_take_current_siege.setText(tr("btn.take_siege"))
        self.btn_validate_siege.setText(tr("btn.validate_pools"))
        self.btn_edit_presets_siege.setText(tr("btn.builds"))
        self.btn_optimize_siege.setText(tr("btn.optimize"))
        self.lbl_siege_passes.setText(tr("label.passes"))
        self.lbl_siege_workers.setText(tr("label.workers"))
        self.lbl_siege_profile.setText("Profil")
        self.spin_multi_pass_siege.setToolTip(tr("tooltip.passes"))
        self.combo_workers_siege.setToolTip(tr("tooltip.workers"))

        # WGB builder
        self.box_wgb_select.setTitle(tr("group.wgb_select"))
        for idx, lbl in enumerate(self.lbl_wgb_defense, start=1):
            lbl.setText(tr("label.defense", n=idx))
        self.btn_validate_wgb.setText(tr("btn.validate_pools"))
        self.btn_edit_presets_wgb.setText(tr("btn.builds"))
        self.btn_optimize_wgb.setText(tr("btn.optimize"))
        self.lbl_wgb_passes.setText(tr("label.passes"))
        self.lbl_wgb_workers.setText(tr("label.workers"))
        self.lbl_wgb_profile.setText("Profil")
        self.spin_multi_pass_wgb.setToolTip(tr("tooltip.passes"))
        self.combo_workers_wgb.setToolTip(tr("tooltip.workers"))

        # RTA builder
        self.box_rta_select.setTitle(tr("group.rta_select"))
        self.btn_rta_add.setText(tr("btn.add"))
        self.btn_rta_remove.setText(tr("btn.remove"))
        self.btn_take_current_rta.setText(tr("btn.take_rta"))
        self.btn_validate_rta.setText(tr("btn.validate"))
        self.btn_edit_presets_rta.setText(tr("btn.builds"))
        self.btn_optimize_rta.setText(tr("btn.optimize"))
        self.lbl_rta_passes.setText(tr("label.passes"))
        self.lbl_rta_workers.setText(tr("label.workers"))
        self.lbl_rta_profile.setText("Profil")
        self.spin_multi_pass_rta.setToolTip(tr("tooltip.passes"))
        self.combo_workers_rta.setToolTip(tr("tooltip.workers"))

        # Team tab
        self.lbl_team.setText(tr("label.team"))
        self.btn_new_team.setText(tr("btn.new_team"))
        self.btn_edit_team.setText(tr("btn.edit_team"))
        self.btn_remove_team.setText(tr("btn.delete_team"))
        self.btn_optimize_team.setText(tr("btn.optimize_team"))
        self.lbl_team_passes.setText(tr("label.passes"))
        self.lbl_team_workers.setText(tr("label.workers"))
        self.lbl_team_profile.setText("Profil")
        self.spin_multi_pass_team.setToolTip(tr("tooltip.passes"))
        self.combo_workers_team.setToolTip(tr("tooltip.workers"))
        self._refresh_team_combo()

        # Search placeholder for all searchable unit combos
        for cmb in self.findChildren(_UnitSearchComboBox):
            le = cmb.lineEdit()
            if le is not None:
                le.setPlaceholderText(tr("main.search_placeholder"))

        # Re-render views that contain translated text generated at render time
        self.overview_widget.retranslate()
        self.rta_overview.retranslate()
        if self.account:
            self._render_siege_raw()
            self._render_wgb_preview()
            self._on_saved_opt_changed("siege")
            self._on_saved_opt_changed("wgb")
            self._on_saved_opt_changed("rta")


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


def _show_update_dialog(window: QMainWindow, result: UpdateCheckResult) -> None:
    if not result.checked or not result.update_available or not result.release:
        return

    message = QMessageBox(window)
    message.setIcon(QMessageBox.Information)
    message.setWindowTitle(tr("update.title"))
    message.setText(
        tr("update.text", latest=result.latest_version, current=result.current_version)
    )
    message.setInformativeText(tr("update.open_release"))

    btn_open_release = message.addButton(tr("btn.release_page"), QMessageBox.AcceptRole)
    message.addButton(tr("btn.later"), QMessageBox.RejectRole)
    message.exec()

    if message.clickedButton() == btn_open_release:
        release_url = (result.release.html_url or "").strip()
        if release_url.startswith("https://"):
            webbrowser.open(release_url)
        else:
            webbrowser.open("https://github.com/San0s-o/Summoners-War-Team-Optimizer/releases")


def _start_update_check(window: QMainWindow) -> None:
    worker = _TaskWorker(check_latest_release)
    window._update_check_worker = worker

    def _on_finished(result_obj: object) -> None:
        window._update_check_worker = None
        if not isinstance(result_obj, UpdateCheckResult):
            return
        _show_update_dialog(window, result_obj)

    def _on_failed(detail: str) -> None:
        window._update_check_worker = None
        if window.statusBar() is not None:
            window.statusBar().showMessage(tr("svc.check_failed", detail=detail), 6000)

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)


def run_app():
    app = QApplication(sys.argv)
    _apply_dark_palette(app)
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


class LicenseDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, initial_key: str = "", auto_validate: bool = False):
        super().__init__(parent)
        self.validation_result: LicenseValidation | None = None
        self._validation_worker: _TaskWorker | None = None
        self.setWindowTitle(tr("license.title"))
        self.resize(520, 180)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("license.enter_key")))

        self.edit_key = QLineEdit()
        self.edit_key.setPlaceholderText("SWTO-...")
        self.edit_key.setText(initial_key)
        layout.addWidget(self.edit_key)

        self.lbl_status = QLabel("")
        layout.addWidget(self.lbl_status)

        buttons = QDialogButtonBox()
        self.btn_validate = buttons.addButton(tr("btn.activate"), QDialogButtonBox.AcceptRole)
        self.btn_cancel = buttons.addButton(tr("btn.quit"), QDialogButtonBox.RejectRole)
        self.btn_validate.clicked.connect(self._on_validate)
        self.btn_cancel.clicked.connect(self.reject)
        layout.addWidget(buttons)

        self.edit_key.returnPressed.connect(self._on_validate)
        if auto_validate and self.key_text:
            QTimer.singleShot(120, self._on_validate)

    @property
    def key_text(self) -> str:
        return self.edit_key.text().strip()

    def _set_busy(self, busy: bool) -> None:
        is_busy = bool(busy)
        self.edit_key.setEnabled(not is_busy)
        self.btn_validate.setEnabled(not is_busy)
        self.btn_cancel.setEnabled(not is_busy)

    def _on_validate(self) -> None:
        if self._validation_worker is not None:
            return
        if not self.key_text:
            self.lbl_status.setText(tr("lic.no_key"))
            return
        self._set_busy(True)
        self.lbl_status.setText(tr("license.validating"))
        worker = _TaskWorker(validate_license_key, self.key_text)
        self._validation_worker = worker
        worker.signals.finished.connect(self._on_validation_result)
        worker.signals.failed.connect(self._on_validation_failed)
        QThreadPool.globalInstance().start(worker)

    def _on_validation_result(self, result_obj: object) -> None:
        self._validation_worker = None
        self._set_busy(False)
        if not isinstance(result_obj, LicenseValidation):
            self.lbl_status.setText(tr("lic.invalid_response", status="unknown"))
            return
        result = result_obj
        if result.valid:
            save_license_key(self.key_text)
            self.validation_result = result
            self.accept()
            return
        self.lbl_status.setText(result.message)

    def _on_validation_failed(self, detail: str) -> None:
        self._validation_worker = None
        self._set_busy(False)
        self.lbl_status.setText(tr("lic.check_failed"))
        if detail:
            self.lbl_status.setToolTip(detail)

    def reject(self) -> None:
        if self._validation_worker is not None:
            return
        super().reject()


def _format_trial_remaining(expires_at: int, now_ts: int | None = None) -> str:
    now = int(now_ts if now_ts is not None else datetime.now().timestamp())
    remaining_s = max(0, int(expires_at) - now)
    if remaining_s >= 24 * 60 * 60:
        days = max(1, remaining_s // (24 * 60 * 60))
        return tr("license.days", n=days)
    if remaining_s >= 60 * 60:
        hours = max(1, remaining_s // (60 * 60))
        return tr("license.hours", n=hours)
    minutes = max(1, remaining_s // 60)
    return tr("license.minutes", n=minutes)


def _apply_license_title(window: QMainWindow, result: LicenseValidation) -> None:
    base_title = "SW Team Optimizer"
    license_type = (result.license_type or "").strip().lower()
    if "trial" not in license_type:
        return
    if result.expires_at:
        remaining = _format_trial_remaining(result.expires_at)
        window.setWindowTitle(f"{base_title} - {tr('license.trial_remaining', remaining=remaining)}")
        return
    window.setWindowTitle(f"{base_title} - {tr('license.trial')}")


def _validate_license_key_threaded_sync(key: str) -> LicenseValidation:
    wait_loop = QEventLoop()
    result_box: dict[str, LicenseValidation] = {"result": LicenseValidation(False, tr("lic.check_failed"))}
    worker = _TaskWorker(validate_license_key, key)

    def _on_finished(result_obj: object) -> None:
        if isinstance(result_obj, LicenseValidation):
            result_box["result"] = result_obj
        wait_loop.quit()

    def _on_failed(_detail: str) -> None:
        wait_loop.quit()

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)
    wait_loop.exec()
    return result_box["result"]


def _ensure_license_accepted() -> LicenseValidation | None:
    known_keys = load_license_keys()
    existing = known_keys[0] if known_keys else None
    cached_candidate: tuple[str, LicenseValidation] | None = None
    for key in known_keys:
        check = _validate_license_key_threaded_sync(key)
        if check.valid and check.error_kind != "cached":
            save_license_key(key)
            return check
        if check.valid:
            if cached_candidate is None:
                cached_candidate = (key, check)
            else:
                current_exp = check.expires_at or -1
                best_exp = (cached_candidate[1].expires_at or -1)
                if current_exp > best_exp:
                    cached_candidate = (key, check)

    if cached_candidate is not None:
        save_license_key(cached_candidate[0])
        return cached_candidate[1]

    dlg = LicenseDialog(initial_key=existing or "")
    if dlg.exec() == QDialog.Accepted:
        return dlg.validation_result
    return None










