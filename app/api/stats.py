from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import DMJob, DuplicateBlock
from app.schemas import StatsOut

router = APIRouter()

@router.get("/stats", response_model=StatsOut)
def get_stats(db: Session = Depends(get_db)):
    sent = db.query(DMJob).filter(DMJob.status == "delivered").count()
    failed = db.query(DMJob).filter(DMJob.status == "failed").count()
    
    queued = db.query(DMJob).filter(
        DMJob.status.in_(["queued", "retry", "sending", "accepted"])
    ).count()
    
    duplicates_blocked = db.query(DuplicateBlock).count()
    
    return StatsOut(
        sent=sent,
        failed=failed,
        queued=queued,
        duplicates_blocked=duplicates_blocked
    )
