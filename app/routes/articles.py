import os

import meilisearch
from fastapi import APIRouter, HTTPException

router = APIRouter()

MEILI_URL = os.getenv("MEILI_URL", "http://localhost:7700")
MEILI_API_KEY = os.getenv("MEILI_API_KEY", "parth123")
MEILI_INDEX = os.getenv("MEILI_INDEX", "wikipedia")

client = meilisearch.Client(MEILI_URL, MEILI_API_KEY)


@router.get("/article/{title}")
async def get_article(title: str):
    try:
        results = client.index(MEILI_INDEX).search(
            title,
            {"limit": 1, "attributesToRetrieve": ["title", "text", "url"]},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Search backend unavailable: {exc}") from exc

    if not results.get("hits"):
        raise HTTPException(status_code=404, detail="Article not found")
    return results["hits"][0]