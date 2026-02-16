from __future__ import annotations

from itertools import product
from typing import Callable, Dict, List, Set, Tuple

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import AccountData
from app.domain.presets import (
    ARTIFACT_MAIN_KEYS,
    Build,
    BuildStore,
    MAINSTAT_KEYS,
    SET_NAMES,
    SET_SIZES,
    SLOT2_DEFAULT,
    SLOT4_DEFAULT,
    SLOT6_DEFAULT,
)
from app.domain.speed_ticks import allowed_spd_ticks, min_spd_for_tick
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

            order_box = QGroupBox(tr("group.turn_order"))
            order_grid = QGridLayout(order_box)
            teams: List[List[Tuple[int, str]]] = [
                self._unit_rows[i : i + self.team_size]
                for i in range(0, len(self._unit_rows), self.team_size)
                if self._unit_rows[i : i + self.team_size]
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

        self.table = QTableWidget(0, 18)
        self.table.setHorizontalHeaderLabels(
            [
                tr("header.monster"),
                tr("header.set1"),
                tr("header.set2"),
                tr("header.set3"),
                tr("header.slot2_main"),
                tr("header.slot4_main"),
                tr("header.slot6_main"),
                tr("header.attr_main"),
                tr("header.attr_sub1"),
                tr("header.attr_sub2"),
                tr("header.type_main"),
                tr("header.type_sub1"),
                tr("header.type_sub2"),
                tr("header.min_spd"),
                tr("header.min_cr"),
                tr("header.min_cd"),
                tr("header.min_res"),
                tr("header.min_acc"),
            ]
        )
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3, 4, 5, 6, 7, 10):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
        for col in (8, 9, 11, 12, 13, 14, 15, 16, 17):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
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

        table_rows = list(self._unit_rows)
        table_rows.sort(
            key=lambda x: (
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0) <= 0,
                int(getattr((self.preset_store.get_unit_builds(self.mode, int(x[0])) or [Build.default_any()])[0], "optimize_order", 0) or 0),
                next((idx for idx, it in enumerate(self._unit_rows) if int(it[0]) == int(x[0])), 10000),
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
                cmb.setToolTip(tr("tooltip.art_sub", kind=_artifact_kind_label(int(artifact_type))))
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
                raise ValueError(tr("val.set_invalid", unit=unit_label))

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
