from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Optional, Tuple

from PySide6.QtCore import Qt, QSize, QRectF
from PySide6.QtGui import QIcon, QPainter, QColor, QFont, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QGroupBox, QScrollArea, QPushButton, QGridLayout,
    QSizePolicy,
)

from app.domain.models import AccountData, Rune, Unit, Artifact, compute_unit_stats
from app.domain.monster_db import MonsterDB
from app.domain.optimization_store import SavedOptimization
from app.domain.presets import EFFECT_ID_TO_MAINSTAT_KEY, SET_NAMES
from app.domain.artifact_effects import (
    ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID,
    artifact_effect_text,
    artifact_rank_label,
)
from app.engine.efficiency import rune_efficiency


# ── colour palette for main-stat pie slices ──────────────────
_STAT_COLOURS: Dict[str, QColor] = {
    "SPD":  QColor(52, 152, 219),   # blue
    "HP%":  QColor(46, 204, 113),   # green
    "HP":   QColor(39, 174, 96),    # darker green
    "ATK%": QColor(231, 76, 60),    # red
    "ATK":  QColor(192, 57, 43),    # darker red
    "DEF%": QColor(243, 156, 18),   # orange
    "DEF":  QColor(211, 132, 10),   # darker orange
    "CR":   QColor(241, 196, 15),   # yellow
    "CD":   QColor(155, 89, 182),   # purple
    "RES":  QColor(26, 188, 156),   # teal
    "ACC":  QColor(233, 30, 99),    # pink
}
_DEFAULT_COLOUR = QColor(149, 165, 166)  # grey fallback


# ── element colours for the name label accent ────────────────
_ELEMENT_COLOURS: Dict[str, str] = {
    "Fire":   "#e74c3c",
    "Water":  "#3498db",
    "Wind":   "#f1c40f",
    "Light":  "#ecf0f1",
    "Dark":   "#8e44ad",
}

_STAT_LABELS_DE: Dict[str, str] = {
    "HP": "HP",
    "ATK": "ATK",
    "DEF": "DEF",
    "SPD": "SPD",
    "CR": "Krit. Rate",
    "CD": "Krit. Schdn",
    "RES": "RES",
    "ACC": "ACC",
}


# ── rich HTML tooltip for a rune ─────────────────────────────
def _rune_rich_tooltip(rune: Rune) -> str:
    set_name = SET_NAMES.get(int(rune.set_id or 0), "?")
    main_key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(rune.pri_eff[0] or 0), "?")
    lines = [
        f"<b>{set_name}</b> &nbsp; Slot {rune.slot_no} &nbsp; +{rune.upgrade_curr}",
        f"Main: <b>{main_key} +{rune.pri_eff[1]}</b>",
    ]
    if rune.prefix_eff and int(rune.prefix_eff[0] or 0) != 0:
        pfx_key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(rune.prefix_eff[0] or 0), "?")
        lines.append(f"Prefix: {pfx_key} +{rune.prefix_eff[1]}")
    if rune.sec_eff:
        lines.append("<b>Subs:</b>")
        for sec in rune.sec_eff:
            if not sec:
                continue
            eff_id = int(sec[0] or 0)
            val = int(sec[1] or 0)
            key = EFFECT_ID_TO_MAINSTAT_KEY.get(eff_id, f"Eff {eff_id}")
            gem_flag = int(sec[2] or 0) if len(sec) >= 3 else 0
            grind = int(sec[3] or 0) if len(sec) >= 4 else 0
            total = val + grind
            txt = f"&nbsp;&nbsp;{key} +{total}"
            if grind:
                txt += f" <span style='color:#f39c12'>({val}+{grind})</span>"
            if gem_flag:
                txt = f"<span style='color:#1abc9c'>{txt} [Gem]</span>"
            lines.append(txt)
    return "<br>".join(lines)


_ARTIFACT_KIND_LABEL = {
    1: "Attribut",
    2: "Typ",
}

def _artifact_focus(art: Artifact) -> str:
    if not art.pri_effect:
        return ""
    try:
        return str(ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID.get(int(art.pri_effect[0] or 0), ""))
    except Exception:
        return ""


def _artifact_effect_text(effect_id: int, value: int | float | str) -> str:
    return artifact_effect_text(effect_id, value, fallback_prefix="Eff")


