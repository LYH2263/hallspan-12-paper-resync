"""排座方案的落库与读取：每室至多一个 is_active 有效方案，历史方案 result_json 永不修改。"""
from __future__ import annotations
import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, SeatPlan
from app.services.seat_engine import (
    find_violations, plan_to_dict, place_candidates, recompute_plan,
)


def hall_roster(db: Session, hall_id: int) -> list[dict]:
    return [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(
            select(Candidate).where(Candidate.hall_id == hall_id).order_by(Candidate.id)
        ).all()
    ]


def get_active_plan(db: Session, hall_id: int) -> SeatPlan | None:
    """当前有效方案：优先 is_active；没有显式标志时退到最新一行。"""
    plan = db.scalars(
        select(SeatPlan)
        .where(SeatPlan.hall_id == hall_id, SeatPlan.is_active.is_(True))
        .order_by(SeatPlan.id.desc())
    ).first()
    if plan:
        return plan
    return db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()


def _deactivate_hall(db: Session, hall_id: int) -> None:
    for p in db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id, SeatPlan.is_active.is_(True))
    ).all():
        p.is_active = False


def _persist(db: Session, hall: Hall, result: dict) -> SeatPlan:
    """同一事务内：旧有效方案置 inactive（其 result_json 不动），写入新的有效方案。"""
    _deactivate_hall(db, hall.id)
    plan = SeatPlan(
        hall_id=hall.id,
        created_at=datetime.utcnow(),
        result_json=json.dumps(result, ensure_ascii=False),
        is_active=True,
    )
    db.add(plan)
    db.flush()
    return plan


def run_new_plan(db: Session, hall: Hall) -> dict:
    roster = hall_roster(db, hall.id)
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, roster)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = _persist(db, hall, result)
    return {"id": plan.id, **result}


def recompute_after_paper_change(
    db: Session, hall: Hall, changed_id: int, active: SeatPlan
) -> dict:
    """按新名单重算有效方案。调用方须已在事务内把 changed_id 的 paper_id 改好。

    重算失败（SeatingConflict）时向上抛出，由端点回滚，字段与方案同归于尽。
    """
    roster = hall_roster(db, hall.id)
    old = json.loads(active.result_json or "{}")
    assigns, unplaced = recompute_plan(
        hall.rows, hall.cols, hall.min_manhattan, roster,
        old.get("assignments", []), {changed_id},
    )
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = _persist(db, hall, result)
    return {"id": plan.id, **result}
