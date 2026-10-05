from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, PaperSet
from app.services.plan_service import get_active_plan, recompute_after_paper_change
from app.services.seat_engine import SeatingConflict
router = APIRouter(prefix="/candidates", tags=["candidates"])

@router.get("")
def list_candidates(db: Session = Depends(get_db)):
    return [{"id": r.id, "hall_id": r.hall_id, "name": r.name, "ticket_no": r.ticket_no, "paper_id": r.paper_id}
            for r in db.scalars(select(Candidate).order_by(Candidate.id)).all()]

@router.put("/{candidate_id}/paper")
def change_paper(candidate_id: int, body: dict, db: Session = Depends(get_db)):
    """更换考生试卷套，必须与其当前有效方案同成功或同失败。

    - 试卷套不存在 / 缺字段：400/404 拒绝，发生在任何写库之前，名单、最新图、
      违规列表、统计全部停在拒绝前。
    - 该生所在考室有有效方案：同一事务内改套别字段并重算邻接/未排，落一条新的
      有效方案；历史方案 result_json 原样不动。
    - 重算触发邻接禁则且整场重排仍无法消解（换套者仍无法入座 / 仍有同套相邻）：
      409 并回滚，杜绝“字段已新而图仍旧”。
    """
    paper_id = body.get("paper_id") if isinstance(body, dict) else None
    # ---- 校验先行：任何写操作之前 ----
    if not isinstance(paper_id, int) or isinstance(paper_id, bool):
        raise HTTPException(400, "缺少合法的 paper_id")
    paper = db.get(PaperSet, paper_id)
    if paper is None:
        raise HTTPException(404, "试卷套不存在")
    cand = db.get(Candidate, candidate_id)
    if cand is None:
        raise HTTPException(404, "考生不存在")
    if cand.paper_id == paper_id:
        return {"id": cand.id, "paper_id": cand.paper_id, "recomputed": False}

    hall = db.get(Hall, cand.hall_id)
    active = get_active_plan(db, hall.id)

    try:
        # ---- 字段与方案在同一事务内同生共死 ----
        cand.paper_id = paper_id
        db.flush()
        if active is not None:
            recompute_after_paper_change(db, hall, cand.id, active)
        db.commit()
    except SeatingConflict:
        db.rollback()
        raise HTTPException(409, "换套后无法在不违反邻接禁则的前提下重排，已整场回滚")
    except Exception:
        db.rollback()
        raise

    db.refresh(cand)
    return {"id": cand.id, "paper_id": cand.paper_id, "recomputed": active is not None}
