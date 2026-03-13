from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable

import requests


API_MONSTERS = "https://swarfarm.com/api/v2/monsters/"


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return bool(value)
    if value is None:
        return bool(default)
    if isinstance(value, (int, float)):
        return bool(value)
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "y"}:
        return True
    if txt in {"0", "false", "no", "n"}:
        return False
    return bool(default)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _iter_swarfarm_monsters(session: requests.Session) -> Iterable[dict]:
    url = API_MONSTERS
    params = {"page": 1}
    while True:
        res = session.get(url, params=params, timeout=40)
        res.raise_for_status()
        payload = res.json()
        rows = payload.get("results")
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    yield row
        else:
            raise RuntimeError("Unexpected SWARFARM response (missing results list).")
        nxt = payload.get("next")
        if not nxt:
            break
        url = str(nxt)
        params = None


def _load_local_monster_ids(monsters_path: Path) -> set[int]:
    raw = json.loads(monsters_path.read_text(encoding="utf-8"))
    rows = list(raw.get("monsters") or [])
    ids = {
        _safe_int(row.get("com2us_id"), 0)
        for row in rows
        if isinstance(row, dict) and _safe_int(row.get("com2us_id"), 0) > 0
    }
    return {int(x) for x in ids if int(x) > 0}


def build_monster_meta(*, local_monster_ids: set[int] | None = None) -> Dict[str, Dict[str, Any]]:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "SWTO-MonsterMeta-Updater/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    out: Dict[str, Dict[str, Any]] = {}
    for row in _iter_swarfarm_monsters(session):
        mid = _safe_int(row.get("com2us_id"), 0)
        if mid <= 0:
            continue
        if local_monster_ids and mid not in local_monster_ids:
            continue
        out[str(mid)] = {
            "base_stars": _safe_int(row.get("base_stars"), 0),
            "natural_stars": _safe_int(row.get("natural_stars"), 0),
            "awaken_level": _safe_int(row.get("awaken_level"), 0),
            "can_awaken": _safe_bool(row.get("can_awaken"), False),
            "obtainable": _safe_bool(row.get("obtainable"), True),
            "family_id": _safe_int(row.get("family_id"), 0),
            "homunculus": _safe_bool(row.get("homunculus"), False),
        }
    return out


def main() -> int:
    root = _project_root()
    parser = argparse.ArgumentParser(description="Update local monster metadata from SWARFARM.")
    parser.add_argument(
        "--monsters-json",
        default=str(root / "app" / "assets" / "monsters.json"),
        help="Path to local monsters.json (used to limit com2us_id set).",
    )
    parser.add_argument(
        "--out",
        default=str(root / "app" / "domain" / "monster_meta.json"),
        help="Output metadata file path.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Export all SWARFARM monsters instead of filtering to local monsters.json IDs.",
    )
    args = parser.parse_args()

    monsters_path = Path(args.monsters_json).resolve()
    out_path = Path(args.out).resolve()

    if not monsters_path.exists() and not bool(args.all):
        raise FileNotFoundError(f"monsters.json not found: {monsters_path}")

    local_ids: set[int] | None = None
    if not bool(args.all):
        local_ids = _load_local_monster_ids(monsters_path)
        print(f"Local monster IDs: {len(local_ids)}")

    print("Fetching monster metadata from SWARFARM...")
    by_id = build_monster_meta(local_monster_ids=local_ids)
    print(f"Fetched metadata rows: {len(by_id)}")

    payload = {
        "version": time.strftime("%Y-%m-%d"),
        "source": "swarfarm api v2",
        "by_com2us_id": {
            str(k): by_id[str(k)]
            for k in sorted((int(x) for x in by_id.keys()), key=int)
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
