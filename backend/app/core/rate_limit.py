from __future__ import annotations

from functools import lru_cache
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

        from sqlalchemy import func, insert, literal, select, text
        from sqlalchemy.exc import SQLAlchemyError

        from backend.app.db.models import TentativaAcesso

        # A reserva acompanha tambem tentativas com banco saudavel: uma falha
        # nao deve dar uma janela inteira nova a quem ja consumiu o limite.
        reserva_permitiu = self._reserva.allow(key)
        chave = hashlib.sha256(key.encode("utf-8")).hexdigest()
        agora = datetime.now(timezone.utc)
        inicio = agora - timedelta(seconds=self.window_seconds)
        try:
            with _sessao_limitador() as db:
                if db.get_bind().dialect.name == "postgresql":
                    db.execute(text("SELECT set_config('statement_timeout', '1000', true), "
                                    "set_config('lock_timeout', '500', true)"))
                    # Serializa a admissao por chave entre replicas. Dois pedidos
                    # simultaneos nao podem consumir a ultima vaga juntos.
                    lock_id = int.from_bytes(bytes.fromhex(chave[:16]), "big", signed=True)
                    db.execute(text("SELECT pg_advisory_xact_lock(:chave)"), {"chave": lock_id})
                total = select(func.count(TentativaAcesso.id)).where(
                    TentativaAcesso.chave == chave, TentativaAcesso.criado_em >= inicio
                ).scalar_subquery()
                admissao = insert(TentativaAcesso).from_select(
                    ["chave", "criado_em"],
                    select(literal(chave), literal(agora)).where(total < self.max_attempts),
                ).returning(TentativaAcesso.id)
                permitido = db.execute(admissao).scalar_one_or_none() is not None
                if random.random() < 0.01:
                    # Sem DELETE por chave em cada login. A faxina eventual e
                    # limitada para nao varrer/apagar o historico inteiro no login.
                    antigos = select(TentativaAcesso.id).where(
                        TentativaAcesso.criado_em < agora - timedelta(days=1)
                    ).limit(1000)
                    db.query(TentativaAcesso).filter(TentativaAcesso.id.in_(antigos)).delete(synchronize_session=False)
                db.commit()
                return permitido
        except SQLAlchemyError:
            logging.getLogger(__name__).warning("Limite de tentativas sem banco; usando o contador em memoria.")
            return reserva_permitiu


def _sessao_limitador():
    from sqlalchemy.orm import Session
    from backend.app.core.config import settings
    from backend.app.db.session import SessionLocal

    if settings.database_url.startswith("sqlite"):
        return SessionLocal()
    return Session(_engine_limitador())


@lru_cache(maxsize=1)
def _engine_limitador():
    from sqlalchemy import create_engine
    from backend.app.core.config import settings

    # Pool pequeno separado: o login nao fica 30 s aguardando o pool do worker.
    # Timeout de conexao e dos comandos limitado, sem alterar o pool da API.
    return create_engine(
        settings.database_url, pool_size=1, max_overflow=2, pool_timeout=1,
        pool_recycle=300, connect_args={"connect_timeout": 2},
    )
