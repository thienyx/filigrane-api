"""comments reactions notifications activity_read

Revision ID: 003
Revises: 002
Create Date: 2026-05-14

"""

from __future__ import annotations

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE reaction_target AS ENUM ('pin','comment');

        CREATE TABLE comments (
            id BIGSERIAL PRIMARY KEY,
            pin_id BIGINT NOT NULL REFERENCES pins (id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            parent_id BIGINT REFERENCES comments (id) ON DELETE SET NULL,
            body TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            edited_at TIMESTAMPTZ,
            deleted_at TIMESTAMPTZ
        );
        CREATE INDEX ix_comments_pin_created_desc
          ON comments (pin_id, created_at DESC, id DESC)
          WHERE deleted_at IS NULL;

        CREATE TABLE reactions (
            target reaction_target NOT NULL,
            target_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            kind TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (target, target_id, user_id, kind)
        );
        CREATE INDEX ix_reactions_target ON reactions (target, target_id);

        CREATE TYPE notification_kind AS ENUM (
          'pin_created','comment_created','reaction_added'
        );

        CREATE TABLE notifications (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            kind notification_kind NOT NULL,
            payload JSONB NOT NULL,
            read_at TIMESTAMPTZ,
            dedupe_key TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ix_notifications_user_dedupe
          ON notifications (user_id, dedupe_key)
          WHERE dedupe_key IS NOT NULL;
        CREATE INDEX ix_notifications_user_created_desc
          ON notifications (user_id, created_at DESC, id DESC);

        CREATE TABLE source_activity_reads (
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            source_id BIGINT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
            read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, source_id)
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS source_activity_reads;
        DROP TABLE IF EXISTS notifications;
        DROP TYPE IF EXISTS notification_kind;
        DROP TABLE IF EXISTS reactions;
        DROP TYPE IF EXISTS reaction_target;
        DROP TABLE IF EXISTS comments;
        """
    )
