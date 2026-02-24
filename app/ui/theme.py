from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.ui.dpi import dp


def apply_dark_palette(app: QApplication) -> None:
    """Force dark UI styling across platforms/widgets."""
    app.setStyle("Fusion")

    p = QPalette()
    p.setColor(QPalette.Window, QColor("#1e1e1e"))
    p.setColor(QPalette.WindowText, QColor("#dddddd"))
    p.setColor(QPalette.Base, QColor("#2b2b2b"))
    p.setColor(QPalette.AlternateBase, QColor("#282828"))
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

    app.setStyleSheet(f"""
        * {{ font-family: "Segoe UI", system-ui, sans-serif; }}
        QToolTip {{ color: #e6edf3; background: #1f242a; border: 1px solid #3a3f46; border-radius: 4px; padding: {dp(4)}px {dp(8)}px; }}
        QPushButton {{ background-color: #2b2b2b; color: #dddddd; border: 1px solid #3a3a3a; border-radius: {dp(6)}px; padding: {dp(5)}px {dp(14)}px; min-height: {dp(24)}px; }}
        QPushButton:hover {{ background-color: #383838; }}
        QPushButton:pressed {{ background-color: #222222; }}
        QPushButton:focus {{ border-color: #4a90e2; outline: none; }}
        QPushButton:disabled {{ color: #555555; border-color: #2a2a2a; }}
        QPushButton[primary="true"] {{ background-color: #1a4a8a; color: #ffffff; border: 1px solid #2d6bc4; font-weight: bold; }}
        QPushButton[primary="true"]:hover {{ background-color: #2260b0; }}
        QPushButton[primary="true"]:pressed {{ background-color: #143870; }}
        QPushButton[primary="true"]:disabled {{ background-color: #1a2a3a; color: #4a6080; border-color: #1a2a3a; }}
        QLineEdit, QSpinBox, QComboBox {{ background-color: #252525; color: #dddddd; border: 1px solid #3a3a3a; border-radius: {dp(5)}px; padding: {dp(4)}px {dp(8)}px; }}
        QLineEdit:focus, QSpinBox:focus {{ border-color: #4a90e2; }}
        QComboBox QAbstractItemView {{ background-color: #2b2b2b; color: #dddddd; selection-background-color: #2d4a7a; border: 1px solid #3a3a3a; }}
        QComboBox::drop-down {{ border: none; }}
        QDialog {{ background-color: #1e1e1e; color: #dddddd; }}
        QMessageBox {{ background-color: #1e1e1e; color: #dddddd; }}
        QLabel {{ color: #dddddd; }}
        QGroupBox {{ color: #9aa4b2; border: 1px solid #303030; border-radius: {dp(6)}px; margin-top: {dp(8)}px; padding-top: {dp(16)}px; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: {dp(10)}px; padding: 0 {dp(6)}px; color: #9aa4b2; }}
        QTabWidget::pane {{ border: 1px solid #2e3138; }}
        QTabBar::tab {{ background-color: #23272e; color: #6c7888; border: 1px solid #2e3138; border-top: 2px solid transparent; padding: {dp(8)}px {dp(18)}px; }}
        QTabBar::tab:selected {{ background-color: #1f2126; color: #eef1f5; border-top: 2px solid #4a90e2; font-weight: bold; }}
        QTabBar::tab:hover {{ color: #b0bac8; }}
        QTableWidget, QTableView {{ background-color: #242424; alternate-background-color: #282828; color: #dddddd; gridline-color: #333333; border: none; selection-background-color: #2d4a7a; selection-color: #ffffff; }}
        QTableWidget::item, QTableView::item {{ padding: {dp(5)}px {dp(6)}px; border: none; }}
        QHeaderView {{ background-color: #1e1e1e; }}
        QHeaderView::section {{ background-color: #1e1e1e; color: #9aa4b2; border: none; border-bottom: 1px solid #353535; border-right: 1px solid #2a2a2a; padding: {dp(5)}px {dp(8)}px; }}
        QScrollBar:vertical {{ background: transparent; width: {dp(8)}px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: #3a3a3a; border-radius: {dp(4)}px; min-height: {dp(24)}px; margin: {dp(2)}px; }}
        QScrollBar::handle:vertical:hover {{ background: #4a90e2; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: {dp(8)}px; margin: 0; }}
        QScrollBar::handle:horizontal {{ background: #3a3a3a; border-radius: {dp(4)}px; min-width: {dp(24)}px; margin: {dp(2)}px; }}
        QScrollBar::handle:horizontal:hover {{ background: #4a90e2; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
        QProgressDialog {{ background-color: #1e1e1e; color: #dddddd; }}
        QProgressBar {{ background-color: #242424; color: #dddddd; border: 1px solid #303030; border-radius: {dp(4)}px; text-align: center; }}
        QProgressBar::chunk {{ background-color: #4a90e2; border-radius: {dp(4)}px; }}
        QListWidget, QListView {{ background-color: #242424; alternate-background-color: #282828; color: #dddddd; border: 1px solid #303030; }}
        QScrollArea {{ background-color: #1e1e1e; border: none; }}
        QMenu {{ background-color: #2b2b2b; color: #dddddd; border: 1px solid #303030; border-radius: {dp(6)}px; }}
        QMenu::item:selected {{ background-color: #2d4a7a; }}
        QStatusBar {{ background-color: #1e1e1e; color: #9aa4b2; }}
        QMenuBar {{ background-color: #1e1e1e; color: #dddddd; }}
        QMenuBar::item:selected {{ background-color: #2d4a7a; }}
        QCheckBox {{ color: #dddddd; spacing: {dp(6)}px; }}
        QCheckBox::indicator {{ width: {dp(14)}px; height: {dp(14)}px; border: 1px solid #3a3a3a; border-radius: {dp(3)}px; background: #252525; }}
        QCheckBox::indicator:checked {{ background: #4a90e2; border-color: #4a90e2; }}
        QCheckBox::indicator:hover {{ border-color: #4a90e2; }}
        QSplitter::handle {{ background: #2a2a2a; }}
        QSplitter::handle:horizontal {{ width: 1px; }}
        QSplitter::handle:vertical {{ height: 1px; }}
    """)
