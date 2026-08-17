import pytest
import datetime
from fastapi.testclient import TestClient
from app.models import DMJob, DuplicateBlock, Rule, Comment

def test_stats_counts(client: TestClient, db_session):
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    db_session.add(rule)
    db_session.commit()

    def add_job(job_id, user_id, comment_id, status):
        comment = Comment(comment_id=comment_id, post_id="p1", user_id=user_id, text="price", status="active", created_at=datetime.datetime.utcnow())
        db_session.merge(comment)
        
        job = DMJob(id=job_id, rule_id="r1", user_id=user_id, comment_id=comment_id, message="Info", status=status, attempts=1)
        db_session.add(job)

    add_job(1, "u1", "c1", "delivered")
    add_job(2, "u2", "c2", "delivered")
    add_job(3, "u3", "c3", "failed")
    add_job(4, "u4", "c4", "queued")
    add_job(5, "u5", "c5", "retry")
    add_job(6, "u6", "c6", "sending")
    add_job(7, "u7", "c7", "accepted")

    block1 = DuplicateBlock(event_id="e1", reason="duplicate_event_id")
    block2 = DuplicateBlock(event_id="e2", reason="duplicate_dm_user_rule")
    db_session.add_all([block1, block2])
    db_session.commit()

    res = client.get("/stats")
    assert res.status_code == 200
    data = res.json()
    
    assert data["sent"] == 2
    assert data["failed"] == 1
    assert data["queued"] == 4
    assert data["duplicates_blocked"] == 2
