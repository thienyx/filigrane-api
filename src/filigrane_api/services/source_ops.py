from __future__ import annotations

from urllib.parse import urlsplit

import httpx
from sqlalchemy import Select, literal_column, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from filigrane_api.models.entities import Source
from filigrane_api.models.enums import SourceKind
from filigrane_api.services.source_metadata import extract_open_graph, infer_kind
from filigrane_api.services.url_canonical import finalize_after_redirects
from filigrane_api.utils.time import utcnow


async def bump_source_revision(session: AsyncSession, source_id: int) -> None:
    await session.execute(
        update(Source)
        .where(Source.id == source_id)
        .values(revision=literal_column("revision + 1")),
    )


async def ensure_source(session: AsyncSession, canonical_url: str) -> Source:
    stmt: Select[tuple[Source]] = select(Source).where(
        Source.canonical_url == canonical_url,
    )
    stored = await session.scalar(stmt)
    if stored:
        return stored

    parsed_host = urlsplit(canonical_url).netloc or urlsplit(canonical_url).path or ""
    row = Source(
        canonical_url=canonical_url,
        host=parsed_host,
        kind=SourceKind.OTHER,
        revision=0,
    )
    session.add(row)
    await session.flush()
    return row


async def hydrate_source_payload(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source_id: int,
    landing_url: str,
) -> None:
    headers = {"User-Agent": "FiligraneBot/1.0"}
    async with httpx.AsyncClient(headers=headers) as http_client:
        try:
            final_url = await finalize_after_redirects(landing_url, http_client)
            response = await http_client.get(
                final_url,
                timeout=httpx.Timeout(12.0, connect=4.0),
                follow_redirects=True,
            )
            response.raise_for_status()
            html_blob = response.text
        except Exception:
            return

    async with session_factory() as scoped_session:
        resource = await scoped_session.get(Source, source_id)
        if resource is None:
            return

        snippet = extract_open_graph(html_blob)
        resource.title = snippet.get("title") or resource.title
        resource.description = snippet.get("description") or resource.description
        resource.image_url = snippet.get("image_url") or resource.image_url
        publication = snippet.get("published_at")
        if publication:
            resource.published_at = publication
        resource.kind = infer_kind(resource.host, snippet.get("og:type"), final_url)
        resource.fetched_at = utcnow()
        await bump_source_revision(scoped_session, resource.id)
        await scoped_session.commit()
