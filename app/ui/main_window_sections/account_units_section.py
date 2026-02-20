from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QFileDialog, QMessageBox, QWidget

from app.importer.sw_json_importer import load_account_from_data
from app.domain.presets import SET_NAMES
from app.i18n import tr
from app.ui.widgets.selection_combos import _UnitSearchComboBox


def on_import(window) -> None:
    path, _ = QFileDialog.getOpenFileName(
        window,
        tr("main.file_dialog_title"),
        str(Path.home()),
        tr("main.file_dialog_filter"),
    )
    if not path:
        return
    try:
        raw_json = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
        window.account_persistence.save(raw_json, source_name=Path(path).name)
        account = load_account_from_data(raw_json)
    except Exception as e:
        QMessageBox.critical(window, tr("main.import_failed"), str(e))
        return
    window._apply_saved_account(account, Path(path).name)


def apply_saved_account(window, account, source_label: str) -> None:
    window.account = account
    window.monster_db.load()
    window._unit_dropdowns_populated = False
    window._populated_unit_combo_ids = set()
    window._icon_cache = {}
    window._unit_combo_model = None
    window._unit_combo_index_by_uid = {}
    window._unit_text_cache_by_uid = {}
    window._loaded_current_runes_compare_by_mode = {}
    window._lazy_view_dirty = {
        "siege_raw": True,
        "rta_overview": True,
        "rune_optimization": True,
        "saved_siege": True,
        "saved_wgb": True,
        "saved_rta": True,
        "saved_arena_rush": True,
    }
    window._arena_rush_state_restore_pending = True

    window.lbl_status.setText(tr("main.import_label", source=source_label))
    window.overview_widget.set_data(account)

    window._on_tab_changed(window.tabs.currentIndex())

    window.btn_take_current_siege.setEnabled(True)
    window.btn_validate_siege.setEnabled(True)
    window.btn_edit_presets_siege.setEnabled(True)
    window.btn_optimize_siege.setEnabled(True)

    window.btn_validate_wgb.setEnabled(True)
    window.btn_edit_presets_wgb.setEnabled(True)
    window.btn_optimize_wgb.setEnabled(True)

    window.btn_take_current_rta.setEnabled(True)
    window.btn_validate_rta.setEnabled(True)
    window.btn_edit_presets_rta.setEnabled(True)
    window.btn_optimize_rta.setEnabled(True)

    if hasattr(window, "btn_take_current_arena_def"):
        window.btn_take_current_arena_def.setEnabled(True)
    if hasattr(window, "btn_take_arena_decks"):
        window.btn_take_arena_decks.setEnabled(True)
    if hasattr(window, "btn_validate_arena_rush"):
        window.btn_validate_arena_rush.setEnabled(True)
    if hasattr(window, "btn_edit_presets_arena_rush"):
        window.btn_edit_presets_arena_rush.setEnabled(True)
    if hasattr(window, "btn_optimize_arena_rush"):
        window.btn_optimize_arena_rush.setEnabled(True)

    window.lbl_siege_validate.setText(tr("status.siege_ready"))
    window.lbl_wgb_validate.setText(tr("status.wgb_ready"))
    if hasattr(window, "lbl_arena_rush_validate"):
        window.lbl_arena_rush_validate.setText(tr("status.arena_rush_ready"))

    window._ensure_siege_team_defaults()
    window._refresh_team_combo()
    window._set_team_controls_enabled(True)

    if hasattr(window, "lbl_settings_import_status"):
        from app.ui.main_window_sections.settings_section import refresh_settings_import_status
        refresh_settings_import_status(window)


def try_restore_snapshot(window) -> None:
    if not window.account_persistence.exists():
        return
    raw = window.account_persistence.load()
    if not raw:
        return
    try:
        account = load_account_from_data(raw)
    except Exception as exc:
        QMessageBox.warning(window, tr("main.snapshot_title"), tr("main.snapshot_failed", exc=exc))
        return
    meta = window.account_persistence.load_meta()
    source_name = str(meta.get("source_name", "")).strip() or tr("main.source_unknown")
    imported_at_raw = str(meta.get("imported_at", "")).strip()
    imported_at = None
    if imported_at_raw:
        try:
            imported_at = datetime.fromisoformat(imported_at_raw)
        except ValueError:
            imported_at = None
    if imported_at is None:
        try:
            imported_at = datetime.fromtimestamp(window.account_persistence.active_snapshot_path().stat().st_mtime)
        except OSError:
            imported_at = None

    if imported_at is not None:
        source_label = f"{source_name} ({imported_at.strftime('%d.%m.%Y %H:%M')})"
    else:
        source_label = source_name
    window._apply_saved_account(account, source_label)

    # Show reminder if import is older than 1 month
    if imported_at is not None:
        from datetime import timedelta
        age = datetime.now() - imported_at
        if age > timedelta(days=30):
            date_str = imported_at.strftime("%d.%m.%Y %H:%M")
            QMessageBox.warning(
                window,
                tr("main.import_outdated_title"),
                tr("main.import_outdated_msg", source=source_name, date=date_str),
            )


