from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QGridLayout, QPushButton,
)

from app.domain.models import AccountData, Unit, Rune, Artifact, compute_unit_stats
from app.domain.monster_db import MonsterDB
from app.ui.siege_cards_widget import MonsterCard, _icon_for
from app.i18n import tr


COLUMNS = 4


class RtaOverviewWidget(QWidget):
    """Shows all fully-equipped RTA monsters in a 4-column grid sorted by SPD.

    A row of speed-lead buttons at the top lets the user toggle different
    speed leads and see how the turn order changes.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._account: Optional[AccountData] = None
        self._monster_db: Optional[MonsterDB] = None
        self._assets_dir: Optional[Path] = None
        self._current_speed_lead_pct = 0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        # ── speed-lead button bar ────────────────────────────
        self._lead_bar = QHBoxLayout()
        self._lead_bar.setSpacing(4)
        self._lead_label = QLabel(tr("rta.spd_lead"))
        self._lead_label.setTextFormat(Qt.RichText)
        self._lead_bar.addWidget(self._lead_label)
        self._lead_bar.addStretch()
        outer.addLayout(self._lead_bar)

        # ── scrollable card grid ─────────────────────────────
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll, 1)

        self._container = QWidget()
        self._grid = QGridLayout(self._container)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._grid.setSpacing(6)
        self._scroll.setWidget(self._container)

        self._lead_buttons: List[QPushButton] = []

    # ── public API ───────────────────────────────────────────
    def set_context(self, account: AccountData, monster_db: MonsterDB, assets_dir: Path) -> None:
        self._account = account
        self._monster_db = monster_db
        self._assets_dir = assets_dir
        self._current_speed_lead_pct = 0
        self._build_speed_lead_buttons()
        self._render_grid()

    def retranslate(self) -> None:
        self._lead_label.setText(tr("rta.spd_lead"))
        self._build_speed_lead_buttons()

    # ── speed-lead buttons ───────────────────────────────────
    def _build_speed_lead_buttons(self) -> None:
        # Remove old buttons
        for btn in self._lead_buttons:
            self._lead_bar.removeWidget(btn)
            btn.deleteLater()
        self._lead_buttons.clear()

        if not self._account or not self._monster_db:
            return

        active_uids = self._account.rta_active_unit_ids()

        # Collect unique speed leads: pct -> list of monster names
        leads: Dict[int, List[str]] = {}
        for uid in active_uids:
            unit = self._account.units_by_id.get(uid)
            if not unit:
                continue
            pct = self._monster_db.rta_speed_lead_percent_for(unit.unit_master_id)
            if pct > 0:
                name = self._monster_db.name_for(unit.unit_master_id)
                leads.setdefault(pct, []).append(name)

        # "Kein Lead" button always first
        btn_none = QPushButton(tr("rta.no_lead"))
        btn_none.setCheckable(True)
        btn_none.setChecked(True)
        btn_none.setStyleSheet(self._lead_btn_style(checked=True))
        btn_none.clicked.connect(lambda: self._on_lead_clicked(0, btn_none))
        # Insert before the stretch
        self._lead_bar.insertWidget(self._lead_bar.count() - 1, btn_none)
        self._lead_buttons.append(btn_none)

        # One button per unique speed-lead percentage (sorted descending)
        for pct in sorted(leads.keys(), reverse=True):
            names = leads[pct]
            label = ", ".join(sorted(set(names)))
            if len(label) > 30:
                label = label[:27] + "..."
            btn = QPushButton(f"{label} ({pct}%)")
            btn.setCheckable(True)
            btn.setStyleSheet(self._lead_btn_style(checked=False))
            btn.clicked.connect(lambda checked, p=pct, b=btn: self._on_lead_clicked(p, b))
            self._lead_bar.insertWidget(self._lead_bar.count() - 1, btn)
            self._lead_buttons.append(btn)

    def _on_lead_clicked(self, pct: int, clicked_btn: QPushButton) -> None:
        self._current_speed_lead_pct = pct
        for btn in self._lead_buttons:
            is_active = btn is clicked_btn
            btn.setChecked(is_active)
            btn.setStyleSheet(self._lead_btn_style(checked=is_active))
        self._render_grid()

    @staticmethod
    def _lead_btn_style(checked: bool) -> str:
        if checked:
            return (
                "QPushButton { background: #2980b9; color: #fff; border: 1px solid #3498db;"
                " border-radius: 3px; padding: 4px 10px; font-weight: bold; }"
            )
        return (
            "QPushButton { background: #3a3a3a; color: #ccc; border: 1px solid #666;"
            " border-radius: 3px; padding: 4px 10px; }"
            " QPushButton:hover { background: #505050; border-color: #888; }"
        )

    # ── grid rendering ───────────────────────────────────────
    def _render_grid(self) -> None:
        # Clear old cards
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        if not self._account or not self._monster_db or not self._assets_dir:
            return

        active_uids = self._account.rta_active_unit_ids()

        # Build (unit, name, element, icon, runes, artifacts, stats) tuples
        entries: List[Tuple[Unit, str, str, QIcon, List[Rune], List[Artifact], Dict[str, int]]] = []
        for uid in active_uids:
            unit = self._account.units_by_id.get(uid)
            if not unit:
                continue
            name = self._monster_db.name_for(unit.unit_master_id)
            element = self._monster_db.element_for(unit.unit_master_id)
            icon = _icon_for(self._monster_db, unit.unit_master_id, self._assets_dir)
            runes = self._account.equipped_runes_for(uid, mode="rta")
            artifacts = self._equipped_artifacts_for(uid)
            stats = compute_unit_stats(
                unit,
                runes,
                self._current_speed_lead_pct,
                int(self._account.sky_tribe_totem_spd_pct or 0),
            )
            entries.append((unit, name, element, icon, runes, artifacts, stats))

        # Sort by SPD descending (turn order: fastest first)
        entries.sort(key=lambda e: e[6].get("SPD", 0), reverse=True)

        # Place into 4-column grid
        for idx, (unit, name, element, icon, runes, artifacts, stats) in enumerate(entries):
            row, col = divmod(idx, COLUMNS)
            card = MonsterCard(
                unit,
                name,
                element,
                icon,
                runes,
                stats,
                self._assets_dir,
                equipped_artifacts=artifacts,
            )
            self._grid.addWidget(card, row, col)

    def _equipped_artifacts_for(self, unit_id: int) -> List[Artifact]:
        if not self._account:
            return []
        by_id: Dict[int, Artifact] = {int(a.artifact_id): a for a in (self._account.artifacts or [])}
        result: Dict[int, Artifact] = {}
        for aid in (self._account.rta_artifact_equip.get(int(unit_id), []) or []):
            art = by_id.get(int(aid))
            if not art:
                continue
            art_type = int(art.type_ or 0)
            if art_type in (1, 2) and art_type not in result:
                result[art_type] = art
        if not result:
            for art in (self._account.artifacts or []):
                if int(art.occupied_id or 0) != int(unit_id):
                    continue
                art_type = int(art.type_ or 0)
                if art_type in (1, 2) and art_type not in result:
                    result[art_type] = art
        return [result[t] for t in (1, 2) if t in result]
