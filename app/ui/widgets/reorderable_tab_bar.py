from __future__ import annotations

from PySide6.QtCore import Qt, Property, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QColor
from PySide6.QtWidgets import QTabBar


class ReorderableTabBar(QTabBar):
    """QTabBar that supports drag-and-drop reordering with a pinned first tab
    and an animated sliding accent indicator on the active tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(True)
        self._pinned_index = 0

        # Sliding indicator state
        self.__ind_x: float = 0.0
        self.__ind_w: float = 60.0

        # Remove QSS border-bottom on selected tab – we paint it ourselves
        self.setStyleSheet("QTabBar::tab:selected { border-bottom: none; }")

        self._anim = QPropertyAnimation(self, b"indicator_x", self)
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.currentChanged.connect(self._slide_to)

    # ── animatable property ──────────────────────────────────────
    def _get_ind_x(self) -> float:
        return self.__ind_x

    def _set_ind_x(self, val: float) -> None:
        self.__ind_x = val
        self.update()

    indicator_x = Property(float, _get_ind_x, _set_ind_x)

    # ── animation trigger ────────────────────────────────────────
    def _slide_to(self, index: int) -> None:
        if index < 0 or self.count() == 0:
            return
        rect = self.tabRect(index)
        self.__ind_w = float(rect.width())
        self._anim.stop()
        self._anim.setStartValue(self.__ind_x)
        self._anim.setEndValue(float(rect.x()))
        self._anim.start()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        idx = self.currentIndex()
        if idx >= 0 and self.count() > 0:
            rect = self.tabRect(idx)
            self.__ind_x = float(rect.x())
            self.__ind_w = float(rect.width())

    # ── custom painting: sliding accent line at bottom ───────────
    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self.count() == 0:
            return
        from app.ui import theme as _theme
        accent = QColor(_theme.C["tab_accent"])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(accent)
        h = 2
        p.drawRoundedRect(
            int(self.__ind_x),
            self.height() - h,
            int(self.__ind_w),
            h,
            1, 1,
        )
        p.end()

    # ── drag lock for pinned tab ─────────────────────────────────
    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            idx = self.tabAt(event.position().toPoint())
            if idx == self._pinned_index:
                self.setMovable(False)
                super().mousePressEvent(event)
                self.setMovable(True)
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        super().mouseReleaseEvent(event)
        if not self.isMovable():
            self.setMovable(True)