def icon_for_master_id(window, master_id: int) -> QIcon:
    cached = window._icon_cache.get(int(master_id))
    if cached is not None:
        return cached
    rel = window.monster_db.icon_path_for(master_id)
    if not rel:
        icon = QIcon()
        window._icon_cache[int(master_id)] = icon
        return icon
    p = (window.assets_dir / rel).resolve()
    icon = QIcon(str(p)) if p.exists() else QIcon()
    window._icon_cache[int(master_id)] = icon
    return icon


def rune_set_icon(window, set_id: int) -> QIcon:
    name = SET_NAMES.get(set_id, "")
    slug = name.lower().replace(" ", "_") if name else str(set_id)
    filename = f"{set_id}_{slug}.png"
    icon_path = window.assets_dir / "runes" / "sets" / filename
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


def unit_text(window, unit_id: int) -> str:
    if not window.account:
        return str(unit_id)
    u = window.account.units_by_id.get(unit_id)
    if not u:
        return f"{unit_id} (—)"
    name = window.monster_db.name_for(u.unit_master_id)
    elem = window.monster_db.element_for(u.unit_master_id)
    return f"{name} ({elem}) | lvl {u.unit_level}"


def unit_text_cached(window, unit_id: int) -> str:
    uid = int(unit_id)
    cached = window._unit_text_cache_by_uid.get(uid)
    if cached is not None:
        return cached
    txt = window._unit_text(uid)
    window._unit_text_cache_by_uid[uid] = txt
    return txt


def populate_combo_with_units(window, cmb: QComboBox) -> None:
    if not window.account:
        return
    model = window._ensure_unit_combo_model()
    prev_uid = int(cmb.currentData() or 0)

    cmb.blockSignals(True)
    if isinstance(cmb, _UnitSearchComboBox):
        cmb.set_filter_suspended(True)
        cmb.set_source_model(model)
    else:
        cmb.setModel(model)
    cmb.setModelColumn(0)
    cmb.setIconSize(QSize(40, 40))
    idx = cmb.findData(prev_uid, role=Qt.UserRole)
    cmb.setCurrentIndex(idx if idx >= 0 else 0)
    if isinstance(cmb, _UnitSearchComboBox):
        cmb.set_filter_suspended(False)
        cmb._reset_search_field()
    cmb.blockSignals(False)


def build_unit_combo_model(window) -> QStandardItemModel:
    model = QStandardItemModel()
    index_by_uid: Dict[int, int] = {}

    placeholder = QStandardItem("—")
    placeholder.setData(0, Qt.UserRole)
    model.appendRow(placeholder)
    index_by_uid[0] = 0

    if window.account:
        unit_rows: List[Tuple[str, str, int, Any]] = []
        for uid, u in window.account.units_by_id.items():
            name = window.monster_db.name_for(u.unit_master_id)
            elem = window.monster_db.element_for(u.unit_master_id)
            unit_rows.append((name.lower(), elem.lower(), int(uid), u))

        for _, _, uid, u in sorted(unit_rows, key=lambda x: (x[0], x[1], x[2])):
            name = window.monster_db.name_for(u.unit_master_id)
            elem = window.monster_db.element_for(u.unit_master_id)
            window._unit_text_cache_by_uid[int(uid)] = f"{name} ({elem}) | lvl {u.unit_level}"
            item = QStandardItem(f"{name} ({elem})")
            item.setIcon(window._icon_for_master_id(u.unit_master_id))
            item.setData(int(uid), Qt.UserRole)
            model.appendRow(item)
            index_by_uid[int(uid)] = model.rowCount() - 1

    window._unit_combo_index_by_uid = index_by_uid
    return model


def ensure_unit_combo_model(window) -> QStandardItemModel:
    if window._unit_combo_model is None:
        window._unit_combo_model = window._build_unit_combo_model()
    return window._unit_combo_model


def populate_all_dropdowns(window) -> None:
    for cmb in getattr(window, "_all_unit_combos", []):
        window._populate_combo_with_units(cmb)


def _unit_combo_tab_key(window, tab: QWidget | None) -> str:
    if tab is window.tab_siege_builder:
        return "siege"
    if tab is window.tab_wgb_builder:
        return "wgb"
    if tab is window.tab_rta_builder:
        return "rta"
    if tab is getattr(window, "tab_arena_rush_builder", None):
        return "arena_rush"
    return ""


