from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any, Set

from app.domain.models import AccountData
from app.domain.presets import BuildStore
from app.engine.greedy_optimizer import (
    DEFAULT_BUILD_PRIORITY_PENALTY,
    GreedyRequest,
    GreedyResult,
    GreedyUnitResult,
    _allowed_artifacts_for_mode,
    _allowed_runes_for_mode,
    _artifact_quality_score,
    _evaluate_pass_score,
    _force_swift_speed_priority,
    _rune_flat_spd,
    _rune_quality_score,
    _run_greedy_pass,
    _run_pass_with_profile,
)
from app.i18n import tr


@dataclass
class _Candidate:
    idx: int
    score: Tuple[int, int, int, int, int, int, int]
    results: List[GreedyUnitResult]


@dataclass
class _Variant:
    idx: int
    order: List[int]
    speed_hard: bool
    objective_mode: str
    build_penalty: int
    set_pref_offset: int
    set_pref_bonus: int
    avoid_rune_penalty: int
    avoid_art_penalty: int
    speed_slack: int


def _variant_key(v: _Variant) -> Tuple[Tuple[int, ...], bool, str, int, int, int, int, int, int]:
    return (
        tuple(int(x) for x in v.order),
        bool(v.speed_hard),
        str(v.objective_mode),
        int(v.build_penalty),
        int(v.set_pref_offset),
        int(v.set_pref_bonus),
        int(v.avoid_rune_penalty),
        int(v.avoid_art_penalty),
        int(v.speed_slack),
    )


def _torch_backend() -> Tuple[str, Optional[Any]]:
    try:
        import torch  # type: ignore

        if bool(torch.cuda.is_available()):
            return "cuda", torch
        return "cpu", torch
    except Exception:
        return "cpu", None


def _unit_features(account: AccountData, presets: BuildStore, req: GreedyRequest, unit_ids: List[int]) -> Tuple[Dict[int, Tuple[float, float, float]], Dict[int, int]]:
    pool = _allowed_runes_for_mode(
        account=account,
        req=req,
        _selected_unit_ids=unit_ids,
        rune_top_per_set_override=max(0, int(getattr(req, "rune_top_per_set", 200) or 200)),
    )
    artifact_pool = _allowed_artifacts_for_mode(account, unit_ids)

    top_rune_spd = 0.0
    top_rune_qual = 0.0
    for r in pool:
        top_rune_spd = max(top_rune_spd, float(_rune_flat_spd(r)))
        top_rune_qual = max(top_rune_qual, float(_rune_quality_score(r, 0, None)))

    top_art_qual = 0.0
    for a in artifact_pool:
        top_art_qual = max(top_art_qual, float(_artifact_quality_score(a, 0, None)))

    per_uid: Dict[int, Tuple[float, float, float]] = {}
    seed_pos: Dict[int, int] = {}
    for pos, uid in enumerate(unit_ids):
        seed_pos[int(uid)] = int(pos)
        unit = account.units_by_id.get(int(uid))
        base_spd = float(int(unit.base_spd or 0) if unit else 0)
        builds = presets.get_unit_builds(req.mode, int(uid))
        swift_flag = 1.0 if _force_swift_speed_priority(req, int(uid), builds) else 0.0

        # Potential proxies for fast variant screening.
        spd_potential = base_spd + (top_rune_spd * 6.0) + (base_spd * 0.25)
        qual_potential = (top_rune_qual * 6.0) + (top_art_qual * 2.0)
        per_uid[int(uid)] = (float(spd_potential), float(qual_potential), float(swift_flag))
    return per_uid, seed_pos


