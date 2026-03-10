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
    if prof in ("max_quality", "ultra_quality"):
        return int(combo.currentData() or default_solver_workers())
    return int(default_solver_workers())


def _is_advanced_profile(profile_value: str) -> bool:
    """Returns True for profiles where the user can manually configure workers/passes."""
    prof = str(profile_value or "").strip().lower()
    return prof in ("max_quality", "ultra_quality")


def _is_ki_profile(profile_value: str) -> bool:
    prof = str(profile_value or "").strip().lower()
    return prof in ("gpu_combo",)


def sync_worker_controls(window) -> None:
    def _apply(profile_combo_attr: str, workers_combo_attr: str, passes_label_attr: str = "", passes_spin_attr: str = "") -> None:
        prof = getattr(window, profile_combo_attr, None)
        workers = getattr(window, workers_combo_attr, None)
        if prof is None or workers is None:
            return
        prof_val = str(prof.currentData() or "")
        is_advanced = _is_advanced_profile(prof_val)
        is_ki = _is_ki_profile(prof_val)
        # Workers: only visible for advanced (manual core selection)
        workers.setVisible(bool(is_advanced))
        label_attr = workers_combo_attr.replace("combo_workers_", "lbl_") + "_workers"
        lbl_workers = getattr(window, label_attr, None)
        if lbl_workers is not None:
            lbl_workers.setVisible(bool(is_advanced))
        if passes_label_attr and passes_spin_attr:
            lbl_passes = getattr(window, passes_label_attr, None)
            spin_passes = getattr(window, passes_spin_attr, None)
            if lbl_passes is not None and spin_passes is not None:
                # Passes: visible only for non-KI, non-advanced profiles (Fast, Balanced)
                show_passes = not is_advanced and not is_ki
                lbl_passes.setVisible(show_passes)
                spin_passes.setVisible(show_passes)
                spin_passes.setEnabled(show_passes)
                if not show_passes:
                    try:
                        spin_passes.setValue(1)
                    except Exception:
                        pass

    _apply("combo_quality_profile_siege", "combo_workers_siege", "lbl_siege_passes", "spin_multi_pass_siege")
    _apply("combo_quality_profile_wgb", "combo_workers_wgb", "lbl_wgb_passes", "spin_multi_pass_wgb")
    _apply("combo_quality_profile_rta", "combo_workers_rta", "lbl_rta_passes", "spin_multi_pass_rta")
    _apply("combo_quality_profile_arena_rush", "combo_workers_arena_rush")
    _apply("combo_quality_profile_team", "combo_workers_team", "lbl_team_passes", "spin_multi_pass_team")
