"""Account overview dashboard with summary cards and charts."""
from __future__ import annotations

import time
from collections import Counter
from typing import Callable, List, Optional, Tuple, Any

from PySide6.QtCore import Qt, QMargins, QPointF, QPropertyAnimation, QEasingCurve, QVariantAnimation, QEvent
from PySide6.QtGui import QColor, QFont, QPainter, QFontMetrics, QCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QScrollArea, QApplication,
    QGridLayout, QComboBox, QGraphicsDropShadowEffect,
)
from PySide6.QtCharts import (
    QChart, QChartView, QBarCategoryAxis,
    QValueAxis, QPieSeries, QLineSeries, QPieSlice,
)

from app.domain.models import AccountData, Rune, Artifact
from app.domain.presets import SET_NAMES, EFFECT_ID_TO_MAINSTAT_KEY
from app.domain.artifact_effects import (
    artifact_rank_label,
    artifact_effect_text,
    ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID,
)
from app.engine.efficiency import (
    rune_efficiencies,
    rune_efficiency,
    artifact_efficiency,
    rune_efficiency_max,
)
from app.i18n import tr
from app.ui.dpi import dp

# -- colours (from active theme) -----------------------------
from app.ui import theme as _theme

_BG = _theme.C["bg"]
_CARD_BG = _theme.C["card_bg"]
_CARD_BORDER = _theme.C["card_border"]
_TEXT = _theme.C["text"]
_TEXT_DIM = _theme.C["text_dim"]
_ACCENT = _theme.C["overview_accent"]
_GREEN = _theme.C["overview_green"]
_ORANGE = _theme.C["overview_orange"]
_RED = _theme.C["overview_red"]
_PURPLE = _theme.C["overview_purple"]
_CHART_BG = QColor(_theme.C["chart_bg"])
_CHART_TEXT = QColor(_theme.C["chart_text"])
_CHART_GRID = QColor(_theme.C["chart_grid"])


def _refresh_overview_colors() -> None:
    """Re-read colours from the active theme (call after theme switch)."""
    global _BG, _CARD_BG, _CARD_BORDER, _TEXT, _TEXT_DIM
    global _ACCENT, _GREEN, _ORANGE, _RED, _PURPLE
    global _CHART_BG, _CHART_TEXT, _CHART_GRID
    _BG = _theme.C["bg"]
    _CARD_BG = _theme.C["card_bg"]
    _CARD_BORDER = _theme.C["card_border"]
    _TEXT = _theme.C["text"]
    _TEXT_DIM = _theme.C["text_dim"]
    _ACCENT = _theme.C["overview_accent"]
    _GREEN = _theme.C["overview_green"]
    _ORANGE = _theme.C["overview_orange"]
    _RED = _theme.C["overview_red"]
    _PURPLE = _theme.C["overview_purple"]
    _CHART_BG = QColor(_theme.C["chart_bg"])
    _CHART_TEXT = QColor(_theme.C["chart_text"])
    _CHART_GRID = QColor(_theme.C["chart_grid"])

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


