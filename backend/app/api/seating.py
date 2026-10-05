import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Hall
from app.services.plan_service import build_seat_plan, latest_plan
router = APIRouter(prefix="/seating", tags=["seating"])

@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall: raise HTTPException(404, "考室不存在")
    plan, result = build_seat_plan(db, hall)
    db.commit()
    return {"id": plan.id, **result}

@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    plan = latest_plan(db, hall_id)
    if not plan:
        return run_seating(hall_id=hall_id, db=db)
    data = json.loads(plan.result_json)
    return {"id": plan.id, **data}

@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, "violations": data.get("violations", []), "unplaced": data.get("unplaced", [])}

@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, **data.get("stats", {})}
