from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests
from tqdm import tqdm


# ------------------------------------------------------------
# 1) Set-ID -> slug Mapping
#    (Wenn Com2uS neue Sets hinzufügt, ergänzen wir hier.)
# ------------------------------------------------------------
# Hinweis: Die numeric set_ids kommen aus dem JSON Export.
# Slugs sind "konventionelle" Dateinamen, die viele Asset-Dumps/Hostings nutzen.
SET_ID_TO_SLUG: Dict[int, str] = {
    1: "energy",
    2: "guard",
    3: "swift",
    4: "blade",
    5: "rage",
    6: "focus",
    7: "endure",
    8: "fatal",
    10: "despair",
    11: "vampire",
    13: "violent",
    14: "nemesis",
    15: "will",
    16: "shield",
    17: "revenge",
    18: "destroy",
    19: "fight",
    20: "determination",
    21: "enhance",
    22: "accuracy",
    23: "tolerance",
    24: "seal",
    25: "intangible",  # Reloaded / neuere Sets – ggf. prüfen/ergänzen
    # ggf. weitere: "focus" etc. sind schon oben.
}

# Falls du ALLE gängigen Sets (auch alte/seltene) abdecken willst,
# kannst du hier später erweitern.


@dataclass(frozen=True)
class DownloadResult:
    ok: bool
    url: Optional[str]
    out_path: Path
    reason: Optional[str] = None


def project_root() -> Path:
    # app/tools/update_rune_icons.py -> app/tools -> app -> project root
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    return project_root() / "app" / "assets"


def out_dir_sets() -> Path:
    return assets_dir() / "runes" / "sets"


def out_mapping_path() -> Path:
    return assets_dir() / "runes" / "rune_sets.json"


def http_get(session: requests.Session, url: str, timeout: int = 30) -> requests.Response:
    r = session.get(url, timeout=timeout)
    return r


def try_download(session: requests.Session, urls: List[str], out_path: Path, retries: int = 3) -> DownloadResult:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    last_reason: Optional[str] = None
    for url in urls:
        for i in range(retries):
            try:
                r = http_get(session, url)
                if r.status_code == 404:
                    last_reason = "404"
                    break
                r.raise_for_status()

                ctype = (r.headers.get("Content-Type") or "").lower()
                # wir wollen nur Bilddaten speichern
                if "image" not in ctype and not url.lower().endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
                    last_reason = f"not-image content-type={ctype}"
                    break

                out_path.write_bytes(r.content)
                return DownloadResult(ok=True, url=url, out_path=out_path, reason=None)
            except Exception as e:
                last_reason = f"{type(e).__name__}: {e}"
                time.sleep(0.6 * (i + 1))

    return DownloadResult(ok=False, url=None, out_path=out_path, reason=last_reason)


def candidate_urls_for_slug(slug: str) -> List[str]:
    """
    Mehrere Kandidaten, weil Hostings/Repos unterschiedlich strukturieren.
    Du kannst später weitere Kandidaten ergänzen, ohne die UI anzupassen.
    """
    slug = slug.strip().lower()

    # SWARFARM static (häufig so)
    candidates = [
        f"https://swarfarm.com/static/herders/images/runes/{slug}.png",
        f"https://swarfarm.com/static/herders/images/runes/{slug}.jpg",
        f"https://swarfarm.com/static/herders/images/runes/{slug}.jpeg",
        f"https://swarfarm.com/static/img/runes/{slug}.png",
        f"https://swarfarm.com/static/runes/{slug}.png",
    ]

    # Manche Dumps nutzen Groß-/Kleinschreibung oder Prefix
    candidates += [
        f"https://swarfarm.com/static/herders/images/runes/rune_{slug}.png",
        f"https://swarfarm.com/static/herders/images/runes/set_{slug}.png",
    ]

    # Dedupe
    seen = set()
    out = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_set_ids_from_json(json_path: Path) -> Set[int]:
    """
    Erwartet SWEX/SWOP-like JSON.
    Zieht set_id aus runes[].
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))
    runes = data.get("runes") or data.get("rune_list") or []
    if not isinstance(runes, list):
        return set()

    out: Set[int] = set()
    for r in runes:
        if not isinstance(r, dict):
            continue
        sid = r.get("set_id")
        if sid is None:
            # manche Exporte nutzen "rune_set_id"
            sid = r.get("rune_set_id")
        try:
            sid_int = int(sid)
            if sid_int > 0:
                out.add(sid_int)
        except Exception:
            continue
    return out


def build_mapping(set_ids: Iterable[int]) -> Dict[str, Any]:
    """
    Mapping-Datei, die du später in der UI direkt laden kannst:
    - set_id -> slug -> icon_path
    """
    out: Dict[str, Any] = {"version": 1, "sets": {}}
    for sid in sorted(set_ids):
        slug = SET_ID_TO_SLUG.get(sid, f"set_{sid}")
        icon_rel = f"runes/sets/{sid}_{slug}.png"
        out["sets"][str(sid)] = {"set_id": sid, "slug": slug, "icon": icon_rel}
    return out


def main():
    ap = argparse.ArgumentParser(description="Download Summoners War rune set icons for offline use.")
    ap.add_argument("--json", type=str, default="", help="Optional: path to your exported account json (to detect used set_ids).")
    ap.add_argument("--all-known", action="store_true", help="Download icons for all set_ids in SET_ID_TO_SLUG.")
    ap.add_argument("--force", action="store_true", help="Redownload even if file exists.")
    args = ap.parse_args()

    json_path = Path(args.json).resolve() if args.json else None

    if args.all_known:
        set_ids = set(SET_ID_TO_SLUG.keys())
    elif json_path and json_path.exists():
        set_ids = parse_set_ids_from_json(json_path)
        if not set_ids:
            print("WARN: No set_ids found in JSON. Use --all-known to fetch known set icons.")
    else:
        print("ERROR: Provide --json <path> or use --all-known.")
        raise SystemExit(2)

    out_sets = out_dir_sets()
    out_sets.mkdir(parents=True, exist_ok=True)

    mapping = build_mapping(set_ids)

    session = requests.Session()
    session.headers.update({"User-Agent": "SWOP2-RuneIconUpdater/1.0"})

    ok_count = 0
    fail: List[Tuple[int, str]] = []

    for sid in tqdm(sorted(set_ids), desc="Downloading rune set icons"):
        slug = mapping["sets"][str(sid)]["slug"]
        out_path = out_sets / f"{sid}_{slug}.png"

        if out_path.exists() and not args.force:
            ok_count += 1
            continue

        urls = candidate_urls_for_slug(slug)
        res = try_download(session, urls, out_path)
        if res.ok:
            ok_count += 1
        else:
            fail.append((sid, slug))
            # Datei ggf. entfernen, falls kaputt/leer
            try:
                if out_path.exists() and out_path.stat().st_size == 0:
                    out_path.unlink()
            except Exception:
                pass

    out_map = out_mapping_path()
    out_map.parent.mkdir(parents=True, exist_ok=True)
    out_map.write_text(json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8")

    print("")
    print(f"Done. Icons OK: {ok_count}/{len(set_ids)}")
    print(f"Mapping: {out_map}")
    print(f"Icons folder: {out_sets}")

    if fail:
        print("")
        print("FAILED set icons (extend mapping or add URL candidates):")
        for sid, slug in fail:
            print(f"  - set_id={sid} slug={slug}")


if __name__ == "__main__":
    main()