# ------------------------------------------------------------
# Summary card
# ------------------------------------------------------------
class _SummaryCard(QFrame):
    def __init__(self, title: str, value: str, accent: str | None = None, parent=None):
        super().__init__(parent)
        if accent is None:
            accent = _theme.C["overview_accent"]
        self._accent = accent
        self.setObjectName("SummaryCard")
        self.setFrameShape(QFrame.NoFrame)

        c = _theme.C
        is_cp = _theme.current_name == "cyberpunk"
        if is_cp:
            self.setStyleSheet(f"""
                QFrame#SummaryCard {{
                    background: {c['card_bg']};
                    border: 1px solid {c['card_border']};
                    border-radius: 8px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QFrame#SummaryCard {{
                    background: {c['card_bg']};
                    border: 1px solid {c['card_border']};
                    border-radius: 10px;
                }}
            """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(dp(14), dp(12), dp(14), dp(12))
        layout.setSpacing(dp(4))

        lbl_title = QLabel(title)
        title_color = c['accent'] if is_cp else c['text_dim']
        title_weight = "font-weight: bold;" if is_cp else ""
        lbl_title.setStyleSheet(
            f"color: {title_color}; font-size: 9pt; border: none; background: transparent;"
            f" text-transform: {c['card_title_transform']}; letter-spacing: {c['card_title_spacing']};"
            f" {title_weight}"
        )
        lbl_title.setAlignment(Qt.AlignLeft | Qt.AlignBottom)
        layout.addWidget(lbl_title)

        mono = c["mono_font"]
        font_css = f"font-family: {mono};" if mono else ""
        val_size = "24pt" if is_cp else "18pt"
        lbl_val = QLabel(value)
        lbl_val.setStyleSheet(
            f"color: {accent}; font-size: {val_size}; font-weight: bold;"
            f" border: none; background: transparent; {font_css}"
        )
        lbl_val.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(lbl_val)

        self._lbl_sub = QLabel("")
        self._lbl_sub.setStyleSheet(
            f"color: {c['text_dim']}; font-size: 7pt; border: none; background: transparent;"
        )
        self._lbl_sub.setAlignment(Qt.AlignLeft)
        self._lbl_sub.setVisible(False)
        layout.addWidget(self._lbl_sub)

        self._lbl_val = lbl_val
        self._lbl_title = lbl_title

        # Drop-shadow effect
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(dp(12))
        shadow.setOffset(0, dp(3))
        shadow.setColor(QColor(0, 0, 0, 70))
        self.setGraphicsEffect(shadow)
        self._shadow = shadow

        # Animation for hover glow
        self._anim_shadow = QPropertyAnimation(shadow, b"blurRadius", self)
        self._anim_shadow.setDuration(200)
        self._anim_shadow.setEasingCurve(QEasingCurve.OutCubic)

    def enterEvent(self, event) -> None:  # noqa: N802
        accent = QColor(self._accent)
        accent.setAlpha(100)
        self._shadow.setColor(accent)
        self._anim_shadow.stop()
        self._anim_shadow.setStartValue(int(self._shadow.blurRadius()))
        self._anim_shadow.setEndValue(dp(24))
        self._anim_shadow.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._shadow.setColor(QColor(0, 0, 0, 70))
        self._anim_shadow.stop()
        self._anim_shadow.setStartValue(int(self._shadow.blurRadius()))
        self._anim_shadow.setEndValue(dp(12))
        self._anim_shadow.start()
        super().leaveEvent(event)

    def update_value(self, value: str, accent: str | None = None):
        if accent:
            mono = _theme.C["mono_font"]
            font_css = f"font-family: {mono};" if mono else ""
            val_size = "24pt" if _theme.current_name == "cyberpunk" else "18pt"
            self._lbl_val.setStyleSheet(
                f"color: {accent}; font-size: {val_size}; font-weight: bold;"
                f" border: none; background: transparent; {font_css}"
            )
        self._animate_value(value)

    def _animate_value(self, new_text: str) -> None:
        """Animate numeric value change; fall back to instant set for non-numbers."""
        # Stop any running counter animation
        if hasattr(self, "_counter_anim") and self._counter_anim:
            self._counter_anim.stop()
            self._counter_anim = None
        try:
            def _parse_numeric(text: str) -> tuple[float, str, bool, int, str | None]:
                raw = text.strip()
                suffix_local = "%"
                if raw.endswith("%"):
                    raw = raw[:-1].strip()
                else:
                    suffix_local = ""
                if not raw:
                    raise ValueError("empty numeric text")

                last_dot = raw.rfind(".")
                last_comma = raw.rfind(",")
                dec_sep: str | None = None

                if last_dot >= 0 and last_comma >= 0:
                    dec_sep = "." if last_dot > last_comma else ","
                elif last_dot >= 0:
                    after = raw[last_dot + 1:]
                    if 0 < len(after) <= 2:
                        dec_sep = "."
                elif last_comma >= 0:
                    after = raw[last_comma + 1:]
                    if 0 < len(after) <= 2:
                        dec_sep = ","

                if dec_sep == ".":
                    normalized = raw.replace(",", "")
                    decimals = len(raw.rsplit(".", 1)[1])
                elif dec_sep == ",":
                    normalized = raw.replace(".", "").replace(",", ".")
                    decimals = len(raw.rsplit(",", 1)[1])
                else:
                    normalized = raw.replace(".", "").replace(",", "")
                    decimals = 0

                value = float(normalized)
                use_float_local = dec_sep is not None
                group_sep: str | None = None
                if not use_float_local:
                    if "." in raw and "," not in raw:
                        group_sep = "."
                    elif "," in raw and "." not in raw:
                        group_sep = ","
                return value, suffix_local, use_float_local, decimals, group_sep

            new_val, suffix, use_float, decimals, group_sep = _parse_numeric(new_text)
            old_val, _, _, _, _ = _parse_numeric(self._lbl_val.text())
            if old_val == new_val:
                self._lbl_val.setText(new_text)
                return
            anim = QVariantAnimation(self)
            anim.setStartValue(old_val)
            anim.setEndValue(new_val)
            anim.setDuration(500)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _tick(v: float) -> None:
                if use_float:
                    prec = max(1, min(2, int(decimals)))
                    txt = f"{v:.{prec}f}"
                    if "," in new_text and "." not in new_text:
                        txt = txt.replace(".", ",")
                    self._lbl_val.setText(f"{txt}{suffix}")
                else:
                    iv = int(round(v))
                    if group_sep:
                        txt = f"{iv:,}"
                        if group_sep == ".":
                            txt = txt.replace(",", ".")
                    else:
                        txt = str(iv)
                    self._lbl_val.setText(f"{txt}{suffix}")

            anim.valueChanged.connect(_tick)
            anim.start()
            self._counter_anim = anim
        except (ValueError, AttributeError):
            self._lbl_val.setText(new_text)

    def set_subtitle(self, text: str) -> None:
        self._lbl_sub.setText(text)
        self._lbl_sub.setVisible(bool(text))

    def update_title(self, title: str) -> None:
        self._lbl_title.setText(title)


# ------------------------------------------------------------
# Chart helpers
# ------------------------------------------------------------
def _make_chart(title: str) -> QChart:
    chart = QChart()
    chart.setTitle(title)
    chart.setAnimationOptions(QChart.SeriesAnimations)
    chart.setBackgroundBrush(QColor(_theme.C["chart_bg"]))
    chart_text = QColor(_theme.C["chart_text"])
    chart.setTitleBrush(chart_text)
    title_font = QFont()
    title_font.setPointSize(9)
    title_font.setWeight(QFont.Bold)
    chart.setTitleFont(title_font)
    legend = chart.legend()
    legend.setLabelColor(chart_text)
    legend_font = QFont()
    legend_font.setPointSize(8)
    legend.setFont(legend_font)
    legend.setAlignment(Qt.AlignBottom)
    chart.setMargins(QMargins(10, 8, 10, 8))
    return chart


def _make_chart_view(chart: QChart) -> QChartView:
    view = QChartView(chart)
    view.setRenderHint(QPainter.Antialiasing)
    view.setMinimumHeight(dp(320))
    view.setStyleSheet(f"background: {_theme.C['bg']}; border: 1px solid {_theme.C['card_border']}; border-radius: 8px;")
    return view


def _style_bar_axis(axis: QBarCategoryAxis | QValueAxis) -> None:
    axis.setLabelsColor(QColor(_theme.C["chart_text"]))
    axis.setGridLineColor(QColor(_theme.C["chart_grid"]))
    axis.setLinePenColor(QColor(_theme.C["chart_grid"]))


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


def _mainstat_key(eff_id: int) -> str:
    return EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"Eff {int(eff_id or 0)}")


def _artifact_mainstat_label(eff_id: int, value: Any) -> str:
    focus = ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID.get(int(eff_id or 0))
    if focus:
        try:
            v = float(value)
            val = str(int(v)) if abs(v - int(v)) < 1e-9 else f"{v:.2f}".rstrip("0").rstrip(".")
        except Exception:
            val = str(value)
        return f"{focus} +{val}"
    return artifact_effect_text(int(eff_id or 0), value, fallback_prefix="Effekt")


def _rune_quality_class(rune: Rune) -> int:
    origin = int(getattr(rune, "origin_class", 0) or 0)
    return origin if origin else int(rune.rune_class or 0)


def _rune_quality_tier_key(rune: Rune) -> str:
    cls_id = _rune_quality_class(rune)
    if cls_id in (5, 6, 15, 16):
        return "legend"
    if cls_id in (4, 14):
        return "hero"
    if cls_id in (3, 13):
        return "rare"
    if cls_id in (2, 12):
        return "magic"
    if cls_id in (1, 11):
        return "normal"
    return "other"


