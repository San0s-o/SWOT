from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QThreadPool, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.i18n import tr
from app.ui.dpi import dp
from app.ui import theme as _theme


_ABOUT_CREATOR = "San0s"
_ABOUT_DISCORD = "san0s"
_CLOUD_OPTIN_KEY = "cloud_learning_enabled_full"
_COMMUNITY_BUILD_TRENDS_KEY = "community_build_trends_enabled_full"
_COMMUNITY_SET_LIMIT_KEY = "community_trends_set_combo_limit_full"
_COMMUNITY_MAINSTAT_LIMIT_KEY = "community_trends_mainstat_limit_full"
_COMMUNITY_ART_SUBSTAT_LIMIT_KEY = "community_trends_artifact_substat_limit_full"
_UI_EXTRA_INFO_KEY = "ui_show_extra_info"


def _open_discord_dm(window) -> None:
    # Direct username-based DM deep links are not supported; open Discord DM view as best effort.
    opened = QDesktopServices.openUrl(QUrl("discord://-/channels/@me"))
    if not opened:
        opened = QDesktopServices.openUrl(QUrl("https://discord.com/channels/@me"))
    if opened:
        window.statusBar().showMessage(tr("settings.discord_opened", handle=_ABOUT_DISCORD), 6000)
    else:
        window.statusBar().showMessage(tr("settings.discord_open_failed", handle=_ABOUT_DISCORD), 6000)


def _settings_path(window) -> Path:
    return Path(window.config_dir) / "app_settings.json"


def _load_app_settings(window) -> dict:
    path = _settings_path(window)
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
        if isinstance(data, dict):
            return dict(data)
    except Exception:
        return {}
    return {}


def _save_app_settings(window, updates: dict) -> None:
    data = _load_app_settings(window)
    data.update(dict(updates or {}))
    path = _settings_path(window)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _cloud_learning_optin(window) -> bool:
    data = _load_app_settings(window)
    return bool(data.get(_CLOUD_OPTIN_KEY, True))


def _set_cloud_learning_optin(window, enabled: bool) -> None:
    _save_app_settings(window, {_CLOUD_OPTIN_KEY: bool(enabled)})


def _community_build_trends_optin(window) -> bool:
    data = _load_app_settings(window)
    return bool(data.get(_COMMUNITY_BUILD_TRENDS_KEY, True))


def _set_community_build_trends_optin(window, enabled: bool) -> None:
    _save_app_settings(window, {_COMMUNITY_BUILD_TRENDS_KEY: bool(enabled)})


def _clamp_top_n_limit(value: object, default: int = 3) -> int:
    try:
        raw = int(value or default)
    except Exception:
        raw = int(default)
    return max(1, min(3, int(raw)))


def _community_set_limit(window) -> int:
    data = _load_app_settings(window)
    return _clamp_top_n_limit(data.get(_COMMUNITY_SET_LIMIT_KEY, 3), default=3)


def _set_community_set_limit(window, value: int) -> None:
    _save_app_settings(window, {_COMMUNITY_SET_LIMIT_KEY: _clamp_top_n_limit(value, default=3)})


def _community_mainstat_limit(window) -> int:
    data = _load_app_settings(window)
    return _clamp_top_n_limit(data.get(_COMMUNITY_MAINSTAT_LIMIT_KEY, 3), default=3)


def _set_community_mainstat_limit(window, value: int) -> None:
    _save_app_settings(window, {_COMMUNITY_MAINSTAT_LIMIT_KEY: _clamp_top_n_limit(value, default=3)})


def _community_artifact_substat_limit(window) -> int:
    data = _load_app_settings(window)
    try:
        raw = int(data.get(_COMMUNITY_ART_SUBSTAT_LIMIT_KEY, 2) or 2)
    except Exception:
        raw = 2
    return max(1, min(2, int(raw)))


def _set_community_artifact_substat_limit(window, value: int) -> None:
    try:
        raw = int(value or 2)
    except Exception:
        raw = 2
    _save_app_settings(window, {_COMMUNITY_ART_SUBSTAT_LIMIT_KEY: max(1, min(2, int(raw)))})


def _populate_top_n_combo(combo: QComboBox, max_n: int = 3) -> None:
    current_data = combo.currentData()
    combo.blockSignals(True)
    combo.clear()
    upper = max(1, int(max_n or 1))
    for n in range(1, upper + 1):
        combo.addItem(tr("settings.top_n_option", n=n), n)
    idx = combo.findData(int(current_data or 0))
    if idx < 0:
        idx = combo.findData(upper)
    combo.setCurrentIndex(max(0, idx))
    combo.blockSignals(False)


def ui_show_extra_info_enabled(window) -> bool:
    data = _load_app_settings(window)
    return bool(data.get(_UI_EXTRA_INFO_KEY, False))


def _set_ui_show_extra_info(window, enabled: bool) -> None:
    _save_app_settings(window, {_UI_EXTRA_INFO_KEY: bool(enabled)})


# ================================================================
# Init
# ================================================================

