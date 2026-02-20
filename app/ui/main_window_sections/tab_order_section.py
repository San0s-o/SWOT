from __future__ import annotations

import json
from typing import Dict, List, Set

from PySide6.QtWidgets import QWidget


DEFAULT_TAB_ORDER = [
    "tab_overview",
    "tab_siege",
    "tab_wgb",
    "tab_rta",
    "tab_arena_rush",
    "tab_rune_optimization",
    "tab_settings",
]


def on_tab_moved(window, from_index: int, to_index: int) -> None:
    if window._tab_move_guard:
        return
    overview_idx = window.tabs.indexOf(window.tab_overview)
    if overview_idx != 0:
        window._tab_move_guard = True
        window.tabs.tabBar().moveTab(overview_idx, 0)
        window._tab_move_guard = False
    save_tab_order(window)


def save_tab_order(window) -> None:
    order = []
    for i in range(window.tabs.count()):
        widget = window.tabs.widget(i)
        for attr_name in DEFAULT_TAB_ORDER:
            if getattr(window, attr_name, None) is widget:
                order.append(attr_name)
                break
    settings_path = window.config_dir / "app_settings.json"
    data: dict = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["tab_order"] = order
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def restore_tab_order(window) -> None:
    settings_path = window.config_dir / "app_settings.json"
    if not settings_path.exists():
        return
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return
    saved_order = data.get("tab_order")
    if not saved_order or not isinstance(saved_order, list):
        return
    if saved_order[0] != "tab_overview":
        return

    known: Dict[str, QWidget] = {}
    for attr_name in DEFAULT_TAB_ORDER:
        widget = getattr(window, attr_name, None)
        if widget is not None:
            known[attr_name] = widget

    valid_order: List[str] = []
    seen: Set[str] = set()
    for name in saved_order:
        if name in known and name not in seen:
            valid_order.append(name)
            seen.add(name)
    for name in DEFAULT_TAB_ORDER:
        if name not in seen and name in known:
            valid_order.append(name)

    window._tab_move_guard = True
    for target_index, attr_name in enumerate(valid_order):
        widget = known[attr_name]
        current_index = window.tabs.indexOf(widget)
        if current_index != target_index and current_index >= 0:
            window.tabs.tabBar().moveTab(current_index, target_index)
    window._tab_move_guard = False
