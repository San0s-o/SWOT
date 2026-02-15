from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.services.account_persistence import AccountPersistence


def _first_existing(paths: List[Path]) -> Path | None:
    for p in paths:
        if p.exists():
            return p
    return None


def _default_snapshot_path() -> Path | None:
    persistence = AccountPersistence()
    primary = persistence.active_snapshot_path()
    if primary.exists():
        return primary
    return _first_existing(
        [
            Path("app/data/account_snapshot.json"),
            Path("app") / "data" / "account_snapshot.json",
        ]
    )


def _dedupe_keep_order(values: List[int]) -> List[int]:
    seen: set[int] = set()
    out: List[int] = []
    for raw in values:
        v = int(raw)
        if v <= 0 or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _pick_unit_ids(mode: str, account_unit_ids: List[int], rta_ids: List[int], siege_ids: List[int], limit: int) -> List[int]:
    mode_key = str(mode).strip().lower()
    source: List[int]
    if mode_key == "rta":
        source = _dedupe_keep_order(rta_ids) or _dedupe_keep_order(account_unit_ids)
    else:
        source = _dedupe_keep_order(siege_ids) or _dedupe_keep_order(account_unit_ids)
    if limit > 0:
        return source[:limit]
    return source


def _team_maps(unit_ids: List[int], presets: Any, mode: str) -> Tuple[Dict[int, int], Dict[int, int]]:
    from app.domain.presets import Build

    team_idx_by_uid: Dict[int, int] = {}
    team_turn_by_uid: Dict[int, int] = {}
    for idx, uid in enumerate(unit_ids):
        team_idx_by_uid[int(uid)] = int(idx // 3)
        builds = presets.get_unit_builds(mode, int(uid))
        b0 = builds[0] if builds else Build.default_any()
        team_turn_by_uid[int(uid)] = int(getattr(b0, "turn_order", 0) or 0)
    return team_idx_by_uid, team_turn_by_uid


def _run_once(
    mode: str,
    unit_ids: List[int],
    account: Any,
    presets: Any,
    time_limit: float,
    workers: int,
    passes: int,
    enforce_turn_order: bool,
    multi_pass_strategy: str,
    speed_slack_for_quality: int,
    rune_top_per_set: int,
    quality_profile: str,
) -> Dict[str, Any]:
    from app.engine.greedy_optimizer import GreedyRequest, optimize_greedy

    team_idx_by_uid: Dict[int, int] | None = None
    team_turn_by_uid: Dict[int, int] | None = None
    if enforce_turn_order:
        team_idx_by_uid, team_turn_by_uid = _team_maps(unit_ids, presets, mode)
    req = GreedyRequest(
        mode=mode,
        unit_ids_in_order=list(unit_ids),
        time_limit_per_unit_s=float(time_limit),
        workers=int(workers),
        multi_pass_enabled=bool(int(passes) > 1),
        multi_pass_count=int(max(1, passes)),
        multi_pass_strategy=str(multi_pass_strategy or "greedy_refine"),
        rune_top_per_set=max(0, int(rune_top_per_set)),
        quality_profile=str(quality_profile or "balanced"),
        speed_slack_for_quality=max(0, int(speed_slack_for_quality)),
        enforce_turn_order=bool(enforce_turn_order),
        unit_team_index=team_idx_by_uid,
        unit_team_turn_order=team_turn_by_uid,
    )
    started = time.perf_counter()
    res = optimize_greedy(account, presets, req)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    ok_units = sum(1 for r in res.results if bool(r.ok))
    speed_sum = sum(int(r.final_speed or 0) for r in res.results if bool(r.ok))
    return {
        "elapsed_ms": round(elapsed_ms, 2),
        "ok_all": bool(res.ok),
        "ok_units": int(ok_units),
        "total_units": int(len(res.results)),
        "speed_sum": int(speed_sum),
        "message": str(res.message),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark greedy optimizer runtime and output quality.")
    parser.add_argument("--snapshot", type=str, default="", help="Path to account snapshot JSON (optional).")
    parser.add_argument("--mode", type=str, default="rta", choices=["rta", "siege", "wgb"], help="Optimization mode.")
    parser.add_argument("--units", type=int, default=15, help="Max number of units to optimize.")
    parser.add_argument("--passes", type=int, default=3, help="Multi-pass count.")
    parser.add_argument(
        "--multi-pass-strategy",
        type=str,
        default="greedy_refine",
        choices=["greedy_only", "greedy_refine"],
        help="Pass strategy for >1 pass.",
    )
    parser.add_argument("--time-limit", type=float, default=1.5, help="Time limit per unit (seconds).")
    parser.add_argument("--speed-slack", type=int, default=1, help="Allowed SPD loss per unit to improve quality.")
    parser.add_argument("--rune-top-per-set", type=int, default=200, help="Top-N runes per set in candidate pool (0 = all).")
    parser.add_argument("--quality-profile", type=str, default="balanced",
                        choices=["fast", "balanced", "max_quality", "gpu_search"],
                        help="Preset profile for optimization behavior.")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 8) // 2), help="OR-Tools worker threads.")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup runs.")
    parser.add_argument("--runs", type=int, default=3, help="Measured runs.")
    parser.add_argument("--no-turn-order", action="store_true", help="Disable turn-order constraints.")
    parser.add_argument("--out-json", type=str, default="", help="Optional output path for JSON summary.")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot) if args.snapshot else _default_snapshot_path()
    if snapshot_path is None or not snapshot_path.exists():
        print("Snapshot not found. Use --snapshot <path-to-json>.")
        return 2

    try:
        from app.domain.presets import BuildStore
        from app.importer.sw_json_importer import load_account_json
    except ModuleNotFoundError as exc:
        print(f"Missing dependency for benchmark run: {exc}. Install requirements first.")
        return 4

    presets_path = Path("app/config/build_presets.json")
    presets = BuildStore.load(presets_path) if presets_path.exists() else BuildStore()
    account = load_account_json(snapshot_path)

    all_unit_ids = [int(uid) for uid in sorted((account.units_by_id or {}).keys())]
    selected = _pick_unit_ids(
        mode=str(args.mode),
        account_unit_ids=all_unit_ids,
        rta_ids=[int(uid) for uid in account.rta_active_unit_ids()],
        siege_ids=[int(uid) for uid in (account.guildsiege_defense_unit_list or [])],
        limit=int(args.units),
    )
    if not selected:
        print("No candidate units found in snapshot for requested mode.")
        return 3

    enforce_turn_order = not bool(args.no_turn_order)
    print(
        f"Benchmark mode={args.mode} units={len(selected)} passes={int(args.passes)} "
        f"time_limit={float(args.time_limit):.2f}s workers={int(args.workers)} "
        f"enforce_turn_order={enforce_turn_order} strategy={args.multi_pass_strategy} "
        f"speed_slack={int(args.speed_slack)} rune_top_per_set={int(args.rune_top_per_set)} "
        f"profile={args.quality_profile}"
    )

    for i in range(max(0, int(args.warmup))):
        try:
            _ = _run_once(
                mode=str(args.mode),
                unit_ids=selected,
                account=account,
                presets=presets,
                time_limit=float(args.time_limit),
                workers=int(args.workers),
                passes=int(args.passes),
                enforce_turn_order=enforce_turn_order,
                multi_pass_strategy=str(args.multi_pass_strategy),
                speed_slack_for_quality=int(args.speed_slack),
                rune_top_per_set=int(args.rune_top_per_set),
                quality_profile=str(args.quality_profile),
            )
        except ModuleNotFoundError as exc:
            print(f"Missing dependency for benchmark run: {exc}. Install requirements first.")
            return 4
        print(f"Warmup {i + 1}/{int(args.warmup)} done")

    runs: List[Dict[str, Any]] = []
    for i in range(max(1, int(args.runs))):
        try:
            row = _run_once(
                mode=str(args.mode),
                unit_ids=selected,
                account=account,
                presets=presets,
                time_limit=float(args.time_limit),
                workers=int(args.workers),
                passes=int(args.passes),
                enforce_turn_order=enforce_turn_order,
                multi_pass_strategy=str(args.multi_pass_strategy),
                speed_slack_for_quality=int(args.speed_slack),
                rune_top_per_set=int(args.rune_top_per_set),
                quality_profile=str(args.quality_profile),
            )
        except ModuleNotFoundError as exc:
            print(f"Missing dependency for benchmark run: {exc}. Install requirements first.")
            return 4
        runs.append(row)
        print(
            f"Run {i + 1}/{int(args.runs)}: "
            f"{row['elapsed_ms']} ms | ok_units={row['ok_units']}/{row['total_units']} | speed_sum={row['speed_sum']}"
        )

    elapsed = [float(r["elapsed_ms"]) for r in runs]
    ok_units_vals = [int(r["ok_units"]) for r in runs]
    speed_sum_vals = [int(r["speed_sum"]) for r in runs]
    summary = {
        "snapshot": str(snapshot_path),
        "mode": str(args.mode),
        "units": len(selected),
        "passes": int(args.passes),
        "multi_pass_strategy": str(args.multi_pass_strategy),
        "time_limit_s": float(args.time_limit),
        "speed_slack_for_quality": int(args.speed_slack),
        "rune_top_per_set": int(args.rune_top_per_set),
        "quality_profile": str(args.quality_profile),
        "workers": int(args.workers),
        "enforce_turn_order": bool(enforce_turn_order),
        "runs": runs,
        "stats": {
            "elapsed_ms_mean": round(statistics.fmean(elapsed), 2),
            "elapsed_ms_median": round(statistics.median(elapsed), 2),
            "elapsed_ms_min": round(min(elapsed), 2),
            "elapsed_ms_max": round(max(elapsed), 2),
            "ok_units_mean": round(statistics.fmean(ok_units_vals), 2),
            "speed_sum_mean": round(statistics.fmean(speed_sum_vals), 2),
        },
    }

    print("Summary:")
    print(
        f"  elapsed mean/median/min/max: "
        f"{summary['stats']['elapsed_ms_mean']} / {summary['stats']['elapsed_ms_median']} / "
        f"{summary['stats']['elapsed_ms_min']} / {summary['stats']['elapsed_ms_max']} ms"
    )
    print(
        f"  ok_units mean: {summary['stats']['ok_units_mean']} | "
        f"speed_sum mean: {summary['stats']['speed_sum_mean']}"
    )

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote summary JSON: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
