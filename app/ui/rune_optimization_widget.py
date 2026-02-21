from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QPushButton,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import QTextDocument, QAbstractTextDocumentLayout, QPainter, QStandardItemModel, QStandardItem

from app.domain.models import AccountData, Rune
from app.domain.presets import SET_NAMES, EFFECT_ID_TO_MAINSTAT_KEY
from app.engine.efficiency import rune_efficiency, rune_efficiency_max
from app.i18n import tr
from app.ui.widgets.selection_combos import _UnitSearchComboBox

_QUALITY_BASE_NAME = {
    1: "Normal",
    2: "Magic",
    3: "Rare",
    4: "Hero",
    5: "Legend",
    6: "Legend",
    11: "Normal",
    12: "Magic",
    13: "Rare",
    14: "Hero",
    15: "Legend",
    16: "Legend",
}

_ANCIENT_CLASS_IDS = {11, 12, 13, 14, 15, 16}


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


def _set_name_for(rune: Rune) -> str:
    sid = int(rune.set_id or 0)
    return str(SET_NAMES.get(sid, f"Set {sid}"))


def _quality_class_id(rune: Rune) -> int:
    origin = int(getattr(rune, "origin_class", 0) or 0)
    return origin if origin else int(rune.rune_class or 0)


def _quality_text(rune: Rune) -> str:
    cls_id = _quality_class_id(rune)
    base = _QUALITY_BASE_NAME.get(cls_id, f"{tr('ui.class_short')} {cls_id}")
    if cls_id in _ANCIENT_CLASS_IDS:
        return tr("rune_opt.quality_ancient", quality=base)
    return base


def _stat_name(eff_id: int) -> str:
    return str(EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"Eff {int(eff_id or 0)}"))


def _substats_text(rune: Rune) -> str:
    parts: list[str] = []
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0) if len(sec) > 0 else 0
        base = int(sec[1] or 0) if len(sec) > 1 else 0
        gemmed = int(sec[2] or 0) if len(sec) > 2 else 0
        grind = int(sec[3] or 0) if len(sec) > 3 else 0

        stat = _stat_name(eff_id)
        total = base + grind
        token = f"{stat}+{total}"
        if grind > 0:
            token += f" ({base}+{grind})"
        parts.append(token)
    return ", ".join(parts)


def _substats_html(rune: Rune) -> str:
    parts: list[str] = []
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0) if len(sec) > 0 else 0
        base = int(sec[1] or 0) if len(sec) > 1 else 0
        gemmed = int(sec[2] or 0) if len(sec) > 2 else 0
        grind = int(sec[3] or 0) if len(sec) > 3 else 0

        stat_raw = _stat_name(eff_id)
        stat = f"<span style='color:#1abc9c'>{stat_raw}</span>" if gemmed else stat_raw
        total = base + grind
        token = f"{stat}+{total}"
        if grind > 0:
            token += f" ({base}+<span style='color:#f39c12'>{grind}</span>)"
        parts.append(token)
    return "<span style='color:#9aa4b2'>, </span>".join(parts)


def _gem_grind_status(rune: Rune) -> str:
    gemmed = 0
    grinded = 0
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        gemmed += 1 if (len(sec) > 2 and int(sec[2] or 0) > 0) else 0
        grinded += 1 if (len(sec) > 3 and int(sec[3] or 0) > 0) else 0
    return tr("rune_opt.gem_grind_status", gems=gemmed, grinds=grinded)


def _icon_item(icon: QIcon, sort_value: int, tooltip: str = "") -> QTableWidgetItem:
    item = _SortableNumericItem("")
    if not icon.isNull():
        item.setIcon(icon)
    item.setData(Qt.UserRole, int(sort_value))
    item.setTextAlignment(Qt.AlignCenter)
    if tooltip:
        item.setToolTip(tooltip)
    return item


class _RichTextDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        options = QStyleOptionViewItem(option)
        self.initStyleOption(options, index)
        style = options.widget.style() if options.widget else QApplication.style()

        doc = QTextDocument()
        doc.setHtml(options.text or "")
        options.text = ""
        style.drawControl(QStyle.CE_ItemViewItem, options, painter, options.widget)

        text_rect = style.subElementRect(QStyle.SE_ItemViewItemText, options, options.widget)
        painter.save()
        try:
            painter.translate(text_rect.topLeft())
            painter.setClipRect(text_rect.translated(-text_rect.topLeft()))
            doc.setTextWidth(float(text_rect.width()))
            ctx = QAbstractTextDocumentLayout.PaintContext()
            if options.state & QStyle.State_Selected:
                ctx.palette.setColor(QPalette.ColorRole.Text, options.palette.highlightedText().color())
            doc.documentLayout().draw(painter, ctx)
        finally:
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index):
        doc = QTextDocument()
        doc.setHtml(str(index.data() or ""))
        doc.setTextWidth(float(max(0, option.rect.width())))
        return doc.size().toSize()