def init_settings_ui(window) -> None:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)

    container = QWidget()
    container.setMaximumWidth(dp(900))
    main_layout = QVBoxLayout(container)
    main_layout.setContentsMargins(dp(16), dp(12), dp(16), dp(12))
    main_layout.setSpacing(dp(16))

    # --- Section 1: Account / JSON Import -----------------------
    window.grp_settings_account = QGroupBox(tr("settings.group_account"))
    account_layout = QVBoxLayout(window.grp_settings_account)

    window.lbl_settings_import_status = QLabel(tr("settings.label_no_import"))
    account_layout.addWidget(window.lbl_settings_import_status)

    btn_row_account = QHBoxLayout()
    window.btn_settings_import = QPushButton(tr("settings.btn_import"))
    window.btn_settings_import.clicked.connect(window._on_settings_import_json)
    btn_row_account.addWidget(window.btn_settings_import)

    window.btn_settings_clear_snapshot = QPushButton(tr("settings.btn_clear_snapshot"))
    window.btn_settings_clear_snapshot.clicked.connect(window._on_settings_clear_snapshot)
    btn_row_account.addWidget(window.btn_settings_clear_snapshot)
    btn_row_account.addStretch(1)
    account_layout.addLayout(btn_row_account)
    main_layout.addWidget(window.grp_settings_account)

    # --- Section 2: License Management --------------------------
    window.grp_settings_license = QGroupBox(tr("settings.group_license"))
    license_layout = QVBoxLayout(window.grp_settings_license)

    window.lbl_settings_license_type = QLabel("")
    license_layout.addWidget(window.lbl_settings_license_type)

    window.lbl_settings_license_key = QLabel("")
    license_layout.addWidget(window.lbl_settings_license_key)

    key_row = QHBoxLayout()
    window.edit_settings_license_key = QLineEdit()
    window.edit_settings_license_key.setPlaceholderText("SWTO-...")
    key_row.addWidget(window.edit_settings_license_key, 1)

    window.btn_settings_activate = QPushButton(tr("btn.activate"))
    window.btn_settings_activate.clicked.connect(window._on_settings_activate_license)
    key_row.addWidget(window.btn_settings_activate)
    license_layout.addLayout(key_row)

    window.lbl_settings_license_feedback = QLabel("")
    license_layout.addWidget(window.lbl_settings_license_feedback)

    main_layout.addWidget(window.grp_settings_license)

    # --- Section 2b: Cloud & Community ---------------------------
    window.grp_settings_cloud = QGroupBox(tr("settings.group_cloud"))
    cloud_layout = QVBoxLayout(window.grp_settings_cloud)
    cloud_layout.setSpacing(dp(6))

    window.chk_settings_cloud_learning = QCheckBox(tr("settings.cloud_learning_optin"))
    window.chk_settings_cloud_learning.setChecked(_cloud_learning_optin(window))
    window.chk_settings_cloud_learning.toggled.connect(
        lambda checked: on_settings_cloud_learning_toggled(window, bool(checked))
    )
    cloud_layout.addWidget(window.chk_settings_cloud_learning)

    window.lbl_settings_cloud_learning_hint = QLabel("")
    window.lbl_settings_cloud_learning_hint.setWordWrap(True)
    window.lbl_settings_cloud_learning_hint.setContentsMargins(dp(20), 0, 0, dp(4))
    cloud_layout.addWidget(window.lbl_settings_cloud_learning_hint)

    window.chk_settings_community_trends = QCheckBox(tr("settings.community_trends_optin"))
    window.chk_settings_community_trends.setChecked(_community_build_trends_optin(window))
    window.chk_settings_community_trends.toggled.connect(
        lambda checked: on_settings_community_trends_toggled(window, bool(checked))
    )
    cloud_layout.addWidget(window.chk_settings_community_trends)

    window.lbl_settings_community_trends_hint = QLabel("")
    window.lbl_settings_community_trends_hint.setWordWrap(True)
    window.lbl_settings_community_trends_hint.setContentsMargins(dp(20), 0, 0, dp(4))
    cloud_layout.addWidget(window.lbl_settings_community_trends_hint)

    # Community limits in a form layout for proper alignment
    limits_form = QFormLayout()
    limits_form.setContentsMargins(dp(20), dp(4), 0, 0)
    limits_form.setHorizontalSpacing(dp(12))
    limits_form.setVerticalSpacing(dp(6))

    window.lbl_settings_community_set_limit = QLabel(tr("settings.community_set_limit_label"))
    window.combo_settings_community_set_limit = QComboBox()
    window.combo_settings_community_set_limit.setFixedWidth(dp(110))
    _populate_top_n_combo(window.combo_settings_community_set_limit)
    idx_set = window.combo_settings_community_set_limit.findData(_community_set_limit(window))
    if idx_set >= 0:
        window.combo_settings_community_set_limit.setCurrentIndex(idx_set)
    window.combo_settings_community_set_limit.currentIndexChanged.connect(
        lambda _idx: on_settings_community_set_limit_changed(window)
    )
    limits_form.addRow(window.lbl_settings_community_set_limit, window.combo_settings_community_set_limit)

    window.lbl_settings_community_mainstat_limit = QLabel(tr("settings.community_mainstat_limit_label"))
    window.combo_settings_community_mainstat_limit = QComboBox()
    window.combo_settings_community_mainstat_limit.setFixedWidth(dp(110))
    _populate_top_n_combo(window.combo_settings_community_mainstat_limit)
    idx_main = window.combo_settings_community_mainstat_limit.findData(_community_mainstat_limit(window))
    if idx_main >= 0:
        window.combo_settings_community_mainstat_limit.setCurrentIndex(idx_main)
    window.combo_settings_community_mainstat_limit.currentIndexChanged.connect(
        lambda _idx: on_settings_community_mainstat_limit_changed(window)
    )
    limits_form.addRow(window.lbl_settings_community_mainstat_limit, window.combo_settings_community_mainstat_limit)

    window.lbl_settings_community_art_substat_limit = QLabel(tr("settings.community_art_substat_limit_label"))
    window.combo_settings_community_art_substat_limit = QComboBox()
    window.combo_settings_community_art_substat_limit.setFixedWidth(dp(110))
    _populate_top_n_combo(window.combo_settings_community_art_substat_limit, max_n=2)
    idx_art_sub = window.combo_settings_community_art_substat_limit.findData(_community_artifact_substat_limit(window))
    if idx_art_sub >= 0:
        window.combo_settings_community_art_substat_limit.setCurrentIndex(idx_art_sub)
    window.combo_settings_community_art_substat_limit.currentIndexChanged.connect(
        lambda _idx: on_settings_community_art_substat_limit_changed(window)
    )
    limits_form.addRow(window.lbl_settings_community_art_substat_limit, window.combo_settings_community_art_substat_limit)

    cloud_layout.addLayout(limits_form)

    window.lbl_settings_community_limit_hint = QLabel("")
    window.lbl_settings_community_limit_hint.setWordWrap(True)
    window.lbl_settings_community_limit_hint.setContentsMargins(dp(20), 0, 0, 0)
    cloud_layout.addWidget(window.lbl_settings_community_limit_hint)

    window.btn_settings_delete_cloud_data = QPushButton(tr("settings.btn_delete_cloud_data"))
    window.btn_settings_delete_cloud_data.clicked.connect(window._on_settings_delete_cloud_data)
    cloud_layout.addWidget(window.btn_settings_delete_cloud_data)

    main_layout.addWidget(window.grp_settings_cloud)

    # --- Section 3: Appearance (Language + Theme) ----------------
    window.grp_settings_appearance = QGroupBox(tr("settings.group_appearance"))
    appearance_form = QFormLayout(window.grp_settings_appearance)
    appearance_form.setHorizontalSpacing(dp(12))
    appearance_form.setVerticalSpacing(dp(6))

    import app.i18n as i18n

    window.lbl_settings_language = QLabel(tr("settings.label_language"))
    window.combo_settings_language = QComboBox()
    window.combo_settings_language.setFixedWidth(dp(200))
    for code, name in i18n.available_languages().items():
        window.combo_settings_language.addItem(name, code)
    idx = window.combo_settings_language.findData(i18n.get_language())
    if idx >= 0:
        window.combo_settings_language.setCurrentIndex(idx)
    window.combo_settings_language.currentIndexChanged.connect(window._on_settings_language_changed)
    appearance_form.addRow(window.lbl_settings_language, window.combo_settings_language)

    window.lbl_settings_theme = QLabel(tr("settings.label_theme"))
    window.combo_settings_theme = QComboBox()
    window.combo_settings_theme.setFixedWidth(dp(200))
    window.combo_settings_theme.addItem("Classic Dark", "classic")
    window.combo_settings_theme.addItem("Cyberpunk HUD", "cyberpunk")
    idx_theme = window.combo_settings_theme.findData(_theme.current_name)
    if idx_theme >= 0:
        window.combo_settings_theme.setCurrentIndex(idx_theme)
    window.combo_settings_theme.currentIndexChanged.connect(
        lambda idx: _on_theme_changed(window, idx)
    )
    appearance_form.addRow(window.lbl_settings_theme, window.combo_settings_theme)

    window.chk_settings_extra_info = QCheckBox(tr("settings.extra_info_optin"))
    window.chk_settings_extra_info.setChecked(ui_show_extra_info_enabled(window))
    window.chk_settings_extra_info.toggled.connect(
        lambda checked: on_settings_extra_info_toggled(window, bool(checked))
    )
    appearance_form.addRow(window.chk_settings_extra_info)

    main_layout.addWidget(window.grp_settings_appearance)

    # --- Section 4: Data Management -----------------------------
    window.grp_settings_data = QGroupBox(tr("settings.group_data"))
    data_layout = QVBoxLayout(window.grp_settings_data)

    window.btn_settings_reset_presets = QPushButton(tr("settings.btn_reset_presets"))
    window.btn_settings_reset_presets.clicked.connect(window._on_settings_reset_presets)
    data_layout.addWidget(window.btn_settings_reset_presets)

    window.btn_settings_clear_optimizations = QPushButton(tr("settings.btn_clear_optimizations"))
    window.btn_settings_clear_optimizations.clicked.connect(window._on_settings_clear_optimizations)
    data_layout.addWidget(window.btn_settings_clear_optimizations)

    window.btn_settings_clear_teams = QPushButton(tr("settings.btn_clear_teams"))
    window.btn_settings_clear_teams.clicked.connect(window._on_settings_clear_teams)
    data_layout.addWidget(window.btn_settings_clear_teams)
    main_layout.addWidget(window.grp_settings_data)

    # --- Section 5: Updates -------------------------------------
    window.grp_settings_updates = QGroupBox(tr("settings.group_updates"))
    update_layout = QVBoxLayout(window.grp_settings_updates)

    window.lbl_settings_version = QLabel("")
    update_layout.addWidget(window.lbl_settings_version)

    window.btn_settings_check_update = QPushButton(tr("settings.btn_check_update"))
    window.btn_settings_check_update.clicked.connect(window._on_settings_check_update)
    update_layout.addWidget(window.btn_settings_check_update)
    main_layout.addWidget(window.grp_settings_updates)

    # --- Section 6: About --------------------------------------
    window.grp_settings_about = QGroupBox(tr("settings.group_about"))
    about_layout = QVBoxLayout(window.grp_settings_about)

    window.lbl_settings_about_version = QLabel("")
    about_layout.addWidget(window.lbl_settings_about_version)

    window.lbl_settings_about_license = QLabel("")
    about_layout.addWidget(window.lbl_settings_about_license)

    window.lbl_settings_about_creator = QLabel("")
    about_layout.addWidget(window.lbl_settings_about_creator)

    window.lbl_settings_about_discord = QLabel("")
    about_layout.addWidget(window.lbl_settings_about_discord)

    window.btn_settings_open_discord_dm = QPushButton(tr("settings.btn_open_discord_dm"))
    window.btn_settings_open_discord_dm.clicked.connect(lambda: _open_discord_dm(window))
    _discord_icon_path = Path(__file__).resolve().parents[2] / "assets" / "discord_icon.svg"
    if _discord_icon_path.exists():
        try:
            from PySide6.QtSvg import QSvgRenderer
            from PySide6.QtGui import QPixmap, QPainter
            _renderer = QSvgRenderer(str(_discord_icon_path))
            if _renderer.isValid():
                _pix = QPixmap(18, 18)
                _pix.fill(Qt.transparent)
                _painter = QPainter(_pix)
                _renderer.render(_painter)
                _painter.end()
                window.btn_settings_open_discord_dm.setIcon(QIcon(_pix))
                window.btn_settings_open_discord_dm.setIconSize(QSize(dp(18), dp(18)))
        except ImportError:
            pass
    about_layout.addWidget(window.btn_settings_open_discord_dm)

    window.lbl_settings_about_open_source = QLabel("")
    window.lbl_settings_about_open_source.setWordWrap(True)
    window.lbl_settings_about_open_source.setTextFormat(Qt.RichText)
    window.lbl_settings_about_open_source.setOpenExternalLinks(True)
    window.lbl_settings_about_open_source.setTextInteractionFlags(Qt.TextBrowserInteraction)
    about_layout.addWidget(window.lbl_settings_about_open_source)

    window.lbl_settings_about_data_sources = QLabel("")
    window.lbl_settings_about_data_sources.setWordWrap(True)
    window.lbl_settings_about_data_sources.setTextFormat(Qt.RichText)
    window.lbl_settings_about_data_sources.setOpenExternalLinks(True)
    window.lbl_settings_about_data_sources.setTextInteractionFlags(Qt.TextBrowserInteraction)
    about_layout.addWidget(window.lbl_settings_about_data_sources)

    window.lbl_settings_about_com2us = QLabel("")
    window.lbl_settings_about_com2us.setWordWrap(True)
    window.lbl_settings_about_com2us.setTextFormat(Qt.RichText)
    window.lbl_settings_about_com2us.setOpenExternalLinks(True)
    window.lbl_settings_about_com2us.setTextInteractionFlags(Qt.TextBrowserInteraction)
    about_layout.addWidget(window.lbl_settings_about_com2us)

    window.lbl_settings_about_data_dir = QLabel("")
    window.lbl_settings_about_data_dir.setTextInteractionFlags(Qt.TextSelectableByMouse)
    about_layout.addWidget(window.lbl_settings_about_data_dir)
    main_layout.addWidget(window.grp_settings_about)

    main_layout.addStretch(1)
    scroll.setWidget(container)

    tab_layout = QVBoxLayout(window.tab_settings)
    tab_layout.setContentsMargins(0, 0, 0, 0)
    tab_layout.addWidget(scroll)

    # Populate dynamic labels
    window._settings_license_worker = None
    window._settings_update_worker = None
    window._settings_cloud_delete_worker = None
    refresh_settings_import_status(window)
    refresh_settings_license_status(window)
    _refresh_settings_about(window)


