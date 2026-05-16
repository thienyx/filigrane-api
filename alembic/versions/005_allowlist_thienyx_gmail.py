"""allowlist thienyx@gmail.com

Revision ID: 005
Revises: 004
Create Date: 2026-05-16

"""

from __future__ import annotations

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO users (handle, email, name)
        VALUES ('thieny', 'thienyx@gmail.com', 'Thieny')
        ON CONFLICT (handle) DO UPDATE
            SET email = EXCLUDED.email,
                name = EXCLUDED.name;

        INSERT INTO magic_login_allowlist (email)
        VALUES ('thienyx@gmail.com')
        ON CONFLICT (email) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM magic_login_allowlist
        WHERE email = 'thienyx@gmail.com';

        DELETE FROM users
        WHERE email = 'thienyx@gmail.com';
        """
    )
