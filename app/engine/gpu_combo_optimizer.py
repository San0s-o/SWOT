"""GPU-native rune/artifact combination optimizer.

Uses numpy for vectorised scoring and optional onnxruntime-directml for
GPU-parallel evaluation of candidate rune+artifact combinations.  Falls back
to pure numpy/CPU when no GPU runtime is available.

Fully GPU-native approach (no OR-Tools in the loop):
1.  Encode every rune + artifact as fixed-size stat vectors.
2.  Pre-filter slots 2/4/6 by mainstat constraints, all slots by set constraints.
3.  For each unit, generate massive batches of random + heuristic-guided
    rune+artifact combinations (evolutionary search).
4.  Evaluate all combinations in one vectorised pass: set validation, mainstat
    check, speed tick bounds, min stat thresholds, scoring â€“ on GPU if available.
5.  Build GreedyUnitResult directly from the best GPU-found combination.
6.  Persist per-account learning data so the scoring weights improve over time.
"""
from __future__ import annotations

import json
import random
import hashlib
import statistics
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import numpy as np

from app.domain.models import AccountData, Rune, Artifact
from app.domain.presets import (
    BuildStore,
    Build,
    SET_SIZES,
    SET_ID_BY_NAME,
    EFFECT_ID_TO_MAINSTAT_KEY,
)
from app.domain.speed_ticks import min_spd_for_tick, max_spd_for_tick
from app.engine.efficiency import rune_efficiency, artifact_efficiency
from app.engine.greedy_optimizer import (
    DEFAULT_BUILD_PRIORITY_PENALTY,
    GreedyRequest,
    GreedyResult,
    GreedyUnitResult,
    REFINE_SAME_ARTIFACT_PENALTY,
    REFINE_SAME_RUNE_PENALTY,
    SET_OPTION_PREFERENCE_BONUS,
    _allowed_artifacts_for_mode,
    _allowed_runes_for_mode,
    _build_pass_orders,
    _evaluate_pass_score,
    _rune_flat_spd,
    _rune_stat_total,
    _rune_quality_score,
    _artifact_quality_score,
    _builds_for_unit_with_cloud_prior,
    _run_pass_with_profile,
)
from app.i18n import tr
from app.services.cloud_learning_service import fetch_cloud_prior, upload_learning_run

# ---------------------------------------------------------------------------
# Stat IDs used for the fixed-size encoding vector
# ---------------------------------------------------------------------------
_STAT_IDS = [1, 2, 3, 4, 5, 6, 8, 9, 10, 11, 12]  # HP,HP%,ATK,ATK%,DEF,DEF%,SPD,CR,CD,RES,ACC
_STAT_ID_TO_COL = {sid: i for i, sid in enumerate(_STAT_IDS)}
_N_STATS = len(_STAT_IDS)
_COL_SPD = _STAT_ID_TO_COL[8]
_COL_CR = _STAT_ID_TO_COL[9]
_COL_CD = _STAT_ID_TO_COL[10]
_COL_RES = _STAT_ID_TO_COL[11]
_COL_ACC = _STAT_ID_TO_COL[12]
_COL_HP = _STAT_ID_TO_COL[1]
_COL_HPP = _STAT_ID_TO_COL[2]
_COL_ATK = _STAT_ID_TO_COL[3]
_COL_ATKP = _STAT_ID_TO_COL[4]
_COL_DEF = _STAT_ID_TO_COL[5]
_COL_DEFP = _STAT_ID_TO_COL[6]

# Extra metadata columns appended after stat columns
_COL_RUNE_ID = _N_STATS
_COL_SET_ID = _N_STATS + 1
_COL_SLOT = _N_STATS + 2
_COL_QUALITY = _N_STATS + 3
_COL_EFFICIENCY = _N_STATS + 4
_COL_MAINSTAT_ID = _N_STATS + 5  # pri_eff[0] for mainstat filtering
_VEC_LEN = _N_STATS + 6

# Artifact vector: stat contributions + metadata
_ART_COL_ID = 0
_ART_COL_TYPE = 1  # 1=attribute, 2=type
_ART_COL_QUALITY = 2
_ART_COL_EFFICIENCY = 3
_ART_VEC_LEN = 4

# Learned weights storage
_LEARN_DIR = Path(__file__).resolve().parents[1] / "data" / "gpu_learn"
_WEIGHTS_PATH = _LEARN_DIR / "scoring_weights.json"
_HISTORY_PATH = _LEARN_DIR / "history.jsonl"
_WEIGHTS_SCHEMA_VERSION = 2
_GLOBAL_CONTEXT_KEY = "global"
_MIN_HISTORY_FOR_CANDIDATE = 6
_MIN_HISTORY_FOR_AB = 8
_MAX_REPLAY_CASES = 2
_AB_ACCEPT_MARGIN = 0.002
_AB_MAX_RUNE_EFF_DROP = 0.30
_AB_MAX_OK_RATIO_DROP = 0.0
_CLOUD_ALPHA_MIN = 0.05
_CLOUD_ALPHA_MAX = 0.60
_ADAPTIVE_HISTORY_WINDOW = 24
_ADAPTIVE_MIN_BATCH_GPU = 80_000
_ADAPTIVE_MAX_BATCH_GPU = 900_000
_ADAPTIVE_MIN_BATCH_CPU = 60_000
_ADAPTIVE_MAX_BATCH_CPU = 500_000
_ADAPTIVE_DEFAULT_SOLVER_TOP = 80
_ADAPTIVE_MIN_SOLVER_TOP = 50
_ADAPTIVE_MAX_SOLVER_TOP = 150

# Combination batch sizes for GPU pre-screening
_GPU_BATCH_SIZE = 500_000
_CPU_BATCH_SIZE = 300_000

# How many top-K elite combinations to maintain per unit
_ELITE_SIZE = 300

# Mainstat key â†’ effect_id reverse mapping
_MAINSTAT_KEY_TO_ID: Dict[str, int] = {v: k for k, v in EFFECT_ID_TO_MAINSTAT_KEY.items()}


# ---------------------------------------------------------------------------
# ONNX Runtime GPU detection and GPU scoring kernel
# ---------------------------------------------------------------------------
def _onnx_gpu_session() -> Tuple[bool, Optional[str]]:
    """Try to create an ONNX InferenceSession with DirectML or CUDA."""
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if "DmlExecutionProvider" in providers:
            return True, "DmlExecutionProvider"
        if "CUDAExecutionProvider" in providers:
            return True, "CUDAExecutionProvider"
        return False, "CPUExecutionProvider"
    except ImportError:
        return False, None


# Pre-built ONNX model (192 bytes): MatMul graph
# combo_stats (batch, 11) @ stat_weights_2d (11, 1) -> stat_score_2d (batch, 1)
import base64 as _b64
_MATMUL_ONNX_BYTES = _b64.b64decode(
    "CAg6twEKPwoLY29tYm9fc3RhdHMKD3N0YXRfd2VpZ2h0c18yZBINc3RhdF9zY29yZV8yZB"
    "oIbWF0bXVsXzAiBk1hdE11bBIHc2NvcmluZ1oiCgtjb21ib19zdGF0cxITChEIARINCgcS"
    "BWJhdGNoCgIIC1ohCg9zdGF0X3dlaWdodHNfMmQSDgoMCAESCAoCCAsKAggBYiQKDXN0YXRf"
    "c2NvcmVfMmQSEwoRCAESDQoHEgViYXRjaAoCCAFCAhAR"
)


class _GpuScorer:
    """Wraps ONNX Runtime for GPU-accelerated batch scoring (MatMul on GPU)."""

    def __init__(self, provider: str):
        self._provider = provider
        self._session: Optional[Any] = None
        self._available = False
        try:
            model_bytes = _MATMUL_ONNX_BYTES
            if model_bytes and len(model_bytes) > 0:
                import onnxruntime as ort
                sess_opts = ort.SessionOptions()
                sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                self._session = ort.InferenceSession(
                    model_bytes,
                    sess_options=sess_opts,
                    providers=[provider, "CPUExecutionProvider"],
                )
                self._available = True
        except Exception:
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def score_batch(
        self,
        combo_stats: np.ndarray,
        weights: "ScoringWeights",
    ) -> np.ndarray:
        """Run stat_score = combo_stats @ weights on GPU, return (batch,)."""
        if not self._available or self._session is None:
            return combo_stats @ weights.stat_weights
        w2d = weights.stat_weights.reshape(-1, 1).astype(np.float32)
        result = self._session.run(
            None,
            {
                "combo_stats": combo_stats.astype(np.float32),
                "stat_weights_2d": w2d,
            },
        )
        return result[0].reshape(-1)  # (batch, 1) -> (batch,)


_gpu_scorer_cache: Dict[str, _GpuScorer] = {}


def _get_gpu_scorer(provider: str) -> _GpuScorer:
    if provider not in _gpu_scorer_cache:
        _gpu_scorer_cache[provider] = _GpuScorer(provider)
    return _gpu_scorer_cache[provider]


# ---------------------------------------------------------------------------
# Rune â†’ numpy vector encoding
# ---------------------------------------------------------------------------
def _encode_rune(r: Rune) -> np.ndarray:
    """Encode a single rune into a fixed-size float32 vector."""
    vec = np.zeros(_VEC_LEN, dtype=np.float32)
    for sid in _STAT_IDS:
        col = _STAT_ID_TO_COL[sid]
        vec[col] = float(_rune_stat_total(r, sid))
    vec[_COL_RUNE_ID] = float(r.rune_id)
    vec[_COL_SET_ID] = float(r.set_id or 0)
    vec[_COL_SLOT] = float(r.slot_no)
    vec[_COL_QUALITY] = float(_rune_quality_score(r, 0, None))
    vec[_COL_EFFICIENCY] = float(rune_efficiency(r))
    # Mainstat effect_id (for filtering slots 2/4/6)
    try:
        vec[_COL_MAINSTAT_ID] = float(int(r.pri_eff[0] or 0))
    except Exception:
        vec[_COL_MAINSTAT_ID] = 0.0
    return vec


def _encode_runes(runes: List[Rune]) -> np.ndarray:
    """Encode a list of runes into a (N, _VEC_LEN) matrix."""
    if not runes:
        return np.zeros((0, _VEC_LEN), dtype=np.float32)
    return np.stack([_encode_rune(r) for r in runes])


def _encode_artifact(a: Artifact) -> np.ndarray:
    vec = np.zeros(_ART_VEC_LEN, dtype=np.float32)
    vec[_ART_COL_ID] = float(a.artifact_id)
    vec[_ART_COL_TYPE] = float(a.type_ or 0)
    vec[_ART_COL_QUALITY] = float(_artifact_quality_score(a, 0, None))
    vec[_ART_COL_EFFICIENCY] = float(artifact_efficiency(a))
    return vec


def _encode_artifacts(arts: List[Artifact]) -> np.ndarray:
    if not arts:
        return np.zeros((0, _ART_VEC_LEN), dtype=np.float32)
    return np.stack([_encode_artifact(a) for a in arts])


