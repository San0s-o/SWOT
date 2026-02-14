"""Account overview dashboard with summary cards and charts."""
from __future__ import annotations

from collections import Counter
from typing import Callable, List, Optional, Tuple, Any

from PySide6.QtCore import Qt, QMargins, QPointF
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea,
    QGridLayout, QSpinBox,
)
from PySide6.QtCharts import (
    QChart, QChartView, QBarCategoryAxis,
    QValueAxis, QPieSeries, QLineSeries,
)

from app.domain.models import AccountData, Rune, Artifact
from app.domain.presets import SET_NAMES, EFFECT_ID_TO_MAINSTAT_KEY
from app.engine.efficiency import (
    rune_efficiencies,
    rune_efficiency,
    artifact_efficiency,
    rune_efficiency_max,
)

# â”€â”€ colours â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
_BG = "#1e1e1e"
_CARD_BG = "#2b2b2b"
_CARD_BORDER = "#3a3a3a"
_TEXT = "#ddd"
_TEXT_DIM = "#999"
_ACCENT = "#3498db"
_GREEN = "#27ae60"
_ORANGE = "#f39c12"
_RED = "#e74c3c"
_PURPLE = "#9b59b6"
_CHART_BG = QColor(0x2b, 0x2b, 0x2b)
_CHART_TEXT = QColor(0xdd, 0xdd, 0xdd)
_CHART_GRID = QColor(0x44, 0x44, 0x44)

_RUNE_CLASS_NAMES = {
    1: "Normal", 2: "Magic", 3: "Rare", 4: "Hero", 5: "Legend",
    11: "Anc. Normal", 12: "Anc. Magic", 13: "Anc. Rare",
    14: "Anc. Hero", 15: "Anc. Legend",
    # com2us uses 6/16 for legend/ancient-legend in some exports
    6: "Legend", 16: "Anc. Legend",
}

_RUNE_CLASS_COLORS = {
    1: "#888", 2: "#2ecc71", 3: "#3498db", 4: "#9b59b6", 5: "#e67e22",
    6: "#e67e22", 11: "#888", 12: "#2ecc71", 13: "#3498db",
    14: "#9b59b6", 15: "#e67e22", 16: "#e67e22",
}

_EFF_BUCKET_COLORS = [
    "#e74c3c",  # <60
    "#e67e22",  # 60-70
    "#f39c12",  # 70-80
    "#f1c40f",  # 80-90
    "#2ecc71",  # 90-100
    "#27ae60",  # 100-110
    "#1abc9c",  # 110+
]

_IMPORTANT_SET_IDS = [13, 15, 3, 10, 18, 14]  # Violent, Will, Swift, Despair, Destroy, Nemesis


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Summary card
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class _SummaryCard(QFrame):
    def __init__(self, title: str, value: str, accent: str = _ACCENT, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            _SummaryCard {{
                background: {_CARD_BG};
                border: 1px solid {_CARD_BORDER};
                border-radius: 6px;
                padding: 10px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"color: {_TEXT_DIM}; font-size: 9pt;")
        lbl_title.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_title)

        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(f"color: {accent}; font-size: 16pt; font-weight: bold;")
        lbl_val.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_val)

        self._lbl_val = lbl_val
        self._lbl_title = lbl_title

    def update_value(self, value: str, accent: str | None = None):
        self._lbl_val.setText(value)
        if accent:
            self._lbl_val.setStyleSheet(f"color: {accent}; font-size: 16pt; font-weight: bold;")


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Chart helpers
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _make_chart(title: str) -> QChart:
    chart = QChart()
    chart.setTitle(title)
    chart.setAnimationOptions(QChart.SeriesAnimations)
    chart.setBackgroundBrush(QColor(_CHART_BG))
    chart.setTitleBrush(QColor(_CHART_TEXT))
    chart.setTitleFont(QFont("Segoe UI", 10, QFont.Bold))
    legend = chart.legend()
    legend.setLabelColor(_CHART_TEXT)
    legend.setAlignment(Qt.AlignBottom)
    chart.setMargins(QMargins(6, 6, 6, 6))
    return chart


