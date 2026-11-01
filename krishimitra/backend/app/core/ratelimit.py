"""Fixed-window rate limiter. Uses Redis when REDIS_URL is set (shared across API instances), else per-process memory."""
import time
from collections import defaultdict

from fastapi import HTTPException

from app.core.config import get_settings

_mem: dict[str, list[float]] = defaultdict(list)
_redis = None


def _client():
    global _redis
    s = get_settings()
    if not s.redis_url:
        return None
    if _redis is None:
        import redis
        _redis = redis.Redis.from_url(s.redis_url, socket_timeout=0.5)
    return _redis


def rate_limit(key: str, limit: int, window: int = 60) -> None:
    limit *= get_settings().rate_limit_multiplier
    r = _client()
    if r is not None:
        try:
            k = f"rl:{key}:{int(time.time() // window)}"
            n = r.incr(k)
            if n == 1:
                r.expire(k, window + 1)
            if n > limit:
                raise HTTPException(429, "Too many requests, try again shortly")
            return
        except HTTPException:
            raise
        except Exception:      # Redis down: fall back to memory rather than failing requests
            pass
    now = time.time()
    _mem[key] = [t for t in _mem[key] if now - t < window]
    if len(_mem[key]) >= limit:
        raise HTTPException(429, "Too many requests, try again shortly")
    _mem[key].append(now)
