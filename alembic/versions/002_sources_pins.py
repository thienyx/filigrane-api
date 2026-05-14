"""sources pins

Revision ID: 002
Revises: 001
Create Date: 2026-05-14

"""

from __future__ import annotations

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TYPE source_kind AS ENUM ('article','video','other');

        CREATE TABLE sources (
            id BIGSERIAL PRIMARY KEY,
            canonical_url TEXT NOT NULL UNIQUE,
            host TEXT NOT NULL,
            kind source_kind NOT NULL DEFAULT 'other',
            title TEXT,
            description TEXT,
            image_url TEXT,
            published_at TIMESTAMPTZ,
            fetched_at TIMESTAMPTZ,
            etag TEXT,
            revision BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );

        CREATE TABLE pins (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
            source_id BIGINT NOT NULL REFERENCES sources (id) ON DELETE CASCADE,
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (user_id, source_id)
        );
        CREATE INDEX ix_pins_source_id_created_at_desc
          ON pins (source_id, created_at DESC, id DESC);
        CREATE INDEX ix_pins_user_created_at_desc
          ON pins (user_id, created_at DESC, id DESC);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS pins;
        DROP TABLE IF EXISTS sources;
        DROP TYPE IF EXISTS source_kind;
        """
    )
