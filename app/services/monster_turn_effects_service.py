from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Iterable

import requests


_SWARFARM_MONSTERS_URL = "https://swarfarm.com/api/v2/monsters/"
_SWARFARM_SKILL_URL_TMPL = "https://swarfarm.com/api/v2/skills/{sid}/"
_EFFECT_ID_SPEED_BUFF = 5
_EFFECT_ID_INCREASE_ATB = 17


def _to_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _default_capability() -> Dict[str, int | bool]:
    return {
        "has_spd_buff": False,
        "has_atb_boost": False,
        "max_atb_boost_pct": 0,
    }


def _load_cache(path: Path) -> Dict:
    try:
        if not path.exists():
            return {"version": 1, "by_com2us_id": {}, "by_skill_id": {}}
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(raw, dict):
            raise ValueError("invalid cache")
        return {
            "version": 1,
            "by_com2us_id": dict(raw.get("by_com2us_id") or {}),
            "by_skill_id": dict(raw.get("by_skill_id") or {}),
        }
    except Exception:
        return {"version": 1, "by_com2us_id": {}, "by_skill_id": {}}


def _save_cache(path: Path, payload: Dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _capability_from_skill_payload(skill_payload: Dict) -> Dict[str, int | bool]:
    out = _default_capability()
    effects = list(skill_payload.get("effects") or [])
    for eff in effects:
        if not isinstance(eff, dict):
            continue
        effect_obj = dict(eff.get("effect") or {})
        effect_id = _to_int(effect_obj.get("id"), 0)
        qty = max(0, _to_int(eff.get("quantity"), 0))
        if effect_id == _EFFECT_ID_SPEED_BUFF:
            out["has_spd_buff"] = True
        if effect_id == _EFFECT_ID_INCREASE_ATB:
            out["has_atb_boost"] = True
            if qty > int(out.get("max_atb_boost_pct", 0) or 0):
                out["max_atb_boost_pct"] = int(qty)
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


def _fetch_skill_capability(skill_id: int, timeout_s: float) -> Dict[str, int | bool]:
    resp = requests.get(_SWARFARM_SKILL_URL_TMPL.format(sid=int(skill_id)), timeout=float(timeout_s))
    if int(resp.status_code) != 200:
        return _default_capability()
    return _capability_from_skill_payload(dict(resp.json() or {}))


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
                "version": 1,
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
