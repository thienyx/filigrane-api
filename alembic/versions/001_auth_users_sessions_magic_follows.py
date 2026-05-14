"""auth users sessions magic_links follows

Revision ID: 001
Revises:
Create Date: 2026-05-14

"""

from __future__ import annotations

from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')
    op.execute(
        """
        CREATE TABLE users (
            id BIGSERIAL PRIMARY KEY,
            handle TEXT NOT NULL UNIQUE,
            email CITEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            avatar_url TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE TABLE magic_links (
            id BIGSERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            token_hash TEXT NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            consumed_at TIMESTAMPTZ,
            request_ip TEXT,
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ix_magic_links_token_hash
          ON magic_links (token_hash);
        CREATE INDEX ix_magic_links_expires_at ON magic_links (expires_at);

        CREATE TABLE sessions (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_agent TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_sessions_user_id ON sessions (user_id);

        CREATE TABLE follows (
            follower_id BIGINT NOT NULL REFERENCES users (id)
              ON DELETE CASCADE,
            followee_id BIGINT NOT NULL REFERENCES users (id)
              ON DELETE CASCADE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (follower_id, followee_id)
        );
        CREATE INDEX ix_follows_followee ON follows (followee_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS follows;
        DROP TABLE IF EXISTS sessions;
        DROP TABLE IF EXISTS magic_links;
        DROP TABLE IF EXISTS users;
        """
    )
