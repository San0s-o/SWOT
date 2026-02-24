from __future__ import annotations

from PySide6.QtWidgets import QApplication

# Reference DPI: 2K (1440p) on a typical 27" monitor ≈ 108-109 DPI.
# At this density the scale factor is 1.0 — the UI looks exactly as designed.
# Lower-density displays (e.g. 1080p at 100% OS scaling) are scaled DOWN,
# higher-density displays (e.g. 4K at 100% OS scaling) are scaled UP,
# so the UI always appears the same physical size as on a 2K screen.
_REF_DPI: float = 108.0

_scale: float = 1.0


def init_dpi_scale(app: QApplication) -> None:
    """Compute and store the physical DPI scale factor.

    Must be called once at startup, after QApplication is created but before
    any widgets are shown.
    """
    global _scale
    screen = app.primaryScreen()
    if not screen:
        return
    phys_dpi = screen.physicalDotsPerInch()
    logic_dpi = screen.logicalDotsPerInch()
    # Use whichever is larger: the OS-reported logical DPI or the 2K reference.
    # This ensures screens already scaled by the OS are not double-scaled.
    extra = phys_dpi / max(logic_dpi, _REF_DPI)
    # Allow scaling in both directions: down to 0.5× and up to 2×.
    _scale = max(0.5, min(2.0, extra))


def dp(value: int) -> int:
    """Scale a pixel value by the physical DPI factor.

    Use for all hardcoded pixel dimensions: widget sizes, icon sizes,
    margins, spacing, etc.  2K monitors get factor 1.0 (no change),
    1080p monitors are scaled down, 4K monitors are scaled up.
    """
    return round(value * _scale)