# ---------------------------------------------------------------------------
# Learned scoring weights
# ---------------------------------------------------------------------------
@dataclass
class ScoringWeights:
    stat_weights: np.ndarray  # shape (_N_STATS,) â€“ per-stat importance
    quality_weight: float
    efficiency_weight: float
    set_bonus_weight: float
    speed_priority: float

    @classmethod
    def default(cls) -> "ScoringWeights":
        # GPU prescreen prioritises rune quality & efficiency over raw speed.
        # The solver (Phase 2) handles speed constraints precisely; our job is
        # to surface the most *efficient* runes from the full pool.
        sw = np.array([
            0.5,   # HP flat
            6.0,   # HP%
            0.5,   # ATK flat
            6.0,   # ATK%
            0.5,   # DEF flat
            6.0,   # DEF%
            10.0,  # SPD â€“ moderate (solver handles speed precisely)
            8.0,   # CR
            7.0,   # CD
            3.0,   # RES
            3.0,   # ACC
        ], dtype=np.float32)
        return cls(
            stat_weights=sw,
            quality_weight=3.0,   # quality (upgrade level, occupied) matters
            efficiency_weight=12.0,  # efficiency is the primary signal
            set_bonus_weight=2.0,
            speed_priority=1.0,   # low: let solver optimise speed
        )

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "stat_weights": self.stat_weights.tolist(),
            "quality_weight": self.quality_weight,
            "efficiency_weight": self.efficiency_weight,
            "set_bonus_weight": self.set_bonus_weight,
            "speed_priority": self.speed_priority,
        }

    @classmethod
    def from_json_dict(cls, raw: Dict[str, Any]) -> "ScoringWeights":
        sw = np.array(raw.get("stat_weights", []), dtype=np.float32)
        if len(sw) != _N_STATS:
            return cls.default()
        return cls(
            stat_weights=sw,
            quality_weight=float(raw.get("quality_weight", 3.0)),
            efficiency_weight=float(raw.get("efficiency_weight", 12.0)),
            set_bonus_weight=float(raw.get("set_bonus_weight", 2.0)),
            speed_priority=float(raw.get("speed_priority", 1.0)),
        )

    def save(self, context_key: str = _GLOBAL_CONTEXT_KEY) -> None:
        _LEARN_DIR.mkdir(parents=True, exist_ok=True)
        store: Dict[str, Any] = {
            "version": int(_WEIGHTS_SCHEMA_VERSION),
            "global": ScoringWeights.default().to_json_dict(),
            "contexts": {},
        }
        if _WEIGHTS_PATH.exists():
            try:
                raw = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    # v1 compatibility: single top-level weight object
                    if "stat_weights" in raw:
                        store["global"] = dict(raw)
                    else:
                        store["global"] = dict(raw.get("global") or store["global"])
                        ctx_raw = raw.get("contexts")
                        if isinstance(ctx_raw, dict):
                            store["contexts"] = dict(ctx_raw)
            except Exception:
                pass

        ctx = str(context_key or _GLOBAL_CONTEXT_KEY).strip().lower() or _GLOBAL_CONTEXT_KEY
        if ctx == _GLOBAL_CONTEXT_KEY:
            store["global"] = self.to_json_dict()
        else:
            contexts = dict(store.get("contexts") or {})
            contexts[ctx] = self.to_json_dict()
            store["contexts"] = contexts
        _WEIGHTS_PATH.write_text(json.dumps(store, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, context_key: str = _GLOBAL_CONTEXT_KEY) -> "ScoringWeights":
        if not _WEIGHTS_PATH.exists():
            return cls.default()
        try:
            raw = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return cls.default()
            # v1 compatibility: single top-level weight object
            if "stat_weights" in raw:
                return cls.from_json_dict(raw)

            ctx = str(context_key or _GLOBAL_CONTEXT_KEY).strip().lower() or _GLOBAL_CONTEXT_KEY
            contexts = raw.get("contexts")
            if isinstance(contexts, dict):
                ctx_payload = contexts.get(ctx)
                if isinstance(ctx_payload, dict):
                    return cls.from_json_dict(ctx_payload)

            global_payload = raw.get("global")
            if isinstance(global_payload, dict):
                return cls.from_json_dict(global_payload)
            return cls.default()
        except Exception:
            return cls.default()

    def perturb(self, rng: random.Random, scale: float = 0.1) -> "ScoringWeights":
        """Create a slightly mutated copy for exploration."""
        new_sw = self.stat_weights.copy()
        for i in range(len(new_sw)):
            new_sw[i] = max(0.0, new_sw[i] + rng.gauss(0, scale * max(1.0, abs(new_sw[i]))))
        return ScoringWeights(
            stat_weights=new_sw,
            quality_weight=max(0.0, self.quality_weight + rng.gauss(0, scale)),
            efficiency_weight=max(0.0, self.efficiency_weight + rng.gauss(0, scale * 2)),
            set_bonus_weight=max(0.0, self.set_bonus_weight + rng.gauss(0, scale)),
            speed_priority=max(0.0, self.speed_priority + rng.gauss(0, scale)),
        )


def _canonical_role_label(archetype: str) -> str:
    raw = str(archetype or "").strip().lower()
    if not raw:
        return "unknown"
    if "rueckhalt" in raw or "rÃ¼ckhalt" in raw or "support" in raw or "heal" in raw:
        return "support"
    if "tank" in raw or "def" in raw or "schutz" in raw:
        return "defense"
    if "hp" in raw:
        return "hp"
    if "atk" in raw or "angriff" in raw or "damage" in raw or "dd" in raw:
        return "attack"
    return "unknown"


def _unit_count_bucket(n_units: int) -> str:
    n = int(max(0, n_units))
    if n <= 3:
        return "u1_3"
    if n <= 6:
        return "u4_6"
    if n <= 10:
        return "u7_10"
    return "u11p"


def _learning_context_key(req: GreedyRequest) -> str:
    mode = str(getattr(req, "mode", "") or "").strip().lower() or "unknown_mode"
    unit_ids = [int(u) for u in (req.unit_ids_in_order or []) if int(u) > 0]
    role_counts: Dict[str, int] = {}
    role_map = dict(getattr(req, "unit_archetype_by_uid", {}) or {})
    for uid in unit_ids:
        role = _canonical_role_label(str(role_map.get(int(uid), "") or ""))
        role_counts[role] = int(role_counts.get(role, 0) + 1)
    ordered_roles = sorted(role_counts.items(), key=lambda x: (-int(x[1]), str(x[0])))
    if not ordered_roles:
        role_sig = "unknown0"
    else:
        role_sig = "+".join(f"{str(name)}{int(cnt)}" for name, cnt in ordered_roles[:3])

    arena_ctx = str(getattr(req, "arena_rush_context", "") or "").strip().lower()
    arena_sig = arena_ctx if arena_ctx else "none"
    turn_sig = "to1" if bool(getattr(req, "enforce_turn_order", False)) else "to0"
    bucket = _unit_count_bucket(len(unit_ids))
    return f"mode={mode}|units={bucket}|{turn_sig}|arena={arena_sig}|roles={role_sig}"


# ---------------------------------------------------------------------------
# Build constraint extraction
# ---------------------------------------------------------------------------
def _extract_build_constraints(
    builds: List[Build],
    mode: str,
) -> Dict[str, Any]:
    """Extract all constraints from a unit's builds into a flat dict."""
    # Collect allowed mainstats per slot (union across all builds)
    allowed_mainstats: Dict[int, Set[int]] = {2: set(), 4: set(), 6: set()}
    # Collect set options (list of alternatives, each is {set_id: count})
    all_set_options: List[Dict[int, int]] = []
    # Min stats (take the max across builds for each stat)
    min_stats: Dict[str, int] = {}
    # Speed tick
    min_spd = 0
    max_spd = 0

    for b in (builds or []):
        # Mainstats
        for slot in (2, 4, 6):
            ms_list = (b.mainstats or {}).get(slot) or (b.mainstats or {}).get(str(slot))
            if ms_list:
                for key in ms_list:
                    eid = _MAINSTAT_KEY_TO_ID.get(str(key))
                    if eid is not None:
                        allowed_mainstats[slot].add(eid)

        # Set options
        for opt in (b.set_options or []):
            needed: Dict[int, int] = {}
            for name in opt:
                sid = SET_ID_BY_NAME.get(str(name))
                if sid:
                    needed[sid] = needed.get(sid, 0) + int(SET_SIZES.get(sid, 2))
            if needed:
                all_set_options.append(needed)

        # Min stats
        for k, v in (b.min_stats or {}).items():
            val = int(v or 0)
            if val > 0:
                min_stats[str(k)] = max(min_stats.get(str(k), 0), val)

        # Speed ticks
        spd_tick = int(getattr(b, "spd_tick", 0) or 0)
        if spd_tick:
            tick_min = int(min_spd_for_tick(spd_tick, mode) or 0)
            tick_max = int(max_spd_for_tick(spd_tick, mode) or 0)
            if tick_min > min_spd:
                min_spd = tick_min
            if tick_max > 0 and (max_spd == 0 or tick_max < max_spd):
                max_spd = tick_max
        build_min_spd = int((b.min_stats or {}).get("SPD", 0) or 0)
        if build_min_spd > min_spd:
            min_spd = build_min_spd

    return {
        "allowed_mainstats": allowed_mainstats,
        "set_options": all_set_options,
        "min_stats": min_stats,
        "min_spd": min_spd,
        "max_spd": max_spd,
    }


def _filter_runes_by_mainstat(
    runes_by_slot: Dict[int, List[Rune]],
    allowed_mainstats: Dict[int, Set[int]],
) -> Dict[int, List[Rune]]:
    """Pre-filter runes on slots 2/4/6 by allowed mainstat constraints."""
    filtered: Dict[int, List[Rune]] = {}
    for slot in range(1, 7):
        runes = runes_by_slot.get(slot, [])
        if slot in (2, 4, 6) and allowed_mainstats.get(slot):
            allowed = allowed_mainstats[slot]
            kept = [r for r in runes if int(r.pri_eff[0] or 0) in allowed]
            # If filtering removes everything, fall back to unfiltered
            filtered[slot] = kept if kept else runes
        else:
            filtered[slot] = runes
    return filtered


# ---------------------------------------------------------------------------
# Vectorised combination scoring with full constraint checking
# ---------------------------------------------------------------------------
def _score_combinations_full(
    slot_matrices: Dict[int, np.ndarray],  # slot -> (N_slot, _VEC_LEN)
    combo_indices: np.ndarray,             # (batch, 6) â€“ indices into slot matrices
    art1_matrix: Optional[np.ndarray],     # (N_art1, _ART_VEC_LEN) or None
    art2_matrix: Optional[np.ndarray],     # (N_art2, _ART_VEC_LEN) or None
    art1_indices: Optional[np.ndarray],    # (batch,) or None
    art2_indices: Optional[np.ndarray],    # (batch,) or None
    weights: ScoringWeights,
    base_spd: int,
    min_spd: int,
    max_spd: int,
    base_cr: int,
    base_res: int,
    base_acc: int,
    set_options: List[Dict[int, int]],     # list of {set_id: required_pieces}
    min_stats: Dict[str, int],
    base_hp: int,
    base_atk: int,
    base_def: int,
    gpu_scorer: Optional["_GpuScorer"] = None,
) -> Tuple[np.ndarray, np.ndarray]:
    """Score a batch of rune+artifact combinations with full constraint checking.

    Returns (scores, valid_mask) both of shape (batch,).
    """
    batch = combo_indices.shape[0]
    # Sum stat vectors across 6 rune slots
    total_stats = np.zeros((batch, _N_STATS), dtype=np.float32)
    total_quality = np.zeros(batch, dtype=np.float32)
    total_efficiency = np.zeros(batch, dtype=np.float32)
    set_ids_per_slot = np.zeros((batch, 6), dtype=np.int32)

    slots = sorted(slot_matrices.keys())
    for col_idx, slot in enumerate(slots):
        mat = slot_matrices[slot]
        idx = combo_indices[:, col_idx]
        idx = np.clip(idx, 0, len(mat) - 1)
        selected = mat[idx]  # (batch, _VEC_LEN)
        total_stats += selected[:, :_N_STATS]
        total_quality += selected[:, _COL_QUALITY]
        total_efficiency += selected[:, _COL_EFFICIENCY]
        set_ids_per_slot[:, col_idx] = selected[:, _COL_SET_ID].astype(np.int32)

    # Add artifact quality/efficiency
    if art1_matrix is not None and art1_indices is not None and len(art1_matrix) > 0:
        a1_idx = np.clip(art1_indices, 0, len(art1_matrix) - 1)
        a1_sel = art1_matrix[a1_idx]
        total_quality += a1_sel[:, _ART_COL_QUALITY]
        total_efficiency += a1_sel[:, _ART_COL_EFFICIENCY]
    if art2_matrix is not None and art2_indices is not None and len(art2_matrix) > 0:
        a2_idx = np.clip(art2_indices, 0, len(art2_matrix) - 1)
        a2_sel = art2_matrix[a2_idx]
        total_quality += a2_sel[:, _ART_COL_QUALITY]
        total_efficiency += a2_sel[:, _ART_COL_EFFICIENCY]

    # ----- Set constraint validation -----
    # Count pieces per set_id for each combination
    # Build a set of all unique set_ids across all slots
    if set_options:
        # Vectorised set counting: for each required set_id, count how many
        # slots have that set_id
        sets_valid = np.zeros(batch, dtype=bool)
        for option in set_options:
            option_ok = np.ones(batch, dtype=bool)
            for sid, needed in option.items():
                count = np.sum(set_ids_per_slot == sid, axis=1)
                option_ok &= count >= needed
            sets_valid |= option_ok
    else:
        sets_valid = np.ones(batch, dtype=bool)

    # ----- Swift set bonus -----
    swift_count = np.sum(set_ids_per_slot == 3, axis=1)
    swift_active = (swift_count >= 4).astype(np.float32)
    swift_bonus = np.floor(float(base_spd) * 0.25) * swift_active

    # Final speed
    final_spd = float(base_spd) + total_stats[:, _COL_SPD] + swift_bonus

    # ----- Speed constraint -----
    valid = np.ones(batch, dtype=bool)
    valid &= sets_valid
    if min_spd > 0:
        valid &= final_spd >= float(min_spd)
    if max_spd > 0:
        valid &= final_spd <= float(max_spd)

    # ----- Min stat constraints -----
    _MIN_STAT_COL = {
        "SPD": None,  # handled via final_spd
        "CR": _COL_CR,
        "CD": _COL_CD,
        "RES": _COL_RES,
        "ACC": _COL_ACC,
        "HP%": _COL_HPP,
        "ATK%": _COL_ATKP,
        "DEF%": _COL_DEFP,
    }
    for stat_key, threshold in min_stats.items():
        if threshold <= 0:
            continue
        if stat_key == "SPD":
            valid &= final_spd >= float(threshold)
        elif stat_key == "SPD_NO_BASE":
            valid &= total_stats[:, _COL_SPD] + swift_bonus >= float(threshold)
        elif stat_key in _MIN_STAT_COL and _MIN_STAT_COL[stat_key] is not None:
            col = _MIN_STAT_COL[stat_key]
            base_val = 0.0
            if stat_key == "CR":
                base_val = float(base_cr)
            elif stat_key == "RES":
                base_val = float(base_res)
            elif stat_key == "ACC":
                base_val = float(base_acc)
            valid &= (base_val + total_stats[:, col]) >= float(threshold)

    # CR/RES/ACC overcap penalties
    cr_total = float(base_cr) + total_stats[:, _COL_CR]
    res_total = float(base_res) + total_stats[:, _COL_RES]
    acc_total = float(base_acc) + total_stats[:, _COL_ACC]
    cr_overcap = np.maximum(0.0, cr_total - 100.0)
    res_overcap = np.maximum(0.0, res_total - 100.0)
    acc_overcap = np.maximum(0.0, acc_total - 100.0)

    # ----- Scoring -----
    if gpu_scorer is not None and gpu_scorer.available:
        stat_score = gpu_scorer.score_batch(total_stats, weights)
    else:
        stat_score = total_stats @ weights.stat_weights

    # Set bonus: reward combos that complete full sets
    set_bonus = np.zeros(batch, dtype=np.float32)
    for sid, size in SET_SIZES.items():
        count = np.sum(set_ids_per_slot == sid, axis=1)
        completed_sets = count // size
        set_bonus += completed_sets.astype(np.float32) * float(size) * 10.0

    scores = (
        stat_score
        + weights.quality_weight * total_quality
        + weights.efficiency_weight * total_efficiency
        + weights.speed_priority * final_spd
        + weights.set_bonus_weight * set_bonus
        - 20.0 * cr_overcap
        - 16.0 * res_overcap
        - 16.0 * acc_overcap
    )

    return scores, valid


# ---------------------------------------------------------------------------
# Combination generation strategies
# ---------------------------------------------------------------------------
def _generate_random_combos(
    slot_sizes: Dict[int, int],
    n_art1: int,
    n_art2: int,
    batch_size: int,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Generate uniformly random slot-index + artifact combinations."""
    slots = sorted(slot_sizes.keys())
    combos = np.zeros((batch_size, 6), dtype=np.int32)
    for col, slot in enumerate(slots):
        combos[:, col] = rng.integers(0, max(1, slot_sizes[slot]), size=batch_size)
    a1 = rng.integers(0, max(1, n_art1), size=batch_size) if n_art1 > 0 else None
    a2 = rng.integers(0, max(1, n_art2), size=batch_size) if n_art2 > 0 else None
    return combos, a1, a2


def _generate_biased_combos(
    slot_matrices: Dict[int, np.ndarray],
    art1_matrix: Optional[np.ndarray],
    art2_matrix: Optional[np.ndarray],
    weights: ScoringWeights,
    batch_size: int,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Generate combinations biased towards top-scoring runes per slot."""
    slots = sorted(slot_matrices.keys())
    combos = np.zeros((batch_size, 6), dtype=np.int32)
    for col, slot in enumerate(slots):
        mat = slot_matrices[slot]
        n = len(mat)
        if n == 0:
            continue
        rune_scores = mat[:, :_N_STATS] @ weights.stat_weights
        rune_scores += weights.quality_weight * mat[:, _COL_QUALITY]
        rune_scores += weights.efficiency_weight * mat[:, _COL_EFFICIENCY]
        # Use temperature scaling: sharper distribution focuses on top runes
        temp = max(0.5, rune_scores.std() * 0.3 + 1e-6)
        rune_scores = rune_scores - rune_scores.max()
        probs = np.exp(rune_scores / temp)
        probs = probs / probs.sum()
        combos[:, col] = rng.choice(n, size=batch_size, p=probs)

    a1 = None
    if art1_matrix is not None and len(art1_matrix) > 0:
        n = len(art1_matrix)
        a_scores = art1_matrix[:, _ART_COL_QUALITY] + art1_matrix[:, _ART_COL_EFFICIENCY]
        a_scores = a_scores - a_scores.max()
        probs = np.exp(a_scores / max(1.0, a_scores.std() + 1e-6))
        probs = probs / probs.sum()
        a1 = rng.choice(n, size=batch_size, p=probs)

    a2 = None
    if art2_matrix is not None and len(art2_matrix) > 0:
        n = len(art2_matrix)
        a_scores = art2_matrix[:, _ART_COL_QUALITY] + art2_matrix[:, _ART_COL_EFFICIENCY]
        a_scores = a_scores - a_scores.max()
        probs = np.exp(a_scores / max(1.0, a_scores.std() + 1e-6))
        probs = probs / probs.sum()
        a2 = rng.choice(n, size=batch_size, p=probs)

    return combos, a1, a2


def _generate_set_aware_combos(
    slot_matrices: Dict[int, np.ndarray],
    set_options: List[Dict[int, int]],
    n_art1: int,
    n_art2: int,
    batch_size: int,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Generate combinations biased towards fulfilling set requirements (vectorised)."""
    slots = sorted(slot_matrices.keys())
    combos = np.zeros((batch_size, 6), dtype=np.int32)

    if not set_options:
        for col, slot in enumerate(slots):
            n = len(slot_matrices[slot])
            combos[:, col] = rng.integers(0, max(1, n), size=batch_size)
    else:
        # Pick target set_id for each combo (the one with highest required count)
        target_sids = []
        for opt in set_options:
            target_sids.append(max(opt.keys(), key=lambda s: opt[s]))
        opt_indices = rng.integers(0, len(set_options), size=batch_size)
        target_per_combo = np.array(target_sids, dtype=np.int32)[opt_indices]  # (batch,)

        for col, slot in enumerate(slots):
            mat = slot_matrices[slot]
            n = len(mat)
            if n == 0:
                continue
            set_ids = mat[:, _COL_SET_ID].astype(np.int32)

            # Build index lookup: for each set_id, the indices of matching runes
            unique_sids = np.unique(target_per_combo)
            # Start with random indices as baseline
            combos[:, col] = rng.integers(0, n, size=batch_size)
            # Override with matching runes where possible
            for sid in unique_sids:
                matching = np.where(set_ids == sid)[0]
                if len(matching) == 0:
                    continue
                mask = target_per_combo == sid
                count = int(np.sum(mask))
                if count > 0:
                    combos[mask, col] = rng.choice(matching, size=count)

    a1 = rng.integers(0, max(1, n_art1), size=batch_size) if n_art1 > 0 else None
    a2 = rng.integers(0, max(1, n_art2), size=batch_size) if n_art2 > 0 else None
    return combos, a1, a2


def _generate_elite_mutations(
    elite_combos: np.ndarray,
    elite_art1: Optional[np.ndarray],
    elite_art2: Optional[np.ndarray],
    slot_sizes: Dict[int, int],
    n_art1: int,
    n_art2: int,
    batch_size: int,
    rng: np.random.Generator,
    mutation_rate: float = 0.25,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Mutate elite combinations by randomly replacing some slots."""
    if len(elite_combos) == 0:
        return _generate_random_combos(slot_sizes, n_art1, n_art2, batch_size, rng)
    slots = sorted(slot_sizes.keys())
    parent_idx = rng.integers(0, len(elite_combos), size=batch_size)
    combos = elite_combos[parent_idx].copy()
    mask = rng.random((batch_size, 6)) < mutation_rate
    for col, slot in enumerate(slots):
        n = slot_sizes[slot]
        if n > 0:
            new_vals = rng.integers(0, n, size=batch_size)
            combos[:, col] = np.where(mask[:, col], new_vals, combos[:, col])

    a1 = None
    if n_art1 > 0:
        if elite_art1 is not None and len(elite_art1) > 0:
            a1 = elite_art1[parent_idx].copy()
            amask = rng.random(batch_size) < mutation_rate
            a1 = np.where(amask, rng.integers(0, n_art1, size=batch_size), a1)
        else:
            a1 = rng.integers(0, n_art1, size=batch_size)
    a2 = None
    if n_art2 > 0:
        if elite_art2 is not None and len(elite_art2) > 0:
            a2 = elite_art2[parent_idx].copy()
            amask = rng.random(batch_size) < mutation_rate
            a2 = np.where(amask, rng.integers(0, n_art2, size=batch_size), a2)
        else:
            a2 = rng.integers(0, n_art2, size=batch_size)

    return combos, a1, a2


def _generate_greedy_seed_combos(
    slot_matrices: Dict[int, np.ndarray],
    set_options: List[Dict[int, int]],
    n_art1: int,
    n_art2: int,
    batch_size: int,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Generate combos by greedily picking top runes per slot, then mutating.

    Creates seed combos where each one picks from the top-N runes per slot
    (ranked by speed contribution), ensuring diversity via random offset.
    """
    slots = sorted(slot_matrices.keys())
    combos = np.zeros((batch_size, 6), dtype=np.int32)

    for col, slot in enumerate(slots):
        mat = slot_matrices[slot]
        n = len(mat)
        if n == 0:
            continue
        # Rank runes by efficiency (primary signal) + quality
        eff_vals = mat[:, _COL_EFFICIENCY]
        qual_vals = mat[:, _COL_QUALITY]
        rank_score = eff_vals * 3.0 + qual_vals
        ranked_idx = np.argsort(rank_score)[::-1]
        # Pick from top-K with geometric distribution (heavily biased towards top)
        top_k = min(n, max(20, n // 5))
        # Geometric-like: higher probability for better ranks
        probs = np.zeros(n, dtype=np.float32)
        decay = np.exp(-np.arange(top_k, dtype=np.float32) * 3.0 / top_k)
        probs[ranked_idx[:top_k]] = decay
        probs = probs / probs.sum()
        combos[:, col] = rng.choice(n, size=batch_size, p=probs)

    a1 = rng.integers(0, max(1, n_art1), size=batch_size) if n_art1 > 0 else None
    a2 = rng.integers(0, max(1, n_art2), size=batch_size) if n_art2 > 0 else None
    return combos, a1, a2


def _generate_crossover(
    elite_combos: np.ndarray,
    elite_art1: Optional[np.ndarray],
    elite_art2: Optional[np.ndarray],
    slot_sizes: Dict[int, int],
    n_art1: int,
    n_art2: int,
    batch_size: int,
    rng: np.random.Generator,
) -> Tuple[np.ndarray, Optional[np.ndarray], Optional[np.ndarray]]:
    """Create children by crossing two elite parents."""
    if len(elite_combos) < 2:
        return _generate_random_combos(slot_sizes, n_art1, n_art2, batch_size, rng)
    p1 = rng.integers(0, len(elite_combos), size=batch_size)
    p2 = rng.integers(0, len(elite_combos), size=batch_size)
    mask = rng.random((batch_size, 6)) < 0.5
    combos = np.where(mask, elite_combos[p1], elite_combos[p2])

    a1 = None
    if n_art1 > 0 and elite_art1 is not None and len(elite_art1) > 0:
        a1 = np.where(rng.random(batch_size) < 0.5, elite_art1[p1], elite_art1[p2])
    elif n_art1 > 0:
        a1 = rng.integers(0, n_art1, size=batch_size)
    a2 = None
    if n_art2 > 0 and elite_art2 is not None and len(elite_art2) > 0:
        a2 = np.where(rng.random(batch_size) < 0.5, elite_art2[p1], elite_art2[p2])
    elif n_art2 > 0:
        a2 = rng.integers(0, n_art2, size=batch_size)

    return combos, a1, a2


# ---------------------------------------------------------------------------
# Per-unit GPU-native search
# ---------------------------------------------------------------------------
def _search_unit_combos_full(
    pool: List[Rune],
    artifact_pool: List[Artifact],
    base_spd: int,
    min_spd: int,
    max_spd: int,
    base_cr: int,
    base_res: int,
    base_acc: int,
    base_hp: int,
    base_atk: int,
    base_def: int,
    weights: ScoringWeights,
    constraints: Dict[str, Any],
    batch_size: int,
    n_cycles: int,
    rng: np.random.Generator,
    gpu_scorer: Optional["_GpuScorer"] = None,
) -> Tuple[Optional[Dict[int, int]], Optional[Dict[int, int]], float]:
    """Find the best rune+artifact combination for one unit.

    Returns (runes_by_slot, artifacts_by_type, best_score).
    runes_by_slot: {slot: rune_id}
    artifacts_by_type: {1: artifact_id, 2: artifact_id} or None
    """
    # Build per-slot rune lists
    runes_by_slot: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= r.slot_no <= 6:
            runes_by_slot[r.slot_no].append(r)

    # Pre-filter by mainstat on slots 2/4/6
    allowed_mainstats = constraints.get("allowed_mainstats", {})
    runes_by_slot = _filter_runes_by_mainstat(runes_by_slot, allowed_mainstats)

    # Encode runes
    slot_matrices: Dict[int, np.ndarray] = {}
    slot_rune_ids: Dict[int, List[int]] = {}
    slot_sizes: Dict[int, int] = {}
    for slot in range(1, 7):
        runes = runes_by_slot[slot]
        if not runes:
            return None, None, -1e9  # infeasible
        mat = _encode_runes(runes)
        slot_matrices[slot] = mat
        slot_rune_ids[slot] = [r.rune_id for r in runes]
        slot_sizes[slot] = len(runes)

    # Encode artifacts
    art1_list = [a for a in artifact_pool if int(a.type_ or 0) == 1]
    art2_list = [a for a in artifact_pool if int(a.type_ or 0) == 2]
    art1_matrix = _encode_artifacts(art1_list) if art1_list else None
    art2_matrix = _encode_artifacts(art2_list) if art2_list else None
    art1_ids = [a.artifact_id for a in art1_list]
    art2_ids = [a.artifact_id for a in art2_list]
    n_art1 = len(art1_list)
    n_art2 = len(art2_list)

    set_options = constraints.get("set_options", [])
    min_stats_map = constraints.get("min_stats", {})

    # Evolutionary search
    elite_combos: Optional[np.ndarray] = None
    elite_art1: Optional[np.ndarray] = None
    elite_art2: Optional[np.ndarray] = None
    elite_scores: Optional[np.ndarray] = None
    elite_size = _ELITE_SIZE

    for cycle in range(n_cycles):
        # Divide batch across strategies
        if cycle == 0:
            # First cycle: heavier on random + set-aware
            n_random = batch_size // 3
            n_biased = batch_size // 3
            n_set_aware = batch_size - 2 * n_random
            parts_rune = []
            parts_a1 = []
            parts_a2 = []

            c, a1, a2 = _generate_random_combos(slot_sizes, n_art1, n_art2, n_random, rng)
            parts_rune.append(c)
            parts_a1.append(a1)
            parts_a2.append(a2)

            c, a1, a2 = _generate_biased_combos(slot_matrices, art1_matrix, art2_matrix, weights, n_biased, rng)
            parts_rune.append(c)
            parts_a1.append(a1)
            parts_a2.append(a2)

            if set_options:
                c, a1, a2 = _generate_set_aware_combos(slot_matrices, set_options, n_art1, n_art2, n_set_aware, rng)
            else:
                c, a1, a2 = _generate_random_combos(slot_sizes, n_art1, n_art2, n_set_aware, rng)
            parts_rune.append(c)
            parts_a1.append(a1)
            parts_a2.append(a2)
        else:
            # Later cycles: mutations + crossover + some fresh random
            n_mut = batch_size // 3
            n_cross = batch_size // 3
            n_fresh = batch_size - 2 * n_mut
            parts_rune = []
            parts_a1 = []
            parts_a2 = []

            if elite_combos is not None:
                c, a1, a2 = _generate_elite_mutations(
                    elite_combos, elite_art1, elite_art2,
                    slot_sizes, n_art1, n_art2, n_mut, rng,
                    mutation_rate=max(0.1, 0.3 - cycle * 0.02),
                )
            else:
                c, a1, a2 = _generate_random_combos(slot_sizes, n_art1, n_art2, n_mut, rng)
            parts_rune.append(c)
            parts_a1.append(a1)
            parts_a2.append(a2)

            if elite_combos is not None and len(elite_combos) >= 2:
                c, a1, a2 = _generate_crossover(
                    elite_combos, elite_art1, elite_art2,
                    slot_sizes, n_art1, n_art2, n_cross, rng,
                )
            else:
                c, a1, a2 = _generate_biased_combos(slot_matrices, art1_matrix, art2_matrix, weights, n_cross, rng)
            parts_rune.append(c)
            parts_a1.append(a1)
            parts_a2.append(a2)

            c, a1, a2 = _generate_random_combos(slot_sizes, n_art1, n_art2, n_fresh, rng)
            parts_rune.append(c)
            parts_a1.append(a1)
            parts_a2.append(a2)

        combos = np.concatenate(parts_rune, axis=0)
        if n_art1 > 0:
            c_a1 = np.concatenate([x for x in parts_a1 if x is not None], axis=0)
        else:
            c_a1 = None
        if n_art2 > 0:
            c_a2 = np.concatenate([x for x in parts_a2 if x is not None], axis=0)
        else:
            c_a2 = None

        scores, valid = _score_combinations_full(
            slot_matrices, combos,
            art1_matrix, art2_matrix,
            c_a1, c_a2,
            weights,
            base_spd, min_spd, max_spd,
            base_cr, base_res, base_acc,
            set_options, min_stats_map,
            base_hp, base_atk, base_def,
            gpu_scorer=gpu_scorer,
        )

        # Penalise invalid heavily but don't discard (might relax later)
        scores = np.where(valid, scores, scores - 1e6)

        # Merge with existing elite
        if elite_combos is not None:
            combos = np.concatenate([elite_combos, combos], axis=0)
            scores = np.concatenate([elite_scores, scores], axis=0)
            if c_a1 is not None and elite_art1 is not None:
                c_a1 = np.concatenate([elite_art1, c_a1], axis=0)
            if c_a2 is not None and elite_art2 is not None:
                c_a2 = np.concatenate([elite_art2, c_a2], axis=0)

        # Select top-K
        if len(scores) > elite_size:
            top_idx = np.argpartition(scores, -elite_size)[-elite_size:]
            top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
        else:
            top_idx = np.argsort(scores)[::-1]
        elite_combos = combos[top_idx]
        elite_scores = scores[top_idx]
        if c_a1 is not None:
            elite_art1 = c_a1[top_idx]
        if c_a2 is not None:
            elite_art2 = c_a2[top_idx]

    if elite_combos is None or len(elite_combos) == 0:
        return None, None, -1e9

    # Return the best combination
    best_combo = elite_combos[0]
    best_score = float(elite_scores[0])

    # Reject if best is heavily penalised (no valid combo found)
    if best_score < -1e5:
        return None, None, best_score

    rune_map: Dict[int, int] = {}
    for col, slot in enumerate(sorted(slot_rune_ids.keys())):
        idx = int(best_combo[col])
        rune_map[slot] = slot_rune_ids[slot][idx]

    art_map: Dict[int, int] = {}
    if elite_art1 is not None and n_art1 > 0:
        a1_idx = int(elite_art1[0])
        art_map[1] = art1_ids[a1_idx]
    if elite_art2 is not None and n_art2 > 0:
        a2_idx = int(elite_art2[0])
        art_map[2] = art2_ids[a2_idx]

    return rune_map, art_map, best_score


# ---------------------------------------------------------------------------
# History tracking for online learning
# ---------------------------------------------------------------------------
def _append_history(entry: Dict[str, Any]) -> None:
    _LEARN_DIR.mkdir(parents=True, exist_ok=True)
    with open(_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _load_history(max_entries: int = 400) -> List[Dict[str, Any]]:
    if not _HISTORY_PATH.exists():
        return []
    entries: List[Dict[str, Any]] = []
    try:
        with open(_HISTORY_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception:
        return []
    return entries[-max_entries:]


def _history_for_context(context_key: str, max_entries: int = 240) -> List[Dict[str, Any]]:
    key = str(context_key or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for h in _load_history(max_entries=max_entries * 2):
        ctx = str((h or {}).get("context_key", "") or "").strip().lower()
        if key and ctx == key:
            out.append(dict(h or {}))
    return out[-max_entries:]


def _float_or(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _int_or(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


@dataclass
class _GpuComboAdaptivePlan:
    batch_size: int
    time_budget_s: float
    pass_time_s: float
    pass_limit: int
    solver_top_per_set: int
    extra_rune_cap: int
    early_stop_patience: int
    min_passes: int
    history_run_count: int


def _clamp_int(value: int, lo: int, hi: int) -> int:
    return max(int(lo), min(int(hi), int(value)))


def _run_history_rows_for_adaptation(context_history: List[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in list(context_history or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("kind", "run") or "run").strip().lower() != "run":
            continue
        rows.append(dict(row))
    return rows[-int(_ADAPTIVE_HISTORY_WINDOW):]


def _adaptive_plan_for_run(
    req: GreedyRequest,
    unit_ids: List[int],
    has_gpu: bool,
    context_history: List[Dict[str, Any]] | None,
) -> _GpuComboAdaptivePlan:
    unit_count = max(1, len([int(u) for u in list(unit_ids or []) if int(u) > 0]))
    base_batch = int(_GPU_BATCH_SIZE if has_gpu else _CPU_BATCH_SIZE)
    base_batch = max(1, int(base_batch // max(1, unit_count // 3)))
    min_batch = int(_ADAPTIVE_MIN_BATCH_GPU if has_gpu else _ADAPTIVE_MIN_BATCH_CPU)
    max_batch = int(_ADAPTIVE_MAX_BATCH_GPU if has_gpu else _ADAPTIVE_MAX_BATCH_CPU)
    batch_size = _clamp_int(base_batch, min_batch, max_batch)

    req_time = max(0.4, float(getattr(req, "time_limit_per_unit_s", 1.0) or 1.0))
    time_budget_s = float(req_time * unit_count * 4.0)
    pass_limit = int(min(8, max(3, unit_count)))
    pass_time_s = float(max(0.5, req_time * 0.7))
    solver_top_per_set = int(max(_ADAPTIVE_MIN_SOLVER_TOP, int(_ADAPTIVE_DEFAULT_SOLVER_TOP)))
    req_top = int(getattr(req, "rune_top_per_set", 0) or 0)
    if req_top > 0:
        solver_top_per_set = int(_clamp_int(req_top, _ADAPTIVE_MIN_SOLVER_TOP, _ADAPTIVE_MAX_SOLVER_TOP))

    extra_rune_cap = int(max(900, unit_count * 320))
    early_stop_patience = 2
    min_passes = int(max(2, min(3, pass_limit)))

    runs = _run_history_rows_for_adaptation(context_history)
    if not runs:
        return _GpuComboAdaptivePlan(
            batch_size=int(batch_size),
            time_budget_s=float(time_budget_s),
            pass_time_s=float(pass_time_s),
            pass_limit=int(pass_limit),
            solver_top_per_set=int(solver_top_per_set),
            extra_rune_cap=int(extra_rune_cap),
            early_stop_patience=int(early_stop_patience),
            min_passes=int(min_passes),
            history_run_count=0,
        )

    total_s_vals = [
        max(0.0, float(_float_or((row or {}).get("total_ms"), 0.0)) / 1000.0)
        for row in runs
        if _float_or((row or {}).get("total_ms"), 0.0) > 0.0
    ]
    phase1_s_vals = [
        max(0.0, float(_float_or((row or {}).get("phase1_ms"), 0.0)) / 1000.0)
        for row in runs
        if _float_or((row or {}).get("phase1_ms"), 0.0) > 0.0
    ]
    ok_ratio_vals = [
        _float_or((row or {}).get("kpis", {}).get("ok_ratio"), 0.0)
        for row in runs
        if isinstance((row or {}).get("kpis"), dict)
    ]
    gpu_runes_found_vals = [
        max(0, int(_int_or((row or {}).get("gpu_runes_found"), 0)))
        for row in runs
        if _int_or((row or {}).get("gpu_runes_found"), 0) > 0
    ]

    med_total_s = float(statistics.median(total_s_vals)) if total_s_vals else 0.0
    med_phase1_s = float(statistics.median(phase1_s_vals)) if phase1_s_vals else 0.0
    med_ok_ratio = float(statistics.median(ok_ratio_vals)) if ok_ratio_vals else 0.0
    med_gpu_runes = float(statistics.median(gpu_runes_found_vals)) if gpu_runes_found_vals else 0.0

    runtime_ratio = float(med_total_s / max(1e-6, time_budget_s)) if med_total_s > 0.0 else 0.0
    phase1_ratio = float(med_phase1_s / max(1e-6, med_total_s)) if med_total_s > 0.0 else 0.0

    batch_scale = 1.0
    if runtime_ratio > 1.25:
        batch_scale *= 0.70
        pass_limit = max(3, int(pass_limit - 2))
        pass_time_s = max(0.5, float(pass_time_s * 0.85))
        solver_top_per_set = max(_ADAPTIVE_MIN_SOLVER_TOP, int(solver_top_per_set - 20))
        extra_rune_cap = int(extra_rune_cap * 0.75)
    elif runtime_ratio > 0.95:
        batch_scale *= 0.85
        pass_limit = max(3, int(pass_limit - 1))
        pass_time_s = max(0.5, float(pass_time_s * 0.9))
        solver_top_per_set = max(_ADAPTIVE_MIN_SOLVER_TOP, int(solver_top_per_set - 10))
    elif runtime_ratio < 0.55 and med_ok_ratio >= 0.92:
        batch_scale *= 1.12
        if med_ok_ratio < 0.985:
            pass_limit = min(10, int(pass_limit + 1))

    if med_ok_ratio < 0.80:
        batch_scale *= 1.12
        pass_limit = min(10, int(pass_limit + 1))
        pass_time_s = max(0.5, float(pass_time_s * 1.10))
        solver_top_per_set = min(_ADAPTIVE_MAX_SOLVER_TOP, int(solver_top_per_set + 20))
        extra_rune_cap = int(extra_rune_cap * 1.20)
        early_stop_patience = 3
    elif med_ok_ratio >= 0.98:
        early_stop_patience = 1

    if phase1_ratio > 0.62 and runtime_ratio > 0.9:
        batch_scale *= 0.88
    if med_gpu_runes > float(extra_rune_cap * 1.5):
        extra_rune_cap = int(max(600, extra_rune_cap * 0.85))

    batch_size = _clamp_int(int(round(batch_size * batch_scale)), min_batch, max_batch)
    solver_top_per_set = _clamp_int(int(solver_top_per_set), _ADAPTIVE_MIN_SOLVER_TOP, _ADAPTIVE_MAX_SOLVER_TOP)
    pass_limit = _clamp_int(int(pass_limit), 3, 10)
    min_passes = _clamp_int(
        int(max(2, min(min_passes, pass_limit - int(max(0, early_stop_patience - 1))))),
        2,
        pass_limit,
    )
    extra_rune_cap = _clamp_int(int(extra_rune_cap), 500, 5000)

    return _GpuComboAdaptivePlan(
        batch_size=int(batch_size),
        time_budget_s=float(time_budget_s),
        pass_time_s=float(max(0.5, pass_time_s)),
        pass_limit=int(pass_limit),
        solver_top_per_set=int(solver_top_per_set),
        extra_rune_cap=int(extra_rune_cap),
        early_stop_patience=int(_clamp_int(early_stop_patience, 1, 4)),
        min_passes=int(min_passes),
        history_run_count=int(len(runs)),
    )


def _cap_extra_gpu_runes(extra_runes: List[Rune], limit: int) -> List[Rune]:
    cap = int(limit or 0)
    if cap <= 0 or len(extra_runes) <= cap:
        return list(extra_runes or [])
    ranked = sorted(
        list(extra_runes or []),
        key=lambda r: (
            float(rune_efficiency(r)),
            float(_rune_quality_score(r, 0, None)),
            float(_rune_flat_spd(r)),
        ),
        reverse=True,
    )
    return ranked[:cap]


def _result_kpis(account: AccountData, results: List[GreedyUnitResult]) -> Dict[str, float]:
    runes_by_id = account.runes_by_id()
    artifacts_by_id: Dict[int, Artifact] = {
        int(a.artifact_id): a for a in list(account.artifacts or [])
    }
    ok_rows = [r for r in (results or []) if bool(getattr(r, "ok", False))]
    total_units = int(len(results or []))
    ok_units = int(len(ok_rows))
    ok_ratio = float(ok_units / max(1, total_units))
    speeds = [int(getattr(r, "final_speed", 0) or 0) for r in ok_rows]

    rune_eff: List[float] = []
    art_eff: List[float] = []
    for row in ok_rows:
        for rid in dict(getattr(row, "runes_by_slot", {}) or {}).values():
            rr = runes_by_id.get(int(rid or 0))
            if rr is not None:
                rune_eff.append(float(rune_efficiency(rr)))
        for aid in dict(getattr(row, "artifacts_by_type", {}) or {}).values():
            aa = artifacts_by_id.get(int(aid or 0))
            if aa is not None:
                art_eff.append(float(artifact_efficiency(aa)))

    speed_sum = int(sum(speeds))
    speed_mean = float(statistics.fmean(speeds)) if speeds else 0.0
    rune_eff_mean = float(statistics.fmean(rune_eff)) if rune_eff else 0.0
    rune_eff_median = float(statistics.median(rune_eff)) if rune_eff else 0.0
    art_eff_mean = float(statistics.fmean(art_eff)) if art_eff else 0.0
    art_eff_median = float(statistics.median(art_eff)) if art_eff else 0.0
    return {
        "ok_units": float(ok_units),
        "total_units": float(total_units),
        "ok_ratio": float(ok_ratio),
        "speed_sum": float(speed_sum),
        "speed_mean": float(speed_mean),
        "rune_eff_mean": float(rune_eff_mean),
        "rune_eff_median": float(rune_eff_median),
        "artifact_eff_mean": float(art_eff_mean),
        "artifact_eff_median": float(art_eff_median),
    }


def _learning_objective_from_kpis(kpis: Dict[str, Any]) -> float:
    ok_ratio = _float_or((kpis or {}).get("ok_ratio"), 0.0)
    rune_eff = _float_or((kpis or {}).get("rune_eff_mean"), 0.0)
    art_eff = _float_or((kpis or {}).get("artifact_eff_mean"), 0.0)
    speed_mean = _float_or((kpis or {}).get("speed_mean"), 0.0)
    return (
        (ok_ratio * 1_000_000.0)
        + (rune_eff * 2_000.0)
        + (art_eff * 700.0)
        + (speed_mean * 5.0)
    )


def _kpis_safe_enough(
    baseline_kpis: Dict[str, Any],
    candidate_kpis: Dict[str, Any],
) -> bool:
    base_ok = _float_or((baseline_kpis or {}).get("ok_ratio"), 0.0)
    cand_ok = _float_or((candidate_kpis or {}).get("ok_ratio"), 0.0)
    if cand_ok + 1e-9 < (base_ok - float(_AB_MAX_OK_RATIO_DROP)):
        return False
    base_rune_eff = _float_or((baseline_kpis or {}).get("rune_eff_mean"), 0.0)
    cand_rune_eff = _float_or((candidate_kpis or {}).get("rune_eff_mean"), 0.0)
    if cand_rune_eff + 1e-9 < (base_rune_eff - float(_AB_MAX_RUNE_EFF_DROP)):
        return False
    return True


def _jsonify(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(v) for v in value]
    if isinstance(value, np.generic):
        try:
            return value.item()
        except Exception:
            return str(value)
    if isinstance(value, (int, float, str, bool)) or value is None:
        return value
    return str(value)


def _int_key_dict(raw: Any) -> Dict[int, Any]:
    out: Dict[int, Any] = {}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        try:
            ki = int(k)
        except Exception:
            continue
        out[int(ki)] = v
    return out


def _int_int_dict(raw: Any) -> Dict[int, int]:
    out: Dict[int, int] = {}
    for k, v in _int_key_dict(raw).items():
        vi = int(_int_or(v, 0))
        if vi != 0:
            out[int(k)] = int(vi)
    return out


def _int_nested_dict(raw: Any) -> Dict[int, Dict[int, int]]:
    out: Dict[int, Dict[int, int]] = {}
    for k, v in _int_key_dict(raw).items():
        nested = _int_int_dict(v)
        if nested:
            out[int(k)] = nested
    return out


def _hint_map_from_raw(raw: Any) -> Dict[int, Dict[str, Any]]:
    out: Dict[int, Dict[str, Any]] = {}
    if not isinstance(raw, dict):
        return out
    for uid_raw, hint_raw in raw.items():
        try:
            uid = int(uid_raw)
        except Exception:
            continue
        if not isinstance(hint_raw, dict):
            continue
        hint_obj: Dict[str, Any] = {}
        for k, v in hint_raw.items():
            key = str(k or "")
            if isinstance(v, list):
                vals: List[Any] = []
                for x in v:
                    try:
                        vals.append(int(x))
                    except Exception:
                        vals.append(x)
                hint_obj[key] = vals
            else:
                hint_obj[key] = v
        out[int(uid)] = hint_obj
    return out


def _build_replay_payload(req: GreedyRequest) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mode": str(req.mode or ""),
        "unit_ids_in_order": [int(x) for x in list(req.unit_ids_in_order or []) if int(x) > 0],
        "time_limit_per_unit_s": float(getattr(req, "time_limit_per_unit_s", 1.0) or 1.0),
        "workers": int(getattr(req, "workers", 1) or 1),
        "multi_pass_enabled": bool(getattr(req, "multi_pass_enabled", True)),
        "multi_pass_count": int(getattr(req, "multi_pass_count", 1) or 1),
        "multi_pass_strategy": str(getattr(req, "multi_pass_strategy", "greedy_refine") or "greedy_refine"),
        "rune_top_per_set": int(getattr(req, "rune_top_per_set", 0) or 0),
        "speed_slack_for_quality": int(getattr(req, "speed_slack_for_quality", 1) or 1),
        "enforce_turn_order": bool(getattr(req, "enforce_turn_order", False)),
        "arena_rush_context": str(getattr(req, "arena_rush_context", "") or ""),
        "baseline_regression_guard_weight": int(
            getattr(req, "baseline_regression_guard_weight", 0) or 0
        ),
        "unit_team_index": _jsonify(dict(getattr(req, "unit_team_index", {}) or {})),
        "unit_team_turn_order": _jsonify(dict(getattr(req, "unit_team_turn_order", {}) or {})),
        "unit_spd_leader_bonus_flat": _jsonify(dict(getattr(req, "unit_spd_leader_bonus_flat", {}) or {})),
        "unit_archetype_by_uid": _jsonify(dict(getattr(req, "unit_archetype_by_uid", {}) or {})),
        "unit_artifact_hints_by_uid": _jsonify(dict(getattr(req, "unit_artifact_hints_by_uid", {}) or {})),
        "unit_team_has_spd_buff_by_uid": _jsonify(dict(getattr(req, "unit_team_has_spd_buff_by_uid", {}) or {})),
        "unit_min_final_speed": _jsonify(dict(getattr(req, "unit_min_final_speed", {}) or {})),
        "unit_max_final_speed": _jsonify(dict(getattr(req, "unit_max_final_speed", {}) or {})),
        "unit_speed_tiebreak_weight": _jsonify(dict(getattr(req, "unit_speed_tiebreak_weight", {}) or {})),
        "unit_fixed_runes_by_slot": _jsonify(dict(getattr(req, "unit_fixed_runes_by_slot", {}) or {})),
        "unit_fixed_artifacts_by_type": _jsonify(dict(getattr(req, "unit_fixed_artifacts_by_type", {}) or {})),
        "unit_baseline_runes_by_slot": _jsonify(dict(getattr(req, "unit_baseline_runes_by_slot", {}) or {})),
        "unit_baseline_artifacts_by_type": _jsonify(dict(getattr(req, "unit_baseline_artifacts_by_type", {}) or {})),
        "excluded_rune_ids": _jsonify(sorted(int(x) for x in (getattr(req, "excluded_rune_ids", None) or set()))),
        "excluded_artifact_ids": _jsonify(sorted(int(x) for x in (getattr(req, "excluded_artifact_ids", None) or set()))),
    }
    return payload


def _replay_payload_hash(payload: Dict[str, Any]) -> str:
    src = json.dumps(_jsonify(payload), ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(src.encode("utf-8", errors="replace")).hexdigest()[:16]


def _request_from_replay_payload(payload: Dict[str, Any]) -> GreedyRequest | None:
    if not isinstance(payload, dict):
        return None
    unit_ids = [int(_int_or(x, 0)) for x in list(payload.get("unit_ids_in_order") or [])]
    unit_ids = [int(x) for x in unit_ids if int(x) > 0]
    if not unit_ids:
        return None
    return GreedyRequest(
        mode=str(payload.get("mode", "") or ""),
        unit_ids_in_order=list(unit_ids),
        time_limit_per_unit_s=float(_float_or(payload.get("time_limit_per_unit_s"), 1.0)),
        workers=max(1, int(_int_or(payload.get("workers"), 1))),
        multi_pass_enabled=bool(payload.get("multi_pass_enabled", True)),
        multi_pass_count=max(1, int(_int_or(payload.get("multi_pass_count"), 1))),
        multi_pass_strategy=str(payload.get("multi_pass_strategy", "greedy_refine") or "greedy_refine"),
        rune_top_per_set=max(0, int(_int_or(payload.get("rune_top_per_set"), 0))),
        quality_profile="gpu_combo",
        speed_slack_for_quality=max(0, int(_int_or(payload.get("speed_slack_for_quality"), 1))),
        enforce_turn_order=bool(payload.get("enforce_turn_order", False)),
        arena_rush_context=str(payload.get("arena_rush_context", "") or ""),
        baseline_regression_guard_weight=max(
            0, int(_int_or(payload.get("baseline_regression_guard_weight"), 0))
        ),
        unit_team_index=_int_int_dict(payload.get("unit_team_index")),
        unit_team_turn_order=_int_int_dict(payload.get("unit_team_turn_order")),
        unit_spd_leader_bonus_flat=_int_int_dict(payload.get("unit_spd_leader_bonus_flat")),
        unit_archetype_by_uid={
            int(k): str(v or "")
            for k, v in _int_key_dict(payload.get("unit_archetype_by_uid")).items()
        },
        unit_artifact_hints_by_uid=_hint_map_from_raw(payload.get("unit_artifact_hints_by_uid")),
        unit_team_has_spd_buff_by_uid={
            int(k): bool(v) for k, v in _int_key_dict(payload.get("unit_team_has_spd_buff_by_uid")).items()
        },
        unit_min_final_speed=_int_int_dict(payload.get("unit_min_final_speed")),
        unit_max_final_speed=_int_int_dict(payload.get("unit_max_final_speed")),
        unit_speed_tiebreak_weight=_int_int_dict(payload.get("unit_speed_tiebreak_weight")),
        unit_fixed_runes_by_slot=_int_nested_dict(payload.get("unit_fixed_runes_by_slot")),
        unit_fixed_artifacts_by_type=_int_nested_dict(payload.get("unit_fixed_artifacts_by_type")),
        unit_baseline_runes_by_slot=_int_nested_dict(payload.get("unit_baseline_runes_by_slot")),
        unit_baseline_artifacts_by_type=_int_nested_dict(payload.get("unit_baseline_artifacts_by_type")),
        excluded_rune_ids={
            int(_int_or(x, 0))
            for x in list(payload.get("excluded_rune_ids") or [])
            if int(_int_or(x, 0)) > 0
        } or None,
        excluded_artifact_ids={
            int(_int_or(x, 0))
            for x in list(payload.get("excluded_artifact_ids") or [])
            if int(_int_or(x, 0)) > 0
        } or None,
    )


def _weights_to_vector(w: ScoringWeights) -> np.ndarray:
    """Flatten ScoringWeights into a 1-D vector for BO (15 dims)."""
    return np.concatenate([
        w.stat_weights.astype(np.float64),  # 11 dims
        np.array([w.quality_weight, w.efficiency_weight,
                  w.set_bonus_weight, w.speed_priority], dtype=np.float64),
    ])


def _vector_to_weights(v: np.ndarray) -> ScoringWeights:
    """Reconstruct ScoringWeights from a 1-D vector."""
    return ScoringWeights(
        stat_weights=np.maximum(0.0, v[:_N_STATS]).astype(np.float32),
        quality_weight=max(0.0, float(v[_N_STATS])),
        efficiency_weight=max(0.0, float(v[_N_STATS + 1])),
        set_bonus_weight=max(0.0, float(v[_N_STATS + 2])),
        speed_priority=max(0.0, float(v[_N_STATS + 3])),
    )


def _blend_scoring_weights(
    local_weights: ScoringWeights,
    cloud_weights: ScoringWeights,
    alpha: float,
) -> ScoringWeights:
    mix = max(0.0, min(float(_CLOUD_ALPHA_MAX), float(alpha)))
    local_mix = max(0.0, 1.0 - mix)
    stat = (
        local_weights.stat_weights.astype(np.float64) * local_mix
        + cloud_weights.stat_weights.astype(np.float64) * mix
    )
    return ScoringWeights(
        stat_weights=np.maximum(0.0, stat).astype(np.float32),
        quality_weight=max(0.0, (local_weights.quality_weight * local_mix) + (cloud_weights.quality_weight * mix)),
        efficiency_weight=max(
            0.0, (local_weights.efficiency_weight * local_mix) + (cloud_weights.efficiency_weight * mix)
        ),
        set_bonus_weight=max(
            0.0, (local_weights.set_bonus_weight * local_mix) + (cloud_weights.set_bonus_weight * mix)
        ),
        speed_priority=max(0.0, (local_weights.speed_priority * local_mix) + (cloud_weights.speed_priority * mix)),
    )


_BO_NDIM = _N_STATS + 4  # 15 weight dimensions


def _rbf_kernel(X: np.ndarray, Y: np.ndarray, length_scale: float,
                signal_var: float) -> np.ndarray:
    """RBF (squared exponential) kernel matrix between X and Y."""
    # X: (n, d), Y: (m, d) -> (n, m)
    sq_dist = np.sum((X[:, None, :] - Y[None, :, :]) ** 2, axis=2)
    return signal_var * np.exp(-0.5 * sq_dist / (length_scale ** 2))


def _gp_predict(X_train: np.ndarray, y_train: np.ndarray,
                X_test: np.ndarray, length_scale: float,
                signal_var: float, noise_var: float
                ) -> Tuple[np.ndarray, np.ndarray]:
    """GP posterior mean and variance at test points.

    Returns (mean, variance) arrays, each shape (n_test,).
    """
    n = X_train.shape[0]
    K = _rbf_kernel(X_train, X_train, length_scale, signal_var)
    K += noise_var * np.eye(n)

    # Cholesky factorisation for numerical stability
    try:
        L = np.linalg.cholesky(K)
    except np.linalg.LinAlgError:
        K += 1e-4 * np.eye(n)
        L = np.linalg.cholesky(K)

    alpha = np.linalg.solve(L.T, np.linalg.solve(L, y_train))

    K_star = _rbf_kernel(X_test, X_train, length_scale, signal_var)  # (m, n)
    mu = K_star @ alpha  # (m,)

    V = np.linalg.solve(L, K_star.T)  # (n, m)
    k_ss = signal_var  # diagonal of K(X_test, X_test) for RBF = signal_var
    var = np.maximum(1e-10, k_ss - np.sum(V ** 2, axis=0))  # (m,)

    return mu, var


def _expected_improvement(mu: np.ndarray, var: np.ndarray,
                          best_y: float, xi: float = 0.01
                          ) -> np.ndarray:
    """Expected Improvement acquisition function (maximisation)."""
    sigma = np.sqrt(var)
    z = (mu - best_y - xi) / sigma
    # Approximate Phi and phi with numpy (no scipy needed)
    # Phi(z) = 0.5 * (1 + erf(z / sqrt(2)))
    phi_z = np.exp(-0.5 * z ** 2) / np.sqrt(2 * np.pi)
    Phi_z = 0.5 * (1.0 + _fast_erf(z / np.sqrt(2.0)))
    ei = sigma * (z * Phi_z + phi_z)
    return ei


def _fast_erf(x: np.ndarray) -> np.ndarray:
    """Approximation of erf() using Abramowitz & Stegun (max error ~1.5e-7)."""
    a = np.abs(x)
    # Constants
    p = 0.3275911
    a1, a2, a3, a4, a5 = 0.254829592, -0.284496736, 1.421413741, -1.453152027, 1.061405429
    t = 1.0 / (1.0 + p * a)
    t2 = t * t
    t3 = t2 * t
    t4 = t3 * t
    t5 = t4 * t
    y = 1.0 - (a1 * t + a2 * t2 + a3 * t3 + a4 * t4 + a5 * t5) * np.exp(-a * a)
    return np.where(x >= 0, y, -y)


def _estimate_gp_hyperparams(X: np.ndarray, y: np.ndarray
                              ) -> Tuple[float, float, float]:
    """Heuristic GP hyperparameters from training data."""
    # Length scale: median pairwise distance (robust heuristic)
    if X.shape[0] <= 1:
        return 1.0, 1.0, 0.01
    diffs = X[:, None, :] - X[None, :, :]
    dists = np.sqrt(np.sum(diffs ** 2, axis=2))
    # Upper triangle only
    triu_idx = np.triu_indices(dists.shape[0], k=1)
    median_dist = float(np.median(dists[triu_idx])) if len(triu_idx[0]) > 0 else 1.0
    length_scale = max(0.1, median_dist)
    signal_var = max(0.01, float(np.var(y)))
    noise_var = max(1e-4, signal_var * 0.05)  # 5% noise
    return length_scale, signal_var, noise_var


def _update_weights_from_history(
    current: ScoringWeights,
    history: List[Dict[str, Any]] | None = None,
) -> ScoringWeights | None:
    """Propose a candidate weight vector from history.

    The proposal is not persisted here. Callers validate via replay and then
    decide whether to store the candidate.
    """
    entries = list(history or [])

    # Extract (X, y) pairs from history entries that stored their weights
    X_list: List[np.ndarray] = []
    y_list: List[float] = []
    for h in entries:
        wv = h.get("weights_vector")
        sc = h.get("learning_objective", None)
        if sc is None:
            kpis = h.get("kpis")
            if isinstance(kpis, dict):
                sc = _learning_objective_from_kpis(kpis)
            else:
                sc = h.get("best_score")
        if wv is not None and sc is not None and len(wv) == _BO_NDIM:
            X_list.append(np.array(wv, dtype=np.float64))
            y_list.append(float(sc))

    if len(X_list) < int(_MIN_HISTORY_FOR_CANDIDATE):
        return None

    X_train = np.array(X_list)  # (n, 15)
    y_train = np.array(y_list)  # (n,)

    # Normalise X for better GP conditioning
    X_mean = X_train.mean(axis=0)
    X_std = X_train.std(axis=0)
    X_std = np.where(X_std < 1e-8, 1.0, X_std)
    X_norm = (X_train - X_mean) / X_std

    # Normalise y
    y_mean = y_train.mean()
    y_std = max(1e-8, y_train.std())
    y_norm = (y_train - y_mean) / y_std

    # Estimate GP hyperparameters
    length_scale, signal_var, noise_var = _estimate_gp_hyperparams(X_norm, y_norm)

    # Generate candidate points: current + perturbations around best + random
    current_vec = _weights_to_vector(current)
    best_idx = int(np.argmax(y_train))
    best_vec = X_train[best_idx]
    best_y_norm = float(y_norm[best_idx])

    rng = np.random.RandomState(int(time.time()) % (2**31))
    n_candidates = 500

    # Candidates centered on best known + current, with varying exploration
    candidates = np.empty((n_candidates, _BO_NDIM), dtype=np.float64)
    # 40% around best known point (exploitation)
    n_exploit = n_candidates * 2 // 5
    candidates[:n_exploit] = best_vec + rng.randn(n_exploit, _BO_NDIM) * (X_std * 0.05)
    # 30% around current point
    n_current = n_candidates * 3 // 10
    candidates[n_exploit:n_exploit + n_current] = (
        current_vec + rng.randn(n_current, _BO_NDIM) * (X_std * 0.08)
    )
    # 30% broader exploration
    n_explore = n_candidates - n_exploit - n_current
    candidates[n_exploit + n_current:] = (
        best_vec + rng.randn(n_explore, _BO_NDIM) * (X_std * 0.2)
    )

    # Clamp all candidates to non-negative
    np.maximum(candidates, 0.0, out=candidates)

    # Normalise candidates
    cand_norm = (candidates - X_mean) / X_std

    # GP predict + EI
    try:
        mu, var = _gp_predict(X_norm, y_norm, cand_norm,
                              length_scale, signal_var, noise_var)
        ei = _expected_improvement(mu, var, best_y_norm, xi=0.01)
        best_cand_idx = int(np.argmax(ei))
        next_vec = candidates[best_cand_idx]
    except Exception:
        # GP failed â€” fall back to perturbation around best
        next_vec = best_vec + rng.randn(_BO_NDIM) * (X_std * 0.05)
        np.maximum(next_vec, 0.0, out=next_vec)

    candidate = _vector_to_weights(next_vec)
    delta = float(np.linalg.norm(_weights_to_vector(candidate) - _weights_to_vector(current)))
    if delta < 1e-4:
        return None
    return candidate


# ---------------------------------------------------------------------------
# Compute final speed for a rune set
# ---------------------------------------------------------------------------
def _compute_final_speed(
    rune_map: Dict[int, int],
    rune_lookup: Dict[int, Rune],
    base_spd: int,
) -> int:
    """Compute total speed including Swift set bonus."""
    total_spd = base_spd
    set_counts: Dict[int, int] = {}
    for _slot, rid in rune_map.items():
        r = rune_lookup.get(rid)
        if r is None:
            continue
        total_spd += _rune_flat_spd(r)
        sid = int(r.set_id or 0)
        set_counts[sid] = set_counts.get(sid, 0) + 1
    # Swift bonus: 25% base speed if 4+ Swift runes
    if set_counts.get(3, 0) >= 4:
        total_spd += int(base_spd * 0.25)
    return int(total_spd)


# ---------------------------------------------------------------------------
# Phase 1: GPU pre-screening to identify best runes from the full pool
# ---------------------------------------------------------------------------
def _gpu_presceen_rune_ids(
    pool: List[Rune],
    artifact_pool: List[Artifact],
    unit_ids: List[int],
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
    weights: ScoringWeights,
    batch_size: int,
    rng_np: np.random.Generator,
    gpu_scorer: Optional[_GpuScorer],
) -> Set[int]:
    """Run GPU combo search per unit to identify the most promising runes.

    Returns a set of rune_ids that appeared in the top combos across all units.
    These runes form a reduced pool for the solver passes.
    """
    promising_rune_ids: Set[int] = set()

    # Pre-encode all runes once (shared across units)
    runes_by_slot_all: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= r.slot_no <= 6:
            runes_by_slot_all[r.slot_no].append(r)
    preencoded_matrices: Dict[int, np.ndarray] = {}
    preencoded_ids: Dict[int, List[int]] = {}
    for slot in range(1, 7):
        runes = runes_by_slot_all[slot]
        if runes:
            preencoded_matrices[slot] = _encode_runes(runes)
            preencoded_ids[slot] = [r.rune_id for r in runes]

    # Pre-encode artifacts once
    art1_list = [a for a in artifact_pool if int(a.type_ or 0) == 1]
    art2_list = [a for a in artifact_pool if int(a.type_ or 0) == 2]
    art1_matrix = _encode_artifacts(art1_list) if art1_list else None
    art2_matrix = _encode_artifacts(art2_list) if art2_list else None
    n_art1 = len(art1_list)
    n_art2 = len(art2_list)

    for uid in unit_ids:
        unit = account.units_by_id.get(uid)
        if not unit:
            continue

        base_spd = int(unit.base_spd or 0)
        base_cr = int(unit.crit_rate or 15)
        base_res = int(unit.base_res or 15)
        base_acc = int(unit.base_acc or 0)
        base_hp = int(unit.base_con or 0)
        base_atk = int(unit.base_atk or 0)
        base_def = int(unit.base_def or 0)

        builds = _builds_for_unit_with_cloud_prior(presets, req, int(uid))
        constraints = _extract_build_constraints(builds or [], req.mode)

        # Filter matrices by mainstat constraints (slots 2/4/6)
        allowed_mainstats = constraints.get("allowed_mainstats", {})
        slot_matrices: Dict[int, np.ndarray] = {}
        slot_rune_ids: Dict[int, List[int]] = {}
        slot_sizes: Dict[int, int] = {}
        for slot in range(1, 7):
            if slot not in preencoded_matrices:
                continue
            mat = preencoded_matrices[slot]
            ids = preencoded_ids[slot]
            if slot in (2, 4, 6) and allowed_mainstats.get(slot):
                allowed = allowed_mainstats[slot]
                mask = np.isin(mat[:, _COL_MAINSTAT_ID].astype(np.int32), list(allowed))
                if mask.any():
                    mat = mat[mask]
                    ids = [ids[i] for i in range(len(ids)) if mask[i]]
            slot_matrices[slot] = mat
            slot_rune_ids[slot] = ids
            slot_sizes[slot] = len(ids)

        if any(slot_sizes.get(s, 0) == 0 for s in range(1, 7)):
            continue

        set_options = constraints.get("set_options", [])
        min_stats_map = constraints.get("min_stats", {})
        prescreen_elite_size = 2000

        # Generate diverse combos
        parts_rune: List[np.ndarray] = []
        parts_a1: List[Optional[np.ndarray]] = []
        parts_a2: List[Optional[np.ndarray]] = []

        n_per = batch_size // 4
        n_last = batch_size - 3 * n_per

        c, a1, a2 = _generate_random_combos(slot_sizes, n_art1, n_art2, n_per, rng_np)
        parts_rune.append(c); parts_a1.append(a1); parts_a2.append(a2)

        c, a1, a2 = _generate_biased_combos(slot_matrices, art1_matrix, art2_matrix, weights, n_per, rng_np)
        parts_rune.append(c); parts_a1.append(a1); parts_a2.append(a2)

        c, a1, a2 = _generate_greedy_seed_combos(slot_matrices, set_options, n_art1, n_art2, n_per, rng_np)
        parts_rune.append(c); parts_a1.append(a1); parts_a2.append(a2)

        if set_options:
            c, a1, a2 = _generate_set_aware_combos(slot_matrices, set_options, n_art1, n_art2, n_last, rng_np)
        else:
            c, a1, a2 = _generate_random_combos(slot_sizes, n_art1, n_art2, n_last, rng_np)
        parts_rune.append(c); parts_a1.append(a1); parts_a2.append(a2)

        combos = np.concatenate(parts_rune, axis=0)
        c_a1 = np.concatenate([x for x in parts_a1 if x is not None], axis=0) if n_art1 > 0 else None
        c_a2 = np.concatenate([x for x in parts_a2 if x is not None], axis=0) if n_art2 > 0 else None

        scores, valid = _score_combinations_full(
            slot_matrices, combos,
            art1_matrix, art2_matrix,
            c_a1, c_a2,
            weights,
            base_spd, constraints["min_spd"], constraints["max_spd"],
            base_cr, base_res, base_acc,
            set_options, min_stats_map,
            base_hp, base_atk, base_def,
            gpu_scorer=gpu_scorer,
        )
        scores = np.where(valid, scores, scores - 1e6)

        k = min(prescreen_elite_size, len(scores))
        if k < len(scores):
            top_idx = np.argpartition(scores, -k)[-k:]
        else:
            top_idx = np.arange(len(scores))
        top_combos = combos[top_idx]

        for i in range(len(top_combos)):
            combo = top_combos[i]
            for col, slot in enumerate(sorted(slot_rune_ids.keys())):
                idx = int(combo[col])
                if 0 <= idx < len(slot_rune_ids[slot]):
                    promising_rune_ids.add(slot_rune_ids[slot][idx])

    return promising_rune_ids


# ---------------------------------------------------------------------------
# Main optimizer entry point
# ---------------------------------------------------------------------------
@dataclass
class _GpuComboRunOutcome:
    result: GreedyResult
    kpis: Dict[str, float]
    best_score_value: int
    phase1_s: float
    total_s: float
    has_gpu: bool
    provider: str
    combos_evaluated: int
    gpu_runes_found: int
    merged_pool_size: int
    passes_planned: int
    passes_executed: int
    adaptive_batch_size: int
    adaptive_solver_top_per_set: int
    adaptive_extra_rune_cap: int
    adaptive_history_runs: int


@dataclass
class _ReplayCase:
    case_id: str
    req: GreedyRequest
    baseline_kpis: Dict[str, float]


def _run_gpu_combo_once(
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
    weights: ScoringWeights,
    context_history: List[Dict[str, Any]] | None = None,
) -> _GpuComboRunOutcome:
    unit_ids = [int(u) for u in (req.unit_ids_in_order or [])]
    if not unit_ids:
        return _GpuComboRunOutcome(
            result=GreedyResult(False, tr("opt.no_units"), []),
            kpis={},
            best_score_value=0,
            phase1_s=0.0,
            total_s=0.0,
            has_gpu=False,
            provider="",
            combos_evaluated=0,
            gpu_runes_found=0,
            merged_pool_size=0,
            passes_planned=0,
            passes_executed=0,
            adaptive_batch_size=0,
            adaptive_solver_top_per_set=0,
            adaptive_extra_rune_cap=0,
            adaptive_history_runs=0,
        )

    has_gpu, provider = _onnx_gpu_session()
    gpu_scorer: Optional[_GpuScorer] = None
    if has_gpu and provider:
        gpu_scorer = _get_gpu_scorer(provider)
        if not gpu_scorer.available:
            gpu_scorer = None
    rng_np = np.random.default_rng(seed=20260308)
    adaptive = _adaptive_plan_for_run(
        req=req,
        unit_ids=unit_ids,
        has_gpu=bool(has_gpu),
        context_history=context_history,
    )
    batch_size = int(adaptive.batch_size)
    started = time.perf_counter()

    full_pool = _allowed_runes_for_mode(
        account=account,
        req=req,
        _selected_unit_ids=unit_ids,
        rune_top_per_set_override=0,
    )
    artifact_pool = _allowed_artifacts_for_mode(account, unit_ids, req=req)
    total_combos_evaluated = int(batch_size * len(unit_ids))

    gpu_rune_ids = _gpu_presceen_rune_ids(
        pool=full_pool,
        artifact_pool=artifact_pool,
        unit_ids=unit_ids,
        account=account,
        presets=presets,
        req=req,
        weights=weights,
        batch_size=batch_size,
        rng_np=rng_np,
        gpu_scorer=gpu_scorer,
    )
    phase1_time = float(time.perf_counter() - started)

    solver_pool_base = _allowed_runes_for_mode(
        account=account,
        req=req,
        _selected_unit_ids=unit_ids,
        rune_top_per_set_override=int(adaptive.solver_top_per_set),
    )
    solver_pool_ids = {int(r.rune_id) for r in solver_pool_base}
    rune_by_id = {int(r.rune_id): r for r in full_pool}
    extra_runes_raw = [
        rune_by_id[rid]
        for rid in gpu_rune_ids
        if rid not in solver_pool_ids and rid in rune_by_id
    ]
    extra_runes = _cap_extra_gpu_runes(extra_runes_raw, int(adaptive.extra_rune_cap))
    merged_pool = list(solver_pool_base) + extra_runes

    best_results: Optional[List[GreedyUnitResult]] = None
    best_score: Optional[Tuple[int, ...]] = None
    n_passes = int(adaptive.pass_limit)
    pass_orders = _build_pass_orders(unit_ids, n_passes)
    rune_top_override = 0
    no_improve_streak = 0
    passes_executed = 0

    for pass_idx, order in enumerate(pass_orders):
        if req.is_cancelled and req.is_cancelled():
            break
        elapsed = float(time.perf_counter() - started)
        time_budget = float(adaptive.time_budget_s)
        if elapsed > time_budget:
            break

        pass_time = float(max(0.5, adaptive.pass_time_s))
        speed_slack = max(1, int(getattr(req, "speed_slack_for_quality", 2) or 2))
        if pass_idx == 0:
            results = _run_pass_with_profile(
                account=account,
                presets=presets,
                req=req,
                unit_ids=order,
                time_limit_per_unit_s=pass_time,
                speed_hard_priority=True,
                build_priority_penalty=DEFAULT_BUILD_PRIORITY_PENALTY,
                objective_mode="efficiency",
                speed_slack_for_quality=speed_slack,
                rune_top_per_set_override=rune_top_override,
                rune_pool_override=merged_pool,
            )
        else:
            avoid_map = None
            if best_results:
                avoid_map = {int(r.unit_id): r for r in best_results if r.ok}
            obj_mode = "balanced" if pass_idx % 4 == 3 else "efficiency"
            results = _run_pass_with_profile(
                account=account,
                presets=presets,
                req=req,
                unit_ids=order,
                time_limit_per_unit_s=pass_time,
                speed_hard_priority=bool(pass_idx % 4 == 0),
                build_priority_penalty=max(40, DEFAULT_BUILD_PRIORITY_PENALTY - pass_idx * 30),
                set_option_preference_offset_base=pass_idx,
                set_option_preference_bonus=SET_OPTION_PREFERENCE_BONUS,
                avoid_solution_by_unit=avoid_map,
                avoid_same_rune_penalty=REFINE_SAME_RUNE_PENALTY,
                avoid_same_artifact_penalty=REFINE_SAME_ARTIFACT_PENALTY,
                speed_slack_for_quality=speed_slack,
                objective_mode=obj_mode,
                rune_top_per_set_override=rune_top_override,
                rune_pool_override=merged_pool,
            )

        passes_executed += 1
        if not results:
            continue
        score = _evaluate_pass_score(account, req, results)
        if best_score is None or score > best_score:
            best_score = score
            best_results = results
            no_improve_streak = 0
        else:
            no_improve_streak += 1
        if req.progress_callback:
            try:
                req.progress_callback(pass_idx + 1, n_passes)
            except Exception:
                pass
        if (
            passes_executed >= int(adaptive.min_passes)
            and no_improve_streak >= int(adaptive.early_stop_patience)
        ):
            break

    total_time = float(time.perf_counter() - started)
    if best_results is None:
        if req.is_cancelled and req.is_cancelled():
            return _GpuComboRunOutcome(
                result=GreedyResult(False, tr("opt.cancelled"), []),
                kpis={},
                best_score_value=0,
                phase1_s=phase1_time,
                total_s=total_time,
                has_gpu=bool(has_gpu),
                provider=str(provider or ""),
                combos_evaluated=total_combos_evaluated,
                gpu_runes_found=len(gpu_rune_ids),
                merged_pool_size=len(merged_pool),
                passes_planned=int(n_passes),
                passes_executed=int(passes_executed),
                adaptive_batch_size=int(adaptive.batch_size),
                adaptive_solver_top_per_set=int(adaptive.solver_top_per_set),
                adaptive_extra_rune_cap=int(adaptive.extra_rune_cap),
                adaptive_history_runs=int(adaptive.history_run_count),
            )
        return _GpuComboRunOutcome(
            result=GreedyResult(False, tr("opt.partial_fail"), []),
            kpis={},
            best_score_value=0,
            phase1_s=phase1_time,
            total_s=total_time,
            has_gpu=bool(has_gpu),
            provider=str(provider or ""),
            combos_evaluated=total_combos_evaluated,
            gpu_runes_found=len(gpu_rune_ids),
            merged_pool_size=len(merged_pool),
            passes_planned=int(n_passes),
            passes_executed=int(passes_executed),
            adaptive_batch_size=int(adaptive.batch_size),
            adaptive_solver_top_per_set=int(adaptive.solver_top_per_set),
            adaptive_extra_rune_cap=int(adaptive.extra_rune_cap),
            adaptive_history_runs=int(adaptive.history_run_count),
        )

    ok_all = all(r.ok for r in best_results)
    prefix = tr("opt.ok") if ok_all else tr("opt.partial_fail")
    gpu_label = f"GPU ({provider})" if has_gpu else "CPU (numpy)"
    msg = (
        f"{prefix} GPU-Combo [{gpu_label}]: "
        f"{total_combos_evaluated:,} Kombinationen bewertet (Phase 1: {phase1_time:.1f}s), "
        f"{len(gpu_rune_ids)} Runen identifiziert, "
        f"Pool: {len(merged_pool)} Runen, "
        f"{passes_executed}/{n_passes} Solver-Passes in {total_time:.1f}s."
    )
    kpis = _result_kpis(account, best_results)
    score_val = int(sum(best_score)) if best_score is not None else 0
    return _GpuComboRunOutcome(
        result=GreedyResult(ok_all, msg, best_results),
        kpis=dict(kpis),
        best_score_value=score_val,
        phase1_s=phase1_time,
        total_s=total_time,
        has_gpu=bool(has_gpu),
        provider=str(provider or ""),
        combos_evaluated=total_combos_evaluated,
        gpu_runes_found=len(gpu_rune_ids),
        merged_pool_size=len(merged_pool),
        passes_planned=int(n_passes),
        passes_executed=int(passes_executed),
        adaptive_batch_size=int(adaptive.batch_size),
        adaptive_solver_top_per_set=int(adaptive.solver_top_per_set),
        adaptive_extra_rune_cap=int(adaptive.extra_rune_cap),
        adaptive_history_runs=int(adaptive.history_run_count),
    )


def _collect_replay_cases(
    current_req: GreedyRequest,
    current_kpis: Dict[str, float],
    context_history: List[Dict[str, Any]],
) -> List[_ReplayCase]:
    cases: List[_ReplayCase] = []
    base_req = replace(
        current_req,
        progress_callback=None,
        is_cancelled=None,
        register_solver=None,
    )
    cases.append(_ReplayCase("current", base_req, dict(current_kpis)))

    seen_hashes: Set[str] = set()
    cur_payload = _build_replay_payload(base_req)
    seen_hashes.add(_replay_payload_hash(cur_payload))
    for row in reversed(list(context_history or [])):
        if len(cases) >= int(max(1, _MAX_REPLAY_CASES)):
            break
        payload = row.get("replay_payload")
        kpis = row.get("kpis")
        if not isinstance(payload, dict) or not isinstance(kpis, dict):
            continue
        payload_hash = str(row.get("replay_payload_hash", "") or _replay_payload_hash(payload))
        if payload_hash in seen_hashes:
            continue
        req_case = _request_from_replay_payload(payload)
        if req_case is None:
            continue
        req_case = replace(req_case, progress_callback=None, is_cancelled=None, register_solver=None)
        cases.append(_ReplayCase(f"history:{payload_hash}", req_case, dict(kpis)))
        seen_hashes.add(payload_hash)
    return cases


def _validate_candidate_with_replays(
    account: AccountData,
    presets: BuildStore,
    candidate_weights: ScoringWeights,
    cases: List[_ReplayCase],
) -> Tuple[bool, Dict[str, Any]]:
    baseline_total = 0.0
    candidate_total = 0.0
    per_case: List[Dict[str, Any]] = []
    for case in list(cases or []):
        baseline_kpis = dict(case.baseline_kpis or {})
        baseline_obj = _learning_objective_from_kpis(baseline_kpis)
        baseline_total += baseline_obj

        cand_run = _run_gpu_combo_once(
            account=account,
            presets=presets,
            req=case.req,
            weights=candidate_weights,
        )
        cand_kpis = dict(cand_run.kpis or {})
        cand_obj = _learning_objective_from_kpis(cand_kpis)
        candidate_total += cand_obj
        safe = _kpis_safe_enough(baseline_kpis, cand_kpis)
        per_case.append(
            {
                "case_id": str(case.case_id),
                "baseline_objective": float(baseline_obj),
                "candidate_objective": float(cand_obj),
                "safe": bool(safe),
            }
        )
        if not safe:
            return False, {
                "reason": f"safety_regression:{str(case.case_id)}",
                "baseline_total": float(baseline_total),
                "candidate_total": float(candidate_total),
                "cases": per_case,
            }

    accept = bool(candidate_total >= (baseline_total * (1.0 + float(_AB_ACCEPT_MARGIN))))
    return accept, {
        "reason": "accept" if accept else "no_gain",
        "baseline_total": float(baseline_total),
        "candidate_total": float(candidate_total),
        "cases": per_case,
    }


def optimize_gpu_combo(
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
) -> GreedyResult:
    """Hybrid GPU+Solver optimizer with guarded online learning."""
    unit_ids = [int(u) for u in (req.unit_ids_in_order or [])]
    if not unit_ids:
        return GreedyResult(False, tr("opt.no_units"), [])

    context_key = _learning_context_key(req)
    context_history_before = _history_for_context(context_key, max_entries=240)
    local_weights = ScoringWeights.load(context_key=context_key)
    runtime_weights = local_weights
    cloud_weights: Optional[ScoringWeights] = None
    cloud_alpha = 0.0
    cloud_samples = 0
    cloud_distinct_licenses = 0
    try:
        cloud_prior = fetch_cloud_prior(context_key=context_key, optimizer_kind="gpu_combo")
        if cloud_prior is not None and len(cloud_prior.weights_vector) == _BO_NDIM:
            cloud_weights = _vector_to_weights(np.array(cloud_prior.weights_vector, dtype=np.float64))
            cloud_alpha = max(float(_CLOUD_ALPHA_MIN), min(float(_CLOUD_ALPHA_MAX), float(cloud_prior.alpha)))
            runtime_weights = _blend_scoring_weights(local_weights, cloud_weights, cloud_alpha)
            cloud_samples = int(cloud_prior.sample_count)
            cloud_distinct_licenses = int(cloud_prior.distinct_licenses)
    except Exception:
        cloud_weights = None
        cloud_alpha = 0.0
        runtime_weights = local_weights

    run = _run_gpu_combo_once(
        account=account,
        presets=presets,
        req=req,
        weights=runtime_weights,
        context_history=context_history_before,
    )
    result = run.result

    # Learning stage with replay safety gate.
    try:
        replay_payload = _build_replay_payload(req)
        learning_objective = float(_learning_objective_from_kpis(dict(run.kpis or {})))
        runtime_weights_vec = _weights_to_vector(runtime_weights).tolist()
        local_weights_vec = _weights_to_vector(local_weights).tolist()
        history_entry = {
            "kind": "run",
            "timestamp": time.time(),
            "context_key": str(context_key),
            "mode": str(req.mode or ""),
            "units": int(len(unit_ids)),
            "ok_count": int(_int_or((run.kpis or {}).get("ok_units"), 0)),
            "best_score": int(run.best_score_value),
            "combos_evaluated": int(run.combos_evaluated),
            "phase1_ms": round(float(run.phase1_s) * 1000.0, 1),
            "total_ms": round(float(run.total_s) * 1000.0, 1),
            "has_gpu": bool(run.has_gpu),
            "gpu_provider": str(run.provider or ""),
            "gpu_runes_found": int(run.gpu_runes_found),
            "merged_pool_size": int(run.merged_pool_size),
            "passes_planned": int(run.passes_planned),
            "passes_executed": int(run.passes_executed),
            "adaptive_batch_size": int(run.adaptive_batch_size),
            "adaptive_solver_top_per_set": int(run.adaptive_solver_top_per_set),
            "adaptive_extra_rune_cap": int(run.adaptive_extra_rune_cap),
            "adaptive_history_runs": int(run.adaptive_history_runs),
            "weights_context_key": str(context_key),
            "weights_vector": list(local_weights_vec),
            "runtime_weights_vector": list(runtime_weights_vec),
            "cloud_prior_used": bool(cloud_weights is not None),
            "cloud_alpha": float(cloud_alpha),
            "cloud_sample_count": int(cloud_samples),
            "cloud_distinct_licenses": int(cloud_distinct_licenses),
            "kpis": dict(run.kpis or {}),
            "learning_objective": float(learning_objective),
            "replay_payload_hash": str(_replay_payload_hash(replay_payload)),
            "replay_payload": dict(replay_payload),
        }
        _append_history(history_entry)
        try:
            upload_learning_run(
                context_key=str(context_key),
                optimizer_kind="gpu_combo",
                mode=str(req.mode or ""),
                units=len(unit_ids),
                weights_vector=runtime_weights_vec,
                kpis=dict(run.kpis or {}),
                learning_objective=learning_objective,
                replay_payload_hash=str(_replay_payload_hash(replay_payload)),
                client_version="",
            )
        except Exception:
            pass
        # Ensure context-local baseline exists even before the first accepted update.
        local_weights.save(context_key=context_key)

        context_history = _history_for_context(context_key, max_entries=240)
        candidate = _update_weights_from_history(local_weights, context_history)
        if (
            candidate is not None
            and len(context_history) >= int(_MIN_HISTORY_FOR_AB)
            and bool(run.kpis)
        ):
            candidate_runtime = candidate
            if cloud_weights is not None:
                candidate_runtime = _blend_scoring_weights(candidate, cloud_weights, cloud_alpha)
            replay_cases = _collect_replay_cases(
                current_req=req,
                current_kpis=dict(run.kpis or {}),
                context_history=context_history,
            )
            accepted, detail = _validate_candidate_with_replays(
                account=account,
                presets=presets,
                candidate_weights=candidate_runtime,
                cases=replay_cases,
            )
            if accepted:
                candidate.save(context_key=context_key)
            _append_history(
                {
                    "kind": "learning_update",
                    "timestamp": time.time(),
                    "context_key": str(context_key),
                    "accepted": bool(accepted),
                    "reason": str(detail.get("reason", "") or ""),
                    "baseline_total": float(_float_or(detail.get("baseline_total"), 0.0)),
                    "candidate_total": float(_float_or(detail.get("candidate_total"), 0.0)),
                    "cases": list(detail.get("cases", []) or []),
                    "current_weights_vector": list(local_weights_vec),
                    "candidate_weights_vector": _weights_to_vector(candidate).tolist(),
                    "candidate_runtime_weights_vector": _weights_to_vector(candidate_runtime).tolist(),
                    "cloud_prior_used": bool(cloud_weights is not None),
                    "cloud_alpha": float(cloud_alpha),
                }
            )
    except Exception:
        pass

    return result

