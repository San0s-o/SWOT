from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import AccountData
from app.domain.monster_db import MonsterDB, MonsterInfo
from app.i18n import tr
from app.ui import theme as _theme
from app.ui.dpi import dp

# Element display order (Fire → Water → Wind → Light → Dark → rest)
_ELEMENT_ORDER: Dict[str, int] = {
    "Fire": 0,
    "Water": 1,
    "Wind": 2,
    "Light": 3,
    "Dark": 4,
}

_ICON_SIZE_BASE = 58   # logical px at 2K reference DPI


class MonsterCollectionWidget(QWidget):
    """Monster collection: owned awakened monsters, sorted by element & name."""

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
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: 1px solid {_theme.C['card_border']}; "
            f"border-radius: {dp(8)}px; background: {_theme.C['bg']}; }}"
        )
        outer.addWidget(self._scroll, 1)

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(120)
        self._resize_timer.timeout.connect(self._rebuild)

        self._container = QWidget()
        self._container.setStyleSheet(f"background: {_theme.C['bg']};")
        self._content = QVBoxLayout(self._container)
        self._content.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        self._content.setSpacing(dp(12))
        self._scroll.setWidget(self._container)

        self._rebuild()

    # -- dynamic column count --------------------------

    def _icon_cell_size(self) -> int:
        return dp(_ICON_SIZE_BASE) + dp(3) * 2 + dp(4)  # icon + 2×pad + spacing

    def _max_cols(self) -> int:
        vp = self._scroll.viewport()
        w = vp.width() if vp else self.width()
        # subtract container margins (2×8) and a small safety buffer
        available = w - dp(16) - dp(8)
        cols = max(1, available // self._icon_cell_size())
        return int(cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._account and self._monster_db:
            self._resize_timer.start()

    # -- public API ------------------------------------

    def set_context(self, account: Optional[AccountData], monster_db: MonsterDB, assets_dir: Path) -> None:
        self._account = account
        self._monster_db = monster_db
        self._assets_dir = Path(assets_dir)
        self._rebuild()

    def retranslate(self) -> None:
        self._rebuild()

    # -- internal --------------------------------------

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

        owned = self._owned_awakened_monsters()
        unique_count = len({info.com2us_id for info in owned})

        self._summary_label.setText(tr("collection.summary", owned=unique_count))

        self._add_icon_section(
            title=tr("collection.section_owned"),
            monsters=owned,
        )
        self._content.addStretch(1)

    def _owned_awakened_monsters(self) -> List[MonsterInfo]:
        """Return one MonsterInfo per owned unit (duplicates included), 6★ awakened."""
        if not self._account or not self._monster_db:
            return []
        result: List[MonsterInfo] = []
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
            if int(info.natural_stars or 0) <= 0:
                continue
            result.append(info)
        return _sort_monsters(result)

    def _add_icon_section(self, *, title: str, monsters: List[MonsterInfo]) -> None:
        section = QFrame()
        section.setObjectName("CollectionSection")
        section.setStyleSheet(
            f"QFrame#CollectionSection {{ background: {_theme.C['card_bg']}; "
            f"border: 1px solid {_theme.C['card_border']}; border-radius: {dp(8)}px; }}"
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

        # Group by nat stars, then render
        by_nat: Dict[int, List[MonsterInfo]] = {}
        for info in monsters:
            nat = int(info.natural_stars or 0)
            by_nat.setdefault(nat, []).append(info)

        max_cols = self._max_cols()

        for nat in sorted(by_nat.keys(), reverse=True):
            row_label = QLabel(tr("collection.nat_group", stars=int(nat)))
            row_label.setStyleSheet(f"color: {_theme.C['text_dim']};")
            lay.addWidget(row_label)

            grid_host = QWidget()
            grid = QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(dp(4))
            grid.setVerticalSpacing(dp(4))
            grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)

            for idx, info in enumerate(by_nat[nat]):
                r = idx // max_cols
                c = idx % max_cols
                grid.addWidget(self._icon_label_for(info), r, c)

            lay.addWidget(grid_host)

        self._content.addWidget(section)

    def _icon_label_for(self, info: MonsterInfo) -> QLabel:
        icon_px = dp(_ICON_SIZE_BASE)
        pad_px = dp(3)
        total = icon_px + pad_px * 2

        lbl = QLabel()
        lbl.setFixedSize(total, total)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f"background: {_theme.C['bg_mid']}; border: 1px solid {_theme.C['card_border']}; border-radius: {dp(4)}px;"
        )

        pix = self._monster_pixmap(info)
        if pix is not None and not pix.isNull():
            lbl.setPixmap(pix.scaled(icon_px, icon_px, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        lbl.setToolTip(str(info.name or f"#{int(info.com2us_id or 0)}"))
        return lbl

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


def _sort_monsters(items: Iterable[MonsterInfo]) -> List[MonsterInfo]:
    """Sort by nat stars (desc), element order, then name (asc)."""
    return sorted(
        list(items),
        key=lambda x: (
            -int(x.natural_stars or 0),
            _ELEMENT_ORDER.get(str(x.element or "").strip(), 99),
            str(x.name or "").lower(),
            int(x.com2us_id or 0),
        ),
    )
