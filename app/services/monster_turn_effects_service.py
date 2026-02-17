from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Iterable

import requests


_SWARFARM_MONSTERS_URL = "https://swarfarm.com/api/v2/monsters/"
_SWARFARM_SKILL_URL_TMPL = "https://swarfarm.com/api/v2/skills/{sid}/"
_SWARFARM_SKILL_ICON_BASES = [
    "https://swarfarm.com/static/herders/images/skills/",
]
_EFFECT_ID_SPEED_BUFF = 5
_EFFECT_ID_INCREASE_ATB = 17


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _default_capability() -> Dict[str, int | bool | str]:
    return {
        "has_spd_buff": False,
        "has_atb_boost": False,
        "max_atb_boost_pct": 0,
        "spd_buff_skill_icon": "",
        "atb_boost_skill_icon": "",
    }


_CACHE_VERSION = 3


def _load_cache(path: Path) -> Dict:
    empty = {"version": _CACHE_VERSION, "by_com2us_id": {}, "by_skill_id": {}}
    try:
        if not path.exists():
            return empty
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(raw, dict):
            raise ValueError("invalid cache")
        if int(raw.get("version", 0) or 0) < _CACHE_VERSION:
            return empty
        return {
            "version": _CACHE_VERSION,
            "by_com2us_id": dict(raw.get("by_com2us_id") or {}),
            "by_skill_id": dict(raw.get("by_skill_id") or {}),
        }
    except Exception:
        return empty