def _make_chart_view(chart: QChart) -> QChartView:
    view = QChartView(chart)
    view.setRenderHint(QPainter.Antialiasing)
    view.setMinimumHeight(320)
    view.setStyleSheet(f"background: {_CARD_BG}; border: 1px solid {_CARD_BORDER}; border-radius: 4px;")
    return view


def _style_bar_axis(axis: QBarCategoryAxis | QValueAxis) -> None:
    axis.setLabelsColor(_CHART_TEXT)
    axis.setGridLineColor(_CHART_GRID)
    axis.setLinePenColor(_CHART_GRID)


def _stat_label(eff_id: int, value: Any) -> str:
    key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"Eff {eff_id}")
    try:
        v = float(value)
        if abs(v - int(v)) < 1e-9:
            val = str(int(v))
        else:
            val = f"{v:.2f}".rstrip("0").rstrip(".")
    except Exception:
        val = str(value)
    return f"{key} +{val}"


def _rune_quality_class(rune: Rune) -> int:
    origin = int(getattr(rune, "origin_class", 0) or 0)
    return origin if origin else int(rune.rune_class or 0)


_GEM_COLOR = "#1abc9c"  # teal for gem-swapped subs


def _rune_detail_text(rune: Rune, idx: int, eff: float) -> str:
    set_name = SET_NAMES.get(int(rune.set_id or 0), f"Set {int(rune.set_id or 0)}")
    cls_id = _rune_quality_class(rune)
    cls = _RUNE_CLASS_NAMES.get(cls_id, f"Kl. {cls_id}")
    lines = [
        f"Rank #{idx + 1} | Effizienz {eff:.2f}%",
        f"Rune ID: {int(rune.rune_id or 0)}",
        f"{set_name} | Slot {int(rune.slot_no or 0)} | +{int(rune.upgrade_curr or 0)} | {cls}",
        f"Main: {_stat_label(int(rune.pri_eff[0] or 0), rune.pri_eff[1] if len(rune.pri_eff) > 1 else 0)}",
    ]
    if rune.prefix_eff and int(rune.prefix_eff[0] or 0) != 0:
        lines.append(
            f"Prefix: {_stat_label(int(rune.prefix_eff[0] or 0), rune.prefix_eff[1] if len(rune.prefix_eff) > 1 else 0)}"
        )
    if rune.sec_eff:
        lines.append("Subs:")
        for sec in rune.sec_eff:
            if not sec:
                continue
            eff_id = int(sec[0] or 0)
            val = sec[1] if len(sec) > 1 else 0
            gem_flag = int(sec[2] or 0) if len(sec) > 2 else 0
            grind = int(sec[3] or 0) if len(sec) > 3 else 0
            total = int(val) + grind
            label = _stat_label(eff_id, total)
            extras = ""
            if grind:
                extras += f" <span style=\"color:#f39c12\">({int(val)}+{grind})</span>"
            if gem_flag:
                extras += " [Gem]"
                lines.append(f'  <span style="color:{_GEM_COLOR}">\u2022 {label}{extras}</span>')
            else:
                lines.append(f"  \u2022 {label}{extras}")
    return "<br>".join(lines)