# ================================================================
# Refresh helpers
# ================================================================

def refresh_settings_import_status(window) -> None:
    if not window.account:
        window.lbl_settings_import_status.setText(tr("settings.label_no_import"))
        return
    meta = window.account_persistence.load_meta()
    source_name = str(meta.get("source_name", "")).strip() or tr("main.source_unknown")
    imported_at_raw = str(meta.get("imported_at", "")).strip()
    if imported_at_raw:
        try:
            from datetime import datetime
            imported_at = datetime.fromisoformat(imported_at_raw)
            date_str = imported_at.strftime("%d.%m.%Y %H:%M")
        except ValueError:
            date_str = imported_at_raw
        text = tr("settings.label_import_status", source=source_name) + "\n" + tr("settings.label_import_date", date=date_str)
    else:
        text = tr("settings.label_import_status", source=source_name)
    window.lbl_settings_import_status.setText(text)


def refresh_settings_license_status(window) -> None:
    from app.services.license_service import _load_local_license_data, _parse_expires_at
    from app.ui.license_flow import _format_trial_remaining

    local_data = _load_local_license_data()
    key = str(local_data.get("key", "")).strip()
    license_type = str(local_data.get("license_type", "")).strip()
    expires_at = _parse_expires_at(local_data.get("license_expires_at"))

    if not key:
        window.lbl_settings_license_type.setText(tr("settings.label_no_license"))
        window.lbl_settings_license_key.setText("")
        window.grp_settings_cloud.setVisible(False)
        return

    # Mask key: show first 5 and last 4 chars
    if len(key) > 9:
        masked = key[:5] + "****" + key[-4:]
    else:
        masked = key
    window.lbl_settings_license_key.setText(tr("settings.label_license_key", license_key=masked))

    is_trial = "trial" in license_type.lower()
    is_full = bool(license_type) and not is_trial

    if is_trial:
        if expires_at:
            remaining = _format_trial_remaining(expires_at)
            type_text = tr("settings.label_license_type_trial", remaining=remaining)
        else:
            type_text = tr("license.trial")
    elif license_type:
        type_text = tr("settings.label_license_type_full")
    else:
        type_text = license_type or "â€”"

    window.lbl_settings_license_type.setText(tr("settings.label_license_type", type=type_text))
    if is_full:
        window.grp_settings_cloud.setVisible(True)
        enabled = _cloud_learning_optin(window)
        trends_enabled = _community_build_trends_optin(window)
        set_limit = _community_set_limit(window)
        main_limit = _community_mainstat_limit(window)
        art_sub_limit = _community_artifact_substat_limit(window)
        window.chk_settings_cloud_learning.blockSignals(True)
        window.chk_settings_cloud_learning.setChecked(bool(enabled))
        window.chk_settings_cloud_learning.blockSignals(False)
        window.chk_settings_cloud_learning.setEnabled(True)
        window.lbl_settings_cloud_learning_hint.setText(tr("settings.cloud_learning_optin_hint"))

        window.chk_settings_community_trends.blockSignals(True)
        window.chk_settings_community_trends.setChecked(bool(trends_enabled))
        window.chk_settings_community_trends.blockSignals(False)
        window.chk_settings_community_trends.setEnabled(bool(enabled))
        if bool(enabled):
            window.lbl_settings_community_trends_hint.setText(tr("settings.community_trends_optin_hint"))
        else:
            window.lbl_settings_community_trends_hint.setText(tr("settings.community_trends_requires_cloud"))

        window.combo_settings_community_set_limit.blockSignals(True)
        idx_set = window.combo_settings_community_set_limit.findData(int(set_limit))
        window.combo_settings_community_set_limit.setCurrentIndex(idx_set if idx_set >= 0 else 0)
        window.combo_settings_community_set_limit.blockSignals(False)
        window.combo_settings_community_mainstat_limit.blockSignals(True)
        idx_main = window.combo_settings_community_mainstat_limit.findData(int(main_limit))
        window.combo_settings_community_mainstat_limit.setCurrentIndex(idx_main if idx_main >= 0 else 0)
        window.combo_settings_community_mainstat_limit.blockSignals(False)
        window.combo_settings_community_art_substat_limit.blockSignals(True)
        idx_art_sub = window.combo_settings_community_art_substat_limit.findData(int(art_sub_limit))
        window.combo_settings_community_art_substat_limit.setCurrentIndex(idx_art_sub if idx_art_sub >= 0 else 0)
        window.combo_settings_community_art_substat_limit.blockSignals(False)
        window.combo_settings_community_set_limit.setEnabled(bool(enabled))
        window.combo_settings_community_mainstat_limit.setEnabled(bool(enabled))
        window.combo_settings_community_art_substat_limit.setEnabled(bool(enabled))
        window.lbl_settings_community_set_limit.setEnabled(bool(enabled))
        window.lbl_settings_community_mainstat_limit.setEnabled(bool(enabled))
        window.lbl_settings_community_art_substat_limit.setEnabled(bool(enabled))
        if bool(enabled):
            window.lbl_settings_community_limit_hint.setText(tr("settings.community_limits_hint"))
        else:
            window.lbl_settings_community_limit_hint.setText(tr("settings.community_trends_requires_cloud"))
        window.btn_settings_delete_cloud_data.setEnabled(window._settings_cloud_delete_worker is None)
    else:
        window.grp_settings_cloud.setVisible(False)