def _artifact_quality_tier_key(art: Artifact) -> str:
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    if base_rank >= 5:
        return "legend"
    if base_rank == 4:
        return "hero"
    if base_rank == 3:
        return "rare"
    if base_rank == 2:
        return "magic"
    if base_rank == 1:
        return "normal"
    return "other"


_GEM_COLOR = "#1abc9c"  # teal for gem-swapped subs


def _rune_detail_text(rune: Rune, idx: int, eff: float) -> str:
    set_name = SET_NAMES.get(int(rune.set_id or 0), f"Set {int(rune.set_id or 0)}")
    cls_id = _rune_quality_class(rune)
    cls = _RUNE_CLASS_NAMES.get(cls_id, f"{tr('ui.class_short')} {cls_id}")
    lines = [
        f"{tr('overview.rank', idx=idx + 1)} | {tr('overview.efficiency')} {eff:.2f}%",
        f"{tr('ui.rune_id')}: {int(rune.rune_id or 0)}",
        f"{set_name} | {tr('ui.slot')} {int(rune.slot_no or 0)} | +{int(rune.upgrade_curr or 0)} | {cls}",
        f"{tr('ui.main')}: {_stat_label(int(rune.pri_eff[0] or 0), rune.pri_eff[1] if len(rune.pri_eff) > 1 else 0)}",
    ]
    if rune.prefix_eff and int(rune.prefix_eff[0] or 0) != 0:
        lines.append(
            f"{tr('ui.prefix')}: {_stat_label(int(rune.prefix_eff[0] or 0), rune.prefix_eff[1] if len(rune.prefix_eff) > 1 else 0)}"
        )
    if rune.sec_eff:
        lines.append(f"<b>{tr('ui.subs')}:</b>")
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
                lines.append(f'<span style="color:{_GEM_COLOR}">&nbsp;&bull;&nbsp;{label}{extras}</span>')
            else:
                lines.append(f"&nbsp;&bull;&nbsp;{label}{extras}")
    return "<br>".join(lines)


def _artifact_detail_text(art: Artifact, idx: int, eff: float) -> str:
    slot_name = tr("overview.slot_left") if int(art.slot or 0) == 1 else tr("overview.slot_right") if int(art.slot or 0) == 2 else f"Slot {int(art.slot or 0)}"
    type_name = (
        tr("art_opt.type_attribute") if int(art.type_ or 0) == 1
        else tr("art_opt.type_type") if int(art.type_ or 0) == 2
        else f"{tr('artifact.type')} {int(art.type_ or 0)}"
    )
    base_rank = int(getattr(art, "original_rank", 0) or 0)
    if base_rank <= 0:
        base_rank = int(art.rank or 0)
    quality = artifact_rank_label(base_rank, fallback_prefix="Rank")
    lines = [
        f"{tr('overview.rank', idx=idx + 1)} | {tr('overview.efficiency')} {eff:.2f}%",
        f"{tr('ui.artifact_id')}: {int(art.artifact_id or 0)}",
        f"{tr('overview.quality')} {quality} | +{int(art.level or 0)}",
    ]
    if art.pri_effect and len(art.pri_effect) >= 2:
        lines.append(f"{tr('overview.mainstat')} {_artifact_mainstat_label(int(art.pri_effect[0] or 0), art.pri_effect[1])}")
    if art.sec_effects:
        lines.append(f"<b>{tr('ui.subs')}:</b>")
        for sec in art.sec_effects:
            if not sec:
                continue
            eff_id = int(sec[0] or 0)
            val = sec[1] if len(sec) > 1 else 0
            upgrades = int(sec[2] or 0) if len(sec) > 2 else 0
            # Artifact export payload keeps conversion metadata in trailing fields.
            # Non-zero values indicate a transformed/changed substat and should be highlighted
            # analogous to rune gem-swaps.
            converted_flag = (
                (int(sec[3] or 0) > 0 if len(sec) > 3 else False)
                or (int(sec[4] or 0) > 0 if len(sec) > 4 else False)
            )
            text = f"{artifact_effect_text(eff_id, val, fallback_prefix='Effekt')} ({tr('ui.rolls', n=upgrades)})"
            if converted_flag:
                lines.append(f'<span style="color:{_GEM_COLOR}">&nbsp;&bull;&nbsp;{text}</span>')
            else:
                lines.append(f"&nbsp;&bull;&nbsp;{text}")
    return "<br>".join(lines)


def _rune_curve_tooltip(item: Tuple[float, Any], idx: int, series_name: str) -> str:
    eff, payload = item
    rune, eff_curr, eff_hero, eff_legend = payload
    lines = [f"<b>{series_name}</b>", _rune_detail_text(rune, idx, eff)]
    lines.append(tr("overview.current_eff", eff=f"{eff_curr:.2f}"))
    lines.append(tr("overview.hero_max", eff=f"{eff_hero:.2f}"))
    lines.append(tr("overview.legend_max", eff=f"{eff_legend:.2f}"))
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
            f"QFrame {{ background: {_theme.C['popup_bg']}; border: 1px solid {_theme.C['popup_border']}; border-radius: 5px; }}"
            "QLabel { color: #e6edf3; padding: 6px 10px; }"
        )
        self._popup_layout = QVBoxLayout(self._popup)
        self._popup_layout.setContentsMargins(0, 0, 0, 0)
        self._popup_label = QLabel("")
        self._popup_label.setTextFormat(Qt.RichText)
        self._popup_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._popup_label.setWordWrap(False)
        self._popup_layout.addWidget(self._popup_label)
        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(dp(320))
        self.setStyleSheet(f"background: {_theme.C['card_bg']}; border: 1px solid {_theme.C['card_border']}; border-radius: 4px;")
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


