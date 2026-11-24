"""进程内滑动窗口限流，用于登录/注册等敏感入口。"""

import time
from collections import defaultdict, deque
from threading import Lock


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = max(1, int(limit))
        self.window_seconds = max(1.0, float(window_seconds))
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, key: str, *, now: float | None = None) -> tuple[bool, int]:
        current = time.time() if now is None else now
        with self._lock:
            bucket = self._hits[key]
            boundary = current - self.window_seconds
            while bucket and bucket[0] <= boundary:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = int(bucket[0] + self.window_seconds - current) + 1
                return False, max(1, retry_after)
            bucket.append(current)
            if len(self._hits) > 10_000:
                for item_key in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(item_key, None)
            return True, 0
