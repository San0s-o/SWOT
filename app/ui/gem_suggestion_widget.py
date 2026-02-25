"""Gem swap suggestion analysis widget.

Shows runes at +12 or higher that have no gem yet and suggests the
best substat to replace based on efficiency gain and account-wide gem
patterns (which stats the player has already been gemming in).

Gem inventory is read from AccountData.craft_stuff when available.
"""
from __future__ import annotations

from collections import Counter
from typing import Callable, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QPainter,
    QStandardItem,
    QStandardItemModel,
    QTextDocument,
)

from app.domain.models import AccountData, Rune
from app.domain.presets import EFFECT_ID_TO_MAINSTAT_KEY, SET_NAMES
from app.engine.efficiency import (
    rune_efficiency,
    rune_efficiency_gem_swap,
)
from app.i18n import tr
from app.ui.dpi import dp
from app.ui.widgets.selection_combos import _UnitSearchComboBox

# All valid substat effect IDs
_ALL_STAT_IDS = {1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12}

# ---------------------------------------------------------------------------
# Enchanted gem craft_stuff ID mapping
#
# Maps stat_id â†’ (hero_craft_stuff_id, legend_craft_stuff_id).
# IDs are sourced from community data (SWEX / SWOP references) and may need
# updating if the game changes its internal item IDs.  The hero ID gives +hero
# gem values; legend gives +legend values.  Both are counted as "available".
#
# To verify/update these IDs: export your SW JSON via SWEX, check the
# "craft_stuff" array, and match quantities against your in-game gem storage.
# ---------------------------------------------------------------------------
_GEM_CRAFT_IDS: dict[int, tuple[int, int]] = {
    # stat_id: (hero_craft_id, legend_craft_id)
    1:  (10001, 10002),   # HP flat
    2:  (10003, 10004),   # HP%
    3:  (10005, 10006),   # ATK flat
    4:  (10007, 10008),   # ATK%
    5:  (10009, 10010),   # DEF flat
    6:  (10011, 10012),   # DEF%
    8:  (10013, 10014),   # SPD
    9:  (10015, 10016),   # CR
    10: (10017, 10018),   # CD
    11: (10019, 10020),   # RES
    12: (10021, 10022),   # ACC
}

# Newer SWEX snapshots expose rune craft inventory via craft_type_id values
# (e.g. in rune_craft_item_list). We can infer gem stat from the last digits.
_GEM_SUFFIX_BASE_BY_STAT_ID: dict[int, int] = {
    1: 100,   # HP flat
    2: 200,   # HP%
    3: 300,   # ATK flat
    4: 400,   # ATK%
    5: 500,   # DEF flat
    6: 600,   # DEF%
    8: 800,   # SPD
    9: 900,   # CR
    10: 1000,  # CD
    11: 1100,  # RES
    12: 1200,  # ACC
}
_GEM_QUALITY_HERO = {4, 14}
_GEM_QUALITY_LEGEND = {5, 15}
_GEM_UNIVERSAL_SET_IDS = {99}


def _gem_count_breakdown_for_stat(
    craft_stuff: dict[int, int],
    stat_id: int,
    set_id: int | None = None,
) -> tuple[int, int]:
    """Return (hero_count, legend_count) for a stat, optionally scoped to a set."""
    hero = 0
    legend = 0

    # Legacy craft_stuff IDs (10001..10022)
    ids = _GEM_CRAFT_IDS.get(stat_id)
    if ids:
        hero_id, legend_id = ids
        hero += int(craft_stuff.get(hero_id, 0) or 0)
        legend += int(craft_stuff.get(legend_id, 0) or 0)

    # Modern rune craft type IDs (e.g. 160804, 241005, ...)
    base = _GEM_SUFFIX_BASE_BY_STAT_ID.get(int(stat_id or 0))
    if base:
        hero_suffixes = {base + q for q in _GEM_QUALITY_HERO}
        legend_suffixes = {base + q for q in _GEM_QUALITY_LEGEND}
        valid_suffixes = hero_suffixes | legend_suffixes
        allowed_sets: set[int] | None = None
        target_set = int(set_id or 0)
        if target_set > 0:
            allowed_sets = {target_set} | _GEM_UNIVERSAL_SET_IDS
        for craft_id, qty in (craft_stuff or {}).items():
            cid = int(craft_id or 0)
            if cid <= 0:
                continue
            suffix = cid % 10000
            if suffix not in valid_suffixes:
                continue
            if allowed_sets is not None:
                set_prefix = cid // 10000
                if set_prefix not in allowed_sets:
                    continue
            if suffix in hero_suffixes:
                hero += int(qty or 0)
            elif suffix in legend_suffixes:
                legend += int(qty or 0)

    return int(hero), int(legend)


