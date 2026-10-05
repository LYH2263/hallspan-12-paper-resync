"""考生换试卷套与有效方案的同生共死一致性测试。"""
import json

from sqlalchemy import select

from app.models.models import Candidate, Hall, PaperSet, SeatPlan


def _mk_hall(session, rows, cols, min_dist=1, n_papers=3, n_cands=0):
    hall = Hall(code=f"H{rows}x{cols}-{hall_salt()}", name="t", rows=rows, cols=cols, min_manhattan=min_dist)
    session.add(hall)
    session.flush()
    pids = []
    for i in range(n_papers):
        p = PaperSet(code=f"P{i}-{hall.id}", title=f"paper{i}")
        session.add(p)
        session.flush()
        pids.append(p.id)
    for i in range(n_cands):
        session.add(Candidate(hall_id=hall.id, name=f"c{i}", ticket_no=f"T{hall.id}-{i}",
                              paper_id=pids[i % n_papers]))
    session.commit()
    return hall, pids


_counter = {"n": 0}
def hall_salt():
    _counter["n"] += 1
    return _counter["n"]


def _cand(session, hall_id, ordinal=0):
    return session.scalars(
        select(Candidate).where(Candidate.hall_id == hall_id).order_by(Candidate.id)
    ).all()[ordinal]


def _plan_rows(session, hall_id):
    return session.scalars(
        select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id)
    ).all()


def _roster(client, hall_id):
    return {c["id"]: c["paper_id"]
            for c in client.get("/api/candidates").json() if c["hall_id"] == hall_id}


# ---------- 套别不存在：拒绝，名单/图/违规/统计停在拒绝前 ----------

def test_reject_nonexistent_paper_changes_nothing(client, session):
    hall, pids = _mk_hall(session, 3, 3, n_cands=3)
    client.post(f"/api/seating/run?hall_id={hall.id}")
    plan_before = _plan_rows(session, hall.id)[-1]
    json_before = plan_before.result_json
    cand = _cand(session, hall.id, 0)
    old_paper = cand.paper_id

    latest_before = client.get(f"/api/seating/latest?hall_id={hall.id}").json()
    viols_before = client.get(f"/api/seating/violations?hall_id={hall.id}").json()
    stats_before = client.get(f"/api/seating/stats?hall_id={hall.id}").json()

    r = client.put(f"/api/candidates/{cand.id}/paper", json={"paper_id": 999999})
    assert r.status_code == 404

    session.expire_all()
    # 名单停在拒绝前
    assert session.get(Candidate, cand.id).paper_id == old_paper
    # 没有新增方案，旧方案 JSON 原样
    rows = _plan_rows(session, hall.id)
    assert len(rows) == 1
    assert rows[0].result_json == json_before
    # 图/违规/统计停在拒绝前
    assert client.get(f"/api/seating/latest?hall_id={hall.id}").json() == latest_before
    assert client.get(f"/api/seating/violations?hall_id={hall.id}").json() == viols_before
    assert client.get(f"/api/seating/stats?hall_id={hall.id}").json() == stats_before


def test_reject_bad_payload(client, session):
    hall, pids = _mk_hall(session, 2, 2, n_cands=1)
    cand = _cand(session, hall.id)
    old = cand.paper_id
    for payload in ({}, {"paper_id": "1"}, {"paper_id": None}):
        r = client.put(f"/api/candidates/{cand.id}/paper", json=payload)
        assert r.status_code == 400
    session.expire_all()
    assert session.get(Candidate, cand.id).paper_id == old
    assert _plan_rows(session, hall.id) == []


def test_reject_unknown_candidate(client, session):
    r = client.put("/api/candidates/999999/paper", json={"paper_id": 1})
    assert r.status_code == 404


# ---------- 无有效方案：只改字段，不造方案 ----------

def test_change_paper_without_plan_only_updates_field(client, session):
    hall, pids = _mk_hall(session, 4, 4, n_cands=2)
    cand = _cand(session, hall.id, 0)
    target = pids[1] if cand.paper_id != pids[1] else pids[2 % len(pids)]
    r = client.put(f"/api/candidates/{cand.id}/paper", json={"paper_id": target})
    assert r.status_code == 200
    assert r.json()["recomputed"] is False
    session.expire_all()
    assert session.get(Candidate, cand.id).paper_id == target
    assert _plan_rows(session, hall.id) == []


def test_same_paper_is_noop(client, session):
    hall, pids = _mk_hall(session, 3, 3, n_cands=2)
    client.post(f"/api/seating/run?hall_id={hall.id}")
    cand = _cand(session, hall.id)
    n_before = len(_plan_rows(session, hall.id))
    r = client.put(f"/api/candidates/{cand.id}/paper", json={"paper_id": cand.paper_id})
    assert r.status_code == 200
    assert r.json()["recomputed"] is False
    assert len(_plan_rows(session, hall.id)) == n_before


# ---------- 有有效方案：字段 + 图 + 违规 + 未排 按新套别一起更新，历史不动 ----------

