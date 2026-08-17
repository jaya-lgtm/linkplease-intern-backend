import asyncio
import datetime
import random
import logging
from sqlalchemy.orm import Session
from sqlalchemy.exc import DBAPIError, OperationalError
from app.database import SessionLocal
from app.models import DMJob
from app.clients.pseudogram import PseudoGramClient
from app.config import settings

logger = logging.getLogger(__name__)

stop_event = asyncio.Event()

async def reconcile_single_job(client: PseudoGramClient, db: Session, job: DMJob):
    if not job.dm_id:
        job.status = "queued"
        db.commit()
        return

    try:
        response = await client.get_dm_status(job.dm_id)
        if response.status_code == 200:
            res_data = response.json()
            api_status = res_data.get("status")
            
            logger.info(f"Reconciliation status for DM ID {job.dm_id}: {api_status}")
            
            if api_status == "delivered":
                job.status = "delivered"
                db.commit()
                logger.info(f"Job {job.id} (DM {job.dm_id}) confirmed delivered.")
                
            elif api_status == "failed":
                if job.attempts < settings.MAX_DM_RETRIES:
                    backoff = (2 ** job.attempts) + random.uniform(0.1, 1.0)
                    backoff = min(backoff, 60.0)
                    job.status = "retry"
                    job.next_attempt_at = datetime.datetime.utcnow() + datetime.timedelta(seconds=backoff)
                    job.last_error = f"Reconciliation returned failed status from API"
                    logger.warning(f"Reconciliation: job {job.id} failed, retry scheduled in {backoff:.2f}s")
                else:
                    job.status = "failed"
                    job.last_error = f"Reconciliation: API status is failed"
                    logger.error(f"Reconciliation: job {job.id} failed permanently.")
                db.commit()
            else:
                now = datetime.datetime.utcnow()
                accepted_ttl = datetime.timedelta(minutes=15)
                if settings.TESTING:
                    accepted_ttl = datetime.timedelta(seconds=10)
                
                if job.updated_at and (now - job.updated_at) > accepted_ttl:
                    logger.warning(f"Reconciliation: job {job.id} stuck in 'accepted' (queued at API) for over {accepted_ttl}. Retrying/failing.")
                    job.attempts += 1
                    job.last_error = f"Reconciliation: stuck in accepted for over {accepted_ttl}"
                    
                    if job.attempts < settings.MAX_DM_RETRIES:
                        backoff = (2 ** job.attempts) + random.uniform(0.1, 1.0)
                        backoff = min(backoff, 60.0)
                        job.status = "retry"
                        job.next_attempt_at = now + datetime.timedelta(seconds=backoff)
                        logger.warning(f"Job {job.id} moved to retry. Next attempt in {backoff:.2f}s")
                    else:
                        job.status = "failed"
                        job.last_error = f"Reconciliation: stuck in accepted and max retries reached"
                        logger.error(f"Job {job.id} reached max retries. Mark as failed.")
                    db.commit()
        else:
            logger.warning(f"Reconciliation status check returned {response.status_code} for DM {job.dm_id}")
    except Exception as e:
        logger.error(f"Error during reconciliation for job {job.id}: {e}")

async def run_reconciliation_worker():
    client = PseudoGramClient()
    logger.info("Reconciliation Background Worker started")
    
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            accepted_jobs = db.query(DMJob).filter(DMJob.status == "accepted").all()
            for job in accepted_jobs:
                if stop_event.is_set():
                    break
                await reconcile_single_job(client, db, job)
                await asyncio.sleep(0.1)
                
            await asyncio.sleep(1.0)
            
        except (OperationalError, DBAPIError) as e:
            logger.warning(f"Database error in reconciliation loop: {e}")
            await asyncio.sleep(1.0)
        except Exception as e:
            logger.exception(f"Unexpected error in reconciliation loop: {e}")
            await asyncio.sleep(1.0)
        finally:
            db.close()
            
    logger.info("Reconciliation Background Worker stopped")