def _refresh_settings_about(window) -> None:
    from app.services.update_service import _load_update_config

    cfg = _load_update_config()
    version = cfg.get("app_version", "dev")

    window.lbl_settings_version.setText(tr("settings.label_version", version=version))
    window.lbl_settings_about_version.setText(tr("settings.about_version", version=version))

    from app.services.license_service import _load_local_license_data

    local_data = _load_local_license_data()
    license_type = str(local_data.get("license_type", "")).strip()
    if "trial" in license_type.lower():
        about_license_type = tr("license.trial")
    elif license_type:
        about_license_type = tr("settings.label_license_type_full")
    else:
        about_license_type = "â€”"
    window.lbl_settings_about_license.setText(tr("settings.about_license", type=about_license_type))
    window.lbl_settings_about_creator.setText(tr("settings.about_creator", name=_ABOUT_CREATOR))
    window.lbl_settings_about_discord.setText(tr("settings.about_discord", handle=_ABOUT_DISCORD))
    window.lbl_settings_about_open_source.setText(tr("settings.about_open_source"))
    window.lbl_settings_about_data_sources.setText(tr("settings.about_data_sources"))
    window.lbl_settings_about_com2us.setText(tr("settings.about_com2us"))

    data_dir = str(window.account_persistence.data_dir)
    window.lbl_settings_about_data_dir.setText(tr("settings.about_data_dir", path=data_dir))


