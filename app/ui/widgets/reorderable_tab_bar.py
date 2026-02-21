from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabBar


class ReorderableTabBar(QTabBar):
    """QTabBar that supports drag-and-drop reordering with a pinned first tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(True)
        self._pinned_index = 0

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            idx = self.tabAt(event.position().toPoint())
            if idx == self._pinned_index:
                self.setMovable(False)
                super().mousePressEvent(event)
                self.setMovable(True)
                return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if not self.isMovable():
            self.setMovable(True)
