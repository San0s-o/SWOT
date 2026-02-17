from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QScrollArea, QVBoxLayout

from app.i18n import tr
from app.ui.widgets.selection_combos import _UnitSearchComboBox


def apply_tab_style(window) -> None:
    window.tabs.setStyleSheet(
        """
        QTabWidget {
            border: none;
            background: transparent;
        }
        QTabWidget::pane {
            border: 1px solid #35383d;
            border-top: none;
            background: #1f2126;
            top: -1px;
        }
        QTabBar {
            qproperty-drawBase: 0;
            background: transparent;
        }
        QTabBar::tab {
            background: #262a30;
            color: #9aa4b2;
            border: 1px solid #35383d;
            border-bottom: none;
            border-top-left-radius: 8px;
            border-top-right-radius: 8px;
            min-width: 120px;
            padding: 7px 16px;
            margin-right: 2px;
        }
        QTabBar::tab:selected {
            background: #1f2126;
            color: #f0f3f7;
            border-color: #4a90e2;
            margin-bottom: -1px;
        }
        QTabBar::tab:hover:!selected {
            background: #2f353d;
            color: #e1e6ec;
        }
        """
    )


def show_help_dialog(window) -> None:
    dlg = QDialog(window)
    dlg.setWindowTitle(tr("help.title"))
    dlg.resize(620, 520)
    layout = QVBoxLayout(dlg)

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setStyleSheet("QScrollArea { border: none; }")
    layout.addWidget(scroll)

    content = QLabel()
    content.setTextFormat(Qt.RichText)
    content.setWordWrap(True)
    content.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    content.setContentsMargins(16, 12, 16, 12)
    content.setStyleSheet("font-size: 10pt; line-height: 1.5;")
    content.setText(tr("help.content"))
    scroll.setWidget(content)

    btn_close = QPushButton(tr("btn.close"))
    btn_close.clicked.connect(dlg.accept)
    layout.addWidget(btn_close, 0, Qt.AlignRight)
    dlg.exec()


def on_language_changed(window, index: int) -> None:
    pass


