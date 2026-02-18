from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from PySide6.QtWidgets import QMessageBox

from app.domain.models import Artifact, Rune
from app.domain.optimization_store import SavedUnitResult
from app.engine.greedy_optimizer import GreedyUnitResult
from app.i18n import tr
from app.ui.dialogs.optimize_result_dialog import OptimizeResultDialog


def show_optimize_results(
    window,
    title: str,
    summary: str,
    results: List[GreedyUnitResult],
    unit_team_index: Optional[Dict[int, int]] = None,
    unit_display_order: Optional[Dict[int, int]] = None,
    mode: str = "",
    teams: Optional[List[List[int]]] = None,
    team_header_by_index: Optional[Dict[int, str]] = None,
    group_size: int = 3,
) -> None:
    if not window.account:
        QMessageBox.warning(window, tr("result.title_siege"), tr("dlg.load_import_first"))
        return
    rune_lookup: Dict[int, Rune] = {r.rune_id: r for r in window.account.runes}
    artifact_lookup: Dict[int, Artifact] = {int(a.artifact_id): a for a in window.account.artifacts}
    mode_rune_owner: Dict[int, int] = {}
    if mode in ("siege", "guild", "wgb", "arena_rush"):
        for uid, rids in window.account.guild_rune_equip.items():
            for rid in rids:
                mode_rune_owner[rid] = uid
    elif mode == "rta":
        for uid, rids in window.account.rta_rune_equip.items():
            for rid in rids:
                mode_rune_owner[rid] = uid
    prev_result_mode_ctx = getattr(window, "_result_mode_context", "")
    window._result_mode_context = str(mode or "").strip().lower()
    mode_key = str(mode or "").strip().lower()
    compare_store = dict(getattr(window, "_loaded_current_runes_compare_by_mode", {}) or {})
    compare_snapshot = dict(compare_store.get(mode_key, {}) or {})
    baseline_runes_by_unit: Dict[int, Dict[int, int]] = {
        int(uid): {int(slot): int(rid) for slot, rid in dict(by_slot or {}).items()}
        for uid, by_slot in dict(compare_snapshot.get("runes_by_unit") or {}).items()
        if int(uid or 0) > 0
    }
    baseline_artifacts_by_unit: Dict[int, Dict[int, int]] = {
        int(uid): {int(t): int(aid) for t, aid in dict(by_type or {}).items()}
        for uid, by_type in dict(compare_snapshot.get("artifacts_by_unit") or {}).items()
        if int(uid or 0) > 0
    }
    try:
        dlg = OptimizeResultDialog(
            window,
            title,
            summary,
            results,
            rune_lookup,
            artifact_lookup,
            window._unit_text,
            window._unit_icon_for_unit_id,
            window._unit_final_spd_value,
            window._unit_final_stats_values,
            window._rune_set_icon,
            window._unit_base_stats,
            window._unit_leader_bonus,
            window._unit_totem_bonus,
            window._unit_spd_buff_bonus,
            unit_team_index=unit_team_index,
            unit_display_order=unit_display_order,
            mode_rune_owner=mode_rune_owner,
            team_header_by_index=team_header_by_index,
            group_size=int(group_size),
            baseline_runes_by_unit=baseline_runes_by_unit,
            baseline_artifacts_by_unit=baseline_artifacts_by_unit,
        )
        dlg.exec()
    finally:
        window._result_mode_context = prev_result_mode_ctx

    if dlg.saved and mode and teams:
        ts = datetime.now().strftime("%d.%m.%Y %H:%M")
        name = tr("result.opt_name", mode=mode.upper(), ts=ts)
        saved_results: List[SavedUnitResult] = []
        for result in results:
            if result.ok and result.runes_by_slot:
                saved_results.append(SavedUnitResult(
                    unit_id=result.unit_id,
                    runes_by_slot=dict(result.runes_by_slot),
                    artifacts_by_type=dict(result.artifacts_by_type or {}),
                    final_speed=result.final_speed,
                ))
        window.opt_store.upsert(mode, name, teams, saved_results)
        window.opt_store.save(window.opt_store_path)
        window._refresh_saved_opt_combo(mode)
