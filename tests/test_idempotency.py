import pytest
from fastapi.testclient import TestClient
from app.models import Rule, DMJob, DuplicateBlock

def test_duplicate_event_id(client: TestClient, db_session):
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    db_session.add(rule)
    db_session.commit()

    payload = {
        "event_id": "evt_dup_1",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22Z",
        "data": {
            "comment_id": "cmt_dup_1",
            "post_id": "post_1",
            "text": "price please",
            "created_at": "2026-08-10T09:14:21Z",
            "from": {"user_id": "usr_dup", "username": "userdup"}
        }
    }
    
    res1 = client.post("/webhook", json=payload)
    assert res1.status_code == 200
    
    res2 = client.post("/webhook", json=payload)
    assert res2.status_code == 200
    assert res2.json()["status"] == "ignored"

    blocks = db_session.query(DuplicateBlock).filter(DuplicateBlock.event_id == "evt_dup_1").all()
    assert len(blocks) == 1
    assert blocks[0].reason == "duplicate_event_id"

    jobs = db_session.query(DMJob).all()
    assert len(jobs) == 1

def test_duplicate_dm_delivery_rule_user(client: TestClient, db_session):
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    db_session.add(rule)
    db_session.commit()

    payload1 = {
        "event_id": "evt_dup_user_1",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22Z",
        "data": {
            "comment_id": "cmt_dup_user_1",
            "post_id": "post_1",
            "text": "price please",
            "created_at": "2026-08-10T09:14:21Z",
            "from": {"user_id": "usr_dup_2", "username": "userdup2"}
        }
    }
    res1 = client.post("/webhook", json=payload1)
    assert res1.status_code == 200

    payload2 = {
        "event_id": "evt_dup_user_2",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:32Z",
        "data": {
            "comment_id": "cmt_dup_user_2",
            "post_id": "post_1",
            "text": "price again please",
            "created_at": "2026-08-10T09:14:31Z",
            "from": {"user_id": "usr_dup_2", "username": "userdup2"}
        }
    }
    res2 = client.post("/webhook", json=payload2)
    assert res2.status_code == 200

    jobs = db_session.query(DMJob).filter(DMJob.user_id == "usr_dup_2").all()
    assert len(jobs) == 1

    blocks = db_session.query(DuplicateBlock).filter(DuplicateBlock.event_id == "evt_dup_user_2").all()
    assert len(blocks) == 1
    assert blocks[0].reason == "duplicate_dm_user_rule"
