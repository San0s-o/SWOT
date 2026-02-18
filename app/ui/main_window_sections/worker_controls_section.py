from __future__ import annotations

import os

from PySide6.QtWidgets import QComboBox

from app.i18n import tr


def max_solver_workers() -> int:
    total = max(1, int(os.cpu_count() or 8))
    return int(total)


def default_solver_workers() -> int:
    m = max_solver_workers()
    return max(1, min(m, m // 2 if m > 1 else 1))


def gpu_search_available() -> bool:
    try:
        import torch  # type: ignore

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def populate_worker_combo(window, combo: QComboBox) -> None:
    combo.clear()
    max_w = max_solver_workers()
    for w in range(1, max_w + 1):
        combo.addItem(str(w), int(w))
    default_w = default_solver_workers()
    idx = combo.findData(int(default_w))
    combo.setCurrentIndex(idx if idx >= 0 else 0)
    combo.setToolTip(tr("tooltip.workers"))


def effective_workers(window, quality_profile: str, combo: QComboBox) -> int:
    prof = str(quality_profile or "").strip().lower()
    if prof in ("max_quality", "ultra_quality", "gpu_search_max"):
        return int(combo.currentData() or default_solver_workers())
    return int(default_solver_workers())


def sync_worker_controls(window) -> None:
    def _apply(profile_combo_attr: str, workers_combo_attr: str) -> None:
        prof = getattr(window, profile_combo_attr, None)
        workers = getattr(window, workers_combo_attr, None)
        if prof is None or workers is None:
            return
        is_max = str(prof.currentData() or "").strip().lower() in ("max_quality", "ultra_quality", "gpu_search_max")
        workers.setEnabled(bool(is_max))

    _apply("combo_quality_profile_siege", "combo_workers_siege")
    _apply("combo_quality_profile_wgb", "combo_workers_wgb")
    _apply("combo_quality_profile_rta", "combo_workers_rta")
    _apply("combo_quality_profile_arena_rush", "combo_workers_arena_rush")
    _apply("combo_quality_profile_team", "combo_workers_team")
