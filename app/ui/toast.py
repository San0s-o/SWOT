"""Animated toast notifications anchored to a parent widget."""
from __future__ import annotations

from typing import Literal

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor, QBrush, QPen, QPainterPath
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout

from app.ui import theme as _theme
from app.ui.dpi import dp

ToastType = Literal["success", "error", "info", "warning"]

_CONFIGS: dict[str, dict[str, str]] = {
    "success": {"icon": "✓", "color": "#27ae60"},
    "error":   {"icon": "✗", "color": "#e74c3c"},
    "info":    {"icon": "●", "color": "#4a90e2"},
    "warning": {"icon": "!", "color": "#f39c12"},
}

_active: list[Toast] = []


class Toast(QWidget):
    def __init__(
        self,
        parent: QWidget,
        message: str,
        toast_type: ToastType = "info",
        duration: int = 3500,
    ) -> None:
        super().__init__(parent, Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowOpacity(0.0)

        cfg = _CONFIGS.get(toast_type, _CONFIGS["info"])
        self._accent = cfg["color"]

        c = _theme.C
        is_cp = _theme.current_name == "cyberpunk"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(dp(16), dp(11), dp(16), dp(11))
        layout.setSpacing(dp(10))

        icon = QLabel(cfg["icon"])
        icon.setFixedSize(dp(20), dp(20))
        icon.setAlignment(Qt.AlignCenter)
        icon.setStyleSheet(
            f"color: {self._accent}; font-size: 12pt; font-weight: 900;"
            " background: transparent; border: none;"
        )
        layout.addWidget(icon, 0)

        msg = QLabel(message)
        msg.setWordWrap(True)
        msg.setMaximumWidth(dp(280))
        font_family = c["ui_font"] if is_cp else ""
        msg.setStyleSheet(
            f"color: {c['text']}; font-size: 9pt;"
            f" {'font-family: ' + font_family + ';' if font_family else ''}"
            " background: transparent; border: none;"
        )
        layout.addWidget(msg, 1)

        self.setFixedWidth(dp(340))
        self.adjustSize()

        # Fade-in
        self._anim_in = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_in.setDuration(220)
        self._anim_in.setStartValue(0.0)
        self._anim_in.setEndValue(0.93)
        self._anim_in.setEasingCurve(QEasingCurve.OutCubic)

        # Fade-out
        self._anim_out = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim_out.setDuration(300)
        self._anim_out.setStartValue(0.93)
        self._anim_out.setEndValue(0.0)
        self._anim_out.setEasingCurve(QEasingCurve.InCubic)
        self._anim_out.finished.connect(self._cleanup)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(duration)
        self._timer.timeout.connect(self._start_fade_out)

    def paintEvent(self, event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        bg = QColor(_theme.C["bg_card"])
        bg.setAlpha(245)

        r = self.rect().adjusted(1, 1, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(r, dp(10), dp(10))

        p.fillPath(path, QBrush(bg))

        border = QColor(self._accent)
        border.setAlpha(180)
        p.setPen(QPen(border, 1.5))
        p.drawPath(path)

        # Left accent strip
        strip = QPainterPath()
        strip.addRoundedRect(1, 1, dp(4), self.height() - 2, dp(2), dp(2))
        p.fillPath(strip, QBrush(QColor(self._accent)))

    def show_positioned(self, x: int, y: int) -> None:
        self.move(x, y)
        self.show()
        self._anim_in.start()
        self._timer.start()

    def _start_fade_out(self) -> None:
        self._timer.stop()
        self._anim_out.start()

    def _cleanup(self) -> None:
        if self in _active:
            _active.remove(self)
        _restack(self.parent())
        self.deleteLater()


def _restack(parent: QWidget | None) -> None:
    if parent is None:
        return
    margin = dp(16)
    y = parent.height() - margin
    for t in reversed(_active):
        y -= t.height() + dp(8)
        t.move(parent.width() - t.width() - margin, y)


def show_toast(
    parent: QWidget,
    message: str,
    toast_type: ToastType = "info",
    duration: int = 3500,
) -> None:
    """Show an animated toast notification anchored to *parent*."""
    if parent is None:
        return
    toast = Toast(parent, message, toast_type, duration)
    _active.append(toast)

    margin = dp(16)
    y = parent.height() - margin - toast.height()
    for existing in _active[:-1]:
        y -= existing.height() + dp(8)
    x = parent.width() - toast.width() - margin
    toast.show_positioned(x, y)
