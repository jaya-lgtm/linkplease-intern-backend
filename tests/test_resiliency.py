import pytest
import datetime
import httpx
from sqlalchemy import text
from unittest.mock import patch, AsyncMock
from app.models import Rule, DMJob, Comment
from app.workers.dm_worker import process_single_job
from app.workers.reconciliation_worker import reconcile_single_job
from app.clients.pseudogram import PseudoGramClient

@pytest.mark.asyncio
async def test_rate_limit_delay_behavior(db_session, mock_pseudogram_client):
    mock_send, _ = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=101, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="sending", attempts=0)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    # Mock reserve_rate_limit_slot to return a delay
    with patch("app.workers.dm_worker.reserve_rate_limit_slot", return_value=15.0):
        client = PseudoGramClient()
        await process_single_job(client, db_session, job)

    db_session.refresh(job)
    assert job.status == "retry"
    assert job.next_attempt_at is not None
    # Verify that send_dm was NOT called
    mock_send.assert_not_called()

@pytest.mark.asyncio
async def test_429_retry_after_behavior(db_session, mock_pseudogram_client):
    mock_send, _ = mock_pseudogram_client
    mock_send.return_value = httpx.Response(429, headers={"Retry-After": "45"}, json={"error": "rate_limited"})

    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=102, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="sending", attempts=0)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    client = PseudoGramClient()
    await process_single_job(client, db_session, job)

    db_session.refresh(job)
    assert job.status == "retry"
    assert job.attempts == 1
    assert "API 429" in job.last_error
    
    time_diff = (job.next_attempt_at - datetime.datetime.utcnow()).total_seconds()
    assert 40 <= time_diff <= 50

@pytest.mark.asyncio
async def test_accepted_job_still_within_ttl(db_session, mock_pseudogram_client):
    _, mock_status = mock_pseudogram_client
    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_abc", "status": "queued"})

    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=103, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="accepted", dm_id="dm_abc", attempts=1)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    # Set updated_at to 2 seconds ago (well within the 10 seconds test TTL)
    recent_time = datetime.datetime.utcnow() - datetime.timedelta(seconds=2)
    db_session.execute(
        text("UPDATE dm_jobs SET updated_at = :t WHERE id = :id"),
        {"t": recent_time, "id": job.id}
    )
    db_session.commit()

    client = PseudoGramClient()
    await reconcile_single_job(client, db_session, job)

    db_session.refresh(job)
    assert job.status == "accepted"
    assert job.attempts == 1

@pytest.mark.asyncio
async def test_accepted_job_exceeding_ttl_retry(db_session, mock_pseudogram_client):
    _, mock_status = mock_pseudogram_client
    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_abc", "status": "queued"})

    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=104, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="accepted", dm_id="dm_abc", attempts=1)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    # Set updated_at to 12 seconds ago (exceeding the 10 seconds test TTL)
    past_time = datetime.datetime.utcnow() - datetime.timedelta(seconds=12)
    db_session.execute(
        text("UPDATE dm_jobs SET updated_at = :t WHERE id = :id"),
        {"t": past_time, "id": job.id}
    )
    db_session.commit()

    client = PseudoGramClient()
    await reconcile_single_job(client, db_session, job)

    db_session.refresh(job)
    assert job.status == "retry"
    assert job.attempts == 2
    assert "reconciliation" in job.last_error.lower()
    assert job.next_attempt_at is not None

@pytest.mark.asyncio
async def test_accepted_job_exceeding_ttl_failed(db_session, mock_pseudogram_client):
    _, mock_status = mock_pseudogram_client
    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_abc", "status": "queued"})

    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    # Assuming max retries = 5, start with attempts = 4. Adding 1 attempt makes it 5 (terminal).
    job = DMJob(id=105, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="accepted", dm_id="dm_abc", attempts=4)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    # Set updated_at to 12 seconds ago
    past_time = datetime.datetime.utcnow() - datetime.timedelta(seconds=12)
    db_session.execute(
        text("UPDATE dm_jobs SET updated_at = :t WHERE id = :id"),
        {"t": past_time, "id": job.id}
    )
    db_session.commit()

    client = PseudoGramClient()
    await reconcile_single_job(client, db_session, job)

    db_session.refresh(job)
    assert job.status == "failed"
    assert job.attempts == 5
    assert "max retries reached" in job.last_error.lower()

@pytest.mark.asyncio
async def test_existing_reconciliation_behavior_still_works(db_session, mock_pseudogram_client):
    _, mock_status = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=106, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="accepted", dm_id="dm_abc", attempts=1)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    # Case 1: Status check returns delivered
    mock_status.return_value = httpx.Response(200, json={"dm_id": "dm_abc", "status": "delivered"})
    client = PseudoGramClient()
    await reconcile_single_job(client, db_session, job)
    
    db_session.refresh(job)
    assert job.status == "delivered"