def retranslate_ui(window) -> None:
    window.setWindowTitle(tr("main.title"))
    if not window.account:
        window.lbl_status.setText(tr("main.no_import"))

    def _set_tab_text(tab_attr: str, key: str) -> None:
        tab = getattr(window, tab_attr, None)
        if tab is None:
            return
        idx = window.tabs.indexOf(tab)
        if idx >= 0:
            window.tabs.setTabText(idx, tr(key))

    _set_tab_text("tab_overview", "tab.overview")
    _set_tab_text("tab_siege_raw", "tab.siege_current")
    _set_tab_text("tab_rta_overview", "tab.rta_current")
    _set_tab_text("tab_rune_optimization", "tab.rune_optimization")
    _set_tab_text("tab_siege_builder", "tab.siege_builder")
    _set_tab_text("tab_saved_siege", "tab.siege_saved")
    _set_tab_text("tab_wgb_builder", "tab.wgb_builder")
    _set_tab_text("tab_saved_wgb", "tab.wgb_saved")
    _set_tab_text("tab_rta_builder", "tab.rta_builder")
    _set_tab_text("tab_saved_rta", "tab.rta_saved")
    _set_tab_text("tab_arena_rush_builder", "tab.arena_rush_builder")
    _set_tab_text("tab_saved_arena_rush", "tab.arena_rush_saved")
    _set_tab_text("tab_settings", "tab.settings")

    window.lbl_saved_siege.setText(tr("label.saved_opt"))
    window.lbl_saved_wgb.setText(tr("label.saved_opt"))
    window.lbl_saved_rta.setText(tr("label.saved_opt"))
    window.lbl_saved_arena_rush.setText(tr("label.saved_opt"))
    window.btn_delete_saved_siege.setText(tr("btn.delete"))
    window.btn_delete_saved_wgb.setText(tr("btn.delete"))
    window.btn_delete_saved_rta.setText(tr("btn.delete"))
    window.btn_delete_saved_arena_rush.setText(tr("btn.delete"))

    window.box_siege_select.setTitle(tr("group.siege_select"))
    for idx, lbl in enumerate(window.lbl_siege_defense, start=1):
        lbl.setText(tr("label.defense", n=idx))
    window.btn_take_current_siege.setText(tr("btn.take_siege"))
    window.btn_validate_siege.setText(tr("btn.validate_pools"))
    window.btn_edit_presets_siege.setText(tr("btn.builds"))
    window.btn_optimize_siege.setText(tr("btn.optimize"))
    window.lbl_siege_passes.setText(tr("label.passes"))
    window.lbl_siege_workers.setText(tr("label.workers"))
    window.lbl_siege_profile.setText("Profil")
    window.spin_multi_pass_siege.setToolTip(tr("tooltip.passes"))
    window.combo_workers_siege.setToolTip(tr("tooltip.workers"))

    window.box_wgb_select.setTitle(tr("group.wgb_select"))
    for idx, lbl in enumerate(window.lbl_wgb_defense, start=1):
        lbl.setText(tr("label.defense", n=idx))
    window.btn_validate_wgb.setText(tr("btn.validate_pools"))
    window.btn_edit_presets_wgb.setText(tr("btn.builds"))
    window.btn_optimize_wgb.setText(tr("btn.optimize"))
    window.lbl_wgb_passes.setText(tr("label.passes"))
    window.lbl_wgb_workers.setText(tr("label.workers"))
    window.lbl_wgb_profile.setText("Profil")
    window.spin_multi_pass_wgb.setToolTip(tr("tooltip.passes"))
    window.combo_workers_wgb.setToolTip(tr("tooltip.workers"))

    window.box_rta_select.setTitle(tr("group.rta_select"))
    window.btn_rta_add.setText(tr("btn.add"))
    window.btn_rta_remove.setText(tr("btn.remove"))
    window.btn_take_current_rta.setText(tr("btn.take_rta"))
    window.btn_validate_rta.setText(tr("btn.validate"))
    window.btn_edit_presets_rta.setText(tr("btn.builds"))
    window.btn_optimize_rta.setText(tr("btn.optimize"))
    window.lbl_rta_passes.setText(tr("label.passes"))
    window.lbl_rta_workers.setText(tr("label.workers"))
    window.lbl_rta_profile.setText("Profil")
    window.spin_multi_pass_rta.setToolTip(tr("tooltip.passes"))
    window.combo_workers_rta.setToolTip(tr("tooltip.workers"))

    window.box_arena_def_select.setTitle(tr("group.arena_def_select"))
    window.box_arena_off_select.setTitle(tr("group.arena_off_select"))
    window.lbl_arena_defense.setText(tr("label.arena_defense"))
    for idx, lbl in enumerate(window.lbl_arena_offense, start=1):
        lbl.setText(tr("label.offense", n=idx))
    for chk in window.chk_arena_offense_enabled:
        chk.setText(tr("label.active"))
    window.btn_take_current_arena_def.setText(tr("btn.take_arena_def"))
    window.btn_take_arena_decks.setText(tr("btn.take_arena_off"))
    window.btn_validate_arena_rush.setText(tr("btn.validate_pools"))
    window.btn_edit_presets_arena_rush.setText(tr("btn.builds"))
    window.btn_optimize_arena_rush.setText(tr("btn.optimize"))
    window.lbl_arena_rush_passes.setText(tr("label.passes"))
    window.lbl_arena_rush_workers.setText(tr("label.workers"))
    window.lbl_arena_rush_profile.setText("Profil")
    window.spin_multi_pass_arena_rush.setToolTip(tr("tooltip.passes"))
    window.combo_workers_arena_rush.setToolTip(tr("tooltip.workers"))
    idx_arena_max = window.combo_quality_profile_arena_rush.findData("max_quality")
    if idx_arena_max >= 0:
        window.combo_quality_profile_arena_rush.setItemText(idx_arena_max, "Max Qualität")

    window.lbl_team.setText(tr("label.team"))
    window.btn_new_team.setText(tr("btn.new_team"))
    window.btn_edit_team.setText(tr("btn.edit_team"))
    window.btn_remove_team.setText(tr("btn.delete_team"))
    window.btn_optimize_team.setText(tr("btn.optimize_team"))
    window.lbl_team_passes.setText(tr("label.passes"))
    window.lbl_team_workers.setText(tr("label.workers"))
    window.lbl_team_profile.setText("Profil")
    window.spin_multi_pass_team.setToolTip(tr("tooltip.passes"))
    window.combo_workers_team.setToolTip(tr("tooltip.workers"))
    window._refresh_team_combo()

    for cmb in window.findChildren(_UnitSearchComboBox):
        le = cmb.lineEdit()
        if le is not None:
            le.setPlaceholderText(tr("main.search_placeholder"))

    window.overview_widget.retranslate()
    window.rta_overview.retranslate()
    window.rune_optimization_widget.retranslate()
    if window.account:
        window._render_siege_raw()
        window._refresh_rune_optimization()
        window._render_wgb_preview()
        window._on_saved_opt_changed("siege")
        window._on_saved_opt_changed("wgb")
        window._on_saved_opt_changed("rta")
        window._on_saved_opt_changed("arena_rush")

    from app.ui.main_window_sections.settings_section import retranslate_settings
    retranslate_settings(window)