def _combos_for_tab(window, tab: QWidget | None) -> List[QComboBox]:
    key = _unit_combo_tab_key(window, tab)
    by_tab = dict(getattr(window, "_unit_combos_by_tab", {}) or {})
    if key and key in by_tab:
        return list(by_tab.get(key) or [])
    return []


def tab_needs_unit_dropdowns(window, tab: QWidget | None) -> bool:
    return tab in (
        window.tab_siege_builder,
        window.tab_wgb_builder,
        window.tab_rta_builder,
        getattr(window, "tab_arena_rush_builder", None),
    )


def _resolve_active_inner_tab(window, outer_tab) -> QWidget:
    """Falls outer_tab ein Gruppen-Container ist, gibt den aktuell aktiven inneren Tab zurück."""
    for group_attr, inner_attr in [
        ("tab_siege", "siege_inner_tabs"),
        ("tab_wgb", "wgb_inner_tabs"),
        ("tab_rta", "rta_inner_tabs"),
        ("tab_arena_rush", "arena_rush_inner_tabs"),
    ]:
        group = getattr(window, group_attr, None)
        inner = getattr(window, inner_attr, None)
        if outer_tab is group and inner is not None:
            return inner.currentWidget()
    return outer_tab


def on_tab_changed(window, index: int) -> None:
    if not window.account:
        return
    outer_tab = window.tabs.widget(index)
    tab = _resolve_active_inner_tab(window, outer_tab)
    if window._tab_needs_unit_dropdowns(tab):
        window._ensure_unit_dropdowns_populated(tab=tab)
    if tab is window.tab_siege_raw and bool(window._lazy_view_dirty.get("siege_raw", False)):
        window._render_siege_raw()
        window._lazy_view_dirty["siege_raw"] = False
    elif tab is window.tab_rta_overview and bool(window._lazy_view_dirty.get("rta_overview", False)):
        window.rta_overview.set_context(window.account, window.monster_db, window.assets_dir)
        window._lazy_view_dirty["rta_overview"] = False
    elif tab is window.tab_rune_optimization and bool(window._lazy_view_dirty.get("rune_optimization", False)):
        window._refresh_rune_optimization()
        window._lazy_view_dirty["rune_optimization"] = False
    elif tab is window.tab_saved_siege and bool(window._lazy_view_dirty.get("saved_siege", False)):
        window._on_saved_opt_changed("siege")
        window._lazy_view_dirty["saved_siege"] = False
    elif tab is window.tab_saved_wgb and bool(window._lazy_view_dirty.get("saved_wgb", False)):
        window._on_saved_opt_changed("wgb")
        window._lazy_view_dirty["saved_wgb"] = False
    elif tab is window.tab_saved_rta and bool(window._lazy_view_dirty.get("saved_rta", False)):
        window._on_saved_opt_changed("rta")
        window._lazy_view_dirty["saved_rta"] = False
    elif tab is window.tab_saved_arena_rush and bool(window._lazy_view_dirty.get("saved_arena_rush", False)):
        window._on_saved_opt_changed("arena_rush")
        window._lazy_view_dirty["saved_arena_rush"] = False
    if tab is getattr(window, "tab_arena_rush_builder", None) and bool(getattr(window, "_arena_rush_state_restore_pending", False)):
        try:
            from app.ui.main_window_sections.arena_rush_actions import restore_arena_rush_ui_state
            restore_arena_rush_ui_state(window)
        except Exception:
            pass
        finally:
            window._arena_rush_state_restore_pending = False


def ensure_unit_dropdowns_populated(window, tab: QWidget | None = None) -> None:
    if not window.account:
        return
    target_tab = tab if tab is not None else window.tabs.currentWidget()
    combos = _combos_for_tab(window, target_tab)
    if not combos:
        combos = list(getattr(window, "_all_unit_combos", []) or [])
    if not combos:
        window._unit_dropdowns_populated = True
        return
    populated_ids = set(getattr(window, "_populated_unit_combo_ids", set()) or set())
    pending = [cmb for cmb in combos if id(cmb) not in populated_ids]
    if not pending:
        all_combos = list(getattr(window, "_all_unit_combos", []) or [])
        window._unit_dropdowns_populated = bool(all_combos) and len(populated_ids) >= len(all_combos)
        return
    for cmb in pending:
        window._populate_combo_with_units(cmb)
        populated_ids.add(id(cmb))
    window._populated_unit_combo_ids = populated_ids
    all_combos = list(getattr(window, "_all_unit_combos", []) or [])
    window._unit_dropdowns_populated = bool(all_combos) and len(populated_ids) >= len(all_combos)
