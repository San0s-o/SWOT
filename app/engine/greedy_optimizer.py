from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Set, Optional

from ortools.sat.python import cp_model

from app.domain.models import AccountData, Rune
from app.domain.presets import (
    BuildStore,
    Build,
    SET_ID_BY_NAME,
    SET_SIZES,
    EFFECT_ID_TO_MAINSTAT_KEY,
)

STAT_SCORE_WEIGHTS: Dict[int, int] = {
    1: 1,   # HP flat
    2: 8,   # HP%
    3: 1,   # ATK flat
    4: 8,   # ATK%
    5: 1,   # DEF flat
    6: 8,   # DEF%
    8: 18,  # SPD
    9: 10,  # CR
    10: 9,  # CD
    11: 4,  # RES
    12: 4,  # ACC
}

SET_SCORE_BONUS: Dict[int, int] = {
    3: 160,   # Swift
    13: 140,  # Violent
    15: 90,   # Will
    10: 80,   # Despair
    17: 70,   # Revenge
    11: 70,   # Vampire
    5: 60,    # Rage
    8: 60,    # Fatal
}


def _score_stat(eff_id: int, value: int) -> int:
    eff = int(eff_id or 0)
    return int(STAT_SCORE_WEIGHTS.get(eff, 0) * int(value or 0))


def _is_good_even_slot_mainstat(eff_id: int, slot_no: int) -> bool:
    if slot_no not in (2, 4, 6):
        return True
    return int(eff_id or 0) in (2, 4, 6, 8, 9, 10, 11, 12)


def _rune_quality_score(r: Rune, uid: int,
                        rta_rune_ids_for_unit: Optional[Set[int]] = None) -> int:
    score = 0
    score += int(r.upgrade_curr or 0) * 8
    score += int(r.rank or 0) * 6
    score += int(r.rune_class or 0) * 10
    score += int(SET_SCORE_BONUS.get(int(r.set_id or 0), 0))

    # Main stat and prefix stat
    score += _score_stat(int(r.pri_eff[0] or 0), int(r.pri_eff[1] or 0))
    score += _score_stat(int(r.prefix_eff[0] or 0), int(r.prefix_eff[1] or 0))

    # Penalize flat mains on even slots when no build mainstat forces it
    if not _is_good_even_slot_mainstat(int(r.pri_eff[0] or 0), int(r.slot_no or 0)):
        score -= 140

    # Substats incl. grind
    for sec in (r.sec_eff or []):
        if not sec:
            continue
        eff_id = int(sec[0] or 0)
        val = int(sec[1] or 0)
        grind = int(sec[3] or 0) if len(sec) >= 4 else 0
        score += _score_stat(eff_id, val + grind)

    # Keep currently equipped rune on same unit slightly preferred
    if rta_rune_ids_for_unit is not None:
        # RTA mode: prefer runes that are RTA-equipped on this unit
        if r.rune_id in rta_rune_ids_for_unit:
            score += 45
    elif r.occupied_type == 1 and r.occupied_id == uid:
        score += 45

    return score


@dataclass
class GreedyRequest:
    mode: str
    unit_ids_in_order: List[int]   # Reihenfolge = Priorität (wie SWOP)
    time_limit_per_unit_s: float = 10.0
    workers: int = 8
    enforce_turn_order: bool = False
    unit_team_index: Dict[int, int] | None = None
    unit_team_turn_order: Dict[int, int] | None = None

@dataclass
class GreedyUnitResult:
    unit_id: int
    ok: bool
    message: str
    chosen_build_id: str = ""
    chosen_build_name: str = ""
    runes_by_slot: Dict[int, int] = None  # slot -> rune_id
    final_speed: int = 0


@dataclass
class GreedyResult:
    ok: bool
    message: str
    results: List[GreedyUnitResult]


def _allowed_runes_for_mode(account: AccountData, selected_unit_ids: List[int]) -> List[Rune]:
    # User requested full account pool: use every rune from the JSON snapshot/import.
    return list(account.runes)


def _count_required_set_pieces(set_names: List[str]) -> Dict[int, int]:
    needed: Dict[int, int] = {}
    for name in set_names:
        sid = SET_ID_BY_NAME.get(name)
        if not sid:
            continue
        needed[sid] = needed.get(sid, 0) + int(SET_SIZES.get(sid, 2))
    return needed


