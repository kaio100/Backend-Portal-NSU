from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.db.models import CnpjCache
from backend.app.services import cnpj_invertexto_service


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "simples": {"optante_simples": "S"},
            "mei": {"optante_mei": "N"},
            "atividade_principal": {"codigo": "6201501", "descricao": "Software"},
        }


def test_fallback_preenchido_e_salvo_por_30_dias(monkeypatch):
    db = _session()
    chamadas = []
    monkeypatch.setattr(cnpj_invertexto_service.settings, "invertexto_enabled", True)
    monkeypatch.setattr(cnpj_invertexto_service.settings, "invertexto_token", "token")
    monkeypatch.setattr(cnpj_invertexto_service.settings, "invertexto_cache_days", 30)
    monkeypatch.setattr(
        cnpj_invertexto_service.requests,
        "get",
        lambda *args, **kwargs: chamadas.append((args, kwargs)) or _Response(),
    )

    resultado = cnpj_invertexto_service.consultar_cnpj(db, "11.222.333/0001-81")

    assert resultado["consulta_simples_api"] == "Optante S.N"
    assert len(chamadas) == 1
    cache = db.query(CnpjCache).one()
    assert cache.fonte == "Invertexto"
    assert cache.codigo_cnae == "6201501"
    assert cache.data_expiracao == cache.data_consulta + timedelta(days=30)


def test_fallback_nao_salva_resposta_sem_classificacao(monkeypatch):
    db = _session()
    monkeypatch.setattr(cnpj_invertexto_service.settings, "invertexto_enabled", True)
    monkeypatch.setattr(cnpj_invertexto_service.settings, "invertexto_token", "token")
    monkeypatch.setattr(_Response, "json", lambda self: {"simples": {}, "mei": {}})
    monkeypatch.setattr(cnpj_invertexto_service.requests, "get", lambda *args, **kwargs: _Response())

    assert cnpj_invertexto_service.consultar_cnpj(db, "11222333000181") is None
    assert db.query(CnpjCache).count() == 0
