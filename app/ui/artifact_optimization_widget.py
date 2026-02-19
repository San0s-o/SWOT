from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QStandardItemModel, QStandardItem
from PySide6.QtWidgets import (
    QAbstractItemView,
    QPushButton,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import AccountData, Artifact
from app.domain.artifact_effects import (
    artifact_rank_label,
    artifact_effect_text,
    ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID,
)
from app.engine.efficiency import artifact_efficiency
from app.i18n import tr
from app.ui.widgets.selection_combos import _UnitSearchComboBox


class _SortableNumericItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        if isinstance(other, QTableWidgetItem):
            a = self.data(Qt.UserRole)
            b = other.data(Qt.UserRole)
            try:
                return float(a) < float(b)
            except Exception:
                pass
        return super().__lt__(other)


def _numeric_item(value: float, suffix: str = "") -> QTableWidgetItem:
    text = f"{value:.2f}{suffix}" if suffix else f"{value:.2f}"
    item = _SortableNumericItem(text)
    item.setData(Qt.UserRole, float(value))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def _int_item(value: int) -> QTableWidgetItem:
    item = _SortableNumericItem(str(int(value)))
    item.setData(Qt.UserRole, int(value))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def _type_text(art: Artifact) -> str:
    t = int(art.type_ or 0)
    if t == 1:
        return tr("art_opt.type_attribute")
    if t == 2:
        return tr("art_opt.type_type")
    return f"Typ {t}"


def _rank_text(art: Artifact) -> str:
    rank = int(getattr(art, "original_rank", 0) or 0)
    if rank <= 0:
        rank = int(art.rank or 0)
    return artifact_rank_label(rank)


def _slot_text(art: Artifact) -> str:
    s = int(art.slot or 0)
    if s == 1:
        return tr("art_opt.type_attribute")
    if s == 2:
        return tr("art_opt.type_type")
    return str(s)


def _mainstat_text(art: Artifact) -> str:
    if not art.pri_effect or len(art.pri_effect) < 2:
        return ""
    eid = int(art.pri_effect[0] or 0)
    val = art.pri_effect[1]
    focus = ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID.get(eid)
    if focus:
        try:
            v = float(val)
            val_str = str(int(v)) if abs(v - int(v)) < 1e-9 else f"{v:.1f}"
            return f"{focus} +{val_str}"
        except Exception:
            return f"{focus} +{val}"
    return artifact_effect_text(eid, val)


def _sec_effects_text(art: Artifact) -> str:
    parts = []
    for sec in (art.sec_effects or []):
        if not sec or len(sec) < 2:
            continue
        eid = int(sec[0] or 0)
        val = sec[1]
        upgrades = int(sec[2] or 0) if len(sec) > 2 else 0
        text = artifact_effect_text(eid, val)
        if upgrades > 0:
            text += f" ({tr('ui.rolls', n=upgrades)})"
        parts.append(text)
    return " | ".join(parts)


class ArtifactOptimizationWidget(QWidget):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        monster_name_fn: Callable[[int], str] | None = None,
    ):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._monster_name_fn = monster_name_fn
        self._updating_filters = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.lbl_info = QLabel("")
        top.addWidget(self.lbl_info)
        top.addStretch(1)
        self.lbl_filter_type = QLabel("")
        top.addWidget(self.lbl_filter_type)
        self.combo_filter_type = QComboBox()
        self.combo_filter_type.setMinimumWidth(120)
        self.combo_filter_type.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_type)
        self.lbl_filter_monster = QLabel("")
        top.addWidget(self.lbl_filter_monster)
        self.combo_filter_monster = _UnitSearchComboBox()
        self.combo_filter_monster.setMinimumWidth(200)
        self.combo_filter_monster.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_monster)
        self.btn_reset_filters = QPushButton("")
        self.btn_reset_filters.clicked.connect(self._on_reset_filters)
        top.addWidget(self.btn_reset_filters)
        top.addStretch(1)
        layout.addLayout(top)

        self.table = QTableWidget(0, 8)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.table, 1)

        self.retranslate()

    def retranslate(self) -> None:
        self.lbl_filter_type.setText(tr("art_opt.filter_type"))
        self.lbl_filter_monster.setText(tr("art_opt.filter_monster"))
        self.btn_reset_filters.setText(tr("art_opt.filter_reset"))
        self.table.setHorizontalHeaderLabels([
            tr("art_opt.col.type"),
            tr("art_opt.col.quality"),
            tr("art_opt.col.level"),
            tr("art_opt.col.slot"),
            tr("art_opt.col.mainstat"),
            tr("art_opt.col.substats"),
            tr("art_opt.col.monster"),
            tr("art_opt.col.efficiency"),
        ])
        self.refresh()

    def set_account(self, account: Optional[AccountData]) -> None:
        self._account = account
        self.refresh()

    def _on_filters_changed(self, _index: int) -> None:
        if self._updating_filters:
            return
        self.refresh()

    def _on_reset_filters(self) -> None:
        self._updating_filters = True
        self.combo_filter_type.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_type.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._reset_search_field()
        finally:
            self.combo_filter_type.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False
        self.refresh()

    def _populate_filters(self, artifacts: list[Artifact]) -> None:
        current_type = int(self.combo_filter_type.currentData() or 0)
        current_monster_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)

        monster_model = QStandardItemModel()
        all_item = QStandardItem(tr("art_opt.filter_all"))
        all_item.setData(0, Qt.UserRole)
        monster_model.appendRow(all_item)
        if self._monster_name_fn:
            seen_uids: dict[int, str] = {}
            for a in artifacts:
                uid = int(a.occupied_id or 0)
                if uid > 0 and uid not in seen_uids:
                    seen_uids[uid] = self._monster_name_fn(uid)
            for uid, name in sorted(seen_uids.items(), key=lambda x: x[1]):
                item = QStandardItem(name)
                item.setData(uid, Qt.UserRole)
                monster_model.appendRow(item)

        self._updating_filters = True
        self.combo_filter_type.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_type.clear()
            self.combo_filter_type.addItem(tr("art_opt.filter_all"), 0)
            self.combo_filter_type.addItem(tr("art_opt.type_attribute"), 1)
            self.combo_filter_type.addItem(tr("art_opt.type_type"), 2)
            idx_type = self.combo_filter_type.findData(current_type)
            self.combo_filter_type.setCurrentIndex(idx_type if idx_type >= 0 else 0)

            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.set_source_model(monster_model)
            idx_monster = self.combo_filter_monster.findData(current_monster_uid, role=Qt.UserRole)
            self.combo_filter_monster.setCurrentIndex(idx_monster if idx_monster >= 0 else 0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._sync_line_edit_to_current()
        finally:
            self.combo_filter_type.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False

    def refresh(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        if not self._account:
            self.lbl_info.setText(tr("art_opt.hint_no_import"))
            self._populate_filters([])
            self.table.setSortingEnabled(True)
            return

        all_artifacts = list(self._account.artifacts or [])
        all_artifacts.sort(key=lambda a: (artifact_efficiency(a), int(a.artifact_id or 0)), reverse=True)
        self._populate_filters(all_artifacts)

        if not all_artifacts:
            self.lbl_info.setText(tr("art_opt.hint_no_rows"))
            self.table.setSortingEnabled(True)
            return

        selected_type = int(self.combo_filter_type.currentData() or 0)
        selected_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        artifacts = [
            a for a in all_artifacts
            if (selected_type <= 0 or int(a.type_ or 0) == selected_type)
            and (selected_uid <= 0 or int(a.occupied_id or 0) == selected_uid)
        ]

        if not artifacts:
            self.lbl_info.setText(tr("art_opt.hint_no_filter_rows"))
            self.table.setSortingEnabled(True)
            return

        if len(artifacts) == len(all_artifacts):
            self.lbl_info.setText(tr("art_opt.count", n=len(artifacts)))
        else:
            self.lbl_info.setText(tr("art_opt.count_filtered", shown=len(artifacts), total=len(all_artifacts)))

        self.table.setRowCount(len(artifacts))

        for row, art in enumerate(artifacts):
            eff = artifact_efficiency(art)

            type_item = QTableWidgetItem(_type_text(art))
            type_item.setData(Qt.UserRole, int(art.type_ or 0))
            self.table.setItem(row, 0, type_item)

            rank_val = int(getattr(art, "original_rank", 0) or art.rank or 0)
            rank_item = _SortableNumericItem(_rank_text(art))
            rank_item.setData(Qt.UserRole, rank_val)
            self.table.setItem(row, 1, rank_item)

            self.table.setItem(row, 2, _int_item(int(art.level or 0)))

            slot_item = QTableWidgetItem(_slot_text(art))
            slot_item.setData(Qt.UserRole, int(art.slot or 0))
            self.table.setItem(row, 3, slot_item)

            self.table.setItem(row, 4, QTableWidgetItem(_mainstat_text(art)))
            self.table.setItem(row, 5, QTableWidgetItem(_sec_effects_text(art)))

            monster_name = ""
            uid = int(art.occupied_id or 0)
            if uid > 0 and self._monster_name_fn:
                monster_name = self._monster_name_fn(uid)
            self.table.setItem(row, 6, QTableWidgetItem(monster_name))

            self.table.setItem(row, 7, _numeric_item(eff, "%"))

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, max(90, self.table.columnWidth(0)))
        self.table.setColumnWidth(1, max(80, self.table.columnWidth(1)))
        self.table.setColumnWidth(4, max(180, self.table.columnWidth(4)))
        self.table.setColumnWidth(5, max(500, self.table.columnWidth(5)))
        self.table.setColumnWidth(6, max(120, self.table.columnWidth(6)))
        self.table.setSortingEnabled(True)
