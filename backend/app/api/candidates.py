from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, PaperSet
from app.services.plan_service import build_seat_plan, latest_plan
router = APIRouter(prefix="/candidates", tags=["candidates"])

@router.get("")
def list_candidates(db: Session = Depends(get_db)):
    return [{"id": r.id, "hall_id": r.hall_id, "name": r.name, "ticket_no": r.ticket_no, "paper_id": r.paper_id}
            for r in db.scalars(select(Candidate).order_by(Candidate.id)).all()]

class PaperChangeIn(BaseModel):
    paper_id: int

@router.put("/{candidate_id}/paper")
def change_paper(candidate_id: int, body: PaperChangeIn, db: Session = Depends(get_db)):
    """更换考生试卷套。

    与该室当前有效方案原子提交：套别字段、最新排座图、违规/未排列表要么一起
    更新，要么一起回滚；历史方案快照保持不动。套别不存在则拒绝，名单、图、
    统计全部停在拒绝前。
    """
    cand = db.get(Candidate, candidate_id)
    if not cand:
        raise HTTPException(404, "考生不存在")
    paper = db.get(PaperSet, body.paper_id)
    if not paper:
        raise HTTPException(404, "试卷套不存在")
    if cand.paper_id == paper.id:
        return {"candidate": _candidate_dict(cand), "plan": None}
    try:
        cand.paper_id = paper.id
        db.flush()
        plan_payload = None
        if latest_plan(db, cand.hall_id) is not None:
            # 该室已有有效方案：按新套别同事务重算邻接与未排，追加新快照
            hall = db.get(Hall, cand.hall_id)
            plan, result = build_seat_plan(db, hall)
            plan_payload = {"id": plan.id, **result}
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"candidate": _candidate_dict(cand), "plan": plan_payload}

def _candidate_dict(c: Candidate) -> dict:
    return {"id": c.id, "hall_id": c.hall_id, "name": c.name,
            "ticket_no": c.ticket_no, "paper_id": c.paper_id}
