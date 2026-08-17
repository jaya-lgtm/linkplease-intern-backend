import hmac
import hashlib
import json
from fastapi.testclient import TestClient
from app.config import settings
from app.models import DMJob, Comment, Rule

def calc_signature(body: bytes, key: str) -> str:
    return hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()

def test_webhook_signature_verification(client: TestClient):
    settings.WEBHOOK_SIGNATURE_REQUIRED = True
    try:
        payload = {
            "event_id": "evt_1",
            "event_type": "comment.created",
            "sent_at": "2026-08-10T09:14:22Z",
            "data": {
                "comment_id": "cmt_1",
                "post_id": "post_1",
                "text": "Hello world",
                "created_at": "2026-08-10T09:14:21Z",
                "from": {"user_id": "usr_1", "username": "user1"}
            }
        }
        body = json.dumps(payload).encode("utf-8")
        
        res = client.post("/webhook", data=body)
        assert res.status_code == 401
        
        res = client.post("/webhook", data=body, headers={"X-PseudoGram-Signature": "sha256=invalid"})
        assert res.status_code == 401
        
        sig = calc_signature(body, "test-secret-key")
        res = client.post("/webhook", data=body, headers={"X-PseudoGram-Signature": f"sha256={sig}"})
        assert res.status_code == 200
        
    finally:
        settings.WEBHOOK_SIGNATURE_REQUIRED = False

def test_webhook_rule_matching(client: TestClient, db_session):
    rule1 = Rule(id="r1", keyword="price", dm_message="Price details")
    rule2 = Rule(id="r2", keyword="Discount", dm_message="Discount details")
    db_session.add_all([rule1, rule2])
    db_session.commit()

    payload = {
        "event_id": "evt_2",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22Z",
        "data": {
            "comment_id": "cmt_2",
            "post_id": "post_1",
            "text": "What is the PrIcE? Please let me know",
            "created_at": "2026-08-10T09:14:21Z",
            "from": {"user_id": "usr_2", "username": "user2"}
        }
    }
    res = client.post("/webhook", json=payload)
    assert res.status_code == 200

    jobs = db_session.query(DMJob).all()
    assert len(jobs) == 1
    assert jobs[0].rule_id == "r1"
    assert jobs[0].user_id == "usr_2"
    assert jobs[0].status == "queued"

def test_webhook_deleted_comment(client: TestClient, db_session):
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    db_session.add(rule)
    db_session.commit()

    payload_created = {
        "event_id": "evt_3",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22Z",
        "data": {
            "comment_id": "cmt_3",
            "post_id": "post_1",
            "text": "price please",
            "created_at": "2026-08-10T09:14:21Z",
            "from": {"user_id": "usr_3", "username": "user3"}
        }
    }
    client.post("/webhook", json=payload_created)
    
    jobs = db_session.query(DMJob).filter(DMJob.comment_id == "cmt_3").all()
    assert len(jobs) == 1
    assert jobs[0].status == "queued"

    payload_deleted = {
        "event_id": "evt_4",
        "event_type": "comment.deleted",
        "sent_at": "2026-08-10T09:15:22Z",
        "data": {
            "comment_id": "cmt_3"
        }
    }
    client.post("/webhook", json=payload_deleted)

    db_session.refresh(jobs[0])
    assert jobs[0].status == "failed"
    assert "deleted" in jobs[0].last_error.lower()

def test_webhook_out_of_order_delete_create(client: TestClient, db_session):
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    db_session.add(rule)
    db_session.commit()

    payload_deleted = {
        "event_id": "evt_5",
        "event_type": "comment.deleted",
        "sent_at": "2026-08-10T09:15:22Z",
        "data": {
            "comment_id": "cmt_4"
        }
    }
    res1 = client.post("/webhook", json=payload_deleted)
    assert res1.status_code == 200

    payload_created = {
        "event_id": "evt_6",
        "event_type": "comment.created",
        "sent_at": "2026-08-10T09:14:22Z",
        "data": {
            "comment_id": "cmt_4",
            "post_id": "post_1",
            "text": "price please",
            "created_at": "2026-08-10T09:14:21Z",
            "from": {"user_id": "usr_4", "username": "user4"}
        }
    }
    res2 = client.post("/webhook", json=payload_created)
    assert res2.status_code == 200

    cmt = db_session.query(Comment).filter(Comment.comment_id == "cmt_4").first()
    assert cmt.status == "deleted"
    
    jobs = db_session.query(DMJob).filter(DMJob.comment_id == "cmt_4").all()
    assert len(jobs) == 0
