import json
import os
import time
from typing import Any

try:
	import redis.asyncio as redis
except Exception:  # pragma: no cover
	redis = None


REDIS_URL = os.getenv("REDIS_URL")
_redis_client = redis.from_url(REDIS_URL, decode_responses=True) if (redis and REDIS_URL) else None
_memory_cache: dict[str, tuple[float, Any]] = {}


async def get_cached(key: str) -> Any | None:
	if _redis_client:
		value = await _redis_client.get(key)
		return json.loads(value) if value else None

	item = _memory_cache.get(key)
	if not item:
		return None

	expires_at, payload = item
	if expires_at < time.time():
		_memory_cache.pop(key, None)
		return None

	return payload


async def set_cached(key: str, value: Any, ttl: int = 600) -> None:
	if _redis_client:
		await _redis_client.setex(key, ttl, json.dumps(value))
		return

	_memory_cache[key] = (time.time() + ttl, value)