def _artifact_rich_tooltip(art: Artifact) -> str:
    kind = _ARTIFACT_KIND_LABEL.get(int(art.type_ or 0), f"Typ {int(art.type_ or 0)}")
    focus = _artifact_focus(art) or "—"
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    quality = artifact_rank_label(base_rank, fallback_prefix="Rank")
    lines = [
        f"<b>{kind}-Artefakt</b> &nbsp; ID {int(art.artifact_id or 0)}",
        f"Fokus: <b>{focus}</b> &nbsp; Qualität {quality} &nbsp; +{int(art.level or 0)}",
    ]
    if art.sec_effects:
        lines.append("<b>Subs:</b>")
        for sec in art.sec_effects:
            if not sec:
                continue
            try:
                eff_id = int(sec[0] or 0)
            except Exception:
                continue
            val = sec[1] if len(sec) > 1 else 0
            rolls = int(sec[2] or 0) if len(sec) > 2 else 0
            lines.append(f"&nbsp;&nbsp;{_artifact_effect_text(eff_id, val)} [Rolls {rolls}]")
    return "<br>".join(lines)


# ============================================================
#  RunePieChart – custom QPainter donut chart (compact)
# ============================================================
class RunePieChart(QWidget):
    """Small donut chart showing main-stat distribution (slots 2/4/6)."""

    def __init__(self, stats: List[Tuple[str, int]], parent: QWidget | None = None):
        super().__init__(parent)
        self._stats = stats
        self.setFixedSize(108, 108)

    def paintEvent(self, event):
        if not self._stats:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        total = sum(v for _, v in self._stats)
        if total == 0:
            painter.end()
            return

        margin = 4
        row_h = 12
        legend_h = row_h * len(self._stats) + 2
        chart_area_h = self.height() - (margin * 2) - legend_h
        chart_size = min(self.width() - margin * 2, chart_area_h) - 2
        if chart_size < 20:
            chart_size = 20
        cx = self.width() / 2
        cy = margin + chart_size / 2
        rect = QRectF(cx - chart_size / 2, cy - chart_size / 2, chart_size, chart_size)
        inner_rect = rect.adjusted(chart_size * 0.25, chart_size * 0.25,
                                   -chart_size * 0.25, -chart_size * 0.25)

        start_angle = 90 * 16
        for key, value in self._stats:
            span = int(round(value / total * 360 * 16))
            colour = _STAT_COLOURS.get(key, _DEFAULT_COLOUR)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(colour))
            painter.drawPie(rect, start_angle, -span)
            start_angle -= span

        painter.setBrush(QBrush(QColor(43, 43, 43)))
        painter.drawEllipse(inner_rect)

        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        ly = self.height() - margin - legend_h + 2
        for key, value in self._stats:
            colour = _STAT_COLOURS.get(key, _DEFAULT_COLOUR)
            painter.setBrush(QBrush(colour))
            painter.setPen(Qt.NoPen)
            painter.drawRect(QRectF(margin, ly, 8, 8))
            painter.setPen(QColor(220, 220, 220))
            painter.drawText(QRectF(margin + 10, ly - 1, 86, 12), Qt.AlignLeft, key)
            ly += row_h

        painter.end()


