from __future__ import annotations

import time
from collections import defaultdict


class RateTracker:
    def __init__(self):
        self._window: dict[str, list[float]] = defaultdict(list)

    def record(self, provider: str):
        now = time.time()
        self._window[provider] = [t for t in self._window[provider] if now - t < 60]
        self._window[provider].append(now)

    def count_in_window(self, provider: str, window_sec: int = 60) -> int:
        now = time.time()
        return sum(1 for t in self._window[provider] if now - t < window_sec)

    def reset(self, provider: str):
        self._window[provider] = []
