from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from app.ui.dpi import dp

# ================================================================
# Dual-theme system: "classic" (original dark) & "cyberpunk" (HUD)
# ================================================================

_CLASSIC = dict(
    # backgrounds
    bg="#1e1e1e", bg_mid="#282828", bg_card="#2b2b2b", bg_input="#252525",
    # borders
    border="#3a3a3a", border_hover="#4a90e2",
    # text
    text="#dddddd", text_dim="#999999", text_disabled="#666666",
    # accents
    accent="#4a90e2", accent_bg="#1a4a8a", accent_hover="#2260b0", accent_pressed="#143870",
    highlight_bg="#2d4a7a",
    # semantic
    green="#27ae60", red="#e74c3c", orange="#f39c12", purple="#9b59b6",
    # tabs
    tab_bg="#23272e", tab_pane="#1f2126", tab_border="#2e3138",
    tab_text="#6c7888", tab_active_text="#eef1f5", tab_hover_text="#b0bac8",
    tab_accent="#4a90e2", tab_hover_accent="#3a4a5e",
    # progress
    progress_chunk="background-color: #4a90e2",
    # scrollbar
    scrollbar_handle="#3a3a3a",
    # cards
    card_bg="#2b2b2b", card_border="#3a3a3a",
    # optimize btn
    opt_bg="#1a6fa8", opt_border="#2980b9", opt_hover="#2980b9", opt_hover_border="#3498db",
    # elements
    elem_fire="#e74c3c", elem_water="#3498db", elem_wind="#f1c40f",
    elem_light="#ecf0f1", elem_dark="#8e44ad",
    # chart
    chart_bg="#23272e", chart_text="#dddddd", chart_grid="#2e2e2e",
    # settings frame
    settings_bg="#232323",
    # tooltip
    tooltip_bg="#1f242a", tooltip_border="#3a3f46",
    # popup
    popup_bg="#1f242a", popup_border="#3a3f46",
    # overview
    overview_green="#27ae60", overview_red="#e74c3c", overview_accent="#3498db",
    overview_purple="#9b59b6", overview_orange="#f39c12",
    # card title style
    card_title_transform="none",
    card_title_spacing="normal",
    # stat key color in monster cards
    stat_key_color="#e8c252",
    stat_val_color="#ddd",
    stat_bonus_color="#6dcc5a",
    stat_ls_color="#ffcc66",
    # mono font for values (empty = inherit default)
    mono_font="",
    ui_font='"Segoe UI Variable", "Segoe UI", system-ui, sans-serif',
)

_CYBERPUNK = dict(
    # backgrounds – deeper, more contrast
    bg="#080b12", bg_mid="#0f1219", bg_card="#0d1018", bg_input="#0a0e16",
    # borders – brighter cyan glow
    border="#0d3a4a", border_hover="#00d4ff",
    # text
    text="#c8d6e5", text_dim="#4a6080", text_disabled="#1e2a3a",
    # accents – electric cyan
    accent="#00d4ff", accent_bg="transparent", accent_hover="#0a2a3a",
    accent_pressed="#0d3545",
    highlight_bg="#0a2535",
    # semantic – neon
    green="#00ff88", red="#ff3366", orange="#ff9f1c", purple="#b44aff",
    # tabs – dark with neon accents
    tab_bg="#0a0e16", tab_pane="#080b12", tab_border="#0d2030",
    tab_text="#3a5570", tab_active_text="#00d4ff", tab_hover_text="#5ab8d8",
    tab_accent="#00d4ff", tab_hover_accent="#0d2a3a",
    # progress – neon gradient
    progress_chunk=(
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
        " stop:0 #00d4ff, stop:0.5 #b44aff, stop:1 #ff3366)"
    ),
    # scrollbar
    scrollbar_handle="#152030",
    # cards – dark with subtle cyan border
    card_bg="#0a0e18", card_border="#0d3a4a",
    # optimize btn – neon outline
    opt_bg="transparent", opt_border="#00d4ff",
    opt_hover="#0a2a3a", opt_hover_border="#00d4ff",
    # elements – vivid neon
    elem_fire="#ff3366", elem_water="#00d4ff", elem_wind="#00ff88",
    elem_light="#ffe066", elem_dark="#b44aff",
    # chart
    chart_bg="#080b12", chart_text="#c8d6e5", chart_grid="#0d1a28",
    # settings frame
    settings_bg="#0a0e16",
    # tooltip
    tooltip_bg="#060910", tooltip_border="#0d3a4a",
    # popup
    popup_bg="#060910", popup_border="#0d3a4a",
    # overview – vivid neon values
    overview_green="#00ff88", overview_red="#ff3366", overview_accent="#00d4ff",
    overview_purple="#b44aff", overview_orange="#ff9f1c",
    # card title style
    card_title_transform="uppercase",
    card_title_spacing="2px",
    # stat key color in monster cards
    stat_key_color="#00d4ff",
    stat_val_color="#c8d6e5",
    stat_bonus_color="#00ff88",
    stat_ls_color="#ff9f1c",
    # mono font for values
    mono_font='"JetBrains Mono", "Fira Code", "Cascadia Code", "Consolas", monospace',
    ui_font='"Bahnschrift", "Segoe UI Variable", "Segoe UI", system-ui, sans-serif',
)

