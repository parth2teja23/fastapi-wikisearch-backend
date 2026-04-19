from fastapi import Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .models import APIKey

async def get_api_key(
    x_api_key: str = Header(...),
    db: AsyncSession = Depends(get_db)
):
    key = await db.execute(
        select(APIKey).where(APIKey.key == x_api_key)
    )
    key = key.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return key