def _artifact_detail_text(art: Artifact, idx: int, eff: float) -> str:
    slot_name = "Links" if int(art.slot or 0) == 1 else "Rechts" if int(art.slot or 0) == 2 else f"Slot {int(art.slot or 0)}"
    lines = [
        f"Rank #{idx + 1} | Effizienz {eff:.2f}%",
        f"Artefakt ID: {int(art.artifact_id or 0)}",
        f"{slot_name} | Typ {int(art.type_ or 0)} | Rank {int(art.rank or 0)} | +{int(art.level or 0)}",
    ]
    if art.pri_effect and len(art.pri_effect) >= 2:
        lines.append(f"Hauptstat: {_stat_label(int(art.pri_effect[0] or 0), art.pri_effect[1])}")
    if art.sec_effects:
        lines.append("Subs:")
        for sec in art.sec_effects:
            if not sec:
                continue
            eff_id = int(sec[0] or 0)
            val = sec[1] if len(sec) > 1 else 0
            upgrades = int(sec[2] or 0) if len(sec) > 2 else 0
            lines.append(f"  \u2022 {_stat_label(eff_id, val)} (Rolls {upgrades})")
    return "<br>".join(lines)


def _rune_curve_tooltip(item: Tuple[float, Any], idx: int, series_name: str) -> str:
    eff, payload = item
    rune, eff_curr, eff_hero, eff_legend = payload
    lines = [f"<b>{series_name}</b>", _rune_detail_text(rune, idx, eff)]
    lines.append(f"Aktuell: {eff_curr:.2f}%")
    lines.append(f"Hero max (Grind/Gem): {eff_hero:.2f}%")
    lines.append(f"Legend max (Grind/Gem): {eff_legend:.2f}%")
    return "<br>".join(lines)


def _artifact_curve_tooltip(item: Tuple[float, Any], idx: int, series_name: str) -> str:
    eff, art = item
    return f"<b>{series_name}</b><br>{_artifact_detail_text(art, idx, eff)}"