def test_change_paper_recomputes_active_plan_atomically(client, session):
    # 2x2：c1 与 c2 初始不同套；把 c2 改成 c1 的套，稳定重排须把 c2 挪到对角
    hall, pids = _mk_hall(session, 2, 2, n_papers=2, n_cands=2)
    client.post(f"/api/seating/run?hall_id={hall.id}")
    old_plan = _plan_rows(session, hall.id)[-1]
    old_json = old_plan.result_json

    c1, c2 = _cand(session, hall.id, 0), _cand(session, hall.id, 1)
    assert c1.paper_id != c2.paper_id
    r = client.put(f"/api/candidates/{c2.id}/paper", json={"paper_id": c1.paper_id})
    assert r.status_code == 200
    assert r.json()["recomputed"] is True

    session.expire_all()
    rows = _plan_rows(session, hall.id)
    assert len(rows) == 2
    # 历史方案 result_json 原样不动且已失效
    session.refresh(old_plan)
    assert old_plan.result_json == old_json
    assert old_plan.is_active is False
    new_plan = rows[-1]
    assert new_plan.is_active is True

    data = json.loads(new_plan.result_json)
    assigns = {a["candidate_id"]: a for a in data["assignments"]}
    assert assigns[c1.id]["paper_id"] == c1.paper_id
    assert assigns[c2.id]["paper_id"] == c1.paper_id
    # 成功重排后邻接消失（对角落座）
    p1 = (assigns[c1.id]["row"], assigns[c1.id]["col"])
    p2 = (assigns[c2.id]["row"], assigns[c2.id]["col"])
    assert abs(p1[0] - p2[0]) + abs(p1[1] - p2[1]) == 2
    assert not [v for v in data["violations"] if v["kind"] == "same_paper_adjacent"]

    # 违规/统计/最新图同源，均指向新方案
    viols = client.get(f"/api/seating/violations?hall_id={hall.id}").json()
    assert viols["violations"] == data["violations"]
    stats = client.get(f"/api/seating/stats?hall_id={hall.id}").json()
    assert stats["seated"] == data["stats"]["seated"] == 2
    assert client.get(f"/api/seating/latest?hall_id={hall.id}").json()["id"] == new_plan.id
    # 名单也已更新
    assert _roster(client, hall.id)[c2.id] == c1.paper_id


def test_successful_recompute_snapshot_reflects_new_paper(client, session):
    # 1x3 容量 3、4 人、两套交替：c1p0@0 c2p1@1 c3p0@2，c4p1 本就未排。
    # 把 c1 改成 p1 会与 c2 同套相邻 -> 稳定重排失败 -> 整场重排成功（c1 仍在座，
    # c2/c3 也都在座，只有原本就未排的 c4 继续未排）。快照 assignments / unplaced
    # 的套别必须全部等于新名单，违规不得再挂旧套。
    hall, pids = _mk_hall(session, 1, 3, min_dist=1, n_papers=2, n_cands=4)
    client.post(f"/api/seating/run?hall_id={hall.id}")
    cands = [_cand(session, hall.id, i) for i in range(4)]
    p0, p1 = pids[0], pids[1]
    for c, p in zip(cands, [p0, p1, p0, p1]):
        c.paper_id = p
    session.commit()
    client.post(f"/api/seating/run?hall_id={hall.id}")

    c1 = cands[0]
    r = client.put(f"/api/candidates/{c1.id}/paper", json={"paper_id": p1})
    assert r.status_code == 200, r.text

    data = client.get(f"/api/seating/latest?hall_id={hall.id}").json()
    roster = _roster(client, hall.id)
    seated_ids = {a["candidate_id"] for a in data["assignments"]}
    # 换套者与其他旧已座者全部在座
    assert {c.id for c in cands[:3]} <= seated_ids
    # 图上每一席的套别 == 新名单（换套者已是新套 p1，非旧套 p0）
    for a in data["assignments"]:
        assert a["paper_id"] == roster[a["candidate_id"]]
    assert next(a for a in data["assignments"] if a["candidate_id"] == c1.id)["paper_id"] == p1
    # 未排名单的套别同样取自新名单，不是旧快照残留
    for u in data["unplaced"]:
        assert u["paper_id"] == roster[u["id"]]
    assert {u["id"] for u in data["unplaced"]} == {cands[3].id}
    # 无同套相邻残留；统计同源
    assert not [v for v in data["violations"] if v["kind"] == "same_paper_adjacent"]
    assert data["stats"]["seated"] == 3 and data["stats"]["unplaced"] == 1
    assert client.get(f"/api/seating/stats?hall_id={hall.id}").json()["unplaced"] == 1
    assert client.get(f"/api/seating/violations?hall_id={hall.id}").json()["unplaced"] == data["unplaced"]


# ---------- 邻接禁则无法消解：整场失败回滚，禁止字段新而图旧 ----------