def _generate_variants(unit_ids: List[int], planned: int, rng: random.Random, speed_slack_base: int) -> List[_Variant]:
    out: List[_Variant] = []
    n = len(unit_ids)
    if n == 0:
        return out

    def _append(order: List[int]) -> None:
        idx = len(out)
        jitter = int(rng.randint(0, 2))
        out.append(
            _Variant(
                idx=idx,
                order=list(order),
                speed_hard=bool(idx % 4 == 0),
                objective_mode="efficiency" if (idx % 3 != 0) else "balanced",
                build_penalty=max(30, int(DEFAULT_BUILD_PRIORITY_PENALTY - rng.randint(0, 130))),
                set_pref_offset=int(rng.randint(0, max(0, n - 1))),
                set_pref_bonus=int(rng.randint(30, 140)),
                avoid_rune_penalty=int(rng.randint(80, 300)),
                avoid_art_penalty=int(rng.randint(50, 220)),
                speed_slack=max(0, int(speed_slack_base + jitter - 1)),
            )
        )

    _append(list(unit_ids))
    if planned > 1:
        _append(list(reversed(unit_ids)))

    while len(out) < planned:
        perm = list(unit_ids)
        rng.shuffle(perm)
        _append(perm)
    return out


def _mutate_order(order: List[int], rng: random.Random) -> List[int]:
    out = list(order)
    n = len(out)
    if n <= 1:
        return out
    for _ in range(int(rng.randint(1, 3))):
        i = int(rng.randrange(n))
        j = int(rng.randrange(n))
        out[i], out[j] = out[j], out[i]
    if n >= 4 and rng.random() < 0.35:
        a = int(rng.randrange(0, n - 1))
        b = int(rng.randrange(a + 1, n))
        seg = out[a:b]
        del out[a:b]
        ins = int(rng.randrange(0, len(out) + 1))
        out[ins:ins] = seg
    return out


def _spawn_variant(
    idx: int,
    order: List[int],
    rng: random.Random,
    speed_slack_base: int,
    parent: Optional[_Variant] = None,
) -> _Variant:
    max_offset = max(0, len(order) - 1)
    if parent is None:
        return _Variant(
            idx=int(idx),
            order=list(order),
            speed_hard=bool(rng.random() < 0.30),
            objective_mode="efficiency" if rng.random() < 0.75 else "balanced",
            build_penalty=max(30, int(DEFAULT_BUILD_PRIORITY_PENALTY - rng.randint(0, 150))),
            set_pref_offset=int(rng.randint(0, max_offset)),
            set_pref_bonus=int(rng.randint(20, 180)),
            avoid_rune_penalty=int(rng.randint(60, 320)),
            avoid_art_penalty=int(rng.randint(40, 260)),
            speed_slack=max(0, int(speed_slack_base + rng.randint(-1, 2))),
        )

    return _Variant(
        idx=int(idx),
        order=list(order),
        speed_hard=bool(parent.speed_hard if rng.random() < 0.7 else (not parent.speed_hard)),
        objective_mode=str(parent.objective_mode if rng.random() < 0.7 else ("efficiency" if rng.random() < 0.8 else "balanced")),
        build_penalty=max(30, int(parent.build_penalty + rng.randint(-40, 40))),
        set_pref_offset=min(max_offset, max(0, int(parent.set_pref_offset + rng.randint(-2, 2)))),
        set_pref_bonus=max(10, int(parent.set_pref_bonus + rng.randint(-40, 40))),
        avoid_rune_penalty=max(0, int(parent.avoid_rune_penalty + rng.randint(-80, 80))),
        avoid_art_penalty=max(0, int(parent.avoid_art_penalty + rng.randint(-60, 60))),
        speed_slack=max(0, int(parent.speed_slack + rng.randint(-1, 1))),
    )


def _build_variant_batch(
    unit_ids: List[int],
    elite: List[_Variant],
    batch_size: int,
    rng: random.Random,
    speed_slack_base: int,
    idx_start: int,
) -> List[_Variant]:
    out: List[_Variant] = []
    seen: Set[Tuple[Tuple[int, ...], bool, str, int, int, int, int, int, int]] = set()

    def _push(v: _Variant) -> None:
        key = _variant_key(v)
        if key in seen:
            return
        seen.add(key)
        out.append(v)

    _push(_spawn_variant(int(idx_start), list(unit_ids), rng, speed_slack_base, None))
    if len(unit_ids) > 1 and len(out) < batch_size:
        _push(_spawn_variant(int(idx_start + len(out)), list(reversed(unit_ids)), rng, speed_slack_base, None))

    while len(out) < batch_size:
        if elite and rng.random() < 0.82:
            parent = elite[int(rng.randrange(len(elite)))]
            order = _mutate_order(parent.order, rng)
            _push(_spawn_variant(int(idx_start + len(out)), order, rng, speed_slack_base, parent))
            continue
        order = list(unit_ids)
        rng.shuffle(order)
        _push(_spawn_variant(int(idx_start + len(out)), order, rng, speed_slack_base, None))

    return out


