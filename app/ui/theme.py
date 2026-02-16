from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


def apply_dark_palette(app: QApplication) -> None:
    """Force dark UI styling across platforms/widgets."""
    app.setStyle("Fusion")

    p = QPalette()
    p.setColor(QPalette.Window, QColor("#1e1e1e"))
    p.setColor(QPalette.WindowText, QColor("#dddddd"))
    p.setColor(QPalette.Base, QColor("#2b2b2b"))
    p.setColor(QPalette.AlternateBase, QColor("#333333"))
    p.setColor(QPalette.ToolTipBase, QColor("#1f242a"))
    p.setColor(QPalette.ToolTipText, QColor("#e6edf3"))
    p.setColor(QPalette.Text, QColor("#dddddd"))
    p.setColor(QPalette.Button, QColor("#2b2b2b"))
    p.setColor(QPalette.ButtonText, QColor("#dddddd"))
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.Link, QColor("#3498db"))
    p.setColor(QPalette.Highlight, QColor("#3498db"))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor("#666666"))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#666666"))
    app.setPalette(p)

    app.setStyleSheet(
        """
        QToolTip { color: #e6edf3; background: #1f242a; border: 1px solid #3a3f46; }
        QPushButton { background-color: #2b2b2b; color: #dddddd; border: 1px solid #3a3a3a; border-radius: 4px; padding: 4px 14px; }
        QPushButton:hover { background-color: #3a3a3a; }
        QPushButton:pressed { background-color: #1a1a1a; }
        QPushButton:disabled { color: #666666; }
        QLineEdit, QSpinBox, QComboBox { background-color: #2b2b2b; color: #dddddd; border: 1px solid #3a3a3a; border-radius: 3px; padding: 3px 6px; }
        QComboBox QAbstractItemView { background-color: #2b2b2b; color: #dddddd; selection-background-color: #3498db; }
        QComboBox::drop-down { border: none; }
        QDialog { background-color: #1e1e1e; color: #dddddd; }
        QMessageBox { background-color: #1e1e1e; color: #dddddd; }
        QLabel { color: #dddddd; }
        QGroupBox { color: #dddddd; border: 1px solid #3a3a3a; border-radius: 4px; margin-top: 6px; padding-top: 14px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
        QTabWidget::pane { border: 1px solid #3a3a3a; }
        QTabBar::tab { background-color: #2b2b2b; color: #999999; border: 1px solid #3a3a3a; padding: 6px 16px; }
        QTabBar::tab:selected { background-color: #1e1e1e; color: #dddddd; }
        QTabBar::tab:hover { color: #dddddd; }
        QTableWidget, QTableView, QHeaderView { background-color: #2b2b2b; color: #dddddd; gridline-color: #3a3a3a; }
        QHeaderView::section { background-color: #333333; color: #dddddd; border: 1px solid #3a3a3a; padding: 4px; }
        QScrollBar:vertical { background: #1e1e1e; width: 12px; }
        QScrollBar::handle:vertical { background: #3a3a3a; border-radius: 4px; min-height: 20px; }
        QScrollBar::handle:vertical:hover { background: #555555; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        QScrollBar:horizontal { background: #1e1e1e; height: 12px; }
        QScrollBar::handle:horizontal { background: #3a3a3a; border-radius: 4px; min-width: 20px; }
        QScrollBar::handle:horizontal:hover { background: #555555; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
        QProgressDialog { background-color: #1e1e1e; color: #dddddd; }
        QProgressBar { background-color: #2b2b2b; color: #dddddd; border: 1px solid #3a3a3a; border-radius: 3px; text-align: center; }
        QProgressBar::chunk { background-color: #3498db; border-radius: 3px; }
        QListWidget, QListView { background-color: #2b2b2b; color: #dddddd; border: 1px solid #3a3a3a; }
        QScrollArea { background-color: #1e1e1e; border: none; }
        QMenu { background-color: #2b2b2b; color: #dddddd; border: 1px solid #3a3a3a; }
        QMenu::item:selected { background-color: #3498db; }
        QStatusBar { background-color: #1e1e1e; color: #dddddd; }
        QMenuBar { background-color: #1e1e1e; color: #dddddd; }
        QMenuBar::item:selected { background-color: #3498db; }
        """
    )
