import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import Rule
from app.schemas import RuleCreate, RuleOut

router = APIRouter()

@router.post("/rules", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(rule_in: RuleCreate, db: Session = Depends(get_db)):
    rule_id = f"rul_{uuid.uuid4().hex[:12]}"
    new_rule = Rule(
        id=rule_id,
        keyword=rule_in.keyword.strip(),
        dm_message=rule_in.dm_message.strip()
    )
    db.add(new_rule)
    db.commit()
    db.refresh(new_rule)
    return RuleOut(
        rule_id=new_rule.id,
        keyword=new_rule.keyword,
        dm_message=new_rule.dm_message
    )
