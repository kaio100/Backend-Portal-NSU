from datetime import date, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.db.base import Base
from backend.app.db.models import CnpjCache
from backend.app.services import cnpj_cache_service, cnpj_receita_service


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _resposta(cnpj: str) -> dict:
    return {
        "cnpj": cnpj,
        "fonte": cnpj_cache_service.RECEITA_FONTE,
        "opcao_simples": "S",
        "opcao_mei": "N",
        "cnae_fiscal_principal": "6201501",
    }


def test_consulta_individual_salva_e_reutiliza_cache_por_30_dias(monkeypatch):
    db = _session()
    chamadas = []

    def consultar(cnpj: str):
        chamadas.append(cnpj)
        return _resposta(cnpj)

    monkeypatch.setattr(cnpj_receita_service, "consultar_cnpj", consultar)
    monkeypatch.setattr(cnpj_receita_service.settings, "cnpj_receita_cache_days", 30)

    primeira = cnpj_receita_service.consultar_cnpj_cacheado(db, "11.222.333/0001-81")
    segunda = cnpj_receita_service.consultar_cnpj_cacheado(db, "11222333000181")

    assert primeira == segunda
    assert chamadas == ["11222333000181"]
    cache = db.query(CnpjCache).one()
    assert cache.consulta_simples_api == "Optante S.N"
    assert cache.data_expiracao == cache.data_consulta + timedelta(days=30)


def test_consulta_individual_renova_cache_expirado(monkeypatch):
    db = _session()
    db.add(
        CnpjCache(
            cnpj="11222333000181",
            fonte=cnpj_cache_service.RECEITA_FONTE,
            consulta_simples_api="Não optante",
            status_consulta="Encontrado",
            json_resposta={"cnpj": "antigo"},
            data_consulta=date.today() - timedelta(days=31),
            data_expiracao=date.today() - timedelta(days=1),
        )
    )
    db.commit()
    monkeypatch.setattr(cnpj_receita_service, "consultar_cnpj", lambda cnpj: _resposta(cnpj))

    resultado = cnpj_receita_service.consultar_cnpj_cacheado(db, "11222333000181")

    assert resultado["cnpj"] == "11222333000181"
    cache = db.query(CnpjCache).one()
    assert cache.consulta_simples_api == "Optante S.N"
    assert cache.data_expiracao == cache.data_consulta + timedelta(days=30)


def test_consulta_sem_resultado_nao_grava_cache(monkeypatch):
    db = _session()
    monkeypatch.setattr(cnpj_receita_service, "consultar_cnpj", lambda _cnpj: None)

    assert cnpj_receita_service.consultar_cnpj_cacheado(db, "11222333000181") is None
    assert db.query(CnpjCache).count() == 0
