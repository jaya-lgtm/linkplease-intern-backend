from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional

class RuleCreate(BaseModel):
    keyword: str
    dm_message: str

    @field_validator("keyword")
    @classmethod
    def validate_keyword(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Keyword must not be empty or whitespace-only")
        return v

    @field_validator("dm_message")
    @classmethod
    def validate_dm_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("DM message must not be empty or whitespace-only")
        return v

class RuleOut(BaseModel):
    rule_id: str
    keyword: str
    dm_message: str

class UserFrom(BaseModel):
    user_id: str
    username: str

class CommentData(BaseModel):
    comment_id: str
    post_id: Optional[str] = None
    text: Optional[str] = None
    created_at: Optional[str] = None
    from_: Optional[UserFrom] = Field(default=None, alias="from")

    model_config = ConfigDict(populate_by_name=True)

class WebhookEvent(BaseModel):
    event_id: str
    event_type: str
    sent_at: str
    data: CommentData

class StatsOut(BaseModel):
    sent: int
    failed: int
    queued: int
    duplicates_blocked: int
