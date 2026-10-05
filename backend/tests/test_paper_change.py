"""考生更换试卷套的原子性：套别字段、最新排座图、违规/未排、统计一起成功或一起失败。"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.database import SessionLocal
from app.main import app
from app.models.models import Candidate, Hall, PaperSet, SeatPlan


def _seed(db, rows=3, cols=3, min_dist=1, paper_codes=("P1", "P2", "P3"), cand_papers=(0, 1, 0, 1)):
    hall = Hall(code="H1", name="一室", rows=rows, cols=cols, min_manhattan=min_dist)
    db.add(hall)
    db.flush()
    pids = []
    for code in paper_codes:
        p = PaperSet(code=code, title=f"{code} 卷")
        db.add(p)
        db.flush()
        pids.append(p.id)
    cids = []
    for i, pi in enumerate(cand_papers):
        c = Candidate(hall_id=hall.id, name=f"考生{i}", ticket_no=f"T{i:03d}", paper_id=pids[pi])
        db.add(c)
        db.flush()
        cids.append(c.id)
    db.commit()
    return hall.id, pids, cids


def _roster(client):
    return {c["id"]: c for c in client.get("/api/candidates").json()}


def _plan_row(plan_id):
    db = SessionLocal()
    try:
        return db.get(SeatPlan, plan_id)
    finally:
        db.close()


def test_change_paper_regenerates_latest_plan_atomically(client, db):
    hall_id, pids, cids = _seed(db)
    plan1 = client.post(f"/api/seating/run?hall_id={hall_id}").json()
    plan1_json_before = _plan_row(plan1["id"]).result_json

    resp = client.put(f"/api/candidates/{cids[0]}/paper", json={"paper_id": pids[2]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["candidate"]["paper_id"] == pids[2]
    assert body["plan"] is not None and body["plan"]["id"] != plan1["id"]

    # 名单已更新
    assert _roster(client)[cids[0]]["paper_id"] == pids[2]

    # 最新图就是本次重算的快照，且每个座位的套别与名单一致（不挂旧套）
    latest = client.get(f"/api/seating/latest?hall_id={hall_id}").json()
    assert latest["id"] == body["plan"]["id"]
    roster = _roster(client)
    for a in latest["assignments"]:
        assert a["paper_id"] == roster[a["candidate_id"]]["paper_id"]
    for u in latest["unplaced"]:
        assert u["paper_id"] == roster[u["id"]]["paper_id"]
    # 违规句按新套别出：同卷相邻句里的套号必须是当事人当前套别
    for v in latest["violations"]:
        if v["kind"] == "same_paper_adjacent":
            cur = roster[v["a_id"]]["paper_id"]
            assert roster[v["b_id"]]["paper_id"] == cur
            assert f"同试卷套 {cur} " in v["detail"]

    # 违规/未排与统计与最新图同源一致
    viol = client.get(f"/api/seating/violations?hall_id={hall_id}").json()
    assert viol["violations"] == latest["violations"]
    assert viol["unplaced"] == latest["unplaced"]
    stats = client.get(f"/api/seating/stats?hall_id={hall_id}").json()
    assert stats["seated"] == latest["stats"]["seated"]
    assert stats["violations"] == latest["stats"]["violations"]

    # 历史方案保持不动
    assert _plan_row(plan1["id"]).result_json == plan1_json_before


def test_unknown_paper_rejected_and_state_frozen(client, db):
    hall_id, pids, cids = _seed(db)
    plan1 = client.post(f"/api/seating/run?hall_id={hall_id}").json()
    stats_before = client.get(f"/api/seating/stats?hall_id={hall_id}").json()
    paper_before = _roster(client)[cids[0]]["paper_id"]

    resp = client.put(f"/api/candidates/{cids[0]}/paper", json={"paper_id": 99999})
    assert resp.status_code == 404

    # 名单、最新图、统计全部停在拒绝前
    assert _roster(client)[cids[0]]["paper_id"] == paper_before
    assert db.query(SeatPlan).count() == 1
    latest = client.get(f"/api/seating/latest?hall_id={hall_id}").json()
    assert latest["id"] == plan1["id"]
    assert client.get(f"/api/seating/stats?hall_id={hall_id}").json() == stats_before


def test_change_to_neighbor_paper_reseats_and_clears_adjacency(client, db):
    # 2x2、min_dist=1：A(0,0)P1 B(0,1)P2 C(1,1)P1 D(1,0)P2，A 与 B、D 四邻相邻
    hall_id, pids, cids = _seed(db, rows=2, cols=2, min_dist=1,
                                paper_codes=("P1", "P2"), cand_papers=(0, 1, 0, 1))
    plan1 = client.post(f"/api/seating/run?hall_id={hall_id}").json()
    seat_of = {a["candidate_id"]: (a["row"], a["col"]) for a in plan1["assignments"]}
    assert seat_of[cids[0]] == (0, 0)  # A 已就座，邻座 B、D 都是 P2

    # 把 A 改到与邻座同套 P2：触发邻接禁则，必须整场重排而不是只改字段
    resp = client.put(f"/api/candidates/{cids[0]}/paper", json={"paper_id": pids[1]})
    assert resp.status_code == 200
    new_plan = resp.json()["plan"]
    assert new_plan["id"] != plan1["id"]

    latest = client.get(f"/api/seating/latest?hall_id={hall_id}").json()
    assert latest["id"] == new_plan["id"]
    # 字段已新，图也必须已新：A 在图上就是新套别
    seat_a = next(a for a in latest["assignments"] if a["candidate_id"] == cids[0])
    assert seat_a["paper_id"] == pids[1]
    # 重排后同卷四邻相邻消失
    assert not any(v["kind"] == "same_paper_adjacent" for v in latest["violations"])
    # 未排按新套别出：D 被挤下，未排记录挂的是新套 P2
    assert [u["id"] for u in latest["unplaced"]] == [cids[3]]
    assert latest["unplaced"][0]["paper_id"] == pids[1]
    # 名单与图一致
    assert _roster(client)[cids[0]]["paper_id"] == pids[1]


def test_replan_failure_rolls_back_everything(client, db, monkeypatch):
    hall_id, pids, cids = _seed(db)
    plan1 = client.post(f"/api/seating/run?hall_id={hall_id}").json()
    paper_before = _roster(client)[cids[0]]["paper_id"]

    def boom(_db, _hall):
        raise RuntimeError("replan exploded")

    monkeypatch.setattr("app.api.candidates.build_seat_plan", boom)
    safe_client = TestClient(app, raise_server_exceptions=False)
    resp = safe_client.put(f"/api/candidates/{cids[0]}/paper", json={"paper_id": pids[2]})
    assert resp.status_code == 500

    # 整场失败回滚：套别字段、方案历史、最新图全部停在改动前
    assert _roster(client)[cids[0]]["paper_id"] == paper_before
    assert db.query(SeatPlan).count() == 1
    latest = client.get(f"/api/seating/latest?hall_id={hall_id}").json()
    assert latest["id"] == plan1["id"]


def test_change_paper_without_existing_plan_only_updates_field(client, db):
    hall_id, pids, cids = _seed(db)
    resp = client.put(f"/api/candidates/{cids[0]}/paper", json={"paper_id": pids[1]})
    assert resp.status_code == 200
    assert resp.json()["plan"] is None
    assert _roster(client)[cids[0]]["paper_id"] == pids[1]
    assert db.query(SeatPlan).count() == 0  # 无有效方案时不凭空造方案


def test_change_paper_candidate_not_found(client, db):
    _seed(db)
    resp = client.put("/api/candidates/99999/paper", json={"paper_id": 1})
    assert resp.status_code == 404