# ================================================================
# Actions
# ================================================================

def on_settings_cloud_learning_toggled(window, enabled: bool) -> None:
    from app.services.license_service import has_full_access_cached

    if not has_full_access_cached():
        window.chk_settings_cloud_learning.blockSignals(True)
        window.chk_settings_cloud_learning.setChecked(False)
        window.chk_settings_cloud_learning.blockSignals(False)
        window.statusBar().showMessage(tr("settings.cloud_learning_optin_unavailable"), 5000)
        return

    _set_cloud_learning_optin(window, bool(enabled))
    window.chk_settings_community_trends.setEnabled(bool(enabled))
    window.combo_settings_community_set_limit.setEnabled(bool(enabled))
    window.combo_settings_community_mainstat_limit.setEnabled(bool(enabled))
    window.combo_settings_community_art_substat_limit.setEnabled(bool(enabled))
    window.lbl_settings_community_set_limit.setEnabled(bool(enabled))
    window.lbl_settings_community_mainstat_limit.setEnabled(bool(enabled))
    window.lbl_settings_community_art_substat_limit.setEnabled(bool(enabled))
    if bool(enabled):
        window.lbl_settings_community_trends_hint.setText(tr("settings.community_trends_optin_hint"))
        window.lbl_settings_community_limit_hint.setText(tr("settings.community_limits_hint"))
    else:
        window.lbl_settings_community_trends_hint.setText(tr("settings.community_trends_requires_cloud"))
        window.lbl_settings_community_limit_hint.setText(tr("settings.community_trends_requires_cloud"))
    if bool(enabled):
        window.statusBar().showMessage(tr("settings.cloud_learning_saved_on"), 4000)
    else:
        window.statusBar().showMessage(tr("settings.cloud_learning_saved_off"), 4000)


