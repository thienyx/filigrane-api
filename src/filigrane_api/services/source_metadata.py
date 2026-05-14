from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from selectolax.parser import HTMLParser

from filigrane_api.models.enums import SourceKind


def extract_open_graph(html: str) -> dict[str, Any]:
    tree = HTMLParser(html)
    data: dict[str, Any] = {}
    og_type = _meta_content(tree, "property", "og:type")
    if og_type:
        data["og:type"] = og_type
    for key, attr_name, attr_value in (
        ("title", "property", "og:title"),
        ("description", "property", "og:description"),
        ("image_url", "property", "og:image"),
        ("site_name", "property", "og:site_name"),
    ):
        value = _meta_content(tree, attr_name, attr_value)
        if value:
            data[key] = value
    fallback_title = tree.css_first("title")
    if fallback_title and not data.get("title"):
        text = fallback_title.text()
        if text:
            data["title"] = text.strip()

    twitter_image = _meta_content(tree, "name", "twitter:image")
    if twitter_image and not data.get("image_url"):
        data["image_url"] = twitter_image

    twitter_desc = _meta_content(tree, "name", "twitter:description")
    if twitter_desc and not data.get("description"):
        data["description"] = twitter_desc
    pub = (
        _meta_content(tree, "property", "article:published_time")
        or _meta_content(tree, "name", "pubdate")
    )
    parsed_date = _parse_iso(pub)
    if parsed_date:
        data["published_at"] = parsed_date
    return data


def infer_kind(host: str, og_type: str | None, canonical_url: str) -> SourceKind:
    lower_host = host.lower()
    if "youtube.com" in lower_host or "youtu.be" in lower_host:
        return SourceKind.VIDEO
    if og_type in {"video.other", "video.movie", "video.episode"}:
        return SourceKind.VIDEO
    if og_type in {"article"}:
        return SourceKind.ARTICLE
    if canonical_url.lower().endswith((".mp4", ".webm", ".m3u8")):
        return SourceKind.VIDEO
    return SourceKind.OTHER


def _meta_content(tree: HTMLParser, attr: str, value: str) -> str | None:
    node = tree.css_first(f'meta[{attr}="{value}"]')
    if node is None:
        return None
    content = node.attributes.get("content")
    if not content:
        return None
    return content.strip()


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    candidate = raw.strip()
    if not candidate:
        return None
    try:
        if candidate.endswith("Z"):
            candidate = candidate[:-1] + "+00:00"
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