def _gem_count_for_stat(craft_stuff: dict[int, int], stat_id: int, set_id: int | None = None) -> int:
    """Return total enchanted gem count (hero + legend) for a stat/set pair."""
    hero, legend = _gem_count_breakdown_for_stat(craft_stuff, stat_id, set_id=set_id)
    return int(hero + legend)


# ---------------------------------------------------------------------------
# Availability sentinel values used as filter keys
# ---------------------------------------------------------------------------
_AVAIL_UNKNOWN = -1   # craft_stuff not in JSON
_AVAIL_ZERO = 0       # craft_stuff imported, but 0 gems of this type
# positive integer = actual count


# ---------------------------------------------------------------------------
# Small helpers (mirrors of rune_optimization_widget helpers)
# ---------------------------------------------------------------------------

class _SortableNumericItem(QTableWidgetItem):
    def __lt__(self, other) -> bool:
        if isinstance(other, QTableWidgetItem):
            try:
                return float(self.data(Qt.UserRole)) < float(other.data(Qt.UserRole))
            except Exception:
                pass
        return super().__lt__(other)


def _numeric_item(value: float, suffix: str = "") -> QTableWidgetItem:
    text = f"{value:+.2f}{suffix}" if suffix else f"{value:+.2f}"
    item = _SortableNumericItem(text)
    item.setData(Qt.UserRole, float(value))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return item


def _numeric_item_plain(value: float, suffix: str = "") -> QTableWidgetItem:
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


def _eff_gain_item(eff: float, gain: float) -> QTableWidgetItem:
    item = _SortableNumericItem(f"{eff:.2f}% ({gain:+.2f}%)")
    item.setData(Qt.UserRole, float(gain))
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if gain > 0:
        item.setForeground(QColor("#2ecc71"))
    elif gain < 0:
        item.setForeground(QColor("#e74c3c"))
    return item


def _stat_name(eff_id: int) -> str:
    return str(EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"Eff {int(eff_id or 0)}"))


def _set_name_for(rune: Rune) -> str:
    sid = int(rune.set_id or 0)
    return str(SET_NAMES.get(sid, f"Set {sid}"))


_QUALITY_BASE_NAME = {
    1: "Normal", 2: "Magic", 3: "Rare", 4: "Hero", 5: "Legend", 6: "Legend",
    11: "Normal", 12: "Magic", 13: "Rare", 14: "Hero", 15: "Legend", 16: "Legend",
}
_ANCIENT_CLASS_IDS = {11, 12, 13, 14, 15, 16}


def _quality_text(rune: Rune) -> str:
    origin = int(getattr(rune, "origin_class", 0) or 0)
    cls_id = origin if origin else int(rune.rune_class or 0)
    base = _QUALITY_BASE_NAME.get(cls_id, f"{tr('ui.class_short')} {cls_id}")
    if cls_id in _ANCIENT_CLASS_IDS:
        return tr("rune_opt.quality_ancient", quality=base)
    return base


def _substats_text(rune: Rune) -> str:
    parts: list[str] = []
    for sec in (rune.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0) if len(sec) > 0 else 0
        base = int(sec[1] or 0) if len(sec) > 1 else 0
        grind = int(sec[3] or 0) if len(sec) > 3 else 0
        total = base + grind
        token = f"{_stat_name(eff_id)}+{total}"
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


def _icon_item(icon: QIcon, sort_value: int, tooltip: str = "") -> QTableWidgetItem:
    item = _SortableNumericItem("")
    if not icon.isNull():
        item.setIcon(icon)
    item.setData(Qt.UserRole, int(sort_value))
    item.setTextAlignment(Qt.AlignCenter)
    if tooltip:
        item.setToolTip(tooltip)
    return item


