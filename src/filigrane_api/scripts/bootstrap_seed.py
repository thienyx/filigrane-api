from __future__ import annotations

import itertools
import os
import sys

import psycopg


def sync_url(raw: str) -> str:
    base, _, query = raw.partition("?")
    suffix = f"?{query}" if query else ""
    if base.startswith("postgresql+asyncpg://"):
        base = base.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    elif base.startswith("postgres://"):
        base = base.replace("postgres://", "postgresql+psycopg://", 1)
    elif base.startswith("postgresql://"):
        base = base.replace("postgresql://", "postgresql+psycopg://", 1)
    suffix = suffix.replace("ssl=require", "sslmode=require")
    synced = base + suffix
    return synced.replace("postgresql+psycopg://", "postgresql://", 1)


def main() -> None:
    raw = os.environ.get("FILIGRANE_DATABASE_URL")
    if raw is None:
        print("FILIGRANE_DATABASE_URL required", file=sys.stderr)
        raise SystemExit(1)

    roster = (
        ("thieny", "Thieny", "thienyx@gmail.com"),
        ("river", "River", "river@filigrane.team"),
        ("noor", "Noor", "noor@filigrane.team"),
        ("kai", "Kai", "kai@filigrane.team"),
        ("ines", "Inès", "ines@filigrane.team"),
        ("leo", "Leo", "leo@filigrane.team"),
        ("hana", "Hana", "hana@filigrane.team"),
        ("ida", "Ida", "ida@filigrane.team"),
        ("omer", "Omer", "omer@filigrane.team"),
        ("sofi", "Sofi", "sofi@filigrane.team"),
        ("milo", "Milo", "milo@filigrane.team"),
    )

    url = sync_url(raw)
    slugs = [entry[0] for entry in roster]

    placeholders = ",".join(["%s"] * len(slugs))

    with psycopg.connect(url) as conn:
        for handle_slug, label, mailbox in roster:
            conn.execute(
                """
                INSERT INTO users (handle, email, name)
                VALUES (%s, %s, %s)
                ON CONFLICT (handle) DO UPDATE
                    SET email = EXCLUDED.email,
                        name = EXCLUDED.name;
                """,
                (handle_slug, mailbox, label),
            )
            conn.execute(
                """
                INSERT INTO magic_login_allowlist (email)
                VALUES (%s)
                ON CONFLICT (email) DO NOTHING;
                """,
                (mailbox,),
            )

        pivot_rows = conn.execute(
            f"SELECT id, handle FROM users WHERE handle IN ({placeholders});",
            slugs,
        ).fetchall()

        pivot = {row[1]: int(row[0]) for row in pivot_rows}

        for follower_handle, target_handle in itertools.permutations(slugs, 2):
            conn.execute(
                """
                INSERT INTO follows (follower_id, followee_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (pivot[follower_handle], pivot[target_handle]),
            )

        conn.commit()

    print("seed_ok")


if __name__ == "__main__":
    main()
