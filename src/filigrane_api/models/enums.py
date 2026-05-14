from __future__ import annotations

from enum import StrEnum


class SourceKind(StrEnum):
    ARTICLE = "article"
    VIDEO = "video"
    OTHER = "other"


class ReactionTarget(StrEnum):
    PIN = "pin"
    COMMENT = "comment"


class NotificationKind(StrEnum):
    PIN_CREATED = "pin_created"
    COMMENT_CREATED = "comment_created"
    REACTION_ADDED = "reaction_added"
