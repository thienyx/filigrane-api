from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

_TRACKER_PREFIXES = (
    "utm_",
    "_ga",
    "_gl",
)
_EXACT_DROP = {
    "gclid",
    "fbclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "si",
    "ref",
    "ref_src",
    "source",
}


def normalize_url(raw: str) -> str:
    stripped = raw.strip()
    if not stripped:
        msg = "URL must not be empty"
        raise ValueError(msg)
    has_scheme = "://" in stripped
    candidate = stripped if has_scheme else f"https://{stripped}"
    parts = urlsplit(candidate)
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if not netloc:
        msg = "URL must include a host"
        raise ValueError(msg)
    path = parts.path or "/"
    filtered_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lower_key = key.lower()
        if _is_tracker(lower_key):
            continue
        filtered_query.append((key, value))
    filtered_query.sort(key=lambda item: item[0].lower())
    query = urlencode(filtered_query, doseq=True)
    rebuilt = urlunsplit((scheme, netloc, path, query, ""))
    return rebuilt


async def finalize_after_redirects(url: str, client: httpx.AsyncClient) -> str:
    resolved = normalize_url(url)
    try:
        response = await client.get(
            resolved,
            follow_redirects=True,
            timeout=httpx.Timeout(8.0, connect=3.0),
        )
        return normalize_url(str(response.url))
    except Exception:
        return resolved


def _is_tracker(param: str) -> bool:
    if param.startswith(_TRACKER_PREFIXES):
        return True
    return param in _EXACT_DROP
