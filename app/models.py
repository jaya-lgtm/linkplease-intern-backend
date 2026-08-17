import datetime
from sqlalchemy import Column, String, Integer, DateTime, Text, UniqueConstraint, ForeignKey, JSON
from app.database import Base

class Rule(Base):
    __tablename__ = "rules"
    id = Column(String, primary_key=True, index=True)
    keyword = Column(String, nullable=False, index=True)
    dm_message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Comment(Base):
    __tablename__ = "comments"
    comment_id = Column(String, primary_key=True, index=True)
    post_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False, index=True)
    text = Column(Text, nullable=False)
    status = Column(String, default="active")
    created_at = Column(DateTime, nullable=False)
    deleted_at = Column(DateTime, nullable=True)

class Event(Base):
    __tablename__ = "events"
    event_id = Column(String, primary_key=True, index=True)
    event_type = Column(String, nullable=False)
    comment_id = Column(String, nullable=True, index=True)
    payload = Column(JSON, nullable=False)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

class DMJob(Base):
    __tablename__ = "dm_jobs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(String, ForeignKey("rules.id"), nullable=False)
    user_id = Column(String, nullable=False, index=True)
    comment_id = Column(String, ForeignKey("comments.comment_id"), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String, default="queued", index=True)
    attempts = Column(Integer, default=0)
    dm_id = Column(String, nullable=True, index=True)
    next_attempt_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("rule_id", "user_id", name="uq_rule_user"),
    )

class RateLimitLog(Base):
    __tablename__ = "rate_limit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    attempted_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)

class DuplicateBlock(Base):
    __tablename__ = "duplicate_blocks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String, nullable=True, index=True)
    rule_id = Column(String, nullable=True)
    user_id = Column(String, nullable=True)
    reason = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