# ============================================================
#  MonsterCard – single monster in a defence team (compact)
# ============================================================
class MonsterCard(QFrame):
    def __init__(
        self,
        unit: Unit,
        name: str,
        element: str,
        monster_icon: QIcon,
        equipped_runes: List[Rune],
        computed_stats: Dict[str, int],
        assets_dir: Path,
        equipped_artifacts: Optional[List[Artifact]] = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._runes = equipped_runes
        self._artifacts = list(equipped_artifacts or [])
        self._assets_dir = assets_dir
        self._computed_stats = computed_stats

        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            MonsterCard {
                background: #2b2b2b;
                border: 1px solid #555;
                border-radius: 4px;
            }
            QLabel { color: #ddd; font-size: 9pt; }
            QPushButton {
                background: #3a3a3a;
                border: 1px solid #666;
                border-radius: 2px;
                padding: 2px;
                min-width: 34px;
                min-height: 34px;
            }
            QPushButton:hover {
                background: #505050;
                border-color: #888;
            }
        """)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # ── monster icon + name ──────────────────────────────
        top = QHBoxLayout()
        top.setSpacing(6)
        if not monster_icon.isNull():
            icon_lbl = QLabel()
            icon_lbl.setPixmap(monster_icon.pixmap(52, 52))
            icon_lbl.setFixedSize(54, 54)
            top.addWidget(icon_lbl)

        info = QVBoxLayout()
        info.setSpacing(0)
        elem_col = _ELEMENT_COLOURS.get(element, "#ddd")
        name_lbl = QLabel(f"<b style='font-size:11pt; color:{elem_col}'>{name}</b>")
        name_lbl.setTextFormat(Qt.RichText)
        info.addWidget(name_lbl)
        meta_lbl = QLabel(f"{element} | Lv {unit.unit_level}")
        meta_lbl.setStyleSheet("font-size: 9pt; color: #aaa;")
        info.addWidget(meta_lbl)
        top.addLayout(info)
        top.addStretch()
        layout.addLayout(top)

        # ── rune set summary + pie side by side ───────────────
        mid = QHBoxLayout()
        mid.setSpacing(8)

        # pie chart
        main_stats: List[Tuple[str, int]] = []
        for r in equipped_runes:
            if int(r.slot_no or 0) in (2, 4, 6):
                key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(r.pri_eff[0] or 0), "?")
                main_stats.append((key, 1))
        if main_stats:
            pie = RunePieChart(main_stats)
            mid.addWidget(pie, 0, Qt.AlignTop)

        # stats grid
        stats_box = QVBoxLayout()
        stats_box.setSpacing(0)

        # set icons row
        set_ids = [int(r.set_id or 0) for r in equipped_runes]
        set_counts: Dict[int, int] = {}
        for sid in set_ids:
            set_counts[sid] = set_counts.get(sid, 0) + 1
        sets_row = QHBoxLayout()
        sets_row.setSpacing(2)
        shown_sets: List[str] = []
        for sid, cnt in set_counts.items():
            sn = SET_NAMES.get(sid, "")
            if sn:
                shown_sets.append(sn)
                icon = self._rune_set_icon(sid)
                if not icon.isNull():
                    ilbl = QLabel()
                    ilbl.setPixmap(icon.pixmap(20, 20))
                    ilbl.setToolTip(sn)
                    sets_row.addWidget(ilbl)
        set_text = " / ".join(dict.fromkeys(shown_sets))
        set_lbl = QLabel(f"<b style='font-size:9pt'>{set_text}</b>")
        set_lbl.setTextFormat(Qt.RichText)
        sets_row.addWidget(set_lbl)
        sets_row.addStretch()
        stats_box.addLayout(sets_row)

        if equipped_runes:
            avg_eff = sum(rune_efficiency(r) for r in equipped_runes) / len(equipped_runes)
            eff_lbl = QLabel(f"Ø Rune-Effizienz: <b>{avg_eff:.2f}%</b>")
        else:
            eff_lbl = QLabel("Ø Rune-Effizienz: <b>—</b>")
        eff_lbl.setTextFormat(Qt.RichText)
        eff_lbl.setStyleSheet("font-size: 8pt; color: #bbb;")
        stats_box.addWidget(eff_lbl)

        # stats 4x2 grid
        stats_grid = QGridLayout()
        stats_grid.setSpacing(3)
        stats_grid.setContentsMargins(0, 4, 0, 0)
        cs = self._computed_stats
        stat_data = [
            ("HP",  cs.get("HP", 0)),
            ("ATK", cs.get("ATK", 0)),
            ("DEF", cs.get("DEF", 0)),
            ("SPD", cs.get("SPD", 0)),
            ("CR",  cs.get("CR", 0)),
            ("CD",  cs.get("CD", 0)),
            ("RES", cs.get("RES", 0)),
            ("ACC", cs.get("ACC", 0)),
        ]
        for i, (label, value) in enumerate(stat_data):
            row, col = divmod(i, 2)
            display_label = _STAT_LABELS_DE.get(label, label)
            key_lbl = QLabel(f"<b>{display_label}:</b>")
            key_lbl.setTextFormat(Qt.RichText)
            key_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            key_lbl.setStyleSheet("font-size: 9pt;")
            val_lbl = QLabel(f"{value:,}".replace(",", "."))
            val_lbl.setStyleSheet("font-size: 9pt;")
            stats_grid.addWidget(key_lbl, row, col * 2)
            stats_grid.addWidget(val_lbl, row, col * 2 + 1)
        stats_box.addLayout(stats_grid)
        mid.addLayout(stats_box, 1)
        layout.addLayout(mid)

        # ── rune slot buttons (with rich tooltip on hover) ────
        rune_bar = QHBoxLayout()
        rune_bar.setSpacing(4)
        rune_by_slot = {int(r.slot_no or 0): r for r in equipped_runes}
        for slot in range(1, 7):
            btn = QPushButton(str(slot))
            btn.setFixedSize(36, 36)
            btn.setIconSize(QSize(24, 24))
            rune = rune_by_slot.get(slot)
            if rune:
                icon = self._rune_set_icon(int(rune.set_id or 0))
                if not icon.isNull():
                    btn.setIcon(icon)
                    btn.setText("")
                btn.setToolTip(_rune_rich_tooltip(rune))
            else:
                btn.setEnabled(False)
                btn.setToolTip("Kein Rune")
            rune_bar.addWidget(btn)
        rune_bar.addStretch()
        layout.addLayout(rune_bar)

        # artifacts (type 1 = attribute, type 2 = type)
        art_bar = QHBoxLayout()
        art_bar.setSpacing(4)
        art_by_type: Dict[int, Artifact] = {int(a.type_ or 0): a for a in self._artifacts}
        for art_type in (1, 2):
            art = art_by_type.get(art_type)
            btn = QPushButton(_ARTIFACT_KIND_LABEL.get(art_type, str(art_type)))
            btn.setFixedHeight(28)
            if art:
                focus = _artifact_focus(art)
                txt = _ARTIFACT_KIND_LABEL.get(art_type, str(art_type))
                if focus:
                    txt = f"{txt} {focus}"
                btn.setText(txt)
                btn.setToolTip(_artifact_rich_tooltip(art))
            else:
                btn.setEnabled(False)
                btn.setToolTip("Kein Artefakt")
            art_bar.addWidget(btn)
        art_bar.addStretch()
        layout.addLayout(art_bar)

    # ── helpers ──────────────────────────────────────────────
    def _rune_set_icon(self, set_id: int) -> QIcon:
        name = SET_NAMES.get(set_id, "")
        slug = name.lower().replace(" ", "_") if name else str(set_id)
        filename = f"{set_id}_{slug}.png"
        icon_path = self._assets_dir / "runes" / "sets" / filename
        return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


# ============================================================
#  TeamCard – one defence (3 monsters)
# ============================================================
class TeamCard(QGroupBox):
    def __init__(
        self,
        team_index: int,
        units: List[Tuple[Unit, str, str, QIcon, List[Rune], List[Artifact], Dict[str, int]]],
        assets_dir: Path,
        parent: QWidget | None = None,
        title: str | None = None,
    ):
        super().__init__(title or f"Verteidigung {team_index}", parent)
        self.setStyleSheet("""
            TeamCard {
                font-weight: bold;
                font-size: 10pt;
                color: #eee;
                border: 1px solid #666;
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 12px;
            }
            TeamCard::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
            }
        """)

        row = QHBoxLayout(self)
        row.setSpacing(8)
        row.setContentsMargins(8, 8, 8, 8)
        for unit, name, element, icon, runes, artifacts, stats in units:
            card = MonsterCard(
                unit,
                name,
                element,
                icon,
                runes,
                stats,
                assets_dir,
                equipped_artifacts=artifacts,
            )
            row.addWidget(card)


# ============================================================
#  SiegeDefCardsWidget – top-level scrollable container
# ============================================================
class SiegeDefCardsWidget(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._container)

    # ── public API ───────────────────────────────────────────
    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def render(self, account: AccountData, monster_db: MonsterDB, assets_dir: Path,
               rune_mode: str = "siege"):
        """Render siege defense teams from imported account data."""
        self._clear()
        if not account:
            return
        teams = account.siege_def_teams()
        self._render_teams(teams, account, monster_db, assets_dir, rune_mode)

    def render_from_selections(self, teams: List[List[int]],
                               account: AccountData, monster_db: MonsterDB,
                               assets_dir: Path, rune_mode: str = "siege",
                               rune_overrides: Optional[Dict[int, List[Rune]]] = None,
                               artifact_overrides: Optional[Dict[int, List[Artifact]]] = None,
                               team_label_prefix: str = "Verteidigung"):
        """Render manually selected teams (e.g. WGB builder).

        *teams* is a list of unit-id lists, e.g. [[uid1, uid2, uid3], ...].
        """
        self._clear()
        if not account or not teams:
            return
        self._render_teams(teams, account, monster_db, assets_dir, rune_mode,
                           rune_overrides, artifact_overrides, team_label_prefix)

    def render_saved_optimization(self, opt: SavedOptimization,
                                  account: AccountData, monster_db: MonsterDB,
                                  assets_dir: Path, rune_mode: str = "siege"):
        """Render a saved optimization using its stored rune assignments."""
        self._clear()
        runes_by_id = account.runes_by_id()
        artifacts_by_id = {int(a.artifact_id): a for a in account.artifacts}
        rune_overrides: Dict[int, List[Rune]] = {}
        artifact_overrides: Dict[int, List[Artifact]] = {}
        for res in opt.results:
            runes = []
            for slot in sorted(res.runes_by_slot.keys()):
                rid = res.runes_by_slot[slot]
                rune = runes_by_id.get(rid)
                if rune:
                    runes.append(rune)
            rune_overrides[res.unit_id] = runes
            arts: List[Artifact] = []
            for art_type in (1, 2):
                aid = int((res.artifacts_by_type or {}).get(art_type, 0) or 0)
                art = artifacts_by_id.get(aid)
                if art:
                    arts.append(art)
            if arts:
                artifact_overrides[res.unit_id] = arts
        self._render_teams(
            opt.teams,
            account,
            monster_db,
            assets_dir,
            rune_mode,
            rune_overrides,
            artifact_overrides,
        )

    def _render_teams(self, teams: List[List[int]], account: AccountData,
                      monster_db: MonsterDB, assets_dir: Path, rune_mode: str,
                      rune_overrides: Optional[Dict[int, List[Rune]]] = None,
                      artifact_overrides: Optional[Dict[int, List[Artifact]]] = None,
                      team_label_prefix: str = "Verteidigung"):
        for ti, team in enumerate(teams, start=1):
            speed_lead_pct = 0
            for uid in team:
                u = account.units_by_id.get(uid)
                if u:
                    lead = int(monster_db.speed_lead_percent_for(u.unit_master_id) or 0)
                    if lead > speed_lead_pct:
                        speed_lead_pct = lead

            unit_data: List[Tuple[Unit, str, str, QIcon, List[Rune], List[Artifact], Dict[str, int]]] = []
            for uid in team:
                u = account.units_by_id.get(uid)
                if not u:
                    continue
                name = monster_db.name_for(u.unit_master_id)
                element = monster_db.element_for(u.unit_master_id)
                icon = _icon_for(monster_db, u.unit_master_id, assets_dir)
                if rune_overrides and uid in rune_overrides:
                    equipped = rune_overrides[uid]
                else:
                    equipped = account.equipped_runes_for(uid, rune_mode)
                if artifact_overrides and uid in artifact_overrides:
                    equipped_artifacts = artifact_overrides[uid]
                else:
                    equipped_artifacts = self._equipped_artifacts_for(account, uid, rune_mode)
                stats = compute_unit_stats(u, equipped, speed_lead_pct)
                unit_data.append((u, name, element, icon, equipped, equipped_artifacts, stats))
            if unit_data:
                title = f"{team_label_prefix} {ti}"
                card = TeamCard(ti, unit_data, assets_dir, title=title)
                self._layout.addWidget(card)

    def _equipped_artifacts_for(self, account: AccountData, unit_id: int, rune_mode: str) -> List[Artifact]:
        by_id: Dict[int, Artifact] = {int(a.artifact_id): a for a in (account.artifacts or [])}
        result: Dict[int, Artifact] = {}
        if rune_mode == "rta":
            for aid in (account.rta_artifact_equip.get(int(unit_id), []) or []):
                art = by_id.get(int(aid))
                if not art:
                    continue
                art_type = int(art.type_ or 0)
                if art_type in (1, 2) and art_type not in result:
                    result[art_type] = art
        if not result:
            for art in (account.artifacts or []):
                if int(art.occupied_id or 0) != int(unit_id):
                    continue
                art_type = int(art.type_ or 0)
                if art_type in (1, 2) and art_type not in result:
                    result[art_type] = art
        return [result[t] for t in (1, 2) if t in result]


# ── module-level helper ──────────────────────────────────────
def _icon_for(monster_db: MonsterDB, master_id: int, assets_dir: Path) -> QIcon:
    rel = monster_db.icon_path_for(master_id)
    if not rel:
        return QIcon()
    p = (assets_dir / rel).resolve()
    return QIcon(str(p)) if p.exists() else QIcon()
