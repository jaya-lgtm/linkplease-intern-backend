import datetime
import pytest
import httpx
from app.models import Rule, DMJob, Comment
from app.workers.dm_worker import process_single_job
from app.clients.pseudogram import PseudoGramClient

@pytest.mark.asyncio
async def test_retry_on_500(db_session, mock_pseudogram_client):
    mock_send, _ = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=1, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="sending", attempts=0)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    mock_send.return_value = httpx.Response(500, text="Internal Server Error")
    
    client = PseudoGramClient()
    await process_single_job(client, db_session, job)
    
    db_session.refresh(job)
    assert job.status == "retry"
    assert job.attempts == 1
    assert "API 500" in job.last_error
    assert job.next_attempt_at > datetime.datetime.utcnow()

@pytest.mark.asyncio
async def test_retry_on_429_respects_retry_after(db_session, mock_pseudogram_client):
    mock_send, _ = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=2, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="sending", attempts=0)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    mock_send.return_value = httpx.Response(429, headers={"Retry-After": "45"}, json={"error": "rate_limited"})
    
    client = PseudoGramClient()
    await process_single_job(client, db_session, job)
    
    db_session.refresh(job)
    assert job.status == "retry"
    assert job.attempts == 1
    assert "API 429" in job.last_error
    
    time_diff = (job.next_attempt_at - datetime.datetime.utcnow()).total_seconds()
    assert 40 <= time_diff <= 50

@pytest.mark.asyncio
async def test_failed_on_400(db_session, mock_pseudogram_client):
    mock_send, _ = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=3, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="sending", attempts=0)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    mock_send.return_value = httpx.Response(400, text="Bad Request")
    
    client = PseudoGramClient()
    await process_single_job(client, db_session, job)
    
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.attempts == 1
    assert "API 400" in job.last_error

@pytest.mark.asyncio
async def test_max_retries_failed(db_session, mock_pseudogram_client):
    mock_send, _ = mock_pseudogram_client
    
    rule = Rule(id="r1", keyword="price", dm_message="Info")
    comment = Comment(comment_id="cmt_1", post_id="post_1", user_id="usr_1", text="price", status="active", created_at=datetime.datetime.utcnow())
    job = DMJob(id=4, rule_id="r1", user_id="usr_1", comment_id="cmt_1", message="Info", status="sending", attempts=4)
    db_session.add_all([rule, comment, job])
    db_session.commit()

    mock_send.return_value = httpx.Response(500, text="Internal Server Error")
    
    client = PseudoGramClient()
    await process_single_job(client, db_session, job)
    
    db_session.refresh(job)
    assert job.status == "failed"
    assert job.attempts == 5
