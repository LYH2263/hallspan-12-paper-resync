"""Exam seating: min Manhattan distance; same paper_id cannot be 4-neighbor adjacent."""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass
class SeatAssign:
    candidate_id: int
    name: str
    ticket_no: str
    paper_id: int
    row: int
    col: int

@dataclass
class Violation:
    kind: str
    a_id: int
    b_id: int
    detail: str

class SeatingConflict(Exception):
    """换套重排后仍无法在不违反间距/邻接禁则的前提下为换套考生入座。

    抛出即表示：禁止落库“字段已新而图仍旧”的半成品，调用方必须整场回滚。
    """

def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])

def neighbors4(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int]]:
    out = []
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc))
    return out

def _seat_ok(rows: int, cols: int, min_dist: int,
             occupied: dict[tuple[int, int], SeatAssign],
             r: int, c: int, paper_id: int) -> bool:
    """空位 (r,c) 是否可放 paper_id：与所有已放者曼哈顿 >= min_dist，且四邻无同套。"""
    for pos, other in occupied.items():
        if manhattan((r, c), pos) < min_dist:
            return False
        if other.paper_id == paper_id and (r, c) in neighbors4(pos[0], pos[1], rows, cols):
            return False
    return True

def _greedy(rows: int, cols: int, min_dist: int, candidates: list[dict],
            occupied: dict[tuple[int, int], SeatAssign] | None = None
            ) -> tuple[dict[tuple[int, int], SeatAssign], list[dict]]:
    """按行主序贪心放置；occupied 可为预置的固定座位。返回 (座位表, 未排名单)。"""
    occupied = dict(occupied or {})
    unplaced: list[dict] = []
    for cand in candidates:
        placed = False
        for r in range(rows):
            for c in range(cols):
                if (r, c) in occupied:
                    continue
                if not _seat_ok(rows, cols, min_dist, occupied, r, c, cand["paper_id"]):
                    continue
                occupied[(r, c)] = SeatAssign(
                    cand["id"], cand["name"], cand["ticket_no"], cand["paper_id"], r, c)
                placed = True
                break
            if placed:
                break
        if not placed:
            unplaced.append(cand)
    return occupied, unplaced

def place_candidates(rows: int, cols: int, min_dist: int, candidates: list[dict]
                     ) -> tuple[list[SeatAssign], list[dict]]:
    """Greedy: try seats row-major; accept if manhattan >= min_dist to all placed AND no same paper 4-neigh."""
    occupied, unplaced = _greedy(rows, cols, min_dist, candidates)
    return list(occupied.values()), unplaced

def find_violations(rows: int, cols: int, min_dist: int, assigns: list[SeatAssign]) -> list[Violation]:
    viols: list[Violation] = []
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            d = manhattan((a.row, a.col), (b.row, b.col))
            if d < min_dist:
                viols.append(Violation("distance", a.candidate_id, b.candidate_id,
                                       f"曼哈顿距离 {d} < 最小要求 {min_dist}"))
            if a.paper_id == b.paper_id and (b.row, b.col) in neighbors4(a.row, a.col, rows, cols):
                viols.append(Violation("same_paper_adjacent", a.candidate_id, b.candidate_id,
                                       f"同试卷套 {a.paper_id} 四邻相邻"))
    return viols

def recompute_plan(rows: int, cols: int, min_dist: int, candidates: list[dict],
                   old_assigns: list[dict], changed_ids: set[int]
                   ) -> tuple[list[SeatAssign], list[dict]]:
    """考生换套后按【新名单】重算邻接与未排。

    策略：
    1. 稳定重排——未换套且此前在座的考生座位不动，腾空换套者旧座，连同旧未排名单
       按新套别补排；本就未排的换套者可继续未排，不强制入座；
    2. 稳定重排若让“此前在座的换套者”失去座位，或留下间距/同套邻接违规，
       升级为整场重新贪心排座；
    3. 整场重排后旧方案里任何已座考生被挤出，或仍有同套四邻相邻 → SeatingConflict，
       由调用方整场回滚，杜绝字段已新而图仍旧。

    candidates 已为新套别，old_assigns 为旧方案快照；
    返回的 assignments/unplaced/violations 一律按新套别。
    """
    roster = {c["id"]: c for c in candidates}
    changed_ids = {cid for cid in changed_ids if cid in roster}

    def full_rerun() -> tuple[list[SeatAssign], list[dict]]:
        assigns, unplaced = place_candidates(rows, cols, min_dist, candidates)
        new_seated = {a.candidate_id for a in assigns}
        # 换套不能连累无辜：旧方案里已座且仍在名单的考生，重排后必须全部在座。
        displaced = old_seated_ids - new_seated
        if displaced:
            raise SeatingConflict(
                "换套重排会导致其他已座考生失去座位（与邻座同套触发邻接禁则）")
        residual = find_violations(rows, cols, min_dist, assigns)
        if any(v.kind == "same_paper_adjacent" for v in residual):
            raise SeatingConflict("整场重排后仍存在同试卷套四邻相邻")
        return assigns, unplaced

    # 旧方案中已座且仍在名单的考生集合：成功重排后这些人一个都不能少
    old_seated_ids = {
        a.get("candidate_id") for a in old_assigns if a.get("candidate_id") in roster
    }
    # 只有“此前在座、现在换套”的考生才必须保住座位；本来就未排的换套者可继续未排
    changed_were_seated = changed_ids & old_seated_ids

    if not old_assigns:
        # 无旧方案（理论上 API 不会进入，这里保持纯贪心语义）
        occupied, unplaced = _greedy(rows, cols, min_dist, candidates)
        return list(occupied.values()), unplaced

    # 1) 固定未换套且仍在名单中的旧座位，paper_id 以新名单为准
    fixed: dict[tuple[int, int], SeatAssign] = {}
    seated_ids: set[int] = set()
    corrupt = False
    for a in old_assigns:
        cid = a.get("candidate_id")
        pos = (a.get("row"), a.get("col"))
        if cid not in roster or cid in changed_ids:
            continue
        if pos in fixed:
            corrupt = True
            break
        c = roster[cid]
        fixed[pos] = SeatAssign(cid, c["name"], c["ticket_no"], c["paper_id"], pos[0], pos[1])
        seated_ids.add(cid)

    if corrupt:
        return full_rerun()

    pending = [c for c in candidates if c["id"] not in seated_ids]
    occupied, unplaced = _greedy(rows, cols, min_dist, pending, occupied=fixed)
    assigns = list(occupied.values())
    viols = find_violations(rows, cols, min_dist, assigns)
    unplaced_ids = {u["id"] for u in unplaced}
    # 此前在座的换套者必须仍在座；本就未排的换套者不强制入座
    stable_ok = not viols and not (changed_were_seated & unplaced_ids)
    if stable_ok:
        # 未排名单按新名单顺序、新套别输出
        unplaced = [c for c in candidates if c["id"] not in {a.candidate_id for a in assigns}]
        return assigns, unplaced

    # 2) 稳定重排失败 → 整场重排（成功则邻接消失，失败则抛错回滚）
    return full_rerun()

def plan_to_dict(assigns: list[SeatAssign], unplaced: list[dict], viols: list[Violation], rows: int, cols: int) -> dict:
    return {
        "rows": rows,
        "cols": cols,
        "assignments": [asdict(a) for a in assigns],
        "unplaced": unplaced,
        "violations": [asdict(v) for v in viols],
        "stats": {
            "seated": len(assigns),
            "unplaced": len(unplaced),
            "violations": len(viols),
            "capacity": rows * cols,
        },
    }
