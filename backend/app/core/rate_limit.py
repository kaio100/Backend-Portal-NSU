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


class RateLimiterBanco:
    """Janela deslizante gravada no banco (tabela tentativas_acesso).

    Vale entre processos e replicas e sobrevive a deploy e reinicio, o que o
    limitador em memoria nao garante. A chave gravada e um hash: o banco nao
    guarda e-mail nem IP. Se o banco falhar, cai no limitador em memoria em vez
    de liberar tudo ou derrubar o login.
    """

    def __init__(self, max_attempts: int, window_seconds: float) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._reserva = RateLimiter(max_attempts, window_seconds)

    def allow(self, key: str) -> bool:
        import hashlib
        import logging
        import random
        from datetime import datetime, timedelta, timezone

        from sqlalchemy import func
        from sqlalchemy.exc import SQLAlchemyError

        from backend.app.db.models import TentativaAcesso
        from backend.app.db.session import SessionLocal

        chave = hashlib.sha256(key.encode("utf-8")).hexdigest()
        agora = datetime.now(timezone.utc)
        inicio = agora - timedelta(seconds=self.window_seconds)
        try:
            with SessionLocal() as db:
                db.query(TentativaAcesso).filter(
                    TentativaAcesso.chave == chave, TentativaAcesso.criado_em < inicio
                ).delete(synchronize_session=False)
                if random.random() < 0.01:
                    # Faxina ocasional das chaves que nunca mais voltaram.
                    db.query(TentativaAcesso).filter(
                        TentativaAcesso.criado_em < agora - timedelta(days=1)
                    ).delete(synchronize_session=False)
                total = db.query(func.count(TentativaAcesso.id)).filter(TentativaAcesso.chave == chave).scalar() or 0
                permitido = total < self.max_attempts
                if permitido:
                    db.add(TentativaAcesso(chave=chave, criado_em=agora))
                db.commit()
                return permitido
        except SQLAlchemyError:
            logging.getLogger(__name__).warning("Limite de tentativas sem banco; usando o contador em memoria.")
            return self._reserva.allow(key)