def on_settings_community_trends_toggled(window, enabled: bool) -> None:
    from app.services.license_service import has_full_access_cached

    if not has_full_access_cached():
        window.chk_settings_community_trends.blockSignals(True)
        window.chk_settings_community_trends.setChecked(False)
        window.chk_settings_community_trends.blockSignals(False)
        window.statusBar().showMessage(tr("settings.community_trends_optin_unavailable"), 5000)
        return
    if not _cloud_learning_optin(window):
        window.chk_settings_community_trends.blockSignals(True)
        window.chk_settings_community_trends.setChecked(False)
        window.chk_settings_community_trends.blockSignals(False)
        window.statusBar().showMessage(tr("settings.community_trends_requires_cloud"), 5000)
        return

    _set_community_build_trends_optin(window, bool(enabled))
    if bool(enabled):
        window.statusBar().showMessage(tr("settings.community_trends_saved_on"), 4000)
    else:
        window.statusBar().showMessage(tr("settings.community_trends_saved_off"), 4000)


def on_settings_community_set_limit_changed(window) -> None:
    from app.services.license_service import has_full_access_cached

    if not has_full_access_cached():
        return
    value = _clamp_top_n_limit(window.combo_settings_community_set_limit.currentData(), default=3)
    _set_community_set_limit(window, int(value))
    window.statusBar().showMessage(tr("settings.community_set_limit_saved", n=int(value)), 4000)


def on_settings_community_mainstat_limit_changed(window) -> None:
    from app.services.license_service import has_full_access_cached

    if not has_full_access_cached():
        return
    value = _clamp_top_n_limit(window.combo_settings_community_mainstat_limit.currentData(), default=3)
    _set_community_mainstat_limit(window, int(value))
    window.statusBar().showMessage(tr("settings.community_mainstat_limit_saved", n=int(value)), 4000)


def on_settings_community_art_substat_limit_changed(window) -> None:
    from app.services.license_service import has_full_access_cached

    if not has_full_access_cached():
        return
    try:
        value = int(window.combo_settings_community_art_substat_limit.currentData() or 2)
    except Exception:
        value = 2
    value = max(1, min(2, int(value)))
    _set_community_artifact_substat_limit(window, int(value))
    window.statusBar().showMessage(tr("settings.community_art_substat_limit_saved", n=int(value)), 4000)


def on_settings_import_json(window) -> None:
    window.on_import()


def on_settings_clear_snapshot(window) -> None:
    reply = QMessageBox.question(
        window,
        tr("settings.confirm_title"),
        tr("settings.confirm_clear_snapshot"),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return
    window.account_persistence.clear()
    window.account = None
    window._unit_dropdowns_populated = False
    window._populated_unit_combo_ids = set()
    window._icon_cache = {}
    window._unit_combo_model = None
    window._unit_combo_index_by_uid = {}
    window._unit_text_cache_by_uid = {}
    window._lazy_view_dirty = {}
    window._arena_rush_state_restore_pending = False
    window.lbl_status.setText(tr("main.no_import"))
    refresh_settings_import_status(window)
    window.statusBar().showMessage(tr("settings.data_cleared", name="Account Snapshot"), 5000)


def on_settings_activate_license(window) -> None:
    key = window.edit_settings_license_key.text().strip()
    if not key:
        window.lbl_settings_license_feedback.setText(tr("lic.no_key"))
        return

    if window._settings_license_worker is not None:
        return

    window.lbl_settings_license_feedback.setText(tr("license.validating"))
    window.btn_settings_activate.setEnabled(False)

    from app.services.license_service import LicenseValidation, save_license_key, validate_license_key
    from app.ui.async_worker import _TaskWorker

    worker = _TaskWorker(validate_license_key, key)
    window._settings_license_worker = worker

    def _on_finished(result_obj: object) -> None:
        window._settings_license_worker = None
        window.btn_settings_activate.setEnabled(True)
        if not isinstance(result_obj, LicenseValidation):
            window.lbl_settings_license_feedback.setText(tr("lic.check_failed"))
            return
        if result_obj.valid:
            save_license_key(key)
            window.lbl_settings_license_feedback.setText(tr("settings.license_activated"))
            from app.ui.license_flow import _apply_license_title
            _apply_license_title(window, result_obj)
            refresh_settings_license_status(window)
            _refresh_settings_about(window)
        else:
            window.lbl_settings_license_feedback.setText(
                tr("settings.license_activation_failed", message=result_obj.message)
            )

    def _on_failed(detail: str) -> None:
        window._settings_license_worker = None
        window.btn_settings_activate.setEnabled(True)
        window.lbl_settings_license_feedback.setText(tr("lic.check_failed"))

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)


