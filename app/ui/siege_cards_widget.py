from __future__ import annotations

import weakref
from pathlib import Path
from typing import ClassVar, List, Dict, Optional, Tuple, Any

from PySide6.QtCore import Qt, QSize, QRectF, QEvent
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
from app.i18n import tr


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
_RTA_GRID_MIN_COLUMNS = 4
_RTA_GRID_MAX_COLUMNS = 6

def _card_stat_label(key: str) -> str:
    return tr("card_stat." + key)


# ── rich HTML tooltip for a rune ─────────────────────────────
def _rune_rich_tooltip(rune: Rune) -> str:
    set_name = SET_NAMES.get(int(rune.set_id or 0), "?")
    main_key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(rune.pri_eff[0] or 0), "?")
    lines = [
        f"<b>{set_name}</b> &nbsp; {tr('ui.slot')} {rune.slot_no} &nbsp; +{rune.upgrade_curr}",
        f"{tr('ui.main')}: <b>{main_key} +{rune.pri_eff[1]}</b>",
    ]
    if rune.prefix_eff and int(rune.prefix_eff[0] or 0) != 0:
        pfx_key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(rune.prefix_eff[0] or 0), "?")
        lines.append(f"{tr('ui.prefix')}: {pfx_key} +{rune.prefix_eff[1]}")
    if rune.sec_eff:
        lines.append(f"<b>{tr('ui.subs')}:</b>")
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


def _artifact_kind_label(type_id: int) -> str:
    if type_id == 1:
        return tr("artifact.attribute")
    if type_id == 2:
        return tr("artifact.type")
    return str(type_id)

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
    kind = _artifact_kind_label(int(art.type_ or 0))
    focus = _artifact_focus(art) or "—"
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    quality = artifact_rank_label(base_rank, fallback_prefix="Rank")
    lines = [
        f"<b>{kind} {tr('ui.artifact')}</b> &nbsp; ID {int(art.artifact_id or 0)}",
        f"{tr('card.focus')} <b>{focus}</b> &nbsp; {tr('overview.quality')} {quality} &nbsp; +{int(art.level or 0)}",
    ]
    if art.sec_effects:
        lines.append(f"<b>{tr('ui.subs')}:</b>")
        for sec in art.sec_effects:
            if not sec:
                continue
            try:
                eff_id = int(sec[0] or 0)
            except Exception:
                continue
            val = sec[1] if len(sec) > 1 else 0
            rolls = int(sec[2] or 0) if len(sec) > 2 else 0
            lines.append(f"&nbsp;&nbsp;{_artifact_effect_text(eff_id, val)} [{tr('ui.rolls', n=rolls)}]")
    return "<br>".join(lines)


def _unit_base_stats(unit: Unit) -> Dict[str, int]:
    return {
        "HP": int((unit.base_con or 0) * 15),
        "ATK": int(unit.base_atk or 0),
        "DEF": int(unit.base_def or 0),
        "SPD": int(unit.base_spd or 0),
        "CR": int(unit.crit_rate or 15),
        "CD": int(unit.crit_dmg or 50),
        "RES": int(unit.base_res or 15),
        "ACC": int(unit.base_acc or 0),
    }


def _leader_bonus_for_unit(unit: Unit, leader_skill: Any) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if leader_skill is None:
        return out
    stat = str(getattr(leader_skill, "stat", "") or "").upper()
    amount = int(getattr(leader_skill, "amount", 0) or 0)
    if amount <= 0:
        return out
    base = _unit_base_stats(unit)
    if stat == "HP%":
        out["HP"] = int(base["HP"] * amount / 100)
    elif stat == "ATK%":
        out["ATK"] = int(base["ATK"] * amount / 100)
    elif stat == "DEF%":
        out["DEF"] = int(base["DEF"] * amount / 100)
    elif stat == "SPD%":
        out["SPD"] = int(base["SPD"] * amount / 100)
    elif stat == "CR%":
        out["CR"] = int(amount)
    elif stat == "CD%":
        out["CD"] = int(amount)
    elif stat == "RES%":
        out["RES"] = int(amount)
    elif stat == "ACC%":
        out["ACC"] = int(amount)
    return out


