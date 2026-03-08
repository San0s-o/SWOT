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
    check, speed tick bounds, min stat thresholds, scoring – on GPU if available.
5.  Build GreedyUnitResult directly from the best GPU-found combination.
6.  Persist per-account learning data so the scoring weights improve over time.
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
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
    _run_pass_with_profile,
)
from app.i18n import tr

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

# Combination batch sizes for GPU pre-screening
_GPU_BATCH_SIZE = 500_000
_CPU_BATCH_SIZE = 300_000

# How many top-K elite combinations to maintain per unit
_ELITE_SIZE = 300

# Mainstat key → effect_id reverse mapping
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
# Rune → numpy vector encoding
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
    stat_weights: np.ndarray  # shape (_N_STATS,) – per-stat importance
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
            10.0,  # SPD – moderate (solver handles speed precisely)
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

    def save(self) -> None:
        _LEARN_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "stat_weights": self.stat_weights.tolist(),
            "quality_weight": self.quality_weight,
            "efficiency_weight": self.efficiency_weight,
            "set_bonus_weight": self.set_bonus_weight,
            "speed_priority": self.speed_priority,
        }
        _WEIGHTS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls) -> "ScoringWeights":
        if not _WEIGHTS_PATH.exists():
            return cls.default()
        try:
            raw = json.loads(_WEIGHTS_PATH.read_text(encoding="utf-8"))
            sw = np.array(raw["stat_weights"], dtype=np.float32)
            if len(sw) != _N_STATS:
                return cls.default()
            return cls(
                stat_weights=sw,
                quality_weight=float(raw.get("quality_weight", 1.0)),
                efficiency_weight=float(raw.get("efficiency_weight", 6.0)),
                set_bonus_weight=float(raw.get("set_bonus_weight", 1.0)),
                speed_priority=float(raw.get("speed_priority", 2.0)),
            )
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
    combo_indices: np.ndarray,             # (batch, 6) – indices into slot matrices
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


def _load_history(max_entries: int = 200) -> List[Dict[str, Any]]:
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