def on_settings_delete_cloud_data(window) -> None:
    from app.services.license_service import has_full_access_cached

    if not has_full_access_cached():
        window.statusBar().showMessage(tr("settings.cloud_delete_unavailable"), 5000)
        return
    if window._settings_cloud_delete_worker is not None:
        return

    dlg_1 = QMessageBox(window)
    dlg_1.setIcon(QMessageBox.Warning)
    dlg_1.setWindowTitle(tr("settings.confirm_title"))
    dlg_1.setText(tr("settings.confirm_delete_cloud_data"))
    btn_yes_1 = dlg_1.addButton(tr("btn.yes"), QMessageBox.YesRole)
    dlg_1.addButton(tr("btn.no"), QMessageBox.NoRole)
    dlg_1.setDefaultButton(btn_yes_1)
    dlg_1.exec()
    if dlg_1.clickedButton() is not btn_yes_1:
        return

    dlg_2 = QMessageBox(window)
    dlg_2.setIcon(QMessageBox.Warning)
    dlg_2.setWindowTitle(tr("settings.confirm_title"))
    dlg_2.setText(tr("settings.confirm_delete_cloud_data_second"))
    btn_yes_2 = dlg_2.addButton(tr("btn.yes"), QMessageBox.YesRole)
    dlg_2.addButton(tr("btn.no"), QMessageBox.NoRole)
    dlg_2.setDefaultButton(btn_yes_2)
    dlg_2.exec()
    if dlg_2.clickedButton() is not btn_yes_2:
        return

    from app.services.cloud_learning_service import CloudDeleteResult, delete_all_cloud_data
    from app.ui.async_worker import _TaskWorker

    window.btn_settings_delete_cloud_data.setEnabled(False)
    window.statusBar().showMessage(tr("settings.cloud_delete_in_progress"), 5000)

    worker = _TaskWorker(delete_all_cloud_data)
    window._settings_cloud_delete_worker = worker

    def _on_finished(result_obj: object) -> None:
        window._settings_cloud_delete_worker = None
        window.btn_settings_delete_cloud_data.setEnabled(True)
        if not isinstance(result_obj, CloudDeleteResult):
            msg = tr("settings.cloud_delete_failed")
            window.statusBar().showMessage(msg, 7000)
            QMessageBox.warning(window, tr("settings.confirm_title"), msg)
            return
        if result_obj.ok:
            msg = tr(
                "settings.cloud_delete_success",
                learning_runs=int(result_obj.deleted_learning_runs),
                build_events=int(result_obj.deleted_build_events),
            )
            window.statusBar().showMessage(
                msg,
                8000,
            )
            QMessageBox.information(window, tr("settings.confirm_title"), msg)
            return
        msg = tr("settings.cloud_delete_failed_reason", reason=str(result_obj.message or ""))
        window.statusBar().showMessage(
            msg,
            8000,
        )
        QMessageBox.warning(window, tr("settings.confirm_title"), msg)

    def _on_failed(detail: str) -> None:
        window._settings_cloud_delete_worker = None
        window.btn_settings_delete_cloud_data.setEnabled(True)
        msg = tr("settings.cloud_delete_failed")
        window.statusBar().showMessage(msg, 7000)
        QMessageBox.warning(window, tr("settings.confirm_title"), msg)

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)


