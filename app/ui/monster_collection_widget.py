from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import AccountData
from app.domain.monster_db import MonsterDB, MonsterInfo
from app.i18n import tr
from app.ui import theme as _theme
from app.ui.dpi import dp


class _MonsterIcon(QWidget):
    """Icon widget that optionally renders a count badge for duplicates."""

    def __init__(self, pixmap: Optional[QPixmap], owned_count: int, icon_px: int, pad_px: int, tooltip: str):
        super().__init__()
        self._pixmap = pixmap
        self._count = owned_count
        self._icon_px = icon_px
        self._pad_px = pad_px
        size = icon_px + pad_px * 2
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Background
        p.fillRect(self.rect(), QColor("#1e1e2e"))
        p.setPen(QColor("#3a3a5a"))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), self._pad_px, self._pad_px)

        # Icon
        if self._pixmap and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                self._icon_px, self._icon_px,
                Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)

        # Badge for duplicates
        if self._count > 1:
            badge_r = max(8, self._icon_px // 4)
            bx = self.width() - badge_r - 1
            by = self.height() - badge_r - 1
            p.setBrush(QColor("#e07b00"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(bx - badge_r, by - badge_r, badge_r * 2, badge_r * 2)
            p.setPen(QColor("#ffffff"))
            font = QFont()
            font.setPixelSize(max(7, badge_r - 2))
            font.setBold(True)
            p.setFont(font)
            p.drawText(
                QRect(bx - badge_r, by - badge_r, badge_r * 2, badge_r * 2),
                Qt.AlignCenter,
                str(self._count),
            )

        p.end()


class MonsterCollectionWidget(QWidget):
    """Small-icon collection overview for owned and missing awakened monsters."""

    _ICON_SIZE = 44
    _ICON_PAD = 3
    _MAX_COLS = 18

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._monster_db: Optional[MonsterDB] = None
        self._assets_dir: Optional[Path] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        outer.setSpacing(dp(8))

        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(f"color: {_theme.C['text_dim']};")
        outer.addWidget(self._summary_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {_theme.C['card_border']}; border-radius: {dp(8)}px; background: {_theme.C['bg']}; }}"
        )
        outer.addWidget(self._scroll, 1)

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {_theme.C['bg']};")
        self._content = QVBoxLayout(self._container)
        self._content.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        self._content.setSpacing(dp(12))
        self._scroll.setWidget(self._container)

        self._rebuild()

    def set_context(self, account: Optional[AccountData], monster_db: MonsterDB, assets_dir: Path) -> None:
        self._account = account
        self._monster_db = monster_db
        self._assets_dir = Path(assets_dir)
        self._rebuild()

    def retranslate(self) -> None:
        self._rebuild()

    def _clear_content(self) -> None:
        while self._content.count():
            item = self._content.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _rebuild(self) -> None:
        self._clear_content()

        if not self._account or not self._monster_db:
            self._summary_label.setText(tr("collection.no_import"))
            hint = QLabel(tr("collection.no_import"))
            hint.setStyleSheet(f"color: {_theme.C['text_dim']};")
            hint.setAlignment(Qt.AlignLeft | Qt.AlignTop)
            self._content.addWidget(hint)
            self._content.addStretch(1)
            return

        owned_by_master = Counter(
            int(u.unit_master_id)
            for u in (self._account.units_by_id or {}).values()
            if int(getattr(u, "unit_master_id", 0) or 0) > 0
        )
        owned_awakened_6 = self._owned_6star_awakened_monsters()

        self._summary_label.setText(
            tr("collection.summary_owned", owned=len(owned_awakened_6))
        )

        self._add_icon_section(
            title=tr("collection.section_owned"),
            monsters=owned_awakened_6,
            owned_counts=owned_by_master,
        )
        self._content.addStretch(1)

    def _owned_6star_awakened_monsters(self) -> List[MonsterInfo]:
        if not self._account or not self._monster_db:
            return []
        by_master: Dict[int, MonsterInfo] = {}
        for unit in (self._account.units_by_id or {}).values():
            if int(getattr(unit, "unit_class", 0) or 0) < 6:
                continue
            mid = int(getattr(unit, "unit_master_id", 0) or 0)
            if mid <= 0:
                continue
            info = self._monster_db.get(mid)
            if info is None:
                continue
            if int(info.awaken_level or 0) <= 0:
                continue
            nat = int(info.natural_stars or 0)
            if nat <= 0:
                continue
            by_master[mid] = info
        return self._sorted_collection_infos(by_master.values())

    _ELEMENT_ORDER = {"fire": 0, "water": 1, "wind": 2, "light": 3, "dark": 4}

    @staticmethod
    def _sorted_collection_infos(items: Iterable[MonsterInfo]) -> List[MonsterInfo]:
        _elem = MonsterCollectionWidget._ELEMENT_ORDER
        return sorted(
            list(items),
            key=lambda x: (
                -int(x.natural_stars or 0),
                _elem.get(str(x.element or "").lower(), 99),
                str(x.name or "").lower(),
                int(x.com2us_id or 0),
            ),
        )

    def _add_icon_section(
        self,
        *,
        title: str,
        monsters: List[MonsterInfo],
        owned_counts: Counter[int],
    ) -> None:
        section = QFrame()
        section.setObjectName("CollectionSection")
        section.setStyleSheet(
            f"QFrame#CollectionSection {{ background: {_theme.C['card_bg']}; border: 1px solid {_theme.C['card_border']}; border-radius: {dp(8)}px; }}"
        )
        lay = QVBoxLayout(section)
        lay.setContentsMargins(dp(10), dp(10), dp(10), dp(10))
        lay.setSpacing(dp(8))

        hdr = QLabel(title)
        hdr.setStyleSheet(f"color: {_theme.C['text']}; font-weight: bold;")
        lay.addWidget(hdr)

        if not monsters:
            empty = QLabel(tr("collection.none"))
            empty.setStyleSheet(f"color: {_theme.C['text_dim']};")
            lay.addWidget(empty)
            self._content.addWidget(section)
            return

        by_nat: Dict[int, List[MonsterInfo]] = {}
        for info in monsters:
            nat = int(info.natural_stars or 0)
            by_nat.setdefault(nat, []).append(info)

        for nat in sorted(by_nat.keys(), reverse=True):
            row_label = QLabel(tr("collection.nat_group", stars=int(nat)))
            row_label.setStyleSheet(f"color: {_theme.C['text_dim']};")
            lay.addWidget(row_label)

            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(dp(4))
            grid.setVerticalSpacing(dp(4))

            for idx, info in enumerate(by_nat[nat]):
                r = idx // int(self._MAX_COLS)
                c = idx % int(self._MAX_COLS)
                grid.addWidget(self._icon_label_for(info, int(owned_counts.get(int(info.com2us_id), 0))), r, c)
            lay.addWidget(grid_host)

        self._content.addWidget(section)

    def _icon_label_for(self, info: MonsterInfo, owned_count: int) -> QWidget:
        icon_px = dp(self._ICON_SIZE)
        pad_px = dp(self._ICON_PAD)

        tooltip = str(info.name or f"#{int(info.com2us_id or 0)}")
        if owned_count > 1:
            tooltip += f" ({owned_count}×)"

        return _MonsterIcon(
            pixmap=self._monster_pixmap(info),
            owned_count=owned_count,
            icon_px=icon_px,
            pad_px=pad_px,
            tooltip=tooltip,
        )

    def _monster_pixmap(self, info: MonsterInfo) -> Optional[QPixmap]:
        if not self._assets_dir:
            return None
        rel = str(info.icon or "").strip()
        if not rel:
            return None
        p = (Path(self._assets_dir) / rel).resolve()
        if not p.exists():
            return None
        return QPixmap(str(p))
