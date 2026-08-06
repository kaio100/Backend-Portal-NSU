from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    """Limitador simples em memoria (janela deslizante) por chave arbitraria.

    Nao e compartilhado entre processos: com mais de um worker de API, cada
    processo mantem sua propria contagem. Suficiente como freio contra
    tentativas repetidas de senha; para um limite exato entre instancias
    seria necessario um backend compartilhado (ex: Redis).
    """

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            bucket = self._hits[key]
            while bucket and now - bucket[0] > self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.max_attempts:
                return False
            bucket.append(now)
            return True