def _rune_flat_spd(r: Rune) -> int:
    total = 0
    try:
        if int(r.pri_eff[0] or 0) == 8:
            total += int(r.pri_eff[1] or 0)
    except Exception:
        pass
    try:
        if int(r.prefix_eff[0] or 0) == 8:
            total += int(r.prefix_eff[1] or 0)
    except Exception:
        pass
    for sec in (r.sec_eff or []):
        if not sec:
            continue
        try:
            if int(sec[0] or 0) != 8:
                continue
            total += int(sec[1] or 0)
            if len(sec) >= 4:
                total += int(sec[3] or 0)
        except Exception:
            continue
    return total


def _rune_stat_total(r: Rune, eff_id_target: int) -> int:
    total = 0
    try:
        if int(r.pri_eff[0] or 0) == eff_id_target:
            total += int(r.pri_eff[1] or 0)
    except Exception:
        pass
    try:
        if int(r.prefix_eff[0] or 0) == eff_id_target:
            total += int(r.prefix_eff[1] or 0)
    except Exception:
        pass
    for sec in (r.sec_eff or []):
        if not sec:
            continue
        try:
            if int(sec[0] or 0) != eff_id_target:
                continue
            total += int(sec[1] or 0)
            if len(sec) >= 4:
                total += int(sec[3] or 0)
        except Exception:
            continue
    return total


def _diagnose_single_unit_infeasible(pool: List[Rune], builds: List[Build]) -> str:
    runes_by_slot: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= r.slot_no <= 6:
            runes_by_slot[r.slot_no].append(r)

    for s in range(1, 7):
        if not runes_by_slot[s]:
            return f"Slot {s}: keine Runen im Pool."

    if not builds:
        return "Keine Builds vorhanden."

    reasons: List[str] = []
    for b in builds:
        # Mainstat feasibility
        ok_main = True
        for slot in (2, 4, 6):
            allowed = (b.mainstats or {}).get(slot) or []
            if not allowed:
                continue
            cnt = 0
            for r in runes_by_slot[slot]:
                key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(r.pri_eff[0] or 0), "")
                if key in allowed:
                    cnt += 1
            if cnt == 0:
                ok_main = False
                reasons.append(f"Build '{b.name}': Slot {slot} Mainstat {allowed} nicht verfügbar.")
                break

        if not ok_main:
            continue

        # Set feasibility
        if not b.set_options:
            return "Build ist bzgl. Set/Mainstats grundsätzlich machbar."

        feasible_any_option = False
        for opt in b.set_options:
            needed = _count_required_set_pieces([str(s) for s in opt])
            total_pieces = sum(int(v) for v in needed.values())
            if total_pieces > 6:
                reasons.append(f"Build '{b.name}': Set-Option {opt} verlangt {total_pieces} Teile (>6).")
                continue
            ok_opt = True
            for set_id, pieces in needed.items():
                avail = 0
                for slot in range(1, 7):
                    avail += sum(1 for r in runes_by_slot[slot] if int(r.set_id) == int(set_id))
                if avail < pieces:
                    ok_opt = False
                    reasons.append(
                        f"Build '{b.name}': Set {set_id} braucht {pieces}, verfügbar {avail}."
                    )
                    break
            if ok_opt:
                feasible_any_option = True
                break

        if feasible_any_option:
            return "Build ist bzgl. Set/Mainstats grundsätzlich machbar."

    if reasons:
        return " | ".join(reasons[:3])
    return "Infeasible: Pool/Build-Constraints passen nicht zusammen."


