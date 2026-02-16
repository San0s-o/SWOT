from __future__ import annotations

from itertools import product
from typing import Callable, Dict, List, Set, Tuple

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
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


_MIN_BASE_STATS = ("SPD", "HP", "ATK", "DEF")
_MIN_BASE_AWARE_STATS = ("SPD", "HP", "ATK", "DEF", "CR", "CD", "RES", "ACC")


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
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(980, 620)
        # Match main window behavior exactly: open maximized.
        self.showMaximized()

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
                    tick_cmb.addItem("-", 0)
                    for tick in allowed_spd_ticks(self.mode):
                        req_spd = int(min_spd_for_tick(tick, self.mode))
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

        editor_split = QSplitter(Qt.Horizontal)
        editor_split.setChildrenCollapsible(False)
        editor_split.setHandleWidth(8)

        list_box = QGroupBox(tr("group.build_monster_list"))
        list_layout = QVBoxLayout(list_box)
        list_layout.setContentsMargins(8, 8, 8, 8)
        list_layout.addWidget(self._unit_list, 1)
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

        for unit_id, label in table_rows:
            item = QListWidgetItem(label)
            icon = self._unit_icon_fn(unit_id)
            if not icon.isNull():
                item.setIcon(icon)
            item.setData(Qt.UserRole, int(unit_id))
            self._unit_list.addItem(item)
            builds = self.preset_store.get_unit_builds(self.mode, unit_id)
            b0 = builds[0] if builds else Build.default_any()
            editor_page = self._build_unit_editor(int(unit_id), b0)
            self._unit_editor_stack.addWidget(editor_page)

        self._unit_list.currentRowChanged.connect(self._on_unit_row_changed)
        if self._unit_list.count() > 0:
            self._unit_list.setCurrentRow(0)

        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_unit_row_changed(self, row: int) -> None:
        if row < 0 or row >= self._unit_editor_stack.count():
            return
        self._unit_editor_stack.setCurrentIndex(int(row))

    def _make_mainstat_combo(self, defaults: List[str]) -> _MainstatMultiCombo:
        cmb = _MainstatMultiCombo(MAINSTAT_KEYS)
        if defaults:
            cmb.set_checked_values([str(defaults[0])])
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
            art_attr_focus_value = str(self._art_attr_focus_combo[unit_id].currentData() or "").upper()
            art_type_focus_value = str(self._art_type_focus_combo[unit_id].currentData() or "").upper()
            art_attr_substats = self._artifact_substat_ids_for_unit(unit_id, "attribute")
            art_type_substats = self._artifact_substat_ids_for_unit(unit_id, "type")
            optimize_order = int(optimize_order_by_uid.get(unit_id, 0) or 0)
            turn_order = int(team_turn_order_by_uid.get(unit_id, 0) or 0)
            spd_tick = int(team_spd_tick_by_uid.get(unit_id, 0) or 0)
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