def _rune_marker_item(
    icon: QIcon,
    rune_id: int,
    option_idx: int,
    option_total: int,
) -> QTableWidgetItem:
    item = _SortableNumericItem(f"{int(rune_id)} [{int(option_idx)}/{int(option_total)}]")
    if not icon.isNull():
        item.setIcon(icon)
    item.setData(Qt.UserRole, int(rune_id))
    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    item.setToolTip(f"{tr('ui.rune_id')}: {int(rune_id)}")
    return item


class _RichTextDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        options = QStyleOptionViewItem(option)
        self.initStyleOption(options, index)
        style = options.widget.style() if options.widget else QApplication.style()
        doc = QTextDocument()
        doc.setDefaultFont(options.font)
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
                ctx.palette.setColor(
                    QPalette.ColorRole.Text, options.palette.highlightedText().color()
                )
            doc.documentLayout().draw(painter, ctx)
        finally:
            painter.restore()

    def sizeHint(self, option: QStyleOptionViewItem, index):
        doc = QTextDocument()
        doc.setDefaultFont(option.font)
        doc.setHtml(str(index.data() or ""))
        doc.setTextWidth(float(max(0, option.rect.width())))
        return doc.size().toSize()


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _has_gem(rune: Rune) -> bool:
    return any(len(s) >= 3 and int(s[2] or 0) == 1 for s in (rune.sec_eff or []))


def _find_top_gem_swaps(
    rune: Rune,
    limit: int = 3,
) -> list[Tuple[int, int, float, float, float, float, float, float]]:
    """Find top gem swap options for a rune that has no gem yet.

    Returns entries of
    ``(sub_idx, new_eff_id, swap_eff, hero_eff, legend_eff, swap_gain, hero_gain, legend_gain)``
    sorted by legend_gain desc, then hero_gain desc.
    """
    subs = rune.sec_eff or []
    if not subs:
        return []

    base_eff = float(rune_efficiency(rune))
    mainstat_id = int(rune.pri_eff[0]) if rune.pri_eff else 0

    options: list[Tuple[int, int, float, float, float, float, float, float]] = []

    for sub_idx in range(len(subs)):
        sub = subs[sub_idx]
        if not sub:
            continue
        current_sub_id = int(sub[0] or 0)
        # Stats in OTHER substats â†’ can't create a duplicate
        other_ids = {
            int(subs[j][0] or 0)
            for j in range(len(subs))
            if j != sub_idx and subs[j]
        }
        excluded = other_ids | {mainstat_id}
        candidates = _ALL_STAT_IDS - excluded

        for new_id in candidates:
            if new_id == current_sub_id:
                continue
            swap_eff = float(rune_efficiency_gem_swap(rune, sub_idx, new_id, None))
            hero_eff = float(rune_efficiency_gem_swap(rune, sub_idx, new_id, "hero"))
            legend_eff = float(rune_efficiency_gem_swap(rune, sub_idx, new_id, "legend"))
            gain_swap = swap_eff - base_eff
            gain_hero = hero_eff - base_eff
            gain_legend = legend_eff - base_eff

            options.append(
                (
                    sub_idx,
                    new_id,
                    swap_eff,
                    hero_eff,
                    legend_eff,
                    gain_swap,
                    gain_hero,
                    gain_legend,
                )
            )

    options.sort(key=lambda x: (x[7], x[6]), reverse=True)
    return options[: max(1, int(limit or 1))]


def _analyze_gem_patterns(runes: list[Rune]) -> Counter:
    """Count how often each stat ID was used as a gem (enchant_flag == 1)."""
    counts: Counter = Counter()
    for rune in runes:
        for sec in (rune.sec_eff or []):
            if not sec or len(sec) < 3:
                continue
            if int(sec[2] or 0) == 1:
                eff_id = int(sec[0] or 0)
                if eff_id > 0:
                    counts[eff_id] += 1
    return counts


# ---------------------------------------------------------------------------
# Widget
# ---------------------------------------------------------------------------

# Filter sentinel values for the "gem availability" combo
_FILTER_AVAIL_ALL = 0
_FILTER_AVAIL_HAVE = 1    # count > 0
_FILTER_AVAIL_MISSING = 2  # count == 0  (only when craft_stuff imported)


