"""magic login email allowlist

Revision ID: 004
Revises: 003
Create Date: 2026-05-15

"""

from __future__ import annotations

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE magic_login_allowlist (
            email CITEXT PRIMARY KEY
              REFERENCES users (email) ON DELETE CASCADE,
            granted_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        INSERT INTO magic_login_allowlist (email)
        SELECT email FROM users;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS magic_login_allowlist")