class _RuneSetDrilldownChartView(QChartView):
    """Interactive rune pie chart: sets -> slots -> main stats."""

    _LEVEL_SETS = "sets"
    _LEVEL_SLOTS = "slots"
    _LEVEL_MAIN = "main"

    def __init__(self, runes: List[Rune], parent=None):
        chart = _make_chart(tr("overview.set_dist_chart"))
        super().__init__(chart, parent)
        self._all_runes = list(runes or [])
        self._level = self._LEVEL_SETS
        self._context_label = ""
        self._active_runes: List[Rune] = list(self._all_runes)
        self._active_slot = 0
        self._series: Optional[QPieSeries] = None
        self._slice_meta: dict[int, dict[str, Any]] = {}
        self._hovered_slice: Optional[QPieSlice] = None
        self._current_pie_size = 0.64
        self._current_hole_size = 0.30
        self._last_slice_click_ts = 0.0
        self._palette = [
            "#3fa9f5", "#f46049", "#31c273", "#f5a623", "#8e6fd1",
            "#17bebb", "#ff8a3d", "#4e79a7", "#d45087", "#7f8c8d",
        ]

        self.setRenderHint(QPainter.Antialiasing)
        self.setMinimumHeight(dp(350))
        self.setStyleSheet(
            f"background: {_theme.C['bg']}; border: 1px solid {_theme.C['card_border']}; border-radius: 8px;"
        )
        self.setMouseTracking(True)
        self._init_overlay_ui()

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._rebuild_sets_level()

    def _init_overlay_ui(self) -> None:
        self._crumb_label = QLabel(self)
        self._crumb_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._crumb_label.setStyleSheet(
            f"color: {_theme.C['text_dim']}; font-size: 8pt;"
            "background: transparent; border: none; padding: 2px 6px;"
        )

        self._hint_label = QLabel(self)
        self._hint_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._hint_label.setStyleSheet(
            f"color: {_theme.C['text_dim']}; font-size: 8pt;"
            "background: transparent; border: none; padding: 2px 6px;"
        )
        self._hint_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self._center_card = QFrame(self)
        self._center_card.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._center_card.setStyleSheet(
            "background: transparent; border: none;"
        )
        self._center_hpad = dp(8)
        self._center_vpad = dp(6)
        center_layout = QVBoxLayout(self._center_card)
        center_layout.setContentsMargins(self._center_hpad, self._center_vpad, self._center_hpad, self._center_vpad)
        center_layout.setSpacing(dp(1))

        self._center_title = QLabel("")
        self._center_title.setAlignment(Qt.AlignCenter)
        self._center_title.setStyleSheet(
            f"color: {_theme.C['text_dim']}; font-weight: 600; background: transparent; border: none;"
        )
        center_layout.addWidget(self._center_title)

        self._center_value = QLabel("")
        self._center_value.setAlignment(Qt.AlignCenter)
        self._center_value.setStyleSheet(
            f"color: {_theme.C['text']}; font-weight: 700; background: transparent; border: none;"
        )
        center_layout.addWidget(self._center_value)

        self._fade_anim = None

    def _animate_transition(self) -> None:
        return

    def _update_center_text(self, title: str, value: str) -> None:
        self._center_title.setText(str(title))
        self._center_value.setText(str(value))
        # Refit fonts/geometry after text change to avoid clipping in the donut hole.
        self._layout_overlay_ui()

    def _base_center_text(self) -> tuple[str, str]:
        rune_count = len(self._active_runes)
        if self._level == self._LEVEL_SETS:
            return tr("overview.drill_center_sets"), tr("overview.drill_center_count", count=rune_count)
        if self._level == self._LEVEL_SLOTS:
            return self._context_label, tr("overview.drill_center_count", count=rune_count)
        return f"{tr('ui.slot')} {int(self._active_slot)}", tr("overview.drill_center_count", count=rune_count)

    def _refresh_overlay_texts(self) -> None:
        root = tr("overview.drill_breadcrumb_root")
        if self._level == self._LEVEL_SETS:
            crumb = root
            hint = tr("overview.drill_hint_sets")
        elif self._level == self._LEVEL_SLOTS:
            crumb = f"{root} / {self._context_label}"
            hint = tr("overview.drill_hint_slots")
        else:
            crumb = f"{root} / {self._context_label} / {tr('ui.slot')} {int(self._active_slot)}"
            hint = tr("overview.drill_hint_main")
        self._crumb_label.setText(crumb)
        self._hint_label.setText(hint)
        self._crumb_label.setVisible(self._level != self._LEVEL_SETS)
        self._hint_label.setVisible(self._level != self._LEVEL_SETS)
        title, value = self._base_center_text()
        self._update_center_text(title, value)
        self._layout_overlay_ui()

    def _layout_overlay_ui(self) -> None:
        pad = dp(10)
        max_w = max(dp(60), self.width() - 2 * pad)

        self._crumb_label.setMaximumWidth(max_w)
        self._crumb_label.adjustSize()
        self._crumb_label.move(pad, pad)

        self._hint_label.setMaximumWidth(max_w)
        self._hint_label.adjustSize()
        self._hint_label.move(self.width() - pad - self._hint_label.width(), pad)

        plot = self.chart().plotArea()
        if plot.isValid():
            hole_diameter = min(plot.width(), plot.height()) * float(self._current_pie_size) * float(self._current_hole_size)
            size = int(max(dp(72), min(hole_diameter * 0.96, dp(124))))
        else:
            size = dp(74)
        if plot.isValid():
            cx = int(plot.center().x())
            cy = int(plot.center().y())
        else:
            cx = self.width() // 2
            cy = self.height() // 2
        self._center_card.setGeometry(cx - size // 2, cy - size // 2, size, size)
        title_pt = max(7, min(10, int(size * 0.12)))
        value_pt = max(9, min(12, int(size * 0.15)))

        title_font = QFont(self._center_title.font())
        value_font = QFont(self._center_value.font())
        title_font.setPointSize(title_pt)
        value_font.setPointSize(value_pt)
        self._center_title.setFont(title_font)
        self._center_value.setFont(value_font)

        # Shrink text slightly if it would clip inside the center hole.
        available_w = max(dp(36), size - (2 * int(self._center_hpad)) - dp(4))
        for _ in range(8):
            t_w = QFontMetrics(self._center_title.font()).horizontalAdvance(self._center_title.text())
            v_w = QFontMetrics(self._center_value.font()).horizontalAdvance(self._center_value.text())
            if t_w <= available_w and v_w <= available_w:
                break
            if value_pt > 7:
                value_pt -= 1
                value_font.setPointSize(value_pt)
                self._center_value.setFont(value_font)
                continue
            if title_pt > 6:
                title_pt -= 1
                title_font.setPointSize(title_pt)
                self._center_title.setFont(title_font)
                continue
            break
        self._center_card.setStyleSheet("QFrame { background: transparent; border: none; }")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._layout_overlay_ui()

    def closeEvent(self, event) -> None:  # noqa: N802
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        if self._level == self._LEVEL_SETS:
            return super().eventFilter(watched, event)
        if event is None or event.type() not in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease):
            return super().eventFilter(watched, event)

        gpos = self._event_global_pos(event)
        if gpos is None:
            return super().eventFilter(watched, event)

        local = self.mapFromGlobal(gpos)
        if not self.rect().contains(local):
            self._rebuild_sets_level()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() != Qt.LeftButton:
            return
        if self._level == self._LEVEL_SETS:
            return
        # Ignore release right after a successful slice click.
        if (time.monotonic() - float(self._last_slice_click_ts)) < 0.18:
            return
        if self._point_hits_donut_ring(event.position()):
            return
        self._rebuild_sets_level()

    def _event_global_pos(self, event) -> Any | None:  # noqa: ANN401
        if hasattr(event, "globalPosition"):
            return event.globalPosition().toPoint()
        if hasattr(event, "globalPos"):
            return event.globalPos()
        try:
            return QCursor.pos()
        except Exception:
            return None

    def _point_hits_donut_ring(self, pos: QPointF) -> bool:
        plot = self.chart().plotArea()
        if not plot.isValid():
            return False
        cx = float(plot.center().x())
        cy = float(plot.center().y())
        dx = float(pos.x()) - cx
        dy = float(pos.y()) - cy
        dist = (dx * dx + dy * dy) ** 0.5
        outer_r = (min(float(plot.width()), float(plot.height())) * float(self._current_pie_size)) / 2.0
        inner_r = outer_r * float(self._current_hole_size)
        return inner_r <= dist <= outer_r

    def _prepare_series(self, title: str) -> None:
        chart = self.chart()
        chart.removeAllSeries()
        chart.setTitle(title)
        chart.legend().setVisible(False)
        chart.setMargins(QMargins(dp(34), dp(10), dp(34), dp(10)))

        series = QPieSeries()
        self._current_hole_size = 0.30
        series.setHoleSize(self._current_hole_size)
        if self._level == self._LEVEL_SETS:
            pie_size = 0.64
        elif self._level == self._LEVEL_SLOTS:
            pie_size = 0.68
        else:
            pie_size = 0.72
        self._current_pie_size = float(pie_size)
        series.setPieSize(pie_size)
        series.setLabelsVisible(True)
        series.hovered.connect(self._on_slice_hovered)
        series.clicked.connect(self._on_slice_clicked)

        chart.addSeries(series)
        self._series = series
        self._slice_meta.clear()
        self._hovered_slice = None
        self._refresh_overlay_texts()
        self._animate_transition()

    def _append_slice(self, label: str, count: int, color_hex: str, payload: dict[str, Any]) -> None:
        if self._series is None:
            return
        if int(count) <= 0:
            return
        slc = self._series.append(label, float(count))
        base = QColor(color_hex)
        slc.setColor(base)
        slc.setLabelPosition(QPieSlice.LabelOutside)
        slc.setLabelArmLengthFactor(0.12)
        slc.setLabelColor(QColor(_theme.C["chart_text"]))
        slc.setBorderColor(QColor(255, 255, 255, 45))
        slc.setBorderWidth(1.2)
        slc.setLabelVisible(True)
        self._slice_meta[id(slc)] = {"payload": payload, "base_color": base}

    def _rebuild_sets_level(self) -> None:
        self._level = self._LEVEL_SETS
        self._context_label = ""
        self._active_slot = 0
        self._active_runes = list(self._all_runes)
        self._prepare_series(tr("overview.set_dist_chart"))

        by_set: dict[int, List[Rune]] = {}
        for rune in self._all_runes:
            sid = int(rune.set_id or 0)
            by_set.setdefault(sid, []).append(rune)

        ranked = sorted(by_set.items(), key=lambda kv: len(kv[1]), reverse=True)
        top = ranked[:10]
        top_ids = {sid for sid, _ in top}
        other_runes: List[Rune] = []
        for sid, lst in ranked:
            if sid not in top_ids:
                other_runes.extend(lst)

        for idx, (sid, lst) in enumerate(top):
            set_name = SET_NAMES.get(int(sid), f"Set {int(sid)}")
            self._append_slice(
                f"{set_name} ({len(lst)})",
                len(lst),
                self._palette[idx % len(self._palette)],
                {"next": self._LEVEL_SLOTS, "runes": list(lst), "context": set_name},
            )

        if other_runes:
            self._append_slice(
                tr("overview.other", count=len(other_runes)),
                len(other_runes),
                "#7f8c8d",
                {"next": self._LEVEL_SLOTS, "runes": list(other_runes), "context": tr("overview.other_sets")},
            )

    def _rebuild_slots_level(self, runes: List[Rune], context_label: str) -> None:
        self._level = self._LEVEL_SLOTS
        self._context_label = str(context_label)
        self._active_slot = 0
        self._active_runes = list(runes)
        self._prepare_series(tr("overview.set_slot_dist_chart", name=self._context_label))

        counts: Counter = Counter(int(r.slot_no or 0) for r in runes if int(r.slot_no or 0) > 0)
        for slot in range(1, 7):
            count = int(counts.get(slot, 0))
            if count <= 0:
                continue
            self._append_slice(
                f"{tr('ui.slot')} {slot} ({count})",
                count,
                self._palette[(slot - 1) % len(self._palette)],
                {
                    "next": self._LEVEL_MAIN,
                    "runes": [r for r in runes if int(r.slot_no or 0) == slot],
                    "slot": int(slot),
                    "context": self._context_label,
                },
            )

    def _rebuild_mainstat_level(self, runes: List[Rune], context_label: str, slot: int) -> None:
        self._level = self._LEVEL_MAIN
        self._context_label = str(context_label)
        self._active_slot = int(slot)
        self._active_runes = list(runes)
        self._prepare_series(tr("overview.slot_mainstat_dist_chart", name=self._context_label, slot=int(slot)))

        counts: Counter = Counter()
        for rune in runes:
            stat_id = int(rune.pri_eff[0] if rune.pri_eff else 0)
            if stat_id <= 0:
                continue
            counts[stat_id] += 1
        ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)

        for idx, (stat_id, count) in enumerate(ranked):
            label = f"{_mainstat_key(stat_id)} ({int(count)})"
            self._append_slice(
                label,
                int(count),
                self._palette[idx % len(self._palette)],
                {"next": "", "runes": [], "slot": int(slot), "context": self._context_label},
            )

    def _apply_hover_style(self, slc: QPieSlice, active: bool) -> None:
        meta = self._slice_meta.get(id(slc))
        if not meta:
            return
        base_color = meta["base_color"]
        if active:
            slc.setColor(base_color.lighter(125))
            slc.setExploded(True)
            slc.setExplodeDistanceFactor(0.08)
        else:
            slc.setColor(base_color)
            slc.setExploded(False)
            slc.setExplodeDistanceFactor(0.0)

    def _on_slice_hovered(self, slc: QPieSlice, state: bool) -> None:
        if state:
            if self._hovered_slice is not None and self._hovered_slice is not slc:
                self._apply_hover_style(self._hovered_slice, False)
            self._hovered_slice = slc
            self._apply_hover_style(slc, True)
            label = str(slc.label() or "").split(" (", 1)[0].strip()
            pct = float(slc.percentage() or 0.0) * 100.0
            self._update_center_text(label, f"{pct:.1f}%")
        else:
            self._apply_hover_style(slc, False)
            if self._hovered_slice is slc:
                self._hovered_slice = None
            title, value = self._base_center_text()
            self._update_center_text(title, value)

    def _on_slice_clicked(self, slc: QPieSlice) -> None:
        self._last_slice_click_ts = time.monotonic()
        meta = self._slice_meta.get(id(slc))
        if not meta:
            return
        payload = meta.get("payload") or {}
        nxt = str(payload.get("next") or "")
        runes = list(payload.get("runes") or [])
        context_label = str(payload.get("context") or "")
        if nxt == self._LEVEL_SLOTS:
            self._rebuild_slots_level(runes, context_label)
            return
        if nxt == self._LEVEL_MAIN:
            self._rebuild_mainstat_level(runes, context_label, int(payload.get("slot") or 0))
            return