class GemSuggestionWidget(QWidget):
    """Displays runes at +12 or higher that have no gem and suggests the
    best substat swap, drawing on account-wide gem usage patterns and the
    player's current enchanted gem inventory (from craft_stuff in the JSON)."""

    # Column indices
    _COL_ICON = 0
    _COL_SET = 1
    _COL_QUALITY = 2
    _COL_SLOT = 3
    _COL_UPGRADE = 4
    _COL_SUBSTATS = 5
    _COL_MONSTER = 6
    _COL_CURRENT_EFF = 7
    _COL_SWAP = 8
    _COL_ACCT_FREQ = 9
    _COL_INVENTORY = 10
    _COL_SWAP_ONLY = 11
    _COL_HERO_GRIND = 12
    _COL_LEGEND_GRIND = 13
    _NUM_COLS = 14

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
        self._swap_combo_states: dict[QComboBox, dict] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        layout.setSpacing(dp(6))

        # Account pattern summary
        self.lbl_pattern = QLabel("")
        self.lbl_pattern.setWordWrap(True)
        layout.addWidget(self.lbl_pattern)

        # Filter bar
        top = QHBoxLayout()
        self.lbl_info = QLabel("")
        top.addWidget(self.lbl_info)
        top.addStretch(1)

        self.lbl_filter_set = QLabel("")
        top.addWidget(self.lbl_filter_set)
        self.combo_filter_set = QComboBox()
        self.combo_filter_set.setMinimumWidth(dp(150))
        self.combo_filter_set.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_set)

        self.lbl_filter_slot = QLabel("")
        top.addWidget(self.lbl_filter_slot)
        self.combo_filter_slot = QComboBox()
        self.combo_filter_slot.setMinimumWidth(dp(90))
        self.combo_filter_slot.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_slot)

        self.lbl_filter_monster = QLabel("")
        top.addWidget(self.lbl_filter_monster)
        self.combo_filter_monster = _UnitSearchComboBox()
        self.combo_filter_monster.setMinimumWidth(dp(200))
        self.combo_filter_monster.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_monster)

        # Gem availability filter
        self.lbl_filter_avail = QLabel("")
        top.addWidget(self.lbl_filter_avail)
        self.combo_filter_avail = QComboBox()
        self.combo_filter_avail.setMinimumWidth(dp(170))
        self.combo_filter_avail.currentIndexChanged.connect(self._on_filters_changed)
        top.addWidget(self.combo_filter_avail)

        self.btn_reset_filters = QPushButton("")
        self.btn_reset_filters.clicked.connect(self._on_reset_filters)
        top.addWidget(self.btn_reset_filters)
        top.addStretch(1)
        layout.addLayout(top)

        # Main table
        self.table = QTableWidget(0, self._NUM_COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().sectionResized.connect(
            lambda *_: self._fit_swap_combo_widths()
        )
        self.table.setItemDelegateForColumn(self._COL_SUBSTATS, _RichTextDelegate(self.table))
        self.table.setItemDelegateForColumn(self._COL_SWAP, _RichTextDelegate(self.table))
        self.table.setItemDelegateForColumn(self._COL_INVENTORY, _RichTextDelegate(self.table))
        layout.addWidget(self.table, 1)

        self.retranslate()

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def retranslate(self) -> None:
        self.lbl_filter_set.setText(tr("rune_opt.filter_set"))
        self.lbl_filter_slot.setText(tr("rune_opt.filter_slot"))
        self.lbl_filter_monster.setText(tr("rune_opt.filter_monster"))
        self.lbl_filter_avail.setText(tr("gem_sug.filter_avail_label"))
        self.btn_reset_filters.setText(tr("rune_opt.filter_reset"))
        self._rebuild_avail_combo()
        self.table.setHorizontalHeaderLabels(
            [
                tr("rune_opt.col.symbol"),
                tr("rune_opt.col.set"),
                tr("rune_opt.col.quality"),
                tr("rune_opt.col.slot"),
                tr("rune_opt.col.upgrade"),
                tr("rune_opt.col.substats"),
                tr("rune_opt.col.monster"),
                tr("rune_opt.col.current_eff"),
                tr("gem_sug.col.swap"),
                tr("gem_sug.col.account_freq"),
                tr("gem_sug.col.inventory"),
                tr("gem_sug.col.swap_only"),
                tr("gem_sug.col.hero_grind"),
                tr("gem_sug.col.legend_grind"),
            ]
        )
        self.refresh()

    def set_account(self, account: Optional[AccountData]) -> None:
        self._account = account
        self.refresh()

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def _rebuild_avail_combo(self) -> None:
        current = int(self.combo_filter_avail.currentData() or 0)
        self.combo_filter_avail.blockSignals(True)
        self.combo_filter_avail.clear()
        self.combo_filter_avail.addItem(tr("rune_opt.filter_all"), _FILTER_AVAIL_ALL)
        self.combo_filter_avail.addItem(tr("gem_sug.filter_avail_have"), _FILTER_AVAIL_HAVE)
        self.combo_filter_avail.addItem(tr("gem_sug.filter_avail_missing"), _FILTER_AVAIL_MISSING)
        idx = self.combo_filter_avail.findData(current)
        self.combo_filter_avail.setCurrentIndex(idx if idx >= 0 else 0)
        self.combo_filter_avail.blockSignals(False)

    def _on_filters_changed(self, _index: int) -> None:
        if self._updating_filters:
            return
        self.refresh()

    def _on_reset_filters(self) -> None:
        self._updating_filters = True
        self.combo_filter_set.blockSignals(True)
        self.combo_filter_slot.blockSignals(True)
        self.combo_filter_monster.blockSignals(True)
        self.combo_filter_avail.blockSignals(True)
        try:
            self.combo_filter_set.setCurrentIndex(0)
            self.combo_filter_slot.setCurrentIndex(0)
            self.combo_filter_avail.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.setCurrentIndex(0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._reset_search_field()
        finally:
            self.combo_filter_set.blockSignals(False)
            self.combo_filter_slot.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self.combo_filter_avail.blockSignals(False)
            self._updating_filters = False
        self.refresh()

    def _populate_filters(self, runes: list[Rune]) -> None:
        current_set = int(self.combo_filter_set.currentData() or 0)
        current_slot = int(self.combo_filter_slot.currentData() or 0)
        current_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        set_ids = sorted({int(r.set_id or 0) for r in runes if int(r.set_id or 0) > 0})
        slot_nos = sorted({int(r.slot_no or 0) for r in runes if int(r.slot_no or 0) > 0})

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
            idx = self.combo_filter_set.findData(current_set)
            self.combo_filter_set.setCurrentIndex(idx if idx >= 0 else 0)

            self.combo_filter_slot.clear()
            self.combo_filter_slot.addItem(tr("rune_opt.filter_all"), 0)
            for slot in slot_nos:
                self.combo_filter_slot.addItem(str(slot), slot)
            idx = self.combo_filter_slot.findData(current_slot)
            self.combo_filter_slot.setCurrentIndex(idx if idx >= 0 else 0)

            self.combo_filter_monster.set_filter_suspended(True)
            self.combo_filter_monster.set_source_model(monster_model)
            idx = self.combo_filter_monster.findData(current_uid, role=Qt.UserRole)
            self.combo_filter_monster.setCurrentIndex(idx if idx >= 0 else 0)
            self.combo_filter_monster.set_filter_suspended(False)
            self.combo_filter_monster._sync_line_edit_to_current()
        finally:
            self.combo_filter_set.blockSignals(False)
            self.combo_filter_slot.blockSignals(False)
            self.combo_filter_monster.blockSignals(False)
            self._updating_filters = False

    @staticmethod
    def _swap_label_from_option(
        rune: Rune,
        option: Tuple[int, int, float, float, float, float, float, float],
        include_rank: tuple[int, int] | None = None,
    ) -> str:
        sub_idx, new_id, _swap_eff, _hero_eff, _legend_eff, _swap_gain, _hero_gain, legend_gain = option
        old_id = int(rune.sec_eff[sub_idx][0]) if int(sub_idx) < len(rune.sec_eff or []) else 0
        text = f"{_stat_name(old_id)} -> {_stat_name(new_id)} ({legend_gain:+.2f}%)"
        if include_rank is not None:
            idx, total = include_rank
            text = f"{idx}/{total} - {text}"
        return text

    def _find_row_by_rune_id(self, rune_id: int) -> int:
        target = int(rune_id)
        for row in range(self.table.rowCount()):
            item = self.table.item(row, self._COL_ICON)
            if item is None:
                continue
            if int(item.data(Qt.UserRole) or 0) == target:
                return row
        return -1

    def _apply_option_to_row(self, row: int, state: dict, option_index: int) -> None:
        options = list(state.get("options") or [])
        if not options:
            return
        idx = max(0, min(int(option_index), len(options) - 1))
        state["current_index"] = idx
        option = options[idx]
        (
            sub_idx,
            new_id,
            swap_eff,
            hero_eff,
            legend_eff,
            swap_gain,
            hero_gain,
            legend_gain,
        ) = option["swap"]
        avail = int(option["avail"])
        hero_avail = int(option["hero_avail"])
        legend_avail = int(option["legend_avail"])
        rune = state["rune"]
        rune_id = int(rune.rune_id or 0)
        total_options = int(state.get("total_options") or len(options))

        removed_name = _stat_name(int(rune.sec_eff[sub_idx][0]))
        added_name = _stat_name(new_id)

        icon = self._rune_set_icon_fn(int(rune.set_id or 0)) if self._rune_set_icon_fn else QIcon()
        self.table.setItem(
            row,
            self._COL_ICON,
            _rune_marker_item(
                icon=icon,
                rune_id=rune_id,
                option_idx=idx + 1,
                option_total=total_options,
            ),
        )

        swap_html = (
            f"<span style='color:#e74c3c'>{removed_name}</span>"
            f"<span style='color:#95a5a6'> -> </span>"
            f"<span style='color:#2ecc71'>{added_name}</span>"
        )
        swap_item = QTableWidgetItem(swap_html)
        swap_item.setData(Qt.UserRole, f"{removed_name} -> {added_name}")
        swap_item.setTextAlignment(Qt.AlignCenter)
        self.table.setItem(row, self._COL_SWAP, swap_item)

        freq = int(state["gem_counts"].get(new_id, 0))
        freq_item = _SortableNumericItem(f"{freq}x")
        freq_item.setData(Qt.UserRole, freq)
        freq_item.setTextAlignment(Qt.AlignCenter)
        if freq > 0:
            freq_item.setForeground(QColor("#2ecc71"))
        self.table.setItem(row, self._COL_ACCT_FREQ, freq_item)

        inv_item = self._make_inventory_item(
            avail=avail,
            craft_imported=bool(state["craft_imported"]),
            hero_avail=hero_avail,
            legend_avail=legend_avail,
        )
        self.table.setItem(row, self._COL_INVENTORY, inv_item)

        self.table.setItem(row, self._COL_SWAP_ONLY, _eff_gain_item(swap_eff, swap_gain))
        self.table.setItem(row, self._COL_HERO_GRIND, _eff_gain_item(hero_eff, hero_gain))
        self.table.setItem(row, self._COL_LEGEND_GRIND, _eff_gain_item(legend_eff, legend_gain))

    def _on_swap_option_changed(self, _index: int) -> None:
        combo = self.sender()
        if not isinstance(combo, QComboBox):
            return
        state = self._swap_combo_states.get(combo)
        if not state:
            return
        rune = state.get("rune")
        if rune is None:
            return
        row = self._find_row_by_rune_id(int(rune.rune_id or 0))
        if row < 0:
            return
        idx = int(combo.currentData() or 0)
        self._apply_option_to_row(row, state, idx)

    def _fit_swap_combo_widths(self) -> None:
        width = max(80, int(self.table.columnWidth(self._COL_SWAP)) - 8)
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, self._COL_SWAP)
            if isinstance(widget, QComboBox):
                widget.setFixedWidth(width)

    # ------------------------------------------------------------------
    # Main refresh
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        if not self._account:
            self.lbl_info.setText(tr("rune_opt.hint_no_import"))
            self.lbl_pattern.setText("")
            self._populate_filters([])
            self.table.setSortingEnabled(True)
            return

        account_runes = list(self._account.runes)
        craft_stuff = self._account.craft_stuff
        craft_imported = self._account.craft_stuff_imported

        # --- Account gem pattern analysis ---
        gem_counts = _analyze_gem_patterns(account_runes)
        total_gemmed = sum(gem_counts.values())
        if gem_counts:
            top = gem_counts.most_common(6)
            parts = [f"{_stat_name(eid)}: {cnt}x" for eid, cnt in top]
            self.lbl_pattern.setText(
                tr("gem_sug.account_pattern", stats=", ".join(parts), total=total_gemmed)
            )
        else:
            self.lbl_pattern.setText(tr("gem_sug.account_pattern_none"))

        # --- Candidate runes: +12, no gem ---
        all_candidates = [
            r for r in account_runes
            if int(r.upgrade_curr or 0) >= 12 and not _has_gem(r)
        ]
        all_candidates.sort(key=lambda r: rune_efficiency(r), reverse=True)
        self._populate_filters(all_candidates)

        if not all_candidates:
            self.lbl_info.setText(tr("gem_sug.hint_no_rows"))
            self.table.setSortingEnabled(True)
            return

        # Pre-compute top swap options and availability for all candidates
        # (avail = _AVAIL_UNKNOWN if not imported, else set-specific gem count >= 0)
        swap_data: list[tuple] = []
        for rune in all_candidates:
            options = _find_top_gem_swaps(rune, limit=3)
            option_rows: list[dict] = []
            for swap in options:
                _, new_id, *_ = swap
                if craft_imported:
                    hero_avail, legend_avail = _gem_count_breakdown_for_stat(
                        craft_stuff,
                        new_id,
                        set_id=int(rune.set_id or 0),
                    )
                    avail = int(hero_avail + legend_avail)
                else:
                    hero_avail = 0
                    legend_avail = 0
                    avail = _AVAIL_UNKNOWN
                option_rows.append(
                    {
                        "swap": swap,
                        "avail": avail,
                        "hero_avail": hero_avail,
                        "legend_avail": legend_avail,
                    }
                )
            swap_data.append((rune, option_rows))

        # --- Apply filters ---
        selected_set = int(self.combo_filter_set.currentData() or 0)
        selected_slot = int(self.combo_filter_slot.currentData() or 0)
        selected_uid = int(self.combo_filter_monster.currentData(Qt.UserRole) or 0)
        selected_avail = int(self.combo_filter_avail.currentData() or 0)

        filtered: list[tuple] = []
        for rune, options in swap_data:
            if selected_set > 0 and int(rune.set_id or 0) != selected_set:
                continue
            if selected_slot > 0 and int(rune.slot_no or 0) != selected_slot:
                continue
            if selected_uid > 0 and int(rune.occupied_id or 0) != selected_uid:
                continue
            display_index = 0
            if selected_avail == _FILTER_AVAIL_HAVE:
                found = -1
                for idx, opt in enumerate(options or []):
                    if int(opt["avail"]) > 0:
                        found = idx
                        break
                if found < 0:
                    continue
                display_index = found
            elif selected_avail == _FILTER_AVAIL_MISSING:
                found = -1
                for idx, opt in enumerate(options or []):
                    if int(opt["avail"]) == _AVAIL_ZERO:
                        found = idx
                        break
                if found < 0:
                    continue
                display_index = found
            filtered.append((rune, options, display_index))

        if not filtered:
            self.lbl_info.setText(tr("gem_sug.hint_no_filter_rows"))
            self.table.setSortingEnabled(True)
            return

        self.lbl_info.setText(
            tr("gem_sug.count_filtered", shown=len(filtered), total=len(all_candidates))
        )
        self.table.setRowCount(len(filtered))
        self._swap_combo_states.clear()

        for row, (rune, options, display_index) in enumerate(filtered):
            current_eff = float(rune_efficiency(rune))
            set_id = int(rune.set_id or 0)
            icon = self._rune_set_icon_fn(set_id) if self._rune_set_icon_fn else QIcon()
            monster_name = ""
            if int(rune.occupied_type or 0) == 1 and self._monster_name_fn:
                monster_name = self._monster_name_fn(int(rune.occupied_id or 0))

            # Columns 0â€“7: basic rune info
            self.table.setItem(
                row, self._COL_ICON,
                _rune_marker_item(
                    icon=icon,
                    rune_id=int(rune.rune_id or 0),
                    option_idx=1,
                    option_total=max(1, len(options)),
                ),
            )
            self.table.setItem(row, self._COL_SET, QTableWidgetItem(_set_name_for(rune)))
            self.table.setItem(row, self._COL_QUALITY, QTableWidgetItem(_quality_text(rune)))
            self.table.setItem(row, self._COL_SLOT, _int_item(int(rune.slot_no or 0)))
            self.table.setItem(row, self._COL_UPGRADE, _int_item(int(rune.upgrade_curr or 0)))
            sub_item = QTableWidgetItem(_substats_html(rune))
            sub_item.setData(Qt.UserRole, _substats_text(rune))
            sub_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.table.setItem(row, self._COL_SUBSTATS, sub_item)
            self.table.setItem(row, self._COL_MONSTER, QTableWidgetItem(monster_name))
            self.table.setItem(row, self._COL_CURRENT_EFF, _numeric_item_plain(current_eff, "%"))

            if not options:
                for col in range(self._COL_SWAP, self._NUM_COLS):
                    self.table.setItem(row, col, QTableWidgetItem("-"))
                continue

            combo = QComboBox(self.table)
            for idx, opt in enumerate(options, start=1):
                label = self._swap_label_from_option(rune, opt["swap"], include_rank=(idx, len(options)))
                combo.addItem(label, idx - 1)
            start_index = max(0, min(int(display_index), len(options) - 1))
            combo.setCurrentIndex(start_index)
            self.table.setCellWidget(row, self._COL_SWAP, combo)
            self._swap_combo_states[combo] = {
                "rune": rune,
                "options": options,
                "craft_imported": craft_imported,
                "gem_counts": gem_counts,
                "total_options": len(options),
                "current_index": start_index,
            }
            combo.currentIndexChanged.connect(self._on_swap_option_changed)
            self._apply_option_to_row(row, self._swap_combo_states[combo], start_index)

        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(self._COL_ICON, 170)
        self.table.setColumnWidth(
            self._COL_QUALITY, max(140, self.table.columnWidth(self._COL_QUALITY))
        )
        self.table.setColumnWidth(
            self._COL_SUBSTATS, max(440, self.table.columnWidth(self._COL_SUBSTATS))
        )
        self.table.setColumnWidth(
            self._COL_MONSTER, max(120, self.table.columnWidth(self._COL_MONSTER))
        )
        self.table.setColumnWidth(
            self._COL_SWAP, max(230, self.table.columnWidth(self._COL_SWAP))
        )
        self.table.setColumnWidth(
            self._COL_SWAP_ONLY, max(165, self.table.columnWidth(self._COL_SWAP_ONLY))
        )
        self.table.setColumnWidth(
            self._COL_HERO_GRIND, max(165, self.table.columnWidth(self._COL_HERO_GRIND))
        )
        self.table.setColumnWidth(
            self._COL_LEGEND_GRIND, max(175, self.table.columnWidth(self._COL_LEGEND_GRIND))
        )
        self._fit_swap_combo_widths()
        self.table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_inventory_item(
        avail: int,
        craft_imported: bool,
        hero_avail: int = 0,
        legend_avail: int = 0,
    ) -> QTableWidgetItem:
        """Create a table item showing gem inventory status.

        Colour coding:
          green  = has >=1 gem of this type
          red    = craft_stuff imported but 0 gems
          gray   = craft_stuff not in JSON (unknown)
        """
        if not craft_imported or avail == _AVAIL_UNKNOWN:
            item = _SortableNumericItem(tr("gem_sug.inventory_unknown"))
            item.setData(Qt.UserRole, -1)
            item.setForeground(QColor("#95a5a6"))   # gray
        elif avail > 0:
            item = _SortableNumericItem(
                "<span style='color:#b36bff'>{}</span>"
                "<span style='color:#95a5a6'> / </span>"
                "<span style='color:#f1c40f'>{}</span>"
                "<span style='color:#95a5a6'> ({}x)</span>".format(
                    int(hero_avail), int(legend_avail), int(avail)
                )
            )
            item.setData(Qt.UserRole, avail)
        else:
            item = _SortableNumericItem(
                "<span style='color:#b36bff'>{}</span>"
                "<span style='color:#95a5a6'> / </span>"
                "<span style='color:#f1c40f'>{}</span>".format(
                    int(hero_avail), int(legend_avail)
                )
            )
            item.setData(Qt.UserRole, 0)
        item.setTextAlignment(Qt.AlignCenter)
        item.setToolTip(tr("gem_sug.inventory_tooltip"))
        return item