def on_settings_reset_presets(window) -> None:
    reply = QMessageBox.question(
        window,
        tr("settings.confirm_title"),
        tr("settings.confirm_reset_presets"),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return
    from app.domain.presets import BuildStore
    window.presets = BuildStore()
    window.presets.save(window.presets_path)
    window.statusBar().showMessage(tr("settings.data_cleared", name="Build Presets"), 5000)


def on_settings_clear_optimizations(window) -> None:
    reply = QMessageBox.question(
        window,
        tr("settings.confirm_title"),
        tr("settings.confirm_clear_optimizations"),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return
    from app.domain.optimization_store import OptimizationStore
    window.opt_store = OptimizationStore()
    window.opt_store.save(window.opt_store_path)
    window._refresh_saved_opt_combo("siege")
    window._refresh_saved_opt_combo("wgb")
    window._refresh_saved_opt_combo("rta")
    window._refresh_saved_opt_combo("arena_rush")
    window.statusBar().showMessage(tr("settings.data_cleared", name="Saved Optimizations"), 5000)


def on_settings_clear_teams(window) -> None:
    reply = QMessageBox.question(
        window,
        tr("settings.confirm_title"),
        tr("settings.confirm_clear_teams"),
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply != QMessageBox.Yes:
        return
    from app.domain.team_store import TeamStore
    window.team_store = TeamStore()
    window.team_store.save(window.team_config_path)
    window._refresh_team_combo()
    window.statusBar().showMessage(tr("settings.data_cleared", name="Teams"), 5000)


def on_settings_check_update(window) -> None:
    if window._settings_update_worker is not None:
        return

    window.lbl_settings_version.setText(tr("settings.update_checking"))
    window.btn_settings_check_update.setEnabled(False)

    from app.services.update_service import UpdateCheckResult, check_latest_release
    from app.ui.async_worker import _TaskWorker
    from app.ui.update_flow import _show_update_dialog

    worker = _TaskWorker(check_latest_release)
    window._settings_update_worker = worker

    def _on_finished(result_obj: object) -> None:
        window._settings_update_worker = None
        window.btn_settings_check_update.setEnabled(True)
        _refresh_settings_about(window)

        if not isinstance(result_obj, UpdateCheckResult):
            window.statusBar().showMessage(tr("settings.update_error"), 5000)
            return
        if result_obj.update_available:
            _show_update_dialog(window, result_obj)
        else:
            window.statusBar().showMessage(
                tr("settings.update_no_update", version=result_obj.current_version), 5000
            )

    def _on_failed(detail: str) -> None:
        window._settings_update_worker = None
        window.btn_settings_check_update.setEnabled(True)
        _refresh_settings_about(window)
        window.statusBar().showMessage(tr("settings.update_error"), 5000)

    worker.signals.finished.connect(_on_finished)
    worker.signals.failed.connect(_on_failed)
    QThreadPool.globalInstance().start(worker)


def _on_theme_changed(window, index: int) -> None:
    name = window.combo_settings_theme.itemData(index)
    if not name or name == _theme.current_name:
        return
    _save_app_settings(window, {"theme": name})
    # Restart the app so the new theme is fully applied everywhere
    import sys, os
    from PySide6.QtCore import QProcess
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app:
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        QProcess.startDetached(sys.executable, ["-m", "app"], project_root)
        app.quit()



def on_settings_language_changed(window, index: int) -> None:
    import app.i18n as i18n

    code = window.combo_settings_language.itemData(index)
    if code and code != i18n.get_language():
        i18n.set_language(code)
        window._retranslate_ui()


def on_settings_extra_info_toggled(window, enabled: bool) -> None:
    _set_ui_show_extra_info(window, bool(enabled))
    if bool(enabled):
        window.statusBar().showMessage(tr("settings.extra_info_saved_on"), 3000)
    else:
        window.statusBar().showMessage(tr("settings.extra_info_saved_off"), 3000)


# ================================================================
# Retranslate
# ================================================================

def retranslate_settings(window) -> None:
    window.grp_settings_account.setTitle(tr("settings.group_account"))
    window.btn_settings_import.setText(tr("settings.btn_import"))
    window.btn_settings_clear_snapshot.setText(tr("settings.btn_clear_snapshot"))

    window.grp_settings_license.setTitle(tr("settings.group_license"))
    window.btn_settings_activate.setText(tr("btn.activate"))

    window.grp_settings_cloud.setTitle(tr("settings.group_cloud"))
    window.chk_settings_cloud_learning.setText(tr("settings.cloud_learning_optin"))
    window.chk_settings_community_trends.setText(tr("settings.community_trends_optin"))
    window.btn_settings_delete_cloud_data.setText(tr("settings.btn_delete_cloud_data"))
    window.lbl_settings_community_set_limit.setText(tr("settings.community_set_limit_label"))
    window.lbl_settings_community_mainstat_limit.setText(tr("settings.community_mainstat_limit_label"))
    window.lbl_settings_community_art_substat_limit.setText(tr("settings.community_art_substat_limit_label"))
    _populate_top_n_combo(window.combo_settings_community_set_limit)
    _populate_top_n_combo(window.combo_settings_community_mainstat_limit)
    _populate_top_n_combo(window.combo_settings_community_art_substat_limit, max_n=2)

    window.grp_settings_appearance.setTitle(tr("settings.group_appearance"))
    window.lbl_settings_language.setText(tr("settings.label_language"))
    window.lbl_settings_theme.setText(tr("settings.label_theme"))
    window.chk_settings_extra_info.setText(tr("settings.extra_info_optin"))

    window.grp_settings_data.setTitle(tr("settings.group_data"))
    window.btn_settings_reset_presets.setText(tr("settings.btn_reset_presets"))
    window.btn_settings_clear_optimizations.setText(tr("settings.btn_clear_optimizations"))
    window.btn_settings_clear_teams.setText(tr("settings.btn_clear_teams"))

    window.grp_settings_updates.setTitle(tr("settings.group_updates"))
    window.btn_settings_check_update.setText(tr("settings.btn_check_update"))

    window.grp_settings_about.setTitle(tr("settings.group_about"))
    window.btn_settings_open_discord_dm.setText(tr("settings.btn_open_discord_dm"))

    # Refresh dynamic content labels
    refresh_settings_import_status(window)
    refresh_settings_license_status(window)
    _refresh_settings_about(window)

    # Sync language combo selection
    import app.i18n as i18n

    idx = window.combo_settings_language.findData(i18n.get_language())
    if idx >= 0:
        window.combo_settings_language.blockSignals(True)
        window.combo_settings_language.setCurrentIndex(idx)
        window.combo_settings_language.blockSignals(False)

