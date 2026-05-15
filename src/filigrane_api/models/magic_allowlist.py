from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, mapped_column

from filigrane_api.models.base import Base


class MagicLoginAllowlist(Base):
    __tablename__ = "magic_login_allowlist"

    email: Mapped[str] = mapped_column(
        CITEXT,
        ForeignKey("users.email", ondelete="CASCADE"),
        primary_key=True,
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