def _update_weights_from_history(current: ScoringWeights) -> ScoringWeights:
    """Simple online learning: try perturbations, keep if historical score improved."""
    history = _load_history(50)
    if len(history) < 3:
        return current
    recent_scores = [float(h.get("best_score", 0)) for h in history[-10:]]
    if len(recent_scores) < 2:
        return current
    improving = all(recent_scores[i] <= recent_scores[i + 1] for i in range(len(recent_scores) - 1))
    if improving:
        return current
    rng = random.Random(int(time.time()))
    candidate = current.perturb(rng, scale=0.05)
    candidate.save()
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

        builds = presets.get_unit_builds(req.mode, uid)
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
def optimize_gpu_combo(
    account: AccountData,
    presets: BuildStore,
    req: GreedyRequest,
) -> GreedyResult:
    """Hybrid GPU+Solver optimizer.

    Phase 1: GPU massively parallel search over the FULL rune+artifact pool
             to identify the most promising runes per unit.
    Phase 2: OR-Tools solver passes on the GPU-identified rune pool for
             precise constraint satisfaction and optimal stat combinations.
    Phase 3: Learn from results for next time.
    """
    unit_ids = [int(u) for u in (req.unit_ids_in_order or [])]
    if not unit_ids:
        return GreedyResult(False, tr("opt.no_units"), [])

    has_gpu, provider = _onnx_gpu_session()
    gpu_scorer: Optional[_GpuScorer] = None
    if has_gpu and provider:
        gpu_scorer = _get_gpu_scorer(provider)
        if not gpu_scorer.available:
            gpu_scorer = None
    rng_np = np.random.default_rng(seed=20260308)


    weights = ScoringWeights.load()

    base_batch = _GPU_BATCH_SIZE if has_gpu else _CPU_BATCH_SIZE
    # Scale batch per unit down when many units to keep prescreen fast
    batch_size = max(100_000, base_batch // max(1, len(unit_ids) // 3))

    started = time.perf_counter()

    # Build FULL rune pool (no top-N filtering)
    full_pool = _allowed_runes_for_mode(
        account=account,
        req=req,
        _selected_unit_ids=unit_ids,
        rune_top_per_set_override=0,
    )
    artifact_pool = _allowed_artifacts_for_mode(account, unit_ids, req=req)

    total_combos_evaluated = batch_size * len(unit_ids)

    # Phase 1: GPU pre-screening over the full pool
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

    phase1_time = time.perf_counter() - started

    # Merge GPU-identified runes into the solver pool.
    # We use a moderate rune_top_per_set so the solver also gets some runes
    # it would normally pick, plus all GPU-discovered runes.
    solver_pool_base = _allowed_runes_for_mode(
        account=account,
        req=req,
        _selected_unit_ids=unit_ids,
        rune_top_per_set_override=80,
    )
    # Add GPU runes not already in solver pool
    solver_pool_ids = {int(r.rune_id) for r in solver_pool_base}
    rune_by_id = {int(r.rune_id): r for r in full_pool}
    extra_runes = [rune_by_id[rid] for rid in gpu_rune_ids if rid not in solver_pool_ids and rid in rune_by_id]
    merged_pool = list(solver_pool_base) + extra_runes

    # Phase 2: OR-Tools solver passes on the enriched pool
    best_results: Optional[List[GreedyUnitResult]] = None
    best_score: Optional[Tuple[int, ...]] = None

    n_passes = min(8, max(3, len(unit_ids)))
    pass_orders = _build_pass_orders(unit_ids, n_passes)

    # Use the merged pool size to set rune_top_per_set for the solver
    # (0 = use all runes in the pool, which now is the enriched pool)
    rune_top_override = 0  # solver gets the full merged pool

    for pass_idx, order in enumerate(pass_orders):
        if req.is_cancelled and req.is_cancelled():
            break
        elapsed = time.perf_counter() - started
        time_budget = float(req.time_limit_per_unit_s) * len(unit_ids) * 4
        if elapsed > time_budget:
            break

        pass_time = max(0.5, float(req.time_limit_per_unit_s) * 0.7)
        # GPU-Combo: mostly "efficiency" objective – find the most efficient
        # rune builds, not just the fastest.  Speed is a constraint, not the
        # objective.  Allow speed slack so the solver can trade a few speed
        # points for substantially better efficiency.
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
            # Alternate: mostly efficiency, with occasional balanced pass
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

        if not results:
            continue

        score = _evaluate_pass_score(account, req, results)
        if best_score is None or score > best_score:
            best_score = score
            best_results = results

        if req.progress_callback:
            try:
                req.progress_callback(pass_idx + 1, n_passes)
            except Exception:
                pass

    total_time = time.perf_counter() - started

    if best_results is None:
        if req.is_cancelled and req.is_cancelled():
            return GreedyResult(False, tr("opt.cancelled"), [])
        return GreedyResult(False, tr("opt.partial_fail"), [])

    # Phase 3: Learn from results
    try:
        ok_count = sum(1 for r in best_results if r.ok)
        score_val = sum(best_score) if best_score else 0
        speed_sum = sum(int(r.final_speed or 0) for r in best_results if r.ok)
        _append_history({
            "timestamp": time.time(),
            "units": len(unit_ids),
            "ok_count": ok_count,
            "best_score": score_val,
            "speed_sum": speed_sum,
            "combos_evaluated": total_combos_evaluated,
            "phase1_ms": round(phase1_time * 1000, 1),
            "total_ms": round(total_time * 1000, 1),
            "has_gpu": has_gpu,
            "gpu_runes_found": len(gpu_rune_ids),
            "merged_pool_size": len(merged_pool),
        })
        weights = _update_weights_from_history(weights)
    except Exception:
        pass

    ok_all = all(r.ok for r in best_results)
    prefix = tr("opt.ok") if ok_all else tr("opt.partial_fail")
    gpu_label = f"GPU ({provider})" if has_gpu else "CPU (numpy)"
    msg = (
        f"{prefix} GPU-Combo [{gpu_label}]: "
        f"{total_combos_evaluated:,} Kombinationen bewertet (Phase 1: {phase1_time:.1f}s), "
        f"{len(gpu_rune_ids)} Runen identifiziert, "
        f"Pool: {len(merged_pool)} Runen, "
        f"{n_passes} Solver-Passes in {total_time:.1f}s."
    )
    return GreedyResult(ok_all, msg, best_results)
