import pytest
import datetime
import httpx
from app.models import Rule, DMJob, Comment
from app.workers.reconciliation_worker import reconcile_single_job
from app.clients.pseudogram import PseudoGramClient

@pytest.mark.asyncio
async def test_reconciliation_to_delivered(db_session, mock_pseudogram_client):
    _, mock_status = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=1, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="accepted", dm_id="dm_abc", attempts=1)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_abc", "status": "delivered"})
    
    client = PseudoGramClient()
    await reconcile_single_job(client, db_session, job)
    
    db_session.refresh(job)
    assert job.status == "delivered"

@pytest.mark.asyncio
async def test_reconciliation_to_failed(db_session, mock_pseudogram_client):
    _, mock_status = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment1 = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    comment2 = Comment(comment_id="cmt_2", post_id="post_1", user_id="usr_2", text="price", status="active", created_at=datetime.datetime.utcnow())
    
    job1 = DMJob(id=2, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="accepted", dm_id="dm_abc", attempts=5)
    job2 = DMJob(id=3, rule_id="r1", user_id="usr_2", comment_id="cmt_2", message="Info", status="accepted", dm_id="dm_xyz", attempts=2)
    
    db_session.add_all([rule, comment1, comment2, job1, job2])
    db_session.commit()

    client = PseudoGramClient()
    
    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_abc", "status": "failed"})
    await reconcile_single_job(client, db_session, job1)
    db_session.refresh(job1)
    assert job1.status == "failed"
    
    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_xyz", "status": "failed"})
    await reconcile_single_job(client, db_session, job2)
    db_session.refresh(job2)
    assert job2.status == "retry"
    assert job2.next_attempt_at is not None

@pytest.mark.asyncio
async def test_reconciliation_still_queued(db_session, mock_pseudogram_client):
    _, mock_status = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=4, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="accepted", dm_id="dm_abc", attempts=1)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_abc", "status": "queued"})
    
    client = PseudoGramClient()
    await reconcile_single_job(client, db_session, job)
    
    db_session.refresh(job)
    assert job.status == "accepted"
