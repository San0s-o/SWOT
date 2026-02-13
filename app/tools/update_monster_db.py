from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from tqdm import tqdm


API_ROOT = "https://swarfarm.com/api/v2"
MONSTERS_ENDPOINT = f"{API_ROOT}/monsters/"  # paginated list


@dataclass(frozen=True)
class MonsterRow:
    com2us_id: int
    name: str
    element: str
    detail_url: Optional[str]


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _get_project_root() -> Path:
    # tools/update_monster_db.py -> tools -> project root
    return Path(__file__).resolve().parents[1]


def _http_get_json(session: requests.Session, url: str, params: Optional[dict] = None, retries: int = 5) -> dict:
    last_err: Optional[Exception] = None
    for i in range(retries):
        try:
            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(0.6 * (i + 1))
    raise RuntimeError(f"GET json failed: {url} ({last_err})")


def _http_download_file(session: requests.Session, url: str, out_path: Path, retries: int = 4) -> bool:
    """
    Downloads url to out_path. Returns True on success.
    """
    for i in range(retries):
        try:
            r = session.get(url, timeout=30, stream=True)
            if r.status_code == 404:
                return False
            r.raise_for_status()

            ctype = (r.headers.get("Content-Type") or "").lower()
            if "image" not in ctype:
                # sometimes servers mislabel, but we at least reject HTML
                peek = r.raw.read(64, decode_content=True)
                if b"<html" in peek.lower():
                    return False

            out_path.parent.mkdir(parents=True, exist_ok=True)
            with out_path.open("wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 64):
                    if chunk:
                        f.write(chunk)
            return True
        except Exception:
            time.sleep(0.5 * (i + 1))
    # don't hard fail the whole run because one image failed
    return False


def _extract_image_url_from_detail(detail: dict) -> Optional[str]:
    """
    Try common SWARFARM fields.
    We accept absolute URLs directly, or filenames that we later map to base paths.
    """
    for key in ("image", "icon", "image_url", "icon_url"):
        v = detail.get(key)
        if isinstance(v, str) and v.startswith("http"):
            return v

    for key in ("image_filename", "icon_filename", "image_file", "icon_file"):
        v = detail.get(key)
        if isinstance(v, str) and v:
            # filename only
            return v

    # sometimes nested
    images = detail.get("images")
    if isinstance(images, dict):
        for key in ("icon", "image", "portrait"):
            v = images.get(key)
            if isinstance(v, str) and v:
                return v

    return None


def _candidate_icon_urls(com2us_id: int, maybe: str) -> List[str]:
    """
    Build candidates from either:
      - absolute url (returned as-is)
      - filename (join with possible static base paths)
    """
    if maybe.startswith("http"):
        return [maybe]

    filename = maybe.lstrip("/")

    # Common-ish SWARFARM static paths (we try multiple; first match wins)
    bases = [
        "https://swarfarm.com/static/herders/images/monsters/",
        "https://swarfarm.com/static/herders/images/monsters/large/",
        "https://swarfarm.com/static/bestiary/monsters/",
        "https://swarfarm.com/static/monsters/",
        "https://swarfarm.com/static/img/monsters/",
    ]
    urls = [b + filename for b in bases]

    # fallback: if filename missing extension, try png
    if "." not in filename:
        urls += [b + filename + ".png" for b in bases]

    # extra fallback: canonical local naming by com2us_id
    # (if the server uses <id>.png)
    urls += [b + f"{com2us_id}.png" for b in bases]

    # dedupe keep order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def fetch_all_monsters(session: requests.Session) -> List[MonsterRow]:
    """
    Pulls all monsters from paginated endpoint.
    Expected schema (common DRF pagination):
      {"count":..., "next": "...", "previous":..., "results":[...]}
    """
    out: List[MonsterRow] = []

    url = MONSTERS_ENDPOINT
    params = {"page": 1}
    while True:
        payload = _http_get_json(session, url, params=params)

        results = payload.get("results")
        if not isinstance(results, list):
            # non-standard schema; try treating payload itself as list
            if isinstance(payload, list):
                results = payload
            else:
                raise RuntimeError("Unexpected monsters payload schema (no results list).")

        for m in results:
            com2us_id = _safe_int(m.get("com2us_id"))
            name = str(m.get("name") or "").strip()
            element = str(m.get("element") or "").strip()
            detail_url = m.get("url") if isinstance(m.get("url"), str) else None

            if com2us_id > 0 and name:
                out.append(MonsterRow(com2us_id=com2us_id, name=name, element=element or "Unknown", detail_url=detail_url))

        nxt = payload.get("next")
        if not nxt:
            break

        # next might be absolute; DRF next usually includes page param already
        url = nxt
        params = None

    return out


def update_db_and_icons() -> int:
    root = _get_project_root()
    assets_dir = root / "app" / "assets"
    icons_dir = assets_dir / "icons"
    db_path = assets_dir / "monsters.json"

    assets_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "SWOP2-MonsterDB-Updater/1.0",
            "Accept": "application/json,text/plain,*/*",
        }
    )

    print(f"Fetching monsters from {MONSTERS_ENDPOINT}")
    monsters = fetch_all_monsters(session)
    print(f"Got {len(monsters)} monsters")

    rows_out: List[Dict[str, Any]] = []
    missing_icons: List[int] = []

    for m in tqdm(monsters, desc="Downloading icons", unit="monster"):
        # Build DB row
        icon_rel = f"icons/{m.com2us_id}.png"
        icon_abs = icons_dir / f"{m.com2us_id}.png"

        # Download icon if not cached
        ok_icon = icon_abs.exists()

        # Resolve icon URL: try detail endpoint first (more fields)
        img_hint: Optional[str] = None
        if not ok_icon:
            if m.detail_url:
                try:
                    detail = _http_get_json(session, m.detail_url)
                    img_hint = _extract_image_url_from_detail(detail)
                except Exception:
                    img_hint = None

            # If we still have no hint, fallback to just com2us_id.png attempts
            if not img_hint:
                img_hint = f"{m.com2us_id}.png"

            # Try candidates until one downloads
            for cand in _candidate_icon_urls(m.com2us_id, img_hint):
                if _http_download_file(session, cand, icon_abs):
                    ok_icon = True
                    break

        if not ok_icon:
            missing_icons.append(m.com2us_id)
            # keep icon empty so UI shows without icon
            icon_rel = ""

        rows_out.append(
            {
                "com2us_id": m.com2us_id,
                "name": m.name,
                "element": m.element,
                "icon": icon_rel,
            }
        )

    # Write monsters.json
    payload = {
        "version": time.strftime("%Y-%m-%d"),
        "source": "swarfarm api v2",
        "monsters": rows_out,
    }
    db_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote DB: {db_path}")

    if missing_icons:
        print(f"WARNING: Missing icons for {len(missing_icons)} monsters (showing first 30): {missing_icons[:30]}")
        print("You can re-run the script later; it will skip already-downloaded icons.")
    else:
        print("All icons downloaded.")

    return 0


if __name__ == "__main__":
    raise SystemExit(update_db_and_icons())
