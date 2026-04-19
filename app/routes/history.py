@router.get("/history")
async def get_history(
    api_key=Depends(get_api_key),
    db: AsyncSession = Depends(get_db)
):
    logs = await db.execute(
        select(SearchLog)
        .where(SearchLog.api_key_id == api_key.id)
        .order_by(SearchLog.searched_at.desc())
        .limit(50)
    )
    return logs.scalars().all()