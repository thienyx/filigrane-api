from __future__ import annotations

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from filigrane_api.models.enums import ReactionTarget


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    handle: str
    name: str
    avatar_url: str | None


class MagicRequest(BaseModel):
    email: EmailStr


class MagicAllowlistMutation(BaseModel):
    email: EmailStr


class MagicConsume(BaseModel):
    token: str = Field(..., min_length=24)


class LoginEnvelope(BaseModel):
    session_token: str
    user: UserPublic


class ResolvePayload(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def trimmed_url_required(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "URL required"
            raise ValueError(msg)
        return stripped


class PinWrite(BaseModel):
    url: str | None = None
    source_id: int | None = None
    note: str | None = None


class CommentWrite(BaseModel):
    body: str = Field(..., min_length=1)
    parent_id: int | None = None

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "Body required"
            raise ValueError(msg)
        return stripped


class CommentPatch(BaseModel):
    body: str = Field(..., min_length=1)

    @field_validator("body")
    @classmethod
    def body_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "Body required"
            raise ValueError(msg)
        return stripped


class ReactionWrite(BaseModel):
    target_type: ReactionTarget
    target_id: int
    kind: str = Field(..., min_length=1)

    @field_validator("kind")
    @classmethod
    def kind_trimmed_nonempty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            msg = "Kind required"
            raise ValueError(msg)
        return stripped


class NotificationsRead(BaseModel):
    ids: list[int] | None = None
    all: bool = False