def _rank_variants_with_torch(
    variants: List[_Variant],
    unit_ids: List[int],
    features_by_uid: Dict[int, Tuple[float, float, float]],
    seed_pos_by_uid: Dict[int, int],
    backend: str,
    torch_mod: Optional[Any],
) -> List[int]:
    if not variants:
        return []
    if torch_mod is None:
        # Fallback ranking without torch.
        ranked = []
        for row_idx, v in enumerate(variants):
            pos_map = {int(uid): p for p, uid in enumerate(v.order)}
            score = 0.0
            n = max(1, len(v.order))
            for uid in unit_ids:
                spd_p, qual_p, swift_f = features_by_uid.get(int(uid), (0.0, 0.0, 0.0))
                p = float(pos_map.get(int(uid), n))
                pos_w = float(n - p)
                score += (spd_p * (1.6 if v.speed_hard else 1.0)) * pos_w
                score += qual_p * (1.2 if v.objective_mode == "efficiency" else 0.9)
                score += swift_f * spd_p * pos_w * 0.5
                score += float(seed_pos_by_uid.get(int(uid), 0) - int(p)) * 8.0
            ranked.append((score, int(row_idx)))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [int(i) for _, i in ranked]

    torch = torch_mod
    device = torch.device("cuda" if backend == "cuda" else "cpu")
    dtype = torch.float16 if backend == "cuda" else torch.float32
    n_units = len(unit_ids)
    n_vars = len(variants)
    uid_to_col = {int(uid): i for i, uid in enumerate(unit_ids)}

    spd_feat = torch.tensor([features_by_uid[int(uid)][0] for uid in unit_ids], dtype=dtype, device=device)
    qual_feat = torch.tensor([features_by_uid[int(uid)][1] for uid in unit_ids], dtype=dtype, device=device)
    swift_feat = torch.tensor([features_by_uid[int(uid)][2] for uid in unit_ids], dtype=dtype, device=device)
    seed_pos = torch.tensor([seed_pos_by_uid[int(uid)] for uid in unit_ids], dtype=dtype, device=device)

    order_cols = torch.tensor(
        [[uid_to_col[int(uid)] for uid in v.order] for v in variants],
        dtype=torch.int64,
        device=device,
    )
    pos_seq = torch.arange(n_units, dtype=dtype, device=device).unsqueeze(0).expand(n_vars, n_units)
    pos_mat = torch.empty((n_vars, n_units), dtype=dtype, device=device)
    pos_mat.scatter_(1, order_cols, pos_seq)
    speed_hard_vec = torch.tensor([1.0 if v.speed_hard else 0.0 for v in variants], dtype=dtype, device=device)
    eff_mode_vec = torch.tensor([1.0 if v.objective_mode == "efficiency" else 0.0 for v in variants], dtype=dtype, device=device)

    pos_weight = float(max(1, n_units)) - pos_mat
    spd_weight = 1.0 + (0.6 * speed_hard_vec.unsqueeze(1))
    qual_weight = 0.9 + (0.3 * eff_mode_vec.unsqueeze(1))
    swift_boost = (swift_feat.unsqueeze(0) * spd_feat.unsqueeze(0) * pos_weight * 0.5)
    seed_shift = ((seed_pos.unsqueeze(0) - pos_mat) * 8.0)

    score_tensor = (
        (spd_feat.unsqueeze(0) * pos_weight * spd_weight).sum(dim=1)
        + (qual_feat.unsqueeze(0) * qual_weight).sum(dim=1)
        + swift_boost.sum(dim=1)
        + seed_shift.sum(dim=1)
    )
    order = torch.argsort(score_tensor, descending=True)
    return [int(x) for x in order.detach().cpu().tolist()]


