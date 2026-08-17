import datetime
import json
import logging
import hmac
import hashlib
from fastapi import APIRouter, Depends, Request, Header, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from app.database import get_db
from app.models import Event, Comment, Rule, DMJob, DuplicateBlock
from app.schemas import WebhookEvent
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_pseudogram_signature: str = Header(None, alias="X-PseudoGram-Signature"),
    db: Session = Depends(get_db)
):
    raw_body = await request.body()
    
    if settings.WEBHOOK_SIGNATURE_REQUIRED:
        if not x_pseudogram_signature:
            logger.warning("Missing webhook signature header")
            raise HTTPException(status_code=401, detail="Missing signature")
            
        sig_val = x_pseudogram_signature
        if sig_val.startswith("sha256="):
            sig_val = sig_val[7:]
            
        expected_sig = hmac.new(
            settings.PSEUDOGRAM_API_KEY.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()
        
        if not hmac.compare_digest(expected_sig, sig_val):
            logger.warning("Invalid webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
        event = WebhookEvent(**payload)
    except Exception as e:
        logger.error(f"Failed to parse webhook payload: {e}")
        raise HTTPException(status_code=400, detail="Invalid payload format")

    event_id = event.event_id
    event_type = event.event_type
    comment_id = event.data.comment_id

    db_event = Event(
        event_id=event_id,
        event_type=event_type,
        comment_id=comment_id,
        payload=payload,
        received_at=datetime.datetime.utcnow()
    )
    
    try:
        db.add(db_event)
        db.commit()
    except IntegrityError:
        db.rollback()
        logger.info(f"Duplicate event blocked: {event_id}")
        dup_block = DuplicateBlock(
            event_id=event_id,
            reason="duplicate_event_id"
        )
        db.add(dup_block)
        db.commit()
        return {"status": "ignored", "reason": "duplicate event"}

    if event_type == "comment.deleted":
        comment = db.query(Comment).filter(Comment.comment_id == comment_id).first()
        now = datetime.datetime.utcnow()
        if not comment:
            comment = Comment(
                comment_id=comment_id,
                post_id="",
                user_id="",
                text="",
                status="deleted",
                created_at=now,
                deleted_at=now
            )
            db.add(comment)
        else:
            comment.status = "deleted"
            comment.deleted_at = now
        
        db.commit()
        logger.info(f"Comment {comment_id} marked as deleted")

        pending_jobs = db.query(DMJob).filter(
            DMJob.comment_id == comment_id,
            DMJob.status.in_(["queued", "retry"])
        ).all()
        for job in pending_jobs:
            job.status = "failed"
            job.last_error = "Comment deleted before send"
            logger.info(f"Cancelled DM job {job.id} because comment was deleted")
        db.commit()

    elif event_type == "comment.created":
        user_id = event.data.from_.user_id if event.data.from_ else None
        post_id = event.data.post_id
        text = event.data.text or ""
        
        comment = db.query(Comment).filter(Comment.comment_id == comment_id).first()
        if comment:
            if comment.status == "deleted":
                logger.info(f"Comment {comment_id} is already deleted (out-of-order), ignoring creation")
                db_event.processed_at = datetime.datetime.utcnow()
                db.commit()
                return {"status": "ok"}
            comment.post_id = post_id
            comment.user_id = user_id
            comment.text = text
        else:
            comment = Comment(
                comment_id=comment_id,
                post_id=post_id,
                user_id=user_id,
                text=text,
                status="active",
                created_at=datetime.datetime.utcnow()
            )
            db.add(comment)
        db.commit()

        all_rules = db.query(Rule).all()
        matched_rules = []
        comment_text_lower = text.lower()
        for rule in all_rules:
            if rule.keyword.lower() in comment_text_lower:
                matched_rules.append(rule)
                
        logger.info(f"Found {len(matched_rules)} matching rules for comment {comment_id}")

        for rule in matched_rules:
            job = DMJob(
                rule_id=rule.id,
                user_id=user_id,
                comment_id=comment_id,
                message=rule.dm_message,
                status="queued",
                attempts=0,
                next_attempt_at=datetime.datetime.utcnow()
            )
            try:
                db.add(job)
                db.commit()
                logger.info(f"Created DM job {job.id} for rule {rule.id} and user {user_id}")
            except IntegrityError:
                db.rollback()
                logger.info(f"Duplicate DM blocked: rule {rule.id} user {user_id} already has a job")
                dup_block = DuplicateBlock(
                    event_id=event_id,
                    rule_id=rule.id,
                    user_id=user_id,
                    reason="duplicate_dm_user_rule"
                )
                db.add(dup_block)
                db.commit()

    db_event.processed_at = datetime.datetime.utcnow()
    db.commit()
    return {"status": "ok"}