def test_previously_unplaced_candidate_change_succeeds(client, session):
    # 1x3 满座 3 人 p0,p1,p0，第 4 人 c4(p1) 本就未排。给 c4 换套（仍无空位可坐），
    # 应成功：不强制其入座，也不得触发整场重排挤掉任何旧已座者；未排条目带新套别。
    hall, pids = _mk_hall(session, 1, 3, min_dist=1, n_papers=2, n_cands=4)
    cands = [_cand(session, hall.id, i) for i in range(4)]
    p0, p1 = pids[0], pids[1]
    for c, p in zip(cands, [p0, p1, p0, p1]):
        c.paper_id = p
    session.commit()
    client.post(f"/api/seating/run?hall_id={hall.id}")

    c4 = cands[3]
    r = client.put(f"/api/candidates/{c4.id}/paper", json={"paper_id": p0})
    assert r.status_code == 200, r.text

    data = client.get(f"/api/seating/latest?hall_id={hall.id}").json()
    seated = {a["candidate_id"] for a in data["assignments"]}
    # 旧已座三人一个不少，c4 仍在未排但套别已是 p0
    assert {c.id for c in cands[:3]} == seated
    unplaced = {u["id"]: u["paper_id"] for u in data["unplaced"]}
    assert unplaced == {c4.id: p0}
    assert _roster(client, hall.id)[c4.id] == p0
    assert not [v for v in data["violations"] if v["kind"] == "same_paper_adjacent"]


def test_adjacency_conflict_rolls_back_entire_transaction(client, session):
    # 1x2：c1、c2 不同套相邻落座；把 c2 改成 c1 的套 -> 无处可挪 -> 409
    hall, pids = _mk_hall(session, 1, 2, n_papers=2, n_cands=2)
    client.post(f"/api/seating/run?hall_id={hall.id}")
    plan_before = _plan_rows(session, hall.id)[-1]
    json_before = plan_before.result_json

    c1, c2 = _cand(session, hall.id, 0), _cand(session, hall.id, 1)
    assert c1.paper_id != c2.paper_id
    old_paper_c2 = c2.paper_id
    r = client.put(f"/api/candidates/{c2.id}/paper", json={"paper_id": c1.paper_id})
    assert r.status_code == 409

    session.expire_all()
    # 字段回滚
    assert session.get(Candidate, c2.id).paper_id == old_paper_c2
    # 没有半成品方案落库，旧有效方案仍 active 且 JSON 原样
    rows = _plan_rows(session, hall.id)
    assert len(rows) == 1
    assert rows[0].id == plan_before.id
    assert rows[0].is_active is True
    assert rows[0].result_json == json_before
    # 图/名单一致停在旧状态
    assert client.get(f"/api/seating/latest?hall_id={hall.id}").json()["id"] == plan_before.id
    assert _roster(client, hall.id)[c2.id] == old_paper_c2


def test_recompute_that_would_displace_seated_candidate_rolls_back(client, session):
    # 1x4 容量 4、5 人交替：c1p0@0 c2p1@1 c3p0@2 c4p1@3，c5p0 未排。
    # 把 c1 改成 p1：整场重排也放不下 3 个互不相邻的 p1，旧已座的 c4 会被挤出未排。
    # 换套不得连累无辜，必须整场回滚。
    hall, pids = _mk_hall(session, 1, 4, min_dist=1, n_papers=2, n_cands=5)
    client.post(f"/api/seating/run?hall_id={hall.id}")
    cands = [_cand(session, hall.id, i) for i in range(5)]
    p0, p1 = pids[0], pids[1]
    for c, p in zip(cands, [p0, p1, p0, p1, p0]):
        c.paper_id = p
    session.commit()
    old = client.post(f"/api/seating/run?hall_id={hall.id}").json()
    assert {a["candidate_id"] for a in old["assignments"]} == {c.id for c in cands[:4]}

    c1, c4 = cands[0], cands[3]
    r = client.put(f"/api/candidates/{c1.id}/paper", json={"paper_id": p1})
    assert r.status_code == 409, r.text

    session.expire_all()
    assert session.get(Candidate, c1.id).paper_id == p0
    rows = _plan_rows(session, hall.id)
    # 两次 run 共两行；回滚不得新增第三行，有效方案仍是旧的那一行
    assert len(rows) == 2 and rows[-1].is_active is True
    latest = client.get(f"/api/seating/latest?hall_id={hall.id}").json()
    assert latest["id"] == rows[-1].id
    # 图停在旧状态：c4 仍在座，c5 仍未排，c1 仍是旧套 p0
    assert c4.id in {a["candidate_id"] for a in latest["assignments"]}
    assert {u["id"] for u in latest["unplaced"]} == {cands[4].id}
    assert next(a for a in latest["assignments"] if a["candidate_id"] == c1.id)["paper_id"] == p0


# ---------- run 使旧方案失效，始终只有一个有效方案 ----------

def test_run_deactivates_previous_plan(client, session):
    hall, pids = _mk_hall(session, 3, 3, n_cands=3)
    client.post(f"/api/seating/run?hall_id={hall.id}")
    first = _plan_rows(session, hall.id)[-1]
    client.post(f"/api/seating/run?hall_id={hall.id}")
    second = _plan_rows(session, hall.id)[-1]
    session.refresh(first)
    assert first.is_active is False
    assert second.is_active is True
    actives = [p for p in _plan_rows(session, hall.id) if p.is_active]
    assert len(actives) == 1
    assert client.get(f"/api/seating/latest?hall_id={hall.id}").json()["id"] == second.id
