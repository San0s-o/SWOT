from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class SavedUnitResult:
    unit_id: int
    runes_by_slot: Dict[int, int]   # slot (1-6) -> rune_id
    artifacts_by_type: Dict[int, int] = field(default_factory=dict)  # artifact type (1/2) -> artifact_id
    final_speed: int = 0


@dataclass
class SavedOptimization:
    id: str
    name: str
    mode: str                        # "siege" / "wgb"
    teams: List[List[int]]           # [[uid, uid, uid], ...]
    results: List[SavedUnitResult]
    timestamp: str = ""


@dataclass
class OptimizationStore:
    version: str = "2026-02-08"
    optimizations: Dict[str, SavedOptimization] = field(default_factory=dict)

    # ── persistence ──────────────────────────────────────────
    @staticmethod
    def load(path: str | Path) -> "OptimizationStore":
        p = Path(path)
        if not p.exists():
            return OptimizationStore()
        raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        store = OptimizationStore()
        store.version = str(raw.get("version") or store.version)
        for oid, data in (raw.get("optimizations") or {}).items():
            if not isinstance(data, dict):
                continue
            results: List[SavedUnitResult] = []
            for r in (data.get("results") or []):
                rbs = {int(k): int(v) for k, v in (r.get("runes_by_slot") or {}).items()}
                abs_ = {int(k): int(v) for k, v in (r.get("artifacts_by_type") or {}).items()}
                results.append(SavedUnitResult(
                    unit_id=int(r.get("unit_id") or 0),
                    runes_by_slot=rbs,
                    artifacts_by_type=abs_,
                    final_speed=int(r.get("final_speed") or 0),
                ))
            teams_raw = data.get("teams") or []
            teams = [[int(u) for u in t] for t in teams_raw if isinstance(t, list)]
            store.optimizations[str(oid)] = SavedOptimization(
                id=str(oid),
                name=str(data.get("name") or ""),
                mode=str(data.get("mode") or "siege"),
                teams=teams,
                results=results,
                timestamp=str(data.get("timestamp") or ""),
            )
        return store

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        out: Dict[str, Any] = {"version": self.version, "optimizations": {}}
        for oid, opt in self.optimizations.items():
            out["optimizations"][oid] = {
                "name": opt.name,
                "mode": opt.mode,
                "teams": opt.teams,
                "timestamp": opt.timestamp,
                "results": [
                    {
                        "unit_id": r.unit_id,
                        "runes_by_slot": {str(k): v for k, v in r.runes_by_slot.items()},
                        "artifacts_by_type": {str(k): v for k, v in (r.artifacts_by_type or {}).items()},
                        "final_speed": r.final_speed,
                    }
                    for r in opt.results
                ],
            }
        p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── queries ──────────────────────────────────────────────
    def get_by_mode(self, mode: str) -> List[SavedOptimization]:
        """Return all optimizations for *mode*, newest first."""
        items = [o for o in self.optimizations.values() if o.mode == mode]
        items.sort(key=lambda o: o.timestamp, reverse=True)
        return items

    def upsert(self, mode: str, name: str, teams: List[List[int]],
               results: List[SavedUnitResult],
               oid: Optional[str] = None) -> SavedOptimization:
        key = oid or str(uuid.uuid4())
        opt = SavedOptimization(
            id=key,
            name=name,
            mode=mode,
            teams=teams,
            results=results,
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.optimizations[key] = opt
        return opt

    def remove(self, oid: str) -> None:
        self.optimizations.pop(oid, None)