def optimize_gpu_search(account: AccountData, presets: BuildStore, req: GreedyRequest) -> GreedyResult:
    unit_ids = [int(u) for u in (req.unit_ids_in_order or [])]
    if not unit_ids:
        return GreedyResult(False, tr("opt.no_units"), [])

    backend, torch_mod = _torch_backend()
    rng = random.Random(20260215)
    profile = str(getattr(req, "quality_profile", "gpu_search_balanced") or "gpu_search_balanced").strip().lower()
    if profile == "gpu_search":
        profile = "gpu_search_balanced"

    has_cuda = backend == "cuda" and torch_mod is not None
    if profile == "gpu_search_fast":
        cuda_batch_factor = 2048
        cpu_batch_factor = 192
        gpu_cycles_bonus = 2
        eval_factor = 10 if has_cuda else 5
        time_factor = 2.0 if has_cuda else 1.5
    elif profile == "gpu_search_max":
        cuda_batch_factor = 12288
        cpu_batch_factor = 768
        gpu_cycles_bonus = 12
        eval_factor = 26 if has_cuda else 10
        time_factor = 6.0 if has_cuda else 3.0
    else:  # gpu_search_balanced
        cuda_batch_factor = 8192
        cpu_batch_factor = 512
        gpu_cycles_bonus = 8
        eval_factor = 20 if has_cuda else 8
        time_factor = 4.0 if has_cuda else 2.0

    batch_size = int(max(256, min(262144, len(unit_ids) * (cuda_batch_factor if has_cuda else cpu_batch_factor))))
    elite_size = int(max(24, min(512, batch_size // 8)))
    cpu_eval_batch = int(max(6, min(28, int(req.workers or 1) * 2)))
    max_cpu_evals = int(max(20, min(720, len(unit_ids) * eval_factor)))
    gpu_batches_per_cycle = int(max(2, min(20, (len(unit_ids) // 2) + gpu_cycles_bonus)))
    time_budget_s = max(
        10.0,
        float(req.time_limit_per_unit_s) * float(max(1, len(unit_ids))) * float(time_factor),
    )
    started = time.perf_counter()
    speed_slack_base = int(max(0, int(getattr(req, "speed_slack_for_quality", 1) or 1)))

    features_by_uid, seed_pos_by_uid = _unit_features(account, presets, req, unit_ids)

    best: Optional[_Candidate] = None
    candidates_done = 0
    no_improve_streak = 0
    no_improve_patience = int(max(10, min(80, max_cpu_evals // 4)))
    screened_total = 0
    batch_count = 0
    gpu_batch_count = 0
    next_variant_idx = 0
    elite: List[_Variant] = _generate_variants(unit_ids, min(24, max(2, len(unit_ids) * 2)), rng, speed_slack_base)
    evaluated_keys: Set[Tuple[Tuple[int, ...], bool, str, int, int, int, int, int, int]] = set()

    while candidates_done < max_cpu_evals:
        if req.is_cancelled and req.is_cancelled():
            break
        if (time.perf_counter() - started) > time_budget_s:
            break
        batch_count += 1
        cycle_elite: List[_Variant] = list(elite)
        for _ in range(gpu_batches_per_cycle):
            variants = _build_variant_batch(
                unit_ids=unit_ids,
                elite=cycle_elite,
                batch_size=batch_size,
                rng=rng,
                speed_slack_base=speed_slack_base,
                idx_start=next_variant_idx,
            )
            next_variant_idx += len(variants)
            screened_total += len(variants)
            gpu_batch_count += 1

            ranked_idx = _rank_variants_with_torch(
                variants=variants,
                unit_ids=unit_ids,
                features_by_uid=features_by_uid,
                seed_pos_by_uid=seed_pos_by_uid,
                backend=backend,
                torch_mod=torch_mod,
            )
            if not ranked_idx:
                break
            safe_idx = [int(i) for i in ranked_idx if 0 <= int(i) < len(variants)]
            if not safe_idx:
                break
            cycle_elite = [variants[i] for i in safe_idx[:elite_size]]
            if req.is_cancelled and req.is_cancelled():
                break
            if (time.perf_counter() - started) > time_budget_s:
                break
        elite = list(cycle_elite)
        if not elite:
            break
        eval_variants: List[_Variant] = []
        for v in elite:
            key = _variant_key(v)
            if key in evaluated_keys:
                continue
            evaluated_keys.add(key)
            eval_variants.append(v)
            if len(eval_variants) >= cpu_eval_batch:
                break
        if not eval_variants:
            continue

        for var in eval_variants:
            if req.is_cancelled and req.is_cancelled():
                break
            if (time.perf_counter() - started) > time_budget_s:
                break
            if req.progress_callback:
                try:
                    req.progress_callback(min(candidates_done + 1, max_cpu_evals), max_cpu_evals)
                except Exception:
                    pass

            order = list(var.order)
            if candidates_done % 7 == 0:
                results = _run_greedy_pass(
                    account=account,
                    presets=presets,
                    req=req,
                    unit_ids=order,
                    time_limit_per_unit_s=float(req.time_limit_per_unit_s),
                    speed_slack_for_quality=0,
                    rune_top_per_set_override=max(0, int(getattr(req, "rune_top_per_set", 200) or 200)),
                )
            else:
                avoid_map: Optional[Dict[int, GreedyUnitResult]] = None
                if best is not None and best.results:
                    avoid_map = {int(r.unit_id): r for r in best.results if r.ok}
                results = _run_pass_with_profile(
                    account=account,
                    presets=presets,
                    req=req,
                    unit_ids=order,
                    time_limit_per_unit_s=max(0.8, float(req.time_limit_per_unit_s) * 0.95),
                    speed_hard_priority=bool(var.speed_hard),
                    build_priority_penalty=int(var.build_penalty),
                    set_option_preference_offset_base=int(var.set_pref_offset),
                    set_option_preference_bonus=int(var.set_pref_bonus),
                    avoid_solution_by_unit=avoid_map,
                    avoid_same_rune_penalty=int(var.avoid_rune_penalty),
                    avoid_same_artifact_penalty=int(var.avoid_art_penalty),
                    speed_slack_for_quality=int(var.speed_slack),
                    objective_mode=str(var.objective_mode),
                    rune_top_per_set_override=max(0, int(getattr(req, "rune_top_per_set", 200) or 200)),
                )
            if not results:
                continue

            score = _evaluate_pass_score(account, req, results)
            cur = _Candidate(idx=int(var.idx), score=score, results=results)
            candidates_done += 1
            if best is None or cur.score > best.score:
                best = cur
                no_improve_streak = 0
            else:
                no_improve_streak += 1

            if no_improve_streak >= no_improve_patience and candidates_done >= max(12, cpu_eval_batch * 2):
                break
        if no_improve_streak >= no_improve_patience and candidates_done >= max(12, cpu_eval_batch * 2):
            break

    if best is None:
        if req.is_cancelled and req.is_cancelled():
            return GreedyResult(False, tr("opt.cancelled"), [])
        return GreedyResult(False, tr("opt.partial_fail"), [])

    if req.is_cancelled and req.is_cancelled():
        return GreedyResult(False, tr("opt.cancelled"), best.results)

    ok_all = all(r.ok for r in best.results)
    prefix = tr("opt.ok") if ok_all else tr("opt.partial_fail")
    msg = (
        f"{prefix} GPU search [{profile}] ({backend}): screened {int(max(1, screened_total))} variants in {int(max(1, gpu_batch_count))} GPU batches/{int(max(1, batch_count))} cycles, "
        f"evaluated {int(max(1, candidates_done))}/{int(max_cpu_evals)}."
    )
    return GreedyResult(ok_all, msg, best.results)
