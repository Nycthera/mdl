"""Rate limiting functionality for async requests."""

import asyncio
from collections import defaultdict
from src.utils import _loop_time


class RateLimiter:
    """Rate limiter for controlling request frequency."""

    def __init__(self, max_calls: int = 5, per_seconds: float = 1):
        """Initialize rate limiter.

        Args:
            max_calls: Maximum number of calls allowed
            per_seconds: Time window in seconds
        """
        self.max_calls = max_calls
        self.per_seconds = per_seconds
        self._lock = None
        self.calls = defaultdict(list)

    async def _get_lock(self) -> asyncio.Lock:
        """Get or create the async lock."""
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    async def acquire(self, key: str = "global") -> None:
        """Acquire a rate limit slot.

        Args:
            key: Identifier for rate limit group
        """
        lock = await self._get_lock()
        async with lock:
            now = _loop_time()
            calls = self.calls[key]
            while calls and calls[0] <= now - self.per_seconds:
                calls.pop(0)
            if len(calls) >= self.max_calls:
                sleep_for = self.per_seconds - (now - calls[0])
                await asyncio.sleep(max(sleep_for, 0))
            self.calls[key].append(_loop_time())


# Global rate limiters
rate_limiter = RateLimiter(max_calls=5, per_seconds=1)
rate_limiter_athome = RateLimiter(max_calls=1, per_seconds=1.5)