class _IndexedLineChartView(QChartView):
    def __init__(
        self,
        chart: QChart,
        series_entries: List[Tuple[str, QLineSeries, List[Tuple[float, Any]], Callable[[Tuple[float, Any], int, str], str]]],
        zoom_callback: Callable[[int], None] | None = None,
    ):
        super().__init__(chart)
        self._entries = series_entries
        self._zoom_callback = zoom_callback
        self._active_key: Optional[Tuple[str, int]] = None
        self._popup = QFrame(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self._popup.setStyleSheet(
            "QFrame { background: #1f242a; border: 1px solid #3a3f46; border-radius: 6px; }"
            "QLabel { color: #e6edf3; padding: 8px; font-size: 9pt; }"
        )
        self._popup_layout = QVBoxLayout(self._popup)
        self._popup_layout.setContentsMargins(0, 0, 0, 0)
        self._popup_label = QLabel("")
        self._popup_label.setTextFormat(Qt.RichText)
        self._popup_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._popup_label.setWordWrap(False)
        self._popup_layout.addWidget(self._popup_label)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(320)
        self.setStyleSheet(f"background: {_CARD_BG}; border: 1px solid {_CARD_BORDER}; border-radius: 4px;")
        self.setMouseTracking(True)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        plot = self.chart().plotArea()
        if not plot.contains(pos):
            self._active_key = None
            self._popup.hide()
            super().mouseMoveEvent(event)
            return
        if not self._entries:
            self._active_key = None
            self._popup.hide()
            super().mouseMoveEvent(event)
            return

        value = self.chart().mapToValue(pos, self._entries[0][1])
        idx = int(round(value.x())) - 1
        if idx < 0:
            self._active_key = None
            self._popup.hide()
            super().mouseMoveEvent(event)
            return

        closest: Optional[Tuple[float, str, int, Tuple[float, Any], Callable[[Tuple[float, Any], int, str], str], QLineSeries]] = None
        for name, series, items, tooltip_fn in self._entries:
            if idx >= len(items):
                continue
            point_eff = float(items[idx][0])
            point_pos = self.chart().mapToPosition(QPointF(float(idx + 1), point_eff), series)
            dx = abs(point_pos.x() - pos.x())
            dy = abs(point_pos.y() - pos.y())
            if dx > 10 or dy > 16:
                continue
            dist = dx + dy
            cand = (dist, name, idx, items[idx], tooltip_fn, series)
            if closest is None or dist < closest[0]:
                closest = cand

        if closest is None:
            self._active_key = None
            self._popup.hide()
            super().mouseMoveEvent(event)
            return

        _, series_name, i, item, tooltip_fn, _ = closest
        active_key = (series_name, i)
        if self._active_key != active_key:
            self._active_key = active_key
            self._popup_label.setText(tooltip_fn(item, i, series_name))
            self._popup.adjustSize()
            gpos = event.globalPosition().toPoint()
            popup_size = self._popup.sizeHint()
            screen = self.screen()
            if screen:
                avail = screen.availableGeometry()
                x = gpos.x() + 14
                y = gpos.y() + 14
                # Flip left if popup would exceed right edge
                if x + popup_size.width() > avail.right():
                    x = gpos.x() - popup_size.width() - 14
                # Flip up if popup would exceed bottom edge
                if y + popup_size.height() > avail.bottom():
                    y = gpos.y() - popup_size.height() - 14
                self._popup.move(x, y)
            else:
                self._popup.move(gpos.x() + 14, gpos.y() + 14)
            self._popup.show()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:
        self._active_key = None
        self._popup.hide()
        super().leaveEvent(event)

    def wheelEvent(self, event) -> None:
        if self._zoom_callback is None:
            super().wheelEvent(event)
            return
        if not (event.modifiers() & Qt.ControlModifier):
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if delta == 0:
            return
        step = -50 if delta > 0 else 50
        self._zoom_callback(step)
        event.accept()


# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Overview widget
# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class OverviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {_BG};")
        self._account: Optional[AccountData] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(8)

        # top section: cards left, rune set distribution right
        self._top_overview_row = QHBoxLayout()
        self._top_overview_row.setSpacing(8)
        outer.addLayout(self._top_overview_row)

        self._cards_host = QWidget()
        self._cards_host.setStyleSheet(f"background: {_BG};")
        self._cards_grid = QGridLayout(self._cards_host)
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        self._cards_grid.setSpacing(8)
        self._top_overview_row.addWidget(self._cards_host, 3)

        self._card_units = _SummaryCard("Monster", "\u2014")
        self._card_runes = _SummaryCard("Runen", "\u2014")
        self._card_artifacts = _SummaryCard("Artefakte", "\u2014")
        self._card_rune_avg = _SummaryCard("Runen Eff. (%)", "\u2014", _GREEN)
        self._card_art_avg_t1 = _SummaryCard("Attribut-Artefakt Eff. (%)", "—", _PURPLE)
        self._card_art_avg_t2 = _SummaryCard("Typ-Artefakt Eff. (%)", "—", _PURPLE)
        self._card_rune_best = _SummaryCard("Beste Rune", "\u2014", _ORANGE)

        self._set_eff_cards: dict[int, _SummaryCard] = {}
        for sid in _IMPORTANT_SET_IDS:
            name = SET_NAMES.get(sid, f"Set {sid}")
            card = _SummaryCard(f"{name} Eff. (%)", "\u2014", _GREEN)
            self._set_eff_cards[sid] = card

        # row 1: count cards
        self._cards_grid.addWidget(self._card_units, 0, 0)
        self._cards_grid.addWidget(self._card_runes, 0, 1)
        self._cards_grid.addWidget(self._card_artifacts, 0, 2)

        # row 2: core efficiency cards
        self._cards_grid.addWidget(self._card_rune_avg, 1, 0)
        self._cards_grid.addWidget(self._card_art_avg_t1, 1, 1)
        self._cards_grid.addWidget(self._card_art_avg_t2, 1, 2)
        self._cards_grid.addWidget(self._card_rune_best, 1, 3)

        # remaining rows: important set efficiencies
        for i, sid in enumerate(_IMPORTANT_SET_IDS):
            row = 2 + (i // 4)
            col = i % 4
            self._cards_grid.addWidget(self._set_eff_cards[sid], row, col)

        self._rune_set_host = QWidget()
        self._rune_set_host_layout = QVBoxLayout(self._rune_set_host)
        self._rune_set_host_layout.setContentsMargins(0, 0, 0, 0)
        self._rune_set_host_layout.setSpacing(0)
        self._top_overview_row.addWidget(self._rune_set_host, 2)

        controls_row = QHBoxLayout()
        controls_row.setSpacing(8)
        lbl_top_n = QLabel("Runen-Chart Top:")
        lbl_top_n.setStyleSheet(f"color: {_TEXT_DIM};")
        self._top_n_spin = QSpinBox()
        self._top_n_spin.setRange(100, 1000)
        self._top_n_spin.setSingleStep(50)
        self._top_n_spin.setValue(400)
        self._top_n_spin.setStyleSheet(
            f"color: {_TEXT}; background: {_CARD_BG}; border: 1px solid {_CARD_BORDER};"
        )
        self._top_n_spin.valueChanged.connect(self._on_top_n_changed)
        controls_row.addWidget(lbl_top_n)
        controls_row.addWidget(self._top_n_spin)
        controls_row.addStretch(1)
        outer.addLayout(controls_row)

        # â”€â”€ scrollable chart grid â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {_BG}; }}")
        outer.addWidget(scroll, 1)

        container = QWidget()
        container.setStyleSheet(f"background: {_BG};")
        self._grid = QGridLayout(container)
        self._grid.setSpacing(8)
        scroll.setWidget(container)

        # placeholders for charts
        self._rune_eff_view: QChartView | None = None
        self._rune_set_view: QChartView | None = None
        self._art_eff_view: QChartView | None = None
        self._set_eff_view: QChartView | None = None

    # â”€â”€ public API â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def set_data(self, account: AccountData) -> None:
        self._account = account
        self._update_cards(account)
        self._build_charts(account)

    # â”€â”€ cards â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _update_cards(self, acc: AccountData) -> None:
        n_units = len(acc.units_by_id)
        filtered_runes = [r for r in acc.runes if int(r.upgrade_curr or 0) >= 12]
        n_runes = len(filtered_runes)
        n_arts = len(acc.artifacts)

        self._card_units.update_value(str(n_units))
        self._card_runes.update_value(str(n_runes))
        self._card_artifacts.update_value(str(n_arts))

        r_effs = rune_efficiencies(filtered_runes) if filtered_runes else []
        artifacts_t1 = [a for a in acc.artifacts if int(a.type_ or 0) == 1 and a.sec_effects]
        artifacts_t2 = [a for a in acc.artifacts if int(a.type_ or 0) == 2 and a.sec_effects]
        a_effs_t1 = [artifact_efficiency(a) for a in artifacts_t1]
        a_effs_t2 = [artifact_efficiency(a) for a in artifacts_t2]

        if r_effs:
            avg = sum(r_effs) / len(r_effs)
            best = max(r_effs)
            self._card_rune_avg.update_value(f"{avg:.1f}%")
            self._card_rune_best.update_value(f"{best:.1f}%")
        if a_effs_t1:
            avg = sum(a_effs_t1) / len(a_effs_t1)
            self._card_art_avg_t1.update_value(f"{avg:.1f}%")
        else:
            self._card_art_avg_t1.update_value("—")

        if a_effs_t2:
            avg = sum(a_effs_t2) / len(a_effs_t2)
            self._card_art_avg_t2.update_value(f"{avg:.1f}%")
        else:
            self._card_art_avg_t2.update_value("—")

        for sid, card in self._set_eff_cards.items():
            vals = [rune_efficiency(r) for r in filtered_runes if int(r.set_id or 0) == sid]
            if vals:
                card.update_value(f"{(sum(vals) / len(vals)):.1f}%")
            else:
                card.update_value("\u2014")

    # â”€â”€ charts â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _clear_grid(self) -> None:
        while self._rune_set_host_layout.count():
            item = self._rune_set_host_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _build_charts(self, acc: AccountData) -> None:
        self._clear_grid()

        filtered_runes = [r for r in acc.runes if int(r.upgrade_curr or 0) >= 12]
        rune_items = (
            [(rune_efficiency(r), r) for r in filtered_runes]
            if filtered_runes else []
        )
        art_items = (
            [(artifact_efficiency(a), a) for a in acc.artifacts if a.sec_effects]
            if acc.artifacts else []
        )

        self._rune_eff_view = self._build_rune_eff_chart(rune_items)
        self._rune_set_view = self._build_rune_set_chart(filtered_runes)
        self._art_eff_view = self._build_art_eff_chart(art_items)
        self._set_eff_view = self._build_important_set_eff_chart(rune_items)

        self._rune_set_view.setMinimumHeight(300)
        self._rune_set_host_layout.addWidget(self._rune_set_view, 1)

        self._grid.addWidget(self._rune_eff_view, 0, 0, 1, 2)
        self._grid.addWidget(self._art_eff_view, 1, 0, 1, 2)
        self._grid.addWidget(self._set_eff_view, 2, 0, 1, 2)

    def _on_top_n_changed(self, _value: int) -> None:
        if self._account is not None:
            self._build_charts(self._account)

    def _change_top_n(self, delta: int) -> None:
        cur = int(self._top_n_spin.value())
        nxt = max(100, min(1000, cur + int(delta)))
        if nxt != cur:
            self._top_n_spin.setValue(nxt)

    def _build_rune_eff_chart(self, items: List[Tuple[float, Rune]]) -> QChartView:
        top_n = int(self._top_n_spin.value())
        ranked_base = sorted(items, key=lambda x: x[0], reverse=True)[:top_n]
        ranked_payload: List[Tuple[Rune, float, float, float]] = []
        for curr_eff, rune in ranked_base:
            hero_eff = rune_efficiency_max(rune, "hero")
            legend_eff = rune_efficiency_max(rune, "legend")
            ranked_payload.append((rune, curr_eff, hero_eff, legend_eff))
        n = len(ranked_payload)

        current_items: List[Tuple[float, Any]] = []
        hero_items: List[Tuple[float, Any]] = []
        legend_items: List[Tuple[float, Any]] = []
        for rune, curr_eff, hero_eff, legend_eff in ranked_payload:
            payload = (rune, curr_eff, hero_eff, legend_eff)
            current_items.append((curr_eff, payload))
            hero_items.append((hero_eff, payload))
            legend_items.append((legend_eff, payload))

        series_current = QLineSeries()
        series_current.setName("Aktuell")
        series_current.setColor(QColor("#f39c12"))
        for idx, (eff, _) in enumerate(current_items, start=1):
            series_current.append(float(idx), float(eff))

        series_hero = QLineSeries()
        series_hero.setName("Hero max")
        series_hero.setColor(QColor("#4aa3ff"))
        for idx, (eff, _) in enumerate(hero_items, start=1):
            series_hero.append(float(idx), float(eff))

        series_legend = QLineSeries()
        series_legend.setName("Legend max")
        series_legend.setColor(QColor("#2ecc71"))
        for idx, (eff, _) in enumerate(legend_items, start=1):
            series_legend.append(float(idx), float(eff))

        chart = _make_chart(f"Runen Effizienz (Top {top_n})")
        chart.addSeries(series_current)
        chart.addSeries(series_hero)
        chart.addSeries(series_legend)
        chart.legend().setVisible(True)

        ax_x = QValueAxis()
        ax_x.setLabelFormat("%d")
        ax_x.setRange(1, max(n, 1))
        ax_x.setTitleText("Anzahl / Rank")
        _style_bar_axis(ax_x)
        chart.addAxis(ax_x, Qt.AlignBottom)
        series_current.attachAxis(ax_x)
        series_hero.attachAxis(ax_x)
        series_legend.attachAxis(ax_x)

        ax_y = QValueAxis()
        all_vals = [x[0] for x in current_items] + [x[0] for x in hero_items] + [x[0] for x in legend_items]
        if all_vals:
            min_eff = min(all_vals)
            max_eff = max(all_vals)
            pad = max(6.0, (max_eff - min_eff) * 0.12)
            ax_y.setRange(max(0.0, min_eff - pad), max_eff + pad)
        else:
            ax_y.setRange(0, 100)
        ax_y.setLabelFormat("%.1f")
        ax_y.setTitleText("Effizienz (%)")
        _style_bar_axis(ax_y)
        chart.addAxis(ax_y, Qt.AlignLeft)
        series_current.attachAxis(ax_y)
        series_hero.attachAxis(ax_y)
        series_legend.attachAxis(ax_y)

        return _IndexedLineChartView(
            chart,
            [
                ("Aktuell", series_current, current_items, _rune_curve_tooltip),
                ("Hero max", series_hero, hero_items, _rune_curve_tooltip),
                ("Legend max", series_legend, legend_items, _rune_curve_tooltip),
            ],
            zoom_callback=self._change_top_n,
        )

    def _build_rune_set_chart(self, runes: List[Rune]) -> QChartView:
        set_counts: Counter = Counter()
        for r in runes:
            sid = int(r.set_id or 0)
            name = SET_NAMES.get(sid, f"Set {sid}")
            set_counts[name] += 1

        top = set_counts.most_common(10)
        other = sum(set_counts.values()) - sum(c for _, c in top)

        series = QPieSeries()
        palette = [
            "#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
            "#1abc9c", "#e67e22", "#34495e", "#d35400", "#c0392b",
        ]
        for i, (name, count) in enumerate(top):
            slc = series.append(f"{name} ({count})", count)
            slc.setColor(QColor(palette[i % len(palette)]))
            slc.setLabelVisible(True)
            slc.setLabelColor(_CHART_TEXT)
        if other > 0:
            slc = series.append(f"Andere ({other})", other)
            slc.setColor(QColor("#7f8c8d"))
            slc.setLabelVisible(True)
            slc.setLabelColor(_CHART_TEXT)

        chart = _make_chart("Runen Set Verteilung")
        chart.addSeries(series)
        chart.legend().setVisible(False)

        return _make_chart_view(chart)

    def _build_important_set_eff_chart(self, items: List[Tuple[float, Rune]]) -> QChartView:
        top_n = int(self._top_n_spin.value())
        chart = _make_chart(f"Wichtige Sets Effizienz (Top {top_n})")
        chart.legend().setVisible(True)

        set_colors = {
            13: "#9b59b6",  # Violent
            15: "#95a5a6",  # Will
            3: "#3498db",   # Swift
            10: "#f39c12",  # Despair
            18: "#e74c3c",  # Destroy
            14: "#1abc9c",  # Nemesis
        }

        entries: List[Tuple[str, QLineSeries, List[Tuple[float, Any]], Callable[[Tuple[float, Any], int, str], str]]] = []
        max_len = 0
        all_vals: List[float] = []
        for sid in _IMPORTANT_SET_IDS:
            set_name = SET_NAMES.get(sid, f"Set {sid}")
            set_items = [(eff, r) for eff, r in items if int(r.set_id or 0) == sid]
            ranked = sorted(set_items, key=lambda x: x[0], reverse=True)[:top_n]
            if not ranked:
                continue
            s = QLineSeries()
            s.setName(set_name)
            s.setColor(QColor(set_colors.get(sid, "#bbbbbb")))
            wrapped: List[Tuple[float, Any]] = []
            for idx, (eff, rune) in enumerate(ranked, start=1):
                payload = (rune, eff, rune_efficiency_max(rune, "hero"), rune_efficiency_max(rune, "legend"))
                wrapped.append((eff, payload))
                s.append(float(idx), float(eff))
                all_vals.append(float(eff))
            chart.addSeries(s)
            entries.append((set_name, s, wrapped, _rune_curve_tooltip))
            max_len = max(max_len, len(ranked))

        ax_x = QValueAxis()
        ax_x.setLabelFormat("%d")
        ax_x.setRange(1, max(max_len, 1))
        ax_x.setTitleText("Anzahl / Rank")
        _style_bar_axis(ax_x)
        chart.addAxis(ax_x, Qt.AlignBottom)
        for _, s, _, _ in entries:
            s.attachAxis(ax_x)

        ax_y = QValueAxis()
        if all_vals:
            min_eff = min(all_vals)
            max_eff = max(all_vals)
            pad = max(6.0, (max_eff - min_eff) * 0.12)
            ax_y.setRange(max(0.0, min_eff - pad), max_eff + pad)
        else:
            ax_y.setRange(0, 100)
        ax_y.setLabelFormat("%.1f")
        ax_y.setTitleText("Effizienz (%)")
        _style_bar_axis(ax_y)
        chart.addAxis(ax_y, Qt.AlignLeft)
        for _, s, _, _ in entries:
            s.attachAxis(ax_y)

        return _IndexedLineChartView(chart, entries, zoom_callback=self._change_top_n)

    def _build_art_eff_chart(self, items: List[Tuple[float, Artifact]]) -> QChartView:
        top_n = int(self._top_n_spin.value())
        by_type: dict[int, List[Tuple[float, Artifact]]] = {1: [], 2: []}
        for eff, art in items:
            t = int(art.type_ or 0)
            if t in by_type:
                by_type[t].append((eff, art))

        chart = _make_chart(f"Artefakt Effizienz (Top {top_n})")
        chart.legend().setVisible(True)

        entries: List[Tuple[str, QLineSeries, List[Tuple[float, Any]], Callable[[Tuple[float, Any], int, str], str]]] = []
        max_len = 0
        all_vals: List[float] = []
        colors = {1: "#1abc9c", 2: "#4aa3ff"}
        names = {1: "Attribut-Artefakt", 2: "Typ-Artefakt"}

        for t in (1, 2):
            ranked = sorted(by_type[t], key=lambda x: x[0], reverse=True)[:top_n]
            if not ranked:
                continue
            s = QLineSeries()
            s.setName(names[t])
            s.setColor(QColor(colors[t]))
            wrapped: List[Tuple[float, Any]] = []
            for idx, (eff, art) in enumerate(ranked, start=1):
                wrapped.append((eff, art))
                s.append(float(idx), float(eff))
                all_vals.append(float(eff))
            chart.addSeries(s)
            entries.append((names[t], s, wrapped, _artifact_curve_tooltip))
            max_len = max(max_len, len(ranked))

        ax_x = QValueAxis()
        ax_x.setLabelFormat("%d")
        ax_x.setRange(1, max(max_len, 1))
        ax_x.setTitleText("Anzahl / Rank")
        _style_bar_axis(ax_x)
        chart.addAxis(ax_x, Qt.AlignBottom)
        for _, s, _, _ in entries:
            s.attachAxis(ax_x)

        ax_y = QValueAxis()
        if all_vals:
            min_eff = min(all_vals)
            max_eff = max(all_vals)
            pad = max(5.0, (max_eff - min_eff) * 0.12)
            ax_y.setRange(max(0.0, min_eff - pad), max_eff + pad)
        else:
            ax_y.setRange(0, 100)
        ax_y.setLabelFormat("%.1f")
        ax_y.setTitleText("Effizienz (%)")
        _style_bar_axis(ax_y)
        chart.addAxis(ax_y, Qt.AlignLeft)
        for _, s, _, _ in entries:
            s.attachAxis(ax_y)

        return _IndexedLineChartView(chart, entries, zoom_callback=self._change_top_n)


