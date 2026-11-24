"""Title, description and keywords for an image from the n8n vision workflow.

The backend sends the stored JPEG preview (long side ``settings.image_preview_side``,
no EXIF) as the multipart field ``image`` to ``settings.n8n_image_url`` with the same
``Authorization`` header as the variable enrichment. The workflow answers
``{"ok": true, "title": ..., "description": ..., "keywords": [...]}``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..config import settings
from ..enrich import EnrichError, NotConfigured
from .collection import Suggestion

ATTEMPTS = 2
MAX_TITLE = 300
MAX_DESCRIPTION = 4000
MAX_KEYWORDS = 15
MAX_KEYWORD = 100


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, str) else ""


def normalize(data: Any) -> Suggestion:
    """The workflow's answer as a suggestion; anything malformed is dropped, not trusted."""
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict) or data.get("ok") is False:
        error = data.get("error") if isinstance(data, dict) else None
        raise EnrichError(f"the image could not be described ({error or 'unexpected answer'})")
    keywords: list[str] = []
    seen: set[str] = set()
    for k in data.get("keywords") or []:
        k = _text(k, MAX_KEYWORD)
        if k and k.lower() not in seen:
            seen.add(k.lower())
            keywords.append(k)
    sug = Suggestion(
        title=_text(data.get("title"), MAX_TITLE),
        description=" ".join(str(data.get("description") or "").split())[:MAX_DESCRIPTION],
        keywords=keywords[:MAX_KEYWORDS],
    )
    if sug.empty:
        raise EnrichError("the model returned no title, description or keywords")
    return sug


async def describe(preview: bytes, filename: str, *, client: httpx.AsyncClient | None = None) -> Suggestion:
    if not settings.n8n_bearer_key:
        raise NotConfigured("AI description is not configured (set DDI_N8N_BEARER_KEY)")
    headers = {"Authorization": settings.n8n_bearer_key}
    own = client is None
    client = client or httpx.AsyncClient(timeout=settings.n8n_timeout)
    last = "no attempts"
    try:
        for attempt in range(ATTEMPTS):
            try:
                r = await client.post(
                    settings.n8n_image_url,
                    files={"image": (filename, preview, "image/jpeg")},
                    headers=headers,
                )
                if 400 <= r.status_code < 500:
                    raise EnrichError(f"n8n refused the image ({r.status_code}: {r.text[:200]})")
                if r.status_code == 502:  # the workflow's own "model failed" answer
                    return normalize(r.json())
                r.raise_for_status()
                return normalize(r.json())
            except EnrichError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < ATTEMPTS - 1:
                await asyncio.sleep(2)
    finally:
        if own:
            await client.aclose()
    raise EnrichError(f"n8n call failed after {ATTEMPTS} attempts ({last})")