# ------------------------------------------------------------
# Overview widget
# ------------------------------------------------------------
class OverviewWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        _bg = _theme.C["bg"]
        self.setStyleSheet(f"background: {_bg};")
        self._account: Optional[AccountData] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(dp(8), dp(8), dp(8), dp(8))
        outer.setSpacing(dp(8))

        # top section: cards left, rune set distribution right
        self._top_overview_row = QHBoxLayout()
        self._top_overview_row.setSpacing(dp(8))
        outer.addLayout(self._top_overview_row)

        self._cards_host = QWidget()
        self._cards_host.setStyleSheet(f"background: {_bg};")
        self._cards_grid = QGridLayout(self._cards_host)
        self._cards_grid.setContentsMargins(0, 0, 0, 0)
        self._cards_grid.setSpacing(dp(8))
        self._top_overview_row.addWidget(self._cards_host, 3)

        c = _theme.C
        self._card_units = _SummaryCard(tr("overview.monsters"), "\u2014")
        self._card_runes = _SummaryCard(tr("overview.runes"), "\u2014")
        self._card_artifacts = _SummaryCard(tr("overview.artifacts"), "\u2014")
        self._card_rune_avg = _SummaryCard(tr("overview.rune_eff"), "\u2014", c["overview_green"])
        self._card_art_avg_t1 = _SummaryCard(tr("overview.attr_art_eff"), "—", c["overview_purple"])
        self._card_art_avg_t2 = _SummaryCard(tr("overview.type_art_eff"), "—", c["overview_purple"])
        self._card_rune_best = _SummaryCard(tr("overview.best_rune"), "\u2014", c["overview_orange"])

        self._set_eff_cards: dict[int, _SummaryCard] = {}
        for sid in _IMPORTANT_SET_IDS:
            name = SET_NAMES.get(sid, f"Set {sid}")
            card = _SummaryCard(tr("overview.set_eff", name=name), "\u2014", c["overview_green"])
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
        controls_row.setSpacing(dp(8))
        self._lbl_top_n = QLabel(tr("overview.chart_top_label"))
        self._lbl_top_n.setStyleSheet(f"color: {_theme.C['text_dim']};")
        self._top_n_combo = QComboBox()
        self._top_n_combo.setStyleSheet(
            f"color: {_theme.C['text']}; background: {_theme.C['card_bg']}; border: 1px solid {_theme.C['card_border']};"
        )
        for n in (100, 400, 800, 1000):
            self._top_n_combo.addItem(str(n), int(n))
        self._top_n_combo.setCurrentIndex(max(0, self._top_n_combo.findData(400)))
        self._top_n_combo.currentIndexChanged.connect(self._on_top_n_changed)
        self._lbl_rune_set_filter = QLabel(tr("overview.rune_set_filter_label"))
        self._lbl_rune_set_filter.setStyleSheet(f"color: {_theme.C['text_dim']};")
        self._rune_set_filter_combo = QComboBox()
        self._rune_set_filter_combo.setStyleSheet(
            f"color: {_theme.C['text']}; background: {_theme.C['card_bg']}; border: 1px solid {_theme.C['card_border']};"
        )
        self._rune_set_filter_combo.currentIndexChanged.connect(self._on_rune_set_filter_changed)
        controls_row.addWidget(self._lbl_top_n)
        controls_row.addWidget(self._top_n_combo)
        controls_row.addWidget(self._lbl_rune_set_filter)
        controls_row.addWidget(self._rune_set_filter_combo)
        controls_row.addStretch(1)
        outer.addLayout(controls_row)

        # -- scrollable chart grid --------------------
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(f"QScrollArea {{ border: none; background: {_bg}; }}")
        outer.addWidget(scroll, 1)

        container = QWidget()
        container.setStyleSheet(f"background: {_bg};")
        self._grid = QGridLayout(container)
        self._grid.setSpacing(dp(8))
        scroll.setWidget(container)

        # placeholders for charts
        self._rune_eff_view: QChartView | None = None
        self._rune_set_view: QChartView | None = None
        self._art_eff_view: QChartView | None = None
        self._rune_pool_view: QChartView | None = None
        self._artifact_pool_view: QChartView | None = None

    # -- public API ------------------------------------
    def set_data(self, account: AccountData) -> None:
        self._account = account
        self._refresh_rune_set_filter_options()
        self._update_cards(account)
        self._build_charts(account)

    def retranslate(self) -> None:
        self._card_units.update_title(tr("overview.monsters"))
        self._card_runes.update_title(tr("overview.runes"))
        self._card_artifacts.update_title(tr("overview.artifacts"))
        self._card_rune_avg.update_title(tr("overview.rune_eff"))
        self._card_art_avg_t1.update_title(tr("overview.attr_art_eff"))
        self._card_art_avg_t2.update_title(tr("overview.type_art_eff"))
        self._card_rune_best.update_title(tr("overview.best_rune"))
        self._lbl_top_n.setText(tr("overview.chart_top_label"))
        self._lbl_rune_set_filter.setText(tr("overview.rune_set_filter_label"))
        self._refresh_rune_set_filter_options()
        for sid, card in self._set_eff_cards.items():
            name = SET_NAMES.get(sid, f"Set {sid}")
            card.update_title(tr("overview.set_eff", name=name))
        if self._account is not None:
            self._build_charts(self._account)

    # -- cards -----------------------------------------
    def _update_cards(self, acc: AccountData) -> None:
        n_units = len(acc.units_by_id)
        filtered_runes = [r for r in acc.runes if int(r.upgrade_curr or 0) >= 12]
        n_runes = len(filtered_runes)
        n_arts = len(acc.artifacts)

        self._card_units.update_value(str(n_units))
        self._card_units.set_subtitle("")
        self._card_runes.update_value(f"{n_runes:,}".replace(",", "."))
        self._card_runes.set_subtitle("")
        self._card_artifacts.update_value(f"{n_arts:,}".replace(",", "."))
        self._card_artifacts.set_subtitle("")

        r_effs = rune_efficiencies(filtered_runes) if filtered_runes else []
        artifacts_t1 = [a for a in acc.artifacts if int(a.type_ or 0) == 1 and a.sec_effects]
        artifacts_t2 = [a for a in acc.artifacts if int(a.type_ or 0) == 2 and a.sec_effects]
        a_effs_t1 = [artifact_efficiency(a) for a in artifacts_t1]
        a_effs_t2 = [artifact_efficiency(a) for a in artifacts_t2]

        if r_effs:
            avg = sum(r_effs) / len(r_effs)
            best = max(r_effs)
            self._card_rune_avg.update_value(f"{avg:.1f}%")
            self._card_rune_avg.set_subtitle("")
            self._card_rune_best.update_value(f"{best:.1f}%")
            self._card_rune_best.set_subtitle("")
        else:
            self._card_rune_avg.set_subtitle("")
            self._card_rune_best.set_subtitle("")
        if a_effs_t1:
            avg = sum(a_effs_t1) / len(a_effs_t1)
            self._card_art_avg_t1.update_value(f"{avg:.1f}%")
            self._card_art_avg_t1.set_subtitle("")
        else:
            self._card_art_avg_t1.update_value("—")
            self._card_art_avg_t1.set_subtitle("")

        if a_effs_t2:
            avg = sum(a_effs_t2) / len(a_effs_t2)
            self._card_art_avg_t2.update_value(f"{avg:.1f}%")
            self._card_art_avg_t2.set_subtitle("")
        else:
            self._card_art_avg_t2.update_value("—")
            self._card_art_avg_t2.set_subtitle("")

        for sid, card in self._set_eff_cards.items():
            vals = [rune_efficiency(r) for r in filtered_runes if int(r.set_id or 0) == sid]
            if vals:
                avg_v = sum(vals) / len(vals)
                card.update_value(f"{avg_v:.1f}%")
                card.set_subtitle("")
            else:
                card.update_value("\u2014")
                card.set_subtitle("")

    # -- charts ----------------------------------------
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

        all_runes = list(acc.runes or [])
        all_arts = list(acc.artifacts or [])
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
        self._rune_pool_view = self._build_rune_pool_chart(all_runes)
        self._artifact_pool_view = self._build_artifact_pool_chart(all_arts)

        self._rune_set_view.setMinimumHeight(dp(300))
        self._rune_set_host_layout.addWidget(self._rune_set_view, 1)

        self._grid.addWidget(self._rune_eff_view, 0, 0, 1, 2)
        self._grid.addWidget(self._art_eff_view, 1, 0, 1, 2)
        self._grid.addWidget(self._rune_pool_view, 2, 0, 1, 1)
        self._grid.addWidget(self._artifact_pool_view, 2, 1, 1, 1)

    def _on_top_n_changed(self, _value: int) -> None:
        if self._account is not None:
            self._build_charts(self._account)

    def _on_rune_set_filter_changed(self, _value: int) -> None:
        if self._account is not None:
            self._build_charts(self._account)

    def _selected_rune_set_id(self) -> int:
        return int(self._rune_set_filter_combo.currentData() or 0)

    def _refresh_rune_set_filter_options(self) -> None:
        selected = self._selected_rune_set_id()
        self._rune_set_filter_combo.blockSignals(True)
        self._rune_set_filter_combo.clear()
        self._rune_set_filter_combo.addItem(tr("overview.filter_all_sets"), 0)

        if self._account is not None:
            filtered_runes = [r for r in self._account.runes if int(r.upgrade_curr or 0) >= 12]
            set_ids = sorted(
                {int(r.set_id or 0) for r in filtered_runes if int(r.set_id or 0) > 0},
                key=lambda sid: SET_NAMES.get(sid, f"Set {sid}"),
            )
            for sid in set_ids:
                self._rune_set_filter_combo.addItem(SET_NAMES.get(sid, f"Set {sid}"), sid)

        idx = self._rune_set_filter_combo.findData(selected)
        self._rune_set_filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._rune_set_filter_combo.blockSignals(False)

    def _change_top_n(self, delta: int) -> None:
        cur_idx = int(self._top_n_combo.currentIndex())
        if cur_idx < 0:
            return
        if int(delta) < 0:
            nxt_idx = max(0, cur_idx - 1)
        elif int(delta) > 0:
            nxt_idx = min(self._top_n_combo.count() - 1, cur_idx + 1)
        else:
            return
        if nxt_idx != cur_idx:
            self._top_n_combo.setCurrentIndex(nxt_idx)

    def _build_rune_eff_chart(self, items: List[Tuple[float, Rune]]) -> QChartView:
        selected_set_id = self._selected_rune_set_id()
        if selected_set_id > 0:
            items = [(eff, rune) for eff, rune in items if int(rune.set_id or 0) == selected_set_id]

        top_n = int(self._top_n_combo.currentData() or 400)
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
        series_current.setName(tr("overview.series_current"))
        series_current.setColor(QColor("#f39c12"))
        for idx, (eff, _) in enumerate(current_items, start=1):
            series_current.append(float(idx), float(eff))

        series_hero = QLineSeries()
        series_hero.setName(tr("overview.series_hero_max"))
        series_hero.setColor(QColor("#4aa3ff"))
        for idx, (eff, _) in enumerate(hero_items, start=1):
            series_hero.append(float(idx), float(eff))

        series_legend = QLineSeries()
        series_legend.setName(tr("overview.series_legend_max"))
        series_legend.setColor(QColor("#2ecc71"))
        for idx, (eff, _) in enumerate(legend_items, start=1):
            series_legend.append(float(idx), float(eff))

        chart_title = tr("overview.rune_eff_chart", n=top_n)
        if selected_set_id > 0:
            chart_title = f"{chart_title} - {SET_NAMES.get(selected_set_id, f'Set {selected_set_id}')}"
        chart = _make_chart(chart_title)
        chart.addSeries(series_current)
        chart.addSeries(series_hero)
        chart.addSeries(series_legend)
        chart.legend().setVisible(True)

        ax_x = QValueAxis()
        ax_x.setLabelFormat("%d")
        ax_x.setRange(1, max(n, 1))
        ax_x.setTitleText(tr("overview.axis_count"))
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
        ax_y.setTitleText(tr("overview.axis_eff"))
        _style_bar_axis(ax_y)
        chart.addAxis(ax_y, Qt.AlignLeft)
        series_current.attachAxis(ax_y)
        series_hero.attachAxis(ax_y)
        series_legend.attachAxis(ax_y)

        return _IndexedLineChartView(
            chart,
            [
                (tr("overview.series_current"), series_current, current_items, _rune_curve_tooltip),
                (tr("overview.series_hero_max"), series_hero, hero_items, _rune_curve_tooltip),
                (tr("overview.series_legend_max"), series_legend, legend_items, _rune_curve_tooltip),
            ],
            zoom_callback=self._change_top_n,
        )

    def _build_rune_set_chart(self, runes: List[Rune]) -> QChartView:
        return _RuneSetDrilldownChartView(runes)

    def _build_art_eff_chart(self, items: List[Tuple[float, Artifact]]) -> QChartView:
        top_n = int(self._top_n_combo.currentData() or 400)
        by_type: dict[int, List[Tuple[float, Artifact]]] = {1: [], 2: []}
        for eff, art in items:
            t = int(art.type_ or 0)
            if t in by_type:
                by_type[t].append((eff, art))

        chart = _make_chart(tr("overview.art_eff_chart", n=top_n))
        chart.legend().setVisible(True)

        entries: List[Tuple[str, QLineSeries, List[Tuple[float, Any]], Callable[[Tuple[float, Any], int, str], str]]] = []
        max_len = 0
        all_vals: List[float] = []
        colors = {1: "#1abc9c", 2: "#4aa3ff"}
        names = {1: tr("overview.series_attr_art"), 2: tr("overview.series_type_art")}

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
        ax_x.setTitleText(tr("overview.axis_count"))
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
        ax_y.setTitleText(tr("overview.axis_eff"))
        _style_bar_axis(ax_y)
        chart.addAxis(ax_y, Qt.AlignLeft)
        for _, s, _, _ in entries:
            s.attachAxis(ax_y)

        return _IndexedLineChartView(chart, entries, zoom_callback=self._change_top_n)

    def _build_pool_pie_chart(self, title: str, rows: List[Tuple[str, int, str]]) -> QChartView:
        chart = _make_chart(title)
        chart.legend().setVisible(True)
        series = QPieSeries()
        non_zero = [(label, int(count), color) for label, count, color in rows if int(count) > 0]
        if not non_zero:
            slc = series.append(tr("collection.none"), 1.0)
            slc.setColor(QColor("#7f8c8d"))
            slc.setLabelVisible(True)
            chart.addSeries(series)
            return _make_chart_view(chart)

        total = float(sum(int(count) for _, count, _ in non_zero))
        for label, count, color in non_zero:
            text = f"{label} ({int(count)})"
            slc = series.append(text, float(count))
            slc.setColor(QColor(color))
            # Keep labels readable and compact.
            slc.setLabelVisible(total <= 1200.0)
        chart.addSeries(series)
        return _make_chart_view(chart)

    def _build_rune_pool_chart(self, runes: List[Rune]) -> QChartView:
        by_tier = Counter(_rune_quality_tier_key(r) for r in (runes or []))
        rows = [
            (tr("overview.quality_legend"), int(by_tier.get("legend", 0)), "#e67e22"),
            (tr("overview.quality_hero"), int(by_tier.get("hero", 0)), "#9b59b6"),
            (tr("overview.quality_rare"), int(by_tier.get("rare", 0)), "#3498db"),
            (tr("overview.quality_magic"), int(by_tier.get("magic", 0)), "#2ecc71"),
            (tr("overview.quality_normal"), int(by_tier.get("normal", 0)), "#95a5a6"),
            (tr("overview.quality_other"), int(by_tier.get("other", 0)), "#e74c3c"),
        ]
        return self._build_pool_pie_chart(tr("overview.rune_pool_dist_chart"), rows)

    def _build_artifact_pool_chart(self, arts: List[Artifact]) -> QChartView:
        by_tier = Counter(_artifact_quality_tier_key(a) for a in (arts or []))
        rows = [
            (tr("overview.quality_legend"), int(by_tier.get("legend", 0)), "#1abc9c"),
            (tr("overview.quality_hero"), int(by_tier.get("hero", 0)), "#4aa3ff"),
            (tr("overview.quality_rare"), int(by_tier.get("rare", 0)), "#f39c12"),
            (tr("overview.quality_magic"), int(by_tier.get("magic", 0)), "#2ecc71"),
            (tr("overview.quality_normal"), int(by_tier.get("normal", 0)), "#95a5a6"),
            (tr("overview.quality_other"), int(by_tier.get("other", 0)), "#e74c3c"),
        ]
        return self._build_pool_pie_chart(tr("overview.artifact_pool_dist_chart"), rows)



