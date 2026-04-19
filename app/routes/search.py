import os

import meilisearch
from fastapi import APIRouter, HTTPException, Query

from ..cache import get_cached, set_cached

router = APIRouter()

MEILI_URL = os.getenv("MEILI_URL", "http://localhost:7700")
MEILI_API_KEY = os.getenv("MEILI_API_KEY", "parth123")
MEILI_INDEX = os.getenv("MEILI_INDEX", "wikipedia")

client = meilisearch.Client(MEILI_URL, MEILI_API_KEY)
client.index("wikipedia").update_settings({
    "displayedAttributes": ["title", "excerpt", "text", "url"]
})


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
):
    cache_key = f"search:{q}:{limit}"
    cached = await get_cached(cache_key)
    if cached:
        return cached

    try:
        results = client.index(MEILI_INDEX).search(
            q,
            {
                "limit": limit,
                "attributesToRetrieve": ["title", "excerpt", "url"],
                "attributesToHighlight": ["title", "excerpt"],
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Search backend unavailable: {exc}") from exc

    response = {
        "query": q,
        "total": results.get("estimatedTotalHits", 0),
        "results": results.get("hits", []),
    }

    await set_cached(cache_key, response, ttl=600)
    return response