class RuneOptimizationWidget(QWidget):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        rune_set_icon_fn: Callable[[int], QIcon] | None = None,
        monster_name_fn: Callable[[int], str] | None = None,
    ):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._rune_set_icon_fn = rune_set_icon_fn
        self._monster_name_fn = monster_name_fn
        self._updating_filters = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top = QHBoxLayout()
        self.lbl_info = QLabel("")
        top.addWidget(self.lbl_info)
        top.addStretch(1)
        self.lbl_filter_set = QLabel("")
        top.addWidget(self.lbl_filter_set)
        self.combo_filter_set = QComboBox()
        self.combo_filter_set.setMinimumWidth(150)
        self.combo_filter_set.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_set)
        self.lbl_filter_slot = QLabel("")
        top.addWidget(self.lbl_filter_slot)
        self.combo_filter_slot = QComboBox()
        self.combo_filter_slot.setMinimumWidth(90)
        self.combo_filter_slot.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_slot)
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

        self.table = QTableWidget(0, 13)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(30)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setItemDelegateForColumn(5, _RichTextDelegate(self.table))
        layout.addWidget(self.table, 1)

        self.retranslate()

    def retranslate(self) -> None:
        self.lbl_filter_set.setText(tr("rune_opt.filter_set"))
        self.lbl_filter_slot.setText(tr("rune_opt.filter_slot"))
        self.lbl_filter_monster.setText(tr("rune_opt.filter_monster"))
        self.btn_reset_filters.setText(tr("rune_opt.filter_reset"))
        self.table.setHorizontalHeaderLabels(
            [
                tr("rune_opt.col.symbol"),
                tr("rune_opt.col.set"),
                tr("rune_opt.col.quality"),
                tr("rune_opt.col.slot"),
                tr("rune_opt.col.upgrade"),
                tr("rune_opt.col.substats"),
                tr("rune_opt.col.gem_grind"),
                tr("rune_opt.col.monster"),
                tr("rune_opt.col.current_eff"),
                tr("rune_opt.col.hero_max_eff"),
                tr("rune_opt.col.legend_max_eff"),
                tr("rune_opt.col.hero_potential"),
                tr("rune_opt.col.legend_potential"),
            ]
        )
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
        self.combo_filter_set.blockSignals(True)
        self.combo_filter_slot.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_set.setCurrentIndex(0)
            self.combo_filter_slot.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._reset_search_field()
        finally:
            self.combo_filter_set.blockSignals(False)
            self.combo_filter_slot.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False
        self.refresh()

    def _populate_filters(self, runes: list[Rune]) -> None:
        current_set = int(self.combo_filter_set.currentData() or 0)
        current_slot = int(self.combo_filter_slot.currentData() or 0)
        current_monster_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        set_ids = sorted({int(r.set_id or 0) for r in runes if int(r.set_id or 0) > 0})
        slot_nos = sorted({int(r.slot_no or 0) for r in runes if int(r.slot_no or 0) > 0})

        # Build monster model: collect unique unit_ids from equipped runes
        monster_model = QStandardItemModel()
        all_item = QStandardItem(tr("rune_opt.filter_all"))
        all_item.setData(0, Qt.UserRole)
        monster_model.appendRow(all_item)
        if self._monster_name_fn:
            seen_uids: dict[int, str] = {}
            for r in runes:
                if int(r.occupied_type or 0) == 1:
                    uid = int(r.occupied_id or 0)
                    if uid > 0 and uid not in seen_uids:
                        seen_uids[uid] = self._monster_name_fn(uid)
            for uid, name in sorted(seen_uids.items(), key=lambda x: x[1]):
                item = QStandardItem(name)
                item.setData(uid, Qt.UserRole)
                monster_model.appendRow(item)

        self._updating_filters = True
        self.combo_filter_set.blockSignals(True)
        self.combo_filter_slot.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        try:
            self.combo_filter_set.clear()
            self.combo_filter_set.addItem(tr("rune_opt.filter_all"), 0)
            for sid in set_ids:
                self.combo_filter_set.addItem(str(SET_NAMES.get(sid, f"Set {sid}")), sid)
            idx_set = self.combo_filter_set.findData(current_set)
            self.combo_filter_set.setCurrentIndex(idx_set if idx_set >= 0 else 0)

            self.combo_filter_slot.clear()
            self.combo_filter_slot.addItem(tr("rune_opt.filter_all"), 0)
            for slot in slot_nos:
                self.combo_filter_slot.addItem(str(slot), slot)
            idx_slot = self.combo_filter_slot.findData(current_slot)
            self.combo_filter_slot.setCurrentIndex(idx_slot if idx_slot >= 0 else 0)

            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.set_source_model(monster_model)
            idx_monster = self.combo_filter_monster.findData(current_monster_uid, role=Qt.UserRole)
            self.combo_filter_monster.setCurrentIndex(idx_monster if idx_monster >= 0 else 0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._sync_line_edit_to_current()
        finally:
            self.combo_filter_set.blockSignals(False)
            self.combo_filter_slot.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False

    def refresh(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        if not self._account:
            self.lbl_info.setText(tr("rune_opt.hint_no_import"))
            self._populate_filters([])
            self.table.setSortingEnabled(True)
            return

        all_runes = [r for r in self._account.runes if int(r.upgrade_curr or 0) >= 12]
        all_runes.sort(key=lambda r: (rune_efficiency(r), int(r.rune_id or 0)), reverse=True)
        self._populate_filters(all_runes)

        if not all_runes:
            self.lbl_info.setText(tr("rune_opt.hint_no_rows"))
            self.table.setSortingEnabled(True)
            return

        selected_set = int(self.combo_filter_set.currentData() or 0)
        selected_slot = int(self.combo_filter_slot.currentData() or 0)
        selected_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        runes = [
            r for r in all_runes
            if (selected_set <= 0 or int(r.set_id or 0) == selected_set)
            and (selected_slot <= 0 or int(r.slot_no or 0) == selected_slot)
            and (selected_uid <= 0 or int(r.occupied_id or 0) == selected_uid)
        ]

        if not runes:
            self.lbl_info.setText(tr("rune_opt.hint_no_filter_rows"))
            self.table.setSortingEnabled(True)
            return

        self.lbl_info.setText(tr("rune_opt.count_filtered", shown=len(runes), total=len(all_runes)))
        self.table.setRowCount(len(runes))

        for row, rune in enumerate(runes):
            current = float(rune_efficiency(rune))
            hero_max = float(rune_efficiency_max(rune, "hero"))
            legend_max = float(rune_efficiency_max(rune, "legend"))
            hero_potential = max(0.0, hero_max - current)
            legend_potential = max(0.0, legend_max - current)
            set_id = int(rune.set_id or 0)
            icon = self._rune_set_icon_fn(set_id) if self._rune_set_icon_fn else QIcon()

            self.table.setItem(
                row,
                0,
                _icon_item(
                    icon,
                    set_id,
                    tooltip=tr("ui.rune_id") + f": {int(rune.rune_id or 0)}",
                ),
            )
            self.table.setItem(row, 1, QTableWidgetItem(_set_name_for(rune)))
            self.table.setItem(row, 2, QTableWidgetItem(_quality_text(rune)))
            self.table.setItem(row, 3, _int_item(int(rune.slot_no or 0)))
            self.table.setItem(row, 4, _int_item(int(rune.upgrade_curr or 0)))
            sub_item = QTableWidgetItem(_substats_html(rune))
            sub_item.setData(Qt.UserRole, _substats_text(rune))
            sub_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, 5, sub_item)
            self.table.setItem(row, 6, QTableWidgetItem(_gem_grind_status(rune)))
            monster_name = ""
            if int(rune.occupied_type or 0) == 1 and self._monster_name_fn:
                monster_name = self._monster_name_fn(int(rune.occupied_id or 0))
            self.table.setItem(row, 7, QTableWidgetItem(monster_name))
            self.table.setItem(row, 8, _numeric_item(current, "%"))
            self.table.setItem(row, 9, _numeric_item(hero_max, "%"))
            self.table.setItem(row, 10, _numeric_item(legend_max, "%"))
            self.table.setItem(row, 11, _numeric_item(hero_potential, "%"))
            self.table.setItem(row, 12, _numeric_item(legend_potential, "%"))

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(0, 44)
        self.table.setColumnWidth(2, max(140, self.table.columnWidth(2)))
        self.table.setColumnWidth(5, max(560, self.table.columnWidth(5)))
        self.table.setColumnWidth(6, max(130, self.table.columnWidth(6)))
        self.table.setColumnWidth(7, max(120, self.table.columnWidth(7)))
        self.table.setSortingEnabled(True)