def _solve_single_unit_best(
    uid: int,
    pool: List[Rune],
    builds: List[Build],
    time_limit_s: float,
    workers: int,
    base_spd: int,
    base_cr: int,
    base_cd: int,
    base_res: int,
    base_acc: int,
    max_final_speed: Optional[int],
    rta_rune_ids_for_unit: Optional[Set[int]] = None,
) -> GreedyUnitResult:
    """
    Solve for ONE unit:
    - pick exactly 1 rune per slot (1..6)
    - pick exactly 1 build
    - enforce build mainstats (2/4/6) + build set_option
    - objective: maximize rune weight - priority penalty
    """
    # candidates by slot
    runes_by_slot: Dict[int, List[Rune]] = {s: [] for s in range(1, 7)}
    for r in pool:
        if 1 <= r.slot_no <= 6:
            runes_by_slot[r.slot_no].append(r)

    # Hard feasibility: each slot must have >= 1 candidate
    for s in range(1, 7):
        if not runes_by_slot[s]:
            return GreedyUnitResult(uid, False, f"Slot {s}: keine Runen im Pool.", runes_by_slot={})

    model = cp_model.CpModel()

    # x[slot, rune_id]
    x: Dict[Tuple[int, int], cp_model.IntVar] = {}
    for slot in range(1, 7):
        vs = []
        for r in runes_by_slot[slot]:
            v = model.NewBoolVar(f"x_u{uid}_s{slot}_r{r.rune_id}")
            x[(slot, r.rune_id)] = v
            vs.append(v)
        model.Add(sum(vs) == 1)

    # rune unique within this unit is automatically true because each rune has fixed slot,
    # but keep it safe anyway (in case slot_no mismatch exists)
    for r in pool:
        uses = []
        for slot in range(1, 7):
            key = (slot, r.rune_id)
            if key in x:
                uses.append(x[key])
        if uses:
            model.Add(sum(uses) <= 1)

    # build selection
    if not builds:
        builds = [Build.default_any()]

    use_build: Dict[int, cp_model.IntVar] = {}
    for b_idx, b in enumerate(builds):
        use_build[b_idx] = model.NewBoolVar(f"use_build_u{uid}_b{b_idx}")
    model.Add(sum(use_build.values()) == 1)

    # for each build, add constraints only if chosen
    # set options: if present => choose one option if build chosen
    for b_idx, b in enumerate(builds):
        vb = use_build[b_idx]

        # mainstats
        for slot in (2, 4, 6):
            allowed = (b.mainstats or {}).get(slot) or []
            if not allowed:
                continue
            for r in runes_by_slot[slot]:
                key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(r.pri_eff[0] or 0), "")
                if key and (key not in allowed):
                    model.Add(x[(slot, r.rune_id)] == 0).OnlyEnforceIf(vb)

        # sets
        if b.set_options:
            opt_vars = []
            for o_idx, _ in enumerate(b.set_options):
                opt_vars.append(model.NewBoolVar(f"use_opt_u{uid}_b{b_idx}_o{o_idx}"))

            model.Add(sum(opt_vars) == 1).OnlyEnforceIf(vb)
            model.Add(sum(opt_vars) == 0).OnlyEnforceIf(vb.Not())

            for o_idx, opt in enumerate(b.set_options):
                vo = opt_vars[o_idx]
                needed = _count_required_set_pieces([str(s) for s in opt])

                for set_id, pieces in needed.items():
                    chosen_set_vars = []
                    for slot in range(1, 7):
                        for r in runes_by_slot[slot]:
                            if r.set_id == set_id:
                                chosen_set_vars.append(x[(slot, r.rune_id)])
                    if not chosen_set_vars:
                        model.Add(vo == 0)
                        continue
                    model.Add(sum(chosen_set_vars) >= int(pieces)).OnlyEnforceIf(vo)

        # min stat thresholds
        min_stats = dict(getattr(b, "min_stats", {}) or {})
        if min_stats:
            cr_terms = []
            cd_terms = []
            res_terms = []
            acc_terms = []
            for slot in range(1, 7):
                for r in runes_by_slot[slot]:
                    xv = x[(slot, r.rune_id)]
                    cr = _rune_stat_total(r, 9)
                    cd = _rune_stat_total(r, 10)
                    res = _rune_stat_total(r, 11)
                    acc = _rune_stat_total(r, 12)
                    if cr:
                        cr_terms.append(cr * xv)
                    if cd:
                        cd_terms.append(cd * xv)
                    if res:
                        res_terms.append(res * xv)
                    if acc:
                        acc_terms.append(acc * xv)

            if int(min_stats.get("CR", 0) or 0) > 0:
                model.Add(base_cr + sum(cr_terms) >= int(min_stats["CR"])).OnlyEnforceIf(vb)
            if int(min_stats.get("CD", 0) or 0) > 0:
                model.Add(base_cd + sum(cd_terms) >= int(min_stats["CD"])).OnlyEnforceIf(vb)
            if int(min_stats.get("RES", 0) or 0) > 0:
                model.Add(base_res + sum(res_terms) >= int(min_stats["RES"])).OnlyEnforceIf(vb)
            if int(min_stats.get("ACC", 0) or 0) > 0:
                model.Add(base_acc + sum(acc_terms) >= int(min_stats["ACC"])).OnlyEnforceIf(vb)

    # speed expression (for SPD-first)
    speed_terms = []
    swift_piece_vars = []
    swift_bonus_value = int(int(base_spd or 0) * 25 / 100)
    for slot in range(1, 7):
        for r in runes_by_slot[slot]:
            v = x[(slot, r.rune_id)]
            spd = _rune_flat_spd(r)
            if spd:
                speed_terms.append(spd * v)
            if int(r.set_id or 0) == 3:
                swift_piece_vars.append(v)

    swift_set_active = model.NewBoolVar(f"swift_set_u{uid}")
    swift_count = sum(swift_piece_vars) if swift_piece_vars else 0
    if swift_piece_vars:
        model.Add(swift_count >= 4).OnlyEnforceIf(swift_set_active)
        model.Add(swift_count <= 3).OnlyEnforceIf(swift_set_active.Not())
    else:
        model.Add(swift_set_active == 0)

    final_speed_expr = int(base_spd or 0) + sum(speed_terms) + (swift_bonus_value * swift_set_active)
    if max_final_speed is not None and max_final_speed > 0:
        model.Add(final_speed_expr <= int(max_final_speed))

    for b_idx, b in enumerate(builds):
        vb = use_build[b_idx]
        min_spd = int((getattr(b, "min_stats", {}) or {}).get("SPD", 0) or 0)
        if min_spd > 0:
            model.Add(final_speed_expr >= min_spd).OnlyEnforceIf(vb)

    # quality objective (2nd phase after speed is pinned)
    quality_terms = []
    for slot in range(1, 7):
        for r in runes_by_slot[slot]:
            v = x[(slot, r.rune_id)]
            w = _rune_quality_score(r, uid, rta_rune_ids_for_unit)
            quality_terms.append(w * v)

    BUILD_PRIORITY_PENALTY = 200
    for b_idx, b in enumerate(builds):
        quality_terms.append((-int(b.priority) * BUILD_PRIORITY_PENALTY) * use_build[b_idx])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit_s)
    solver.parameters.num_search_workers = int(workers)

    model.Maximize(final_speed_expr)
    status = solver.Solve(model)
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        best_speed = int(solver.Value(final_speed_expr))
        model.Add(final_speed_expr == best_speed)
        model.Maximize(sum(quality_terms))
        status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        detail = _diagnose_single_unit_infeasible(pool, builds)
        return GreedyUnitResult(uid, False, f"infeasible ({detail})", runes_by_slot={})

    # extract build
    chosen_build = builds[0]
    for b_idx, b in enumerate(builds):
        if solver.Value(use_build[b_idx]) == 1:
            chosen_build = b
            break

    chosen: Dict[int, int] = {}
    for slot in range(1, 7):
        rid = None
        for r in runes_by_slot[slot]:
            if solver.Value(x[(slot, r.rune_id)]) == 1:
                rid = r.rune_id
                break
        if rid is None:
            return GreedyUnitResult(uid, False, f"interner Fehler: Slot {slot} keine Rune.", runes_by_slot={})
        chosen[slot] = rid

    return GreedyUnitResult(
        unit_id=uid,
        ok=True,
        message="OK",
        chosen_build_id=chosen_build.id,
        chosen_build_name=chosen_build.name,
        runes_by_slot=chosen,
        final_speed=int(solver.Value(final_speed_expr)),
    )


