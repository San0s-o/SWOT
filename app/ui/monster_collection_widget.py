from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
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


class MonsterCollectionWidget(QWidget):
    """Small-icon collection overview for owned and missing awakened monsters."""

    _ICON_SIZE = 30
    _ICON_PAD = 4
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
        missing_awakened = self._missing_awakened_monsters(set(owned_by_master.keys()))

        self._summary_label.setText(
            tr(
                "collection.summary",
                owned=len(owned_awakened_6),
                missing=len(missing_awakened),
            )
        )

        self._add_icon_section(
            title=tr("collection.section_owned"),
            monsters=owned_awakened_6,
            owned_counts=owned_by_master,
        )
        self._add_icon_section(
            title=tr("collection.section_missing"),
            monsters=missing_awakened,
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

    def _missing_awakened_monsters(self, owned_master_ids: set[int]) -> List[MonsterInfo]:
        if not self._monster_db:
            return []
        candidates: List[MonsterInfo] = []
        for info in self._monster_db.all_monsters():
            nat = int(info.natural_stars or 0)
            if nat < 2 or nat > 5:
                continue
            if int(info.awaken_level or 0) != 1:
                continue
            if not bool(info.can_awaken):
                continue
            if not bool(info.obtainable):
                continue
            if bool(info.homunculus):
                continue
            if int(info.com2us_id) in owned_master_ids:
                continue
            candidates.append(info)
        return self._sorted_collection_infos(candidates)

    @staticmethod
    def _sorted_collection_infos(items: Iterable[MonsterInfo]) -> List[MonsterInfo]:
        return sorted(
            list(items),
            key=lambda x: (
                -int(x.natural_stars or 0),
                str(x.name or "").lower(),
                str(x.element or "").lower(),
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

    def _icon_label_for(self, info: MonsterInfo, owned_count: int) -> QLabel:
        lbl = QLabel()
        icon_px = dp(self._ICON_SIZE)
        pad_px = dp(self._ICON_PAD)
        lbl.setFixedSize(icon_px + pad_px * 2, icon_px + pad_px * 2)
        lbl.setAlignment(Qt.AlignCenter)
        lbl.setStyleSheet(
            f"background: {_theme.C['bg_mid']}; border: 1px solid {_theme.C['card_border']}; border-radius: {dp(4)}px;"
        )

        pix = self._monster_pixmap(info)
        if pix is not None and not pix.isNull():
            lbl.setPixmap(pix.scaled(icon_px, icon_px, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        parts = [
            str(info.name or f"#{int(info.com2us_id or 0)}"),
            str(info.element or "Unknown"),
            tr("collection.tooltip_nat", stars=int(info.natural_stars or 0)),
        ]
        if owned_count > 1:
            parts.append(tr("collection.tooltip_copies", count=int(owned_count)))
        lbl.setToolTip(" | ".join(parts))
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
