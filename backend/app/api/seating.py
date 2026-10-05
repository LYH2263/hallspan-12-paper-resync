import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Hall
from app.services.plan_service import get_active_plan, run_new_plan
router = APIRouter(prefix="/seating", tags=["seating"])

@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    result = run_new_plan(db, hall)
    db.commit()
    return result

def _latest_data(hall_id: int, db: Session) -> tuple[int | None, dict]:
    """返回当前有效方案（无则当场跑一场）。最新图/违规/统计同源，杜绝只改一处。"""
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    plan = get_active_plan(db, hall_id)
    if plan is None:
        result = run_new_plan(db, hall)
        db.commit()
        return result["id"], result
    return plan.id, json.loads(plan.result_json or "{}")

@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    plan_id, data = _latest_data(hall_id, db)
    return {"id": plan_id, **data}

@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    _, data = _latest_data(hall_id, db)
    return {"hall_id": hall_id, "violations": data.get("violations", []), "unplaced": data.get("unplaced", [])}

@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    _, data = _latest_data(hall_id, db)
    return {"hall_id": hall_id, **data.get("stats", {})}