def _save_cache(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_active_teamwide_skill(skill_payload: Dict) -> bool:
    # Opening turn controls should only include active team-wide skills.
    if bool(skill_payload.get("passive", False)):
        return False
    return bool(skill_payload.get("aoe", False))


def _capability_from_skill_payload(skill_payload: Dict) -> Dict[str, int | bool | str]:
    out = _default_capability()
    if not _is_active_teamwide_skill(skill_payload):
        return out
    icon_filename = str(skill_payload.get("icon_filename") or "")
    effects = list(skill_payload.get("effects") or [])
    for eff in effects:
        if not isinstance(eff, dict):
            continue
        if bool(eff.get("self_effect", False)):
            continue
        effect_obj = dict(eff.get("effect") or {})
        effect_id = _to_int(effect_obj.get("id"), 0)
        qty = max(0, _to_int(eff.get("quantity"), 0))
        if effect_id == _EFFECT_ID_SPEED_BUFF:
            out["has_spd_buff"] = True
            if icon_filename:
                out["spd_buff_skill_icon"] = icon_filename
        if effect_id == _EFFECT_ID_INCREASE_ATB:
            out["has_atb_boost"] = True
            if qty > int(out.get("max_atb_boost_pct", 0) or 0):
                out["max_atb_boost_pct"] = int(qty)
            if icon_filename:
                out["atb_boost_skill_icon"] = icon_filename
    if bool(out.get("has_atb_boost")) and int(out.get("max_atb_boost_pct", 0) or 0) <= 0:
        out["max_atb_boost_pct"] = 100
    return out


def _fetch_monster_skill_ids(com2us_id: int, timeout_s: float) -> list[int]:
    resp = requests.get(
        _SWARFARM_MONSTERS_URL,
        params={"com2us_id": int(com2us_id)},
        timeout=float(timeout_s),
    )
    if int(resp.status_code) != 200:
        return []
    payload = resp.json()
    results = list(payload.get("results") or [])
    if not results:
        return []
    first = dict(results[0] or {})
    return [_to_int(x, 0) for x in (first.get("skills") or []) if _to_int(x, 0) > 0]


def _fetch_skill_capability(skill_id: int, timeout_s: float) -> Dict[str, int | bool | str]:
    resp = requests.get(_SWARFARM_SKILL_URL_TMPL.format(sid=int(skill_id)), timeout=float(timeout_s))
    if int(resp.status_code) != 200:
        return _default_capability()
    return _capability_from_skill_payload(dict(resp.json() or {}))


def _download_skill_icon(icon_filename: str, icons_dir: Path, timeout_s: float = 10.0) -> Path | None:
    """Download a skill icon from Swarfarm if not already cached locally."""
    if not icon_filename:
        return None
    local_path = icons_dir / icon_filename
    if local_path.exists():
        return local_path
    icons_dir.mkdir(parents=True, exist_ok=True)
    for base in _SWARFARM_SKILL_ICON_BASES:
        url = base + icon_filename
        try:
            resp = requests.get(url, timeout=float(timeout_s))
            if resp.status_code == 200 and len(resp.content) > 100:
                local_path.write_bytes(resp.content)
                return local_path
        except Exception:
            continue
    return None


def ensure_skill_icons(
    capabilities: Dict[int, Dict],
    icons_dir: Path,
    timeout_s: float = 10.0,
) -> None:
    """Download any missing skill icons for the given capabilities."""
    seen: set[str] = set()
    for cfg in capabilities.values():
        for key in ("spd_buff_skill_icon", "atb_boost_skill_icon"):
            fname = str(cfg.get(key) or "")
            if fname and fname not in seen:
                seen.add(fname)
                _download_skill_icon(fname, icons_dir, timeout_s=timeout_s)


def resolve_turn_effect_capabilities(
    com2us_ids: Iterable[int],
    cache_path: Path,
    timeout_s: float = 12.0,
    fetch_missing: bool = True,
    max_new_monsters: int | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Dict[int, Dict[str, int | bool]]:
    cache = _load_cache(Path(cache_path))
    by_com2us_id = dict(cache.get("by_com2us_id") or {})
    by_skill_id = dict(cache.get("by_skill_id") or {})
    requested = sorted({int(x) for x in (com2us_ids or []) if int(x) > 0})
    changed = False

    if not bool(fetch_missing):
        out_cached: Dict[int, Dict[str, int | bool]] = {}
        for cid in requested:
            cfg = dict(by_com2us_id.get(str(int(cid))) or _default_capability())
            out_cached[int(cid)] = {
                "has_spd_buff": bool(cfg.get("has_spd_buff", False)),
                "has_atb_boost": bool(cfg.get("has_atb_boost", False)),
                "max_atb_boost_pct": int(cfg.get("max_atb_boost_pct", 0) or 0),
                "spd_buff_skill_icon": str(cfg.get("spd_buff_skill_icon", "") or ""),
                "atb_boost_skill_icon": str(cfg.get("atb_boost_skill_icon", "") or ""),
            }
        return out_cached

    missing = [int(cid) for cid in requested if str(int(cid)) not in by_com2us_id]
    if max_new_monsters is not None and int(max_new_monsters) > 0:
        missing = missing[: int(max_new_monsters)]

    for cid in requested:
        key = str(int(cid))
        if key in by_com2us_id:
            continue
        if int(cid) not in missing:
            continue
        if callable(is_cancelled) and bool(is_cancelled()):
            break
        capability = _default_capability()
        try:
            skill_ids = _fetch_monster_skill_ids(int(cid), timeout_s=float(timeout_s))
            for sid in skill_ids:
                if callable(is_cancelled) and bool(is_cancelled()):
                    break
                s_key = str(int(sid))
                if s_key not in by_skill_id:
                    by_skill_id[s_key] = _fetch_skill_capability(int(sid), timeout_s=float(timeout_s))
                    changed = True
                s_cap = dict(by_skill_id.get(s_key) or {})
                if bool(s_cap.get("has_spd_buff", False)) and not bool(capability.get("has_spd_buff", False)):
                    capability["spd_buff_skill_icon"] = str(s_cap.get("spd_buff_skill_icon", "") or "")
                if bool(s_cap.get("has_atb_boost", False)) and not bool(capability.get("has_atb_boost", False)):
                    capability["atb_boost_skill_icon"] = str(s_cap.get("atb_boost_skill_icon", "") or "")
                capability["has_spd_buff"] = bool(capability["has_spd_buff"] or s_cap.get("has_spd_buff", False))
                capability["has_atb_boost"] = bool(capability["has_atb_boost"] or s_cap.get("has_atb_boost", False))
                capability["max_atb_boost_pct"] = max(
                    int(capability.get("max_atb_boost_pct", 0) or 0),
                    int(s_cap.get("max_atb_boost_pct", 0) or 0),
                )
            if bool(capability.get("has_atb_boost")) and int(capability.get("max_atb_boost_pct", 0) or 0) <= 0:
                capability["max_atb_boost_pct"] = 100
        except Exception:
            capability = _default_capability()
        by_com2us_id[key] = capability
        changed = True

    if changed:
        _save_cache(
            Path(cache_path),
            {
                "version": _CACHE_VERSION,
                "by_com2us_id": by_com2us_id,
                "by_skill_id": by_skill_id,
            },
        )

    out: Dict[int, Dict[str, int | bool]] = {}
    for cid in requested:
        cfg = dict(by_com2us_id.get(str(int(cid))) or _default_capability())
        out[int(cid)] = {
            "has_spd_buff": bool(cfg.get("has_spd_buff", False)),
            "has_atb_boost": bool(cfg.get("has_atb_boost", False)),
            "max_atb_boost_pct": int(cfg.get("max_atb_boost_pct", 0) or 0),
            "spd_buff_skill_icon": str(cfg.get("spd_buff_skill_icon", "") or ""),
            "atb_boost_skill_icon": str(cfg.get("atb_boost_skill_icon", "") or ""),
        }
    return out


def capabilities_by_unit_id(
    unit_to_com2us_id: Dict[int, int],
    cache_path: Path,
    timeout_s: float = 12.0,
    fetch_missing: bool = True,
    max_new_monsters: int | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Dict[int, Dict[str, int | bool]]:
    cids = sorted({int(cid) for cid in (unit_to_com2us_id or {}).values() if int(cid) > 0})
    by_cid = resolve_turn_effect_capabilities(
        cids,
        cache_path=Path(cache_path),
        timeout_s=float(timeout_s),
        fetch_missing=bool(fetch_missing),
        max_new_monsters=max_new_monsters,
        is_cancelled=is_cancelled,
    )
    out: Dict[int, Dict[str, int | bool]] = {}
    for uid, cid in (unit_to_com2us_id or {}).items():
        ui = int(uid or 0)
        ci = int(cid or 0)
        if ui <= 0 or ci <= 0:
            continue
        out[ui] = dict(by_cid.get(ci) or _default_capability())
    return out