def optimize_greedy(account: AccountData, presets: BuildStore, req: GreedyRequest) -> GreedyResult:
    """
    SWOP-like greedy:
    - iterates units in given order
    - for each unit: solve best assignment under current pool
    - remove chosen runes from pool (block)
    """
    unit_ids = list(req.unit_ids_in_order)
    if not unit_ids:
        return GreedyResult(False, "Keine Units.", [])

    # When enforce_turn_order is active, reorder units within each team
    # so that lower turn_order values are optimized first.  This ensures
    # the speed cap mechanism works correctly (unit with turn_order=1 is
    # optimized first -> gets fastest runes -> turn_order=2 is capped below it).
    if req.enforce_turn_order and req.unit_team_index and req.unit_team_turn_order:
        team_queues: Dict[int, List[int]] = {}
        for uid in unit_ids:
            team = req.unit_team_index.get(int(uid))
            if team is not None:
                team_queues.setdefault(int(team), []).append(int(uid))
        for team in team_queues:
            orig = list(team_queues[team])
            team_queues[team].sort(
                key=lambda u, _o=orig: (
                    int(req.unit_team_turn_order.get(u, 0) or 0) or 999,
                    _o.index(u),
                )
            )
        team_iters: Dict[int, int] = {t: 0 for t in team_queues}
        reordered: List[int] = []
        for uid in unit_ids:
            team = req.unit_team_index.get(int(uid))
            if team is not None and int(team) in team_queues:
                t = int(team)
                reordered.append(team_queues[t][team_iters[t]])
                team_iters[t] += 1
            else:
                reordered.append(int(uid))
        unit_ids = reordered

    # initial pool
    pool = _allowed_runes_for_mode(account, unit_ids)
    blocked: Set[int] = set()  # rune_id

    # For RTA mode, build lookup of RTA-equipped rune IDs per unit
    rta_equip = account.rta_rune_equip if req.mode == "rta" else {}

    results: List[GreedyUnitResult] = []

    for uid in unit_ids:
        cur_pool = [r for r in pool if r.rune_id not in blocked]
        unit = account.units_by_id.get(uid)
        base_spd = int(unit.base_spd or 0) if unit else 0
        base_cr = int(unit.crit_rate or 15) if unit else 15
        base_cd = int(unit.crit_dmg or 50) if unit else 50
        base_res = int(unit.base_res or 15) if unit else 15
        base_acc = int(unit.base_acc or 0) if unit else 0
        max_speed_cap: Optional[int] = None
        if req.enforce_turn_order:
            team_idx_map = req.unit_team_index or {}
            team_turn_map = req.unit_team_turn_order or {}
            my_team = team_idx_map.get(int(uid))
            my_turn = int(team_turn_map.get(int(uid), 0) or 0)
            if my_team is not None and my_turn > 1:
                prev_caps: List[int] = []
                for prev in results:
                    if not prev.ok:
                        continue
                    puid = int(prev.unit_id)
                    if team_idx_map.get(puid) != my_team:
                        continue
                    pturn = int(team_turn_map.get(puid, 0) or 0)
                    if pturn > 0 and pturn < my_turn and int(prev.final_speed or 0) > 1:
                        prev_caps.append(int(prev.final_speed) - 1)
                if prev_caps:
                    max_speed_cap = min(prev_caps)

        # RTA mode: pass RTA-equipped rune IDs for scoring preference
        rta_rids: Optional[Set[int]] = None
        if rta_equip:
            rta_rids = set(int(rid) for rid in rta_equip.get(uid, []))

        builds = presets.get_unit_builds(req.mode, uid)
        # IMPORTANT: greedy feels more SWOP-like if we sort builds by priority ascending
        builds = sorted(builds, key=lambda b: int(b.priority))

        r = _solve_single_unit_best(
            uid=uid,
            pool=cur_pool,
            builds=builds,
            time_limit_s=req.time_limit_per_unit_s,
            workers=req.workers,
            base_spd=base_spd,
            base_cr=base_cr,
            base_cd=base_cd,
            base_res=base_res,
            base_acc=base_acc,
            max_final_speed=max_speed_cap,
            rta_rune_ids_for_unit=rta_rids,
        )
        results.append(r)

        if r.ok and r.runes_by_slot:
            for rid in r.runes_by_slot.values():
                blocked.add(int(rid))
        else:
            # SWOP-like: keep going, but mark as failed
            # (alternativ: break; wenn du "alles muss klappen" willst)
            pass

    ok_all = all(r.ok for r in results)
    msg = "OK" if ok_all else "Fertig, aber mindestens ein Monster konnte nicht gebaut werden."
    return GreedyResult(ok_all, msg, results)


