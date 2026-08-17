import asyncio
import datetime
import random
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError, OperationalError
from app.database import SessionLocal
from app.models import DMJob, RateLimitLog, Comment
from app.clients.pseudogram import PseudoGramClient
from app.config import settings

logger = logging.getLogger(__name__)

stop_event = asyncio.Event()

def reserve_rate_limit_slot(db: Session) -> float:
    now = datetime.datetime.utcnow()
    sixty_seconds_ago = now - datetime.timedelta(seconds=60)
    
    db.query(RateLimitLog).filter(RateLimitLog.attempted_at < sixty_seconds_ago).delete()
    
    new_log = RateLimitLog(attempted_at=now)
    db.add(new_log)
    db.flush()
    
    attempts = db.query(RateLimitLog).filter(
        RateLimitLog.attempted_at >= sixty_seconds_ago
    ).order_by(RateLimitLog.attempted_at.asc()).all()
    
    if len(attempts) > 10:
        db.delete(new_log)
        db.commit()
        
        oldest_attempt = attempts[0]
        expires_at = oldest_attempt.attempted_at + datetime.timedelta(seconds=60)
        sleep_duration = (expires_at - now).total_seconds()
        return max(sleep_duration, 0.1)
    
    db.commit()
    return 0.0

def handle_retryable_failure(db: Session, job: DMJob, error_msg: str):
    job.attempts += 1
    job.last_error = error_msg
    if job.attempts >= settings.MAX_DM_RETRIES:
        job.status = "failed"
        logger.error(f"Job {job.id} reached max retries. Mark as failed.")
    else:
        backoff = (2 ** job.attempts) + random.uniform(0.1, 1.0)
        backoff = min(backoff, 60.0)
        job.status = "retry"
        job.next_attempt_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=backoff)
        logger.warning(f"Job {job.id} failed. Retrying in {backoff:.2f}s (attempt {job.attempts})")
    db.commit()

async def graceful_sleep(delay: float):
    if settings.TESTING:
        return
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay)
    except asyncio.TimeoutError:
        pass

async def process_single_job(client: PseudoGramClient, db: Session, job: DMJob):
    comment = db.query(Comment).filter(Comment.comment_id == job.comment_id).first()
    if comment and comment.status == "deleted":
        logger.info(f"Job {job.id} cancelled: comment {job.comment_id} was deleted")
        job.status = "failed"
        job.last_error = "Comment deleted before send"
        db.commit()
        return

    delay = reserve_rate_limit_slot(db)
    if delay > 0.0:
        logger.info(f"Rate limit hit. Re-queuing job {job.id} for retry after {delay:.2f}s")
        job.status = "retry"
        job.next_attempt_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=delay)
        db.commit()
        await graceful_sleep(delay)
        return

    idempotency_key = f"{job.rule_id}:{job.user_id}"
    logger.info(f"Sending DM for job {job.id} with key {idempotency_key}")
    
    try:
        response = await client.send_dm(
            recipient_user_id=job.user_id,
            message=job.message,
            comment_id=job.comment_id,
            idempotency_key=idempotency_key
        )
        
        status_code = response.status_code
        logger.info(f"API send response code {status_code} for job {job.id}")
        
        if status_code in (200, 201, 202):
            res_data = response.json()
            job.dm_id = res_data.get("dm_id")
            api_status = res_data.get("status", "queued")
            if api_status == "delivered":
                job.status = "delivered"
            else:
                job.status = "accepted"
            job.attempts += 1
            job.last_error = None
            db.commit()
            logger.info(f"Job {job.id} successfully sent/accepted. Status: {job.status}, DM ID: {job.dm_id}")
            
        elif status_code == 429:
            retry_after_header = response.headers.get("Retry-After")
            retry_after = 10
            if retry_after_header:
                try:
                    retry_after = int(retry_after_header)
                except ValueError:
                    pass
            job.status = "retry"
            job.attempts += 1
            job.next_attempt_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=retry_after)
            job.last_error = f"API 429: Rate limited. Retry-After: {retry_after}s"
            db.commit()
            logger.warning(f"Job {job.id} got 429. Retrying after {retry_after}s")
            await graceful_sleep(retry_after)
            
        elif status_code == 400:
            job.status = "failed"
            job.attempts += 1
            job.last_error = f"API 400: Non-retryable error: {response.text}"
            db.commit()
            logger.error(f"Job {job.id} failed with 400. Not retrying.")
            
        else:
            handle_retryable_failure(db, job, f"API {status_code}: {response.text}")
            
    except Exception as e:
        logger.error(f"Network error sending DM for job {job.id}: {e}")
        handle_retryable_failure(db, job, f"Network error: {str(e)}")

def recover_sending_jobs(db: Session):
    stale_jobs = db.query(DMJob).filter(DMJob.status == "sending").all()
    for job in stale_jobs:
        logger.info(f"Recovered stale sending job {job.id} to queued status")
        job.status = "queued"
    db.commit()

async def run_dm_worker():
    client = PseudoGramClient()
    logger.info("DM Background Worker started")
    
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            now = datetime.datetime.utcnow()
            job = db.query(DMJob).filter(
                DMJob.status.in_(["queued", "retry"]),
                DMJob.next_attempt_at <= now
            ).first()
            
            if job:
                updated = db.query(DMJob).filter(
                    DMJob.id == job.id,
                    DMJob.status.in_(["queued", "retry"])
                ).update({"status": "sending", "updated_at": datetime.datetime.utcnow()})
                db.commit()
                
                if updated == 1:
                    db.refresh(job)
                    await process_single_job(client, db, job)
            else:
                await asyncio.sleep(0.2)
                
        except (OperationalError, DBAPIError) as e:
            logger.warning(f"Database error in DM worker loop: {e}")
            await asyncio.sleep(0.5)
        except Exception as e:
            logger.exception(f"Unexpected error in DM worker loop: {e}")
            await asyncio.sleep(0.5)
        finally:
            db.close()
            
    logger.info("DM Background Worker stopped")