# ── active theme state ─────────────────────────────────────────
THEMES = {"classic": _CLASSIC, "cyberpunk": _CYBERPUNK}
current_name: str = "classic"
C: dict[str, str] = dict(_CLASSIC)  # mutable copy – active colours


def set_theme(name: str) -> None:
    """Switch the active colour dict (call *before* apply_dark_palette)."""
    global current_name
    if name not in THEMES:
        name = "classic"
    current_name = name
    C.clear()
    C.update(THEMES[name])


def apply_dark_palette(app: QApplication) -> None:
    """Apply the active theme's palette + global stylesheet."""
    app.setStyle("Fusion")
    c = C  # shorthand

    p = QPalette()
    p.setColor(QPalette.Window, QColor(c["bg"]))
    p.setColor(QPalette.WindowText, QColor(c["text"]))
    p.setColor(QPalette.Base, QColor(c["bg_card"]))
    p.setColor(QPalette.AlternateBase, QColor(c["bg_mid"]))
    _tooltip_text = "#e6edf3"
    p.setColor(QPalette.ToolTipBase, QColor(c["tooltip_bg"]))
    p.setColor(QPalette.ToolTipText, QColor(_tooltip_text))
    p.setColor(QPalette.Text, QColor(c["text"]))
    p.setColor(QPalette.Button, QColor(c["bg_card"]))
    p.setColor(QPalette.ButtonText, QColor(c["text"]))
    p.setColor(QPalette.BrightText, QColor("#ffffff"))
    p.setColor(QPalette.Link, QColor(c["accent"]))
    p.setColor(QPalette.Highlight, QColor(c["accent"]))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(c["text_disabled"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c["text_disabled"]))
    app.setPalette(p)

    # Optional monospace for spin-boxes (cyberpunk only)
    spin_font = ""
    if c["mono_font"]:
        spin_font = f"font-family: {c['mono_font']};"

    progress_font = ""
    if c["mono_font"]:
        progress_font = f"font-family: {c['mono_font']};"

    # primary button style varies per theme
    if current_name == "cyberpunk":
        primary_btn = (
            f"QPushButton[primary=\"true\"] {{ background-color: transparent; color: {c['accent']}; font-weight: 700; border: 1px solid {c['accent']}; }}"
            f"QPushButton[primary=\"true\"]:hover {{ background-color: {c['accent_hover']}; border-color: {c['accent']}; }}"
            f"QPushButton[primary=\"true\"]:pressed {{ background-color: {c['accent_pressed']}; }}"
            f"QPushButton[primary=\"true\"]:disabled {{ color: #0d2030; border-color: #0d1a28; }}"
        )
    else:
        primary_btn = (
            f"QPushButton[primary=\"true\"] {{ background-color: {c['accent_bg']}; color: #ffffff; font-weight: 700; border: 1px solid #2d6bc4; }}"
            f"QPushButton[primary=\"true\"]:hover {{ background-color: {c['accent_hover']}; }}"
            f"QPushButton[primary=\"true\"]:pressed {{ background-color: {c['accent_pressed']}; }}"
            f"QPushButton[primary=\"true\"]:disabled {{ background-color: #1a2a3a; color: #4a6080; border-color: #1a2a3a; }}"
        )

    # cyberpunk-specific extras
    cp_extras = ""
    if current_name == "cyberpunk":
        cp_extras = f"""
        /* ── Cyberpunk HUD overrides ── */
        QPushButton {{
            background-color: transparent; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: {dp(4)}px;
            padding: {dp(5)}px {dp(14)}px; min-height: {dp(24)}px;
            font-weight: 500;
        }}
        QPushButton:hover {{ background-color: {c['accent_hover']}; border-color: {c['accent']}; color: {c['accent']}; }}
        QPushButton:pressed {{ background-color: {c['accent_pressed']}; }}
        QPushButton:disabled {{ color: {c['text_disabled']}; border-color: #0d1a28; background: transparent; }}

        QGroupBox {{
            color: {c['accent']}; border: 1px solid {c['border']};
            border-radius: {dp(4)}px; margin-top: {dp(8)}px; padding-top: {dp(16)}px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin; left: {dp(10)}px; padding: 0 {dp(6)}px;
            color: {c['accent']}; font-weight: bold;
            text-transform: uppercase; letter-spacing: 1px;
        }}

        QTabBar::tab {{
            background-color: {c['tab_bg']}; color: {c['tab_text']};
            border: 1px solid {c['tab_border']}; border-top: 2px solid transparent;
            border-bottom: none;
            padding: {dp(8)}px {dp(18)}px;
            font-weight: 500; text-transform: uppercase; letter-spacing: 1px;
        }}
        QTabBar::tab:selected {{
            background-color: {c['bg']}; color: {c['tab_active_text']};
            border-top: 2px solid {c['tab_accent']}; font-weight: bold;
        }}
        QTabBar::tab:hover {{ color: {c['tab_hover_text']}; background-color: {c['tab_hover_accent']}; }}

        QHeaderView::section {{
            background-color: {c['bg']}; color: {c['accent']};
            border: none; border-bottom: 1px solid {c['border']};
            border-right: 1px solid {c['bg']};
            padding: {dp(5)}px {dp(8)}px;
            font-weight: bold; text-transform: uppercase; letter-spacing: 1px; font-size: 8pt;
        }}

        QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}

        QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
        QScrollBar::handle:horizontal:hover {{ background: {c['accent']}; }}
        """

    app.setStyleSheet(f"""
        * {{ font-family: {c['ui_font']}; }}

        QToolTip {{ color: {_tooltip_text}; background: {c['tooltip_bg']}; border: 1px solid {c['tooltip_border']}; border-radius: {dp(8)}px; padding: {dp(6)}px {dp(10)}px; }}

        QPushButton {{
            background-color: {c['bg_card']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: {dp(8)}px;
            padding: {dp(6)}px {dp(14)}px; min-height: {dp(28)}px;
            font-weight: 500;
        }}
        QPushButton:hover {{ background-color: {c['bg_mid']}; border-color: {c['border_hover']}; }}
        QPushButton:pressed {{ background-color: {c['bg']}; }}
        QPushButton:focus {{ border-color: {c['accent']}; outline: none; }}
        QPushButton:disabled {{ color: {c['text_disabled']}; border-color: {c['border']}; }}
        QPushButton[danger="true"] {{
            background-color: transparent;
            color: {c['red']};
            border-color: {c['red']};
        }}
        QPushButton[danger="true"]:hover {{
            background-color: {c['red']};
            color: #ffffff;
        }}
        QPushButton[ghost="true"] {{
            background-color: transparent;
        }}
        {primary_btn}

        QLineEdit, QComboBox {{
            background-color: {c['bg_input']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: {dp(8)}px;
            padding: {dp(6)}px {dp(10)}px;
            min-height: {dp(28)}px;
        }}
        QSpinBox {{
            background-color: {c['bg_input']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: {dp(8)}px;
            padding: {dp(5)}px {dp(10)}px;
            min-height: {dp(28)}px;
            {spin_font}
        }}
        QLineEdit::placeholder {{ color: {c['text_dim']}; }}
        QLineEdit:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
        QComboBox QAbstractItemView {{
            background-color: {c['bg_card']}; color: {c['text']};
            selection-background-color: {c['highlight_bg']};
            border: 1px solid {c['border']};
            border-radius: {dp(8)}px;
            outline: none;
        }}
        QComboBox::drop-down {{ border: none; }}
        QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ width: {dp(18)}px; border: none; }}

        QDialog {{ background-color: {c['bg']}; color: {c['text']}; }}
        QMessageBox {{ background-color: {c['bg']}; color: {c['text']}; }}
        QLabel {{ color: {c['text']}; }}
        QLabel[status="muted"] {{ color: {c['text_dim']}; font-size: 9pt; }}
        QLabel[status="success"] {{ color: {c['green']}; font-weight: 600; }}
        QLabel[status="error"] {{ color: {c['red']}; font-weight: 600; }}

        QGroupBox {{
            color: {c['text_dim']}; border: 1px solid {c['border']};
            border-radius: {dp(10)}px; margin-top: {dp(10)}px; padding-top: {dp(16)}px;
        }}
        QGroupBox::title {{ subcontrol-origin: margin; left: {dp(10)}px; padding: 0 {dp(6)}px; color: {c['text_dim']}; }}
        QFrame#OptSettings {{
            background: {c['settings_bg']};
            border: 1px solid {c['border']};
            border-radius: {dp(10)}px;
        }}

        QTabWidget::pane {{ border: 1px solid {c['tab_border']}; }}
        QTabBar::tab {{
            background-color: transparent; color: {c['tab_text']};
            border: 1px solid transparent; border-radius: {dp(8)}px;
            padding: {dp(8)}px {dp(14)}px;
        }}
        QTabBar::tab:selected {{
            background-color: {c['bg_mid']}; color: {c['tab_active_text']};
            border-color: {c['tab_border']}; border-bottom: 2px solid {c['tab_accent']}; font-weight: bold;
        }}
        QTabBar::tab:hover {{ color: {c['tab_hover_text']}; border-color: {c['tab_border']}; }}

        QTableWidget, QTableView {{
            background-color: {c['bg_mid']}; alternate-background-color: {c['bg']};
            color: {c['text']}; gridline-color: {c['border']};
            border: 1px solid {c['border']}; border-radius: {dp(10)}px;
            selection-background-color: {c['highlight_bg']}; selection-color: #ffffff;
        }}
        QTableWidget::item, QTableView::item {{ padding: {dp(6)}px {dp(8)}px; border: none; }}
        QHeaderView {{ background-color: {c['bg']}; }}
        QHeaderView::section {{
            background-color: {c['bg']}; color: {c['text_dim']};
            border: none; border-bottom: 1px solid {c['border']}; border-right: 1px solid {c['bg']};
            padding: {dp(7)}px {dp(10)}px;
            font-weight: 600;
        }}

        QScrollBar:vertical {{ background: transparent; width: {dp(8)}px; margin: 0; }}
        QScrollBar::handle:vertical {{ background: {c['scrollbar_handle']}; border-radius: {dp(4)}px; min-height: {dp(24)}px; margin: {dp(2)}px; }}
        QScrollBar::handle:vertical:hover {{ background: {c['accent']}; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        QScrollBar:horizontal {{ background: transparent; height: {dp(8)}px; margin: 0; }}
        QScrollBar::handle:horizontal {{ background: {c['scrollbar_handle']}; border-radius: {dp(4)}px; min-width: {dp(24)}px; margin: {dp(2)}px; }}
        QScrollBar::handle:horizontal:hover {{ background: {c['accent']}; }}
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

        QProgressDialog {{ background-color: {c['bg']}; color: {c['text']}; }}
        QProgressBar {{
            background-color: {c['bg_input']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: {dp(4)}px; text-align: center;
            {progress_font}
        }}
        QProgressBar::chunk {{ {c['progress_chunk']}; border-radius: {dp(4)}px; }}

        QListWidget, QListView {{
            background-color: {c['bg_mid']}; alternate-background-color: {c['bg']}; color: {c['text']};
            border: 1px solid {c['border']}; border-radius: {dp(10)}px;
            outline: none;
        }}
        QListWidget::item, QListView::item {{
            padding: {dp(7)}px {dp(10)}px;
            border-radius: {dp(6)}px;
            margin: {dp(1)}px {dp(4)}px;
        }}
        QListWidget::item:hover, QListView::item:hover {{ background-color: {c['bg_card']}; }}
        QListWidget::item:selected, QListView::item:selected {{
            background-color: {c['highlight_bg']};
            color: #ffffff;
        }}
        QScrollArea {{ background-color: {c['bg']}; border: none; }}

        QMenu {{ background-color: {c['bg_card']}; color: {c['text']}; border: 1px solid {c['border']}; border-radius: {dp(6)}px; }}
        QMenu::item:selected {{ background-color: {c['highlight_bg']}; }}

        QStatusBar {{
            background-color: {c['bg']};
            color: {c['text_dim']};
            border-top: 1px solid {c['border']};
        }}
        QMenuBar {{ background-color: {c['bg']}; color: {c['text']}; }}
        QMenuBar::item:selected {{ background-color: {c['highlight_bg']}; }}

        QCheckBox {{ color: {c['text']}; spacing: {dp(6)}px; }}
        QCheckBox::indicator {{ width: {dp(14)}px; height: {dp(14)}px; border: 1px solid {c['border']}; border-radius: {dp(3)}px; background: {c['bg_input']}; }}
        QCheckBox::indicator:checked {{ background: {c['accent']}; border-color: {c['accent']}; }}
        QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}

        QSplitter::handle {{ background: {c['bg_mid']}; }}
        QSplitter::handle:horizontal {{ width: 1px; }}
        QSplitter::handle:vertical {{ height: 1px; }}

        {cp_extras}
    """)
