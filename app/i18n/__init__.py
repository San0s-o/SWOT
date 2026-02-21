"""Lightweight i18n module – dictionary-based translations with .format() interpolation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

_current_lang: str = "de"
_translations: Dict[str, Dict[str, str]] = {}
_settings_path: Optional[Path] = None


def init(config_dir: Path) -> None:
    """Load language modules and restore persisted preference."""
    global _settings_path, _current_lang
    _settings_path = config_dir / "app_settings.json"

    from app.i18n import de, en
    _translations["de"] = de.STRINGS
    _translations["en"] = en.STRINGS

    if _settings_path.exists():
        try:
            data = json.loads(_settings_path.read_text(encoding="utf-8"))
            saved = data.get("language", "de")
            if saved in _translations:
                _current_lang = saved
        except Exception:
            pass


def set_language(lang: str) -> None:
    global _current_lang
    if lang not in _translations:
        return
    _current_lang = lang
    _save_preference()


def get_language() -> str:
    return _current_lang


def available_languages() -> Dict[str, str]:
    return {"de": "Deutsch", "en": "English"}


def tr(key: str, **kwargs: Any) -> str:
    """Return translated string for *key*.  Falls back to German, then to the key itself."""
    text = _translations.get(_current_lang, {}).get(key)
    if text is None:
        text = _translations.get("de", {}).get(key)
    if text is None:
        return key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def _save_preference() -> None:
    if _settings_path is None:
        return
    data: dict = {}
    if _settings_path.exists():
        try:
            data = json.loads(_settings_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    data["language"] = _current_lang
    _settings_path.parent.mkdir(parents=True, exist_ok=True)
    _settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
