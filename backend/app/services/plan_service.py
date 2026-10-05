"""Build and persist seat-plan snapshots for a hall.

Shared by ``/seating/run`` and the candidate paper-change endpoint so a plan
always reflects the roster (and paper sets) at call time. The caller owns the
transaction: these helpers flush but never commit, so a paper-set update and
its regenerated plan commit together or roll back together.
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import Candidate, Hall, SeatPlan
from app.services.seat_engine import find_violations, place_candidates, plan_to_dict


def latest_plan(db: Session, hall_id: int) -> SeatPlan | None:
    """The hall's current effective plan (most recent snapshot), if any."""
    return db.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())
    ).first()


def build_seat_plan(db: Session, hall: Hall) -> tuple[SeatPlan, dict]:
    """Recompute seating from the CURRENT roster and append a new plan snapshot.

    Reads candidates through ``db`` so uncommitted roster changes made earlier
    in the same transaction (e.g. a paper-set swap) are what get seated.
    Historical plans are never modified.
    """
    cands = [
        {"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
        for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall.id)).all()
    ]
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = SeatPlan(
        hall_id=hall.id,
        created_at=datetime.utcnow(),
        result_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(plan)
    db.flush()
    return plan, result