def _artifact_stat_bonus(artifacts: List[Artifact]) -> Dict[str, int]:
    out: Dict[str, int] = {k: 0 for k in ("HP", "ATK", "DEF", "SPD", "CR", "CD", "RES", "ACC")}

    def _acc(eff_id: int, value: int) -> None:
        # Keep only direct primary-stat effects; artifact combat effects are not base stat lines.
        if eff_id in (1, 100):
            out["HP"] += int(value)
        elif eff_id in (3, 101):
            out["ATK"] += int(value)
        elif eff_id in (5, 102):
            out["DEF"] += int(value)

    for art in artifacts or []:
        try:
            if art.pri_effect and len(art.pri_effect) >= 2:
                _acc(int(art.pri_effect[0] or 0), int(art.pri_effect[1] or 0))
        except Exception:
            pass
    return out


def _build_stat_breakdown(
    unit: Unit,
    artifacts: List[Artifact],
    total_with_tower_and_leader: Dict[str, int],
    leader_bonus: Dict[str, int],
    sky_tribe_totem_spd_pct: int = 0,
) -> Dict[str, Dict[str, int]]:
    base = _unit_base_stats(unit)
    totem_spd = int(base["SPD"] * int(sky_tribe_totem_spd_pct or 0) / 100)
    total = {k: int(total_with_tower_and_leader.get(k, 0)) for k in base.keys()}
    # subtract totem bonus from SPD so card shows only rune values
    total["SPD"] -= totem_spd
    leader = {k: int(leader_bonus.get(k, 0)) for k in base.keys()}
    total_no_leader = {k: int(total[k] - leader[k]) for k in base.keys()}
    art = _artifact_stat_bonus(artifacts)
    total_no_leader = {k: int(total_no_leader[k] + art.get(k, 0)) for k in base.keys()}
    total_with_leader = {k: int(total_no_leader[k] + leader[k]) for k in base.keys()}
    rune_art: Dict[str, int] = {}
    for k in base.keys():
        rune_art[k] = int(total_no_leader[k] - base[k])
    return {
        k: {
            "base": int(base[k]),
            "rune_art": int(rune_art[k]),
            "total": int(total_no_leader[k]),
            "total_leader": int(total_with_leader[k]),
        }
        for k in base.keys()
    }


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
    # 0 = Gesamt, 1 = Gesamt+LS, 2 = Detail (Base + Bonus)
    _view_mode: ClassVar[int] = 2
    _all_instances: ClassVar[weakref.WeakSet["MonsterCard"]] = weakref.WeakSet()

    def __init__(
        self,
        unit: Unit,
        name: str,
        element: str,
        monster_icon: QIcon,
        equipped_runes: List[Rune],
        computed_stats: Dict[str, Dict[str, int]],
        assets_dir: Path,
        equipped_artifacts: Optional[List[Artifact]] = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        MonsterCard._all_instances.add(self)
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
            eff_lbl = QLabel(tr("card.avg_rune_eff", eff=f"{avg_eff:.2f}"))
        else:
            eff_lbl = QLabel(tr("card.avg_rune_eff_none"))
        eff_lbl.setTextFormat(Qt.RichText)
        eff_lbl.setStyleSheet("font-size: 8pt; color: #bbb;")
        stats_box.addWidget(eff_lbl)

        # stats grid (clickable to toggle view mode)
        self._stats_grid = QGridLayout()
        self._stats_grid.setSpacing(3)
        self._stats_grid.setContentsMargins(0, 4, 0, 0)
        self._refresh_stats()
        stats_box.addLayout(self._stats_grid)
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
                btn.setToolTip(tr("artifact.no_rune"))
            rune_bar.addWidget(btn)
        rune_bar.addStretch()
        layout.addLayout(rune_bar)

        # artifacts (type 1 = attribute, type 2 = type)
        art_bar = QHBoxLayout()
        art_bar.setSpacing(4)
        art_by_type: Dict[int, Artifact] = {int(a.type_ or 0): a for a in self._artifacts}
        for art_type in (1, 2):
            art = art_by_type.get(art_type)
            btn = QPushButton(_artifact_kind_label(art_type))
            btn.setFixedHeight(28)
            if art:
                focus = _artifact_focus(art)
                txt = _artifact_kind_label(art_type)
                if focus:
                    txt = f"{txt} {focus}"
                btn.setText(txt)
                btn.setToolTip(_artifact_rich_tooltip(art))
            else:
                btn.setEnabled(False)
                btn.setToolTip(tr("artifact.no_artifact"))
            art_bar.addWidget(btn)
        art_bar.addStretch()
        layout.addLayout(art_bar)

    # ── stats view toggle ──────────────────────────────────
    def _refresh_stats(self) -> None:
        """Rebuild stats grid based on current view mode."""
        # clear existing widgets
        while self._stats_grid.count():
            item = self._stats_grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        cs = self._computed_stats
        mode = MonsterCard._view_mode
        _PERCENT_STATS = {"CR", "CD", "RES", "ACC"}
        row = 0

        for group in (["HP", "ATK", "DEF", "SPD"], ["CR", "CD", "RES", "ACC"]):
            for label in group:
                display_label = _card_stat_label(label)
                key_lbl = QLabel(f"<b>{display_label}</b>")
                key_lbl.setTextFormat(Qt.RichText)
                key_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                key_lbl.setStyleSheet("font-size: 9pt; color: #e8c252;")

                vals = cs.get(label, {})
                base_v = int(vals.get("base", 0))
                rune_art_v = int(vals.get("rune_art", 0))
                total_v = int(vals.get("total", 0))
                total_ls_v = int(vals.get("total_leader", total_v))
                suffix = "%" if label in _PERCENT_STATS else ""

                self._stats_grid.addWidget(key_lbl, row, 0)

                if mode == 0:  # Gesamt
                    val_lbl = QLabel(f"{total_v:,}{suffix}".replace(",", "."))
                    val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    val_lbl.setStyleSheet("font-size: 9pt; color: #ddd;")
                    self._stats_grid.addWidget(val_lbl, row, 1)
                elif mode == 1:  # Gesamt+LS
                    val_lbl = QLabel(f"{total_ls_v:,}{suffix}".replace(",", "."))
                    val_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    val_lbl.setStyleSheet("font-size: 9pt; color: #ffcc66;")
                    self._stats_grid.addWidget(val_lbl, row, 1)
                else:  # Detail: Base + green bonus
                    base_lbl = QLabel(f"{base_v:,}{suffix}".replace(",", "."))
                    base_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    base_lbl.setStyleSheet("font-size: 9pt; color: #ddd;")
                    bonus_lbl = QLabel(f"+{rune_art_v:,}{suffix}".replace(",", "."))
                    bonus_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    bonus_lbl.setStyleSheet("font-size: 9pt; color: #6dcc5a;")
                    self._stats_grid.addWidget(base_lbl, row, 1)
                    self._stats_grid.addWidget(bonus_lbl, row, 2)

                row += 1
            # spacer row between groups
            if group[0] == "HP":
                spacer = QLabel("")
                spacer.setFixedHeight(6)
                self._stats_grid.addWidget(spacer, row, 0)
                row += 1

    def mousePressEvent(self, event) -> None:
        MonsterCard._view_mode = (MonsterCard._view_mode + 1) % 3
        for card in MonsterCard._all_instances:
            card._refresh_stats()
        super().mousePressEvent(event)

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
        units: List[Tuple[Unit, str, str, QIcon, List[Rune], List[Artifact], Dict[str, Dict[str, int]]]],
        assets_dir: Path,
        parent: QWidget | None = None,
        title: str | None = None,
    ):
        super().__init__(title or tr("card.defense", n=team_index), parent)
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

        # ── speed-lead button bar (hidden by default, shown for RTA) ──
        self._lead_bar = QHBoxLayout()
        self._lead_bar.setSpacing(4)
        self._lead_label = QLabel(tr("rta.spd_lead"))
        self._lead_label.setTextFormat(Qt.RichText)
        self._lead_bar.addWidget(self._lead_label)
        self._lead_bar.addStretch()
        self._lead_bar_widget = QWidget()
        self._lead_bar_widget.setLayout(self._lead_bar)
        self._lead_bar_widget.setVisible(False)
        outer.addWidget(self._lead_bar_widget)
        self._lead_buttons: List[QPushButton] = []
        self._current_speed_lead_pct = 0

        # ── state for RTA flat-grid re-rendering ──
        self._rta_grid_params: Optional[Dict] = None
        self._rta_grid_columns = _RTA_GRID_MIN_COLUMNS
        self._rta_flat_grid_active = False

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.viewport().installEventFilter(self)
        outer.addWidget(self._scroll)

        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setAlignment(Qt.AlignTop)
        self._scroll.setWidget(self._container)

    def eventFilter(self, watched, event) -> bool:
        if watched is self._scroll.viewport() and event.type() == QEvent.Wheel:
            if self._rta_flat_grid_active and bool(event.modifiers() & Qt.ControlModifier):
                delta_y = int(event.angleDelta().y())
                if delta_y > 0:
                    self._set_rta_grid_columns(self._rta_grid_columns + 1)
                elif delta_y < 0:
                    self._set_rta_grid_columns(self._rta_grid_columns - 1)
                event.accept()
                return True
        return super().eventFilter(watched, event)

    # ── public API ───────────────────────────────────────────
    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._lead_bar_widget.setVisible(False)
        for btn in self._lead_buttons:
            self._lead_bar.removeWidget(btn)
            btn.deleteLater()
        self._lead_buttons.clear()
        self._rta_grid_params = None
        self._rta_flat_grid_active = False
        self._current_speed_lead_pct = 0

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
                               team_label_prefix: str = ""):
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
        if rune_mode == "rta":
            self._render_flat_grid(
                opt.teams,
                account,
                monster_db,
                assets_dir,
                rune_mode,
                rune_overrides,
                artifact_overrides,
            )
        else:
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
                      team_label_prefix: str = ""):
        self._rta_flat_grid_active = False
        for ti, team in enumerate(teams, start=1):
            team_leader = None
            if team:
                lead_unit = account.units_by_id.get(int(team[0]))
                if lead_unit:
                    ls = monster_db.leader_skill_for(lead_unit.unit_master_id)
                    if ls:
                        area = str(getattr(ls, "area", "") or "")
                        if rune_mode == "rta":
                            if area in ("General", "Arena"):
                                team_leader = ls
                        else:
                            if area in ("General", "Guild"):
                                team_leader = ls

            speed_lead_pct = 0
            if team_leader and str(getattr(team_leader, "stat", "") or "").upper() == "SPD%":
                speed_lead_pct = int(getattr(team_leader, "amount", 0) or 0)

            unit_data: List[Tuple[Unit, str, str, QIcon, List[Rune], List[Artifact], Dict[str, Dict[str, int]]]] = []
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
                stats = compute_unit_stats(
                    u,
                    equipped,
                    speed_lead_pct,
                    int(account.sky_tribe_totem_spd_pct or 0),
                )
                leader_bonus = _leader_bonus_for_unit(u, team_leader)
                stat_breakdown = _build_stat_breakdown(
                    unit=u,
                    artifacts=equipped_artifacts,
                    total_with_tower_and_leader=stats,
                    leader_bonus=leader_bonus,
                    sky_tribe_totem_spd_pct=int(account.sky_tribe_totem_spd_pct or 0),
                )
                unit_data.append((u, name, element, icon, equipped, equipped_artifacts, stat_breakdown))
            if unit_data:
                prefix = team_label_prefix or tr("card.defense", n="").strip()
                title = f"{prefix} {ti}"
                card = TeamCard(ti, unit_data, assets_dir, title=title)
                self._layout.addWidget(card)

    def _render_flat_grid(self, teams: List[List[int]], account: AccountData,
                          monster_db: MonsterDB, assets_dir: Path, rune_mode: str,
                          rune_overrides: Optional[Dict[int, List[Rune]]] = None,
                          artifact_overrides: Optional[Dict[int, List[Artifact]]] = None):
        """Render all units from all teams in a flat RTA grid sorted by SPD."""
        # Store params so we can re-render when the speed lead changes
        self._rta_grid_params = dict(
            teams=teams, account=account, monster_db=monster_db,
            assets_dir=assets_dir, rune_mode=rune_mode,
            rune_overrides=rune_overrides, artifact_overrides=artifact_overrides,
        )
        self._build_speed_lead_buttons(teams, account, monster_db)
        self._lead_bar_widget.setVisible(True)
        self._rta_flat_grid_active = True
        self._rebuild_flat_grid()

    def _rebuild_flat_grid(self) -> None:
        """(Re)build the flat card grid using stored params and current speed lead."""
        # Clear existing grid content only
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        p = self._rta_grid_params
        if not p:
            return

        teams = p["teams"]
        account = p["account"]
        monster_db = p["monster_db"]
        assets_dir = p["assets_dir"]
        rune_mode = p["rune_mode"]
        rune_overrides = p["rune_overrides"]
        artifact_overrides = p["artifact_overrides"]
        speed_lead_pct = self._current_speed_lead_pct

        all_units: List[Tuple[Unit, str, str, QIcon, List[Rune], List[Artifact], Dict[str, Dict[str, int]], int]] = []
        for team in teams:
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
                stats = compute_unit_stats(
                    u,
                    equipped,
                    speed_lead_pct,
                    int(account.sky_tribe_totem_spd_pct or 0),
                )
                leader_bonus: Dict[str, int] = {}
                if speed_lead_pct > 0:
                    leader_bonus["SPD"] = int(int(u.base_spd or 0) * speed_lead_pct / 100)
                stat_breakdown = _build_stat_breakdown(
                    unit=u,
                    artifacts=equipped_artifacts,
                    total_with_tower_and_leader=stats,
                    leader_bonus=leader_bonus,
                    sky_tribe_totem_spd_pct=int(account.sky_tribe_totem_spd_pct or 0),
                )
                all_units.append((u, name, element, icon, equipped, equipped_artifacts, stat_breakdown, int(stats.get("SPD", 0))))

        all_units.sort(key=lambda e: e[7], reverse=True)

        grid = QGridLayout()
        grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        grid.setSpacing(6)
        for idx, (unit, name, element, icon, runes, artifacts, stats, _spd) in enumerate(all_units):
            row, col = divmod(idx, int(self._rta_grid_columns))
            card = MonsterCard(
                unit, name, element, icon, runes, stats, assets_dir,
                equipped_artifacts=artifacts,
            )
            grid.addWidget(card, row, col)
        container = QWidget()
        container.setLayout(grid)
        self._layout.addWidget(container)

    def _set_rta_grid_columns(self, columns: int) -> None:
        new_columns = max(_RTA_GRID_MIN_COLUMNS, min(_RTA_GRID_MAX_COLUMNS, int(columns)))
        if new_columns == int(self._rta_grid_columns):
            return
        self._rta_grid_columns = int(new_columns)
        if self._rta_flat_grid_active:
            self._rebuild_flat_grid()

    # ── speed-lead buttons (RTA flat grid) ────────────────────
    def _build_speed_lead_buttons(self, teams: List[List[int]],
                                   account: AccountData, monster_db: MonsterDB) -> None:
        for btn in self._lead_buttons:
            self._lead_bar.removeWidget(btn)
            btn.deleteLater()
        self._lead_buttons.clear()
        self._current_speed_lead_pct = 0

        # Collect unique speed leads from the optimization's units
        all_uids = [uid for team in teams for uid in team]
        leads: Dict[int, List[str]] = {}
        for uid in all_uids:
            unit = account.units_by_id.get(uid)
            if not unit:
                continue
            pct = monster_db.rta_speed_lead_percent_for(unit.unit_master_id)
            if pct > 0:
                name = monster_db.name_for(unit.unit_master_id)
                leads.setdefault(pct, []).append(name)

        btn_none = QPushButton(tr("rta.no_lead"))
        btn_none.setCheckable(True)
        btn_none.setChecked(True)
        btn_none.setStyleSheet(self._lead_btn_style(checked=True))
        btn_none.clicked.connect(lambda: self._on_lead_clicked(0, btn_none))
        self._lead_bar.insertWidget(self._lead_bar.count() - 1, btn_none)
        self._lead_buttons.append(btn_none)

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
        self._rebuild_flat_grid()

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
