"""Script de correcao do status fiscal gravado pela classificacao antiga."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app.db.models import Arquivo, Empresa, Evento, Nota, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.scripts import corrigir_status_fiscal
from backend.app.services import legacy_ingestion_service
from backend.app.services.storage_service import LocalFilesystemStorage

FIXTURES = Path(__file__).parent / "fixtures" / "nfse_reais"


def _resumo(nome: str) -> dict:
    return legacy_ingestion_service._parse_xml_resumo(FIXTURES / nome)


def _nota_xml(chave: str, cstat: str = "100") -> bytes:
    return (
        '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS' + chave + '">'
        f"<cStat>{cstat}</cStat><nNFSe>1</nNFSe></infNFSe></NFSe>"
    ).encode("utf-8")


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()
    with SessionLocal() as db:
        for modelo in (Evento, Arquivo, Nota, Processo, Empresa):
            db.query(modelo).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        for modelo in (Evento, Arquivo, Nota, Processo, Empresa):
            db.query(modelo).delete()
        db.commit()


@pytest.fixture()
def cenario(tmp_path):
    storage = LocalFilesystemStorage(tmp_path / "storage")
    solicitacao = _resumo("evento_e101103_solicitacao_analise_fiscal.xml")
    por_substituicao = _resumo("evento_e105102_cancelamento_por_substituicao.xml")
    cancelamento = _resumo("evento_e101101_cancelamento.xml")
    fantasma = _resumo("nota_substituta_servico_de_eventos.xml")
    substituta = _resumo("nota_cstat101_substituta.xml")

    chaves = {
        "pedido_so": solicitacao["chave_afetada"],
        "substituida_por_evento": por_substituicao["chave_afetada"],
        "cancelada_sem_status": cancelamento["chave_afetada"],
        "antiga_da_fantasma": fantasma["chave_substituida"],
        "substituta": substituta["chave"],
        "antiga_da_substituta": substituta["chave_substituida"],
        "fantasma": fantasma["chave"],
        "cstat102": "7" * 50,
        "cstat102_conferida": "8" * 50,
        "simples_da_tela": "9" * 50,
        "cancelada_sem_evento": "6" * 50,
    }

    def put(key: str, data: bytes) -> str:
        storage.put_bytes(key, data)
        return key

    with SessionLocal() as db:
        empresa = Empresa(nome="Correcao LTDA", cnpj="22333444000155", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()

        def nota(nome, status, xml, **extra):
            db.add(
                Nota(
                    empresa_id=empresa.id,
                    chave=chaves[nome],
                    status_documento=status,
                    status_rotulo=(status or "").capitalize() or None,
                    xml_storage_key=put(f"xml/{nome}.xml", xml),
                    **extra,
                )
            )

        nota("pedido_so", "cancelada", _nota_xml(chaves["pedido_so"]))
        nota("substituida_por_evento", "cancelada", _nota_xml(chaves["substituida_por_evento"]))
        nota("cancelada_sem_status", "autorizada", _nota_xml(chaves["cancelada_sem_status"]))
        nota("antiga_da_fantasma", "autorizada", _nota_xml(chaves["antiga_da_fantasma"]))
        nota("substituta", "substituida", (FIXTURES / "nota_cstat101_substituta.xml").read_bytes())
        nota("antiga_da_substituta", "autorizada", _nota_xml(chaves["antiga_da_substituta"]))
        nota("cstat102", "cstat_102", _nota_xml(chaves["cstat102"], "102"))
        nota("cstat102_conferida", "cstat_102", _nota_xml(chaves["cstat102_conferida"], "102"), conferencia_status="ok")
        nota("cancelada_sem_evento", "cancelada", _nota_xml(chaves["cancelada_sem_evento"]))
        nota(
            "simples_da_tela",
            "autorizada",
            _nota_xml(chaves["simples_da_tela"]),
            simples_xml="Optante S.N",
            status_simples_nacional="Correto",
        )

        def evento(nome_fixture, chave_evento, tipo, chave_afetada):
            db.add(
                Evento(
                    empresa_id=empresa.id,
                    chave_evento=chave_evento,
                    chave_afetada=chave_afetada,
                    tipo_evento=tipo,
                    xml_storage_key=put(f"xml/{nome_fixture}", (FIXTURES / nome_fixture).read_bytes()),
                )
            )

        evento("evento_e101103_solicitacao_analise_fiscal.xml", "EV1", "cancelada", chaves["pedido_so"])
        evento("evento_e105102_cancelamento_por_substituicao.xml", "EV2", "cancelada", chaves["substituida_por_evento"])
        evento("evento_e101101_cancelamento.xml", "EV3", "cancelada", chaves["cancelada_sem_status"])
        evento("nota_substituta_servico_de_eventos.xml", "EV4", "autorizada", chaves["antiga_da_fantasma"])
        db.commit()
    return storage, chaves


def _status(chave: str) -> tuple[str | None, str | None] | None:
    with SessionLocal() as db:
        nota = db.query(Nota).filter(Nota.chave == chave).one_or_none()
        return (nota.status_documento, nota.status_rotulo) if nota else None


def _foto() -> list[tuple]:
    with SessionLocal() as db:
        notas = [(n.chave, n.status_documento, n.status_simples_nacional) for n in db.query(Nota).order_by(Nota.id)]
        eventos = [(e.chave_evento, e.tipo_evento) for e in db.query(Evento).order_by(Evento.id)]
    return notas + eventos


def test_simulacao_nao_altera_nada_e_relata_as_correcoes(cenario):
    storage, chaves = cenario
    antes = _foto()

    relatorio = corrigir_status_fiscal.executar(aplicar=False, storage=storage, workers=2)

    assert _foto() == antes
    resumo = relatorio.resumo()
    assert resumo["eventos_reclassificados"] == 2  # solicitacao e por substituicao
    assert resumo["eventos_que_sao_notas"] == 1
    # Conferida com status a mudar e cancelada sem nenhum evento (sem prova).
    assert resumo["revisao_manual"] == 2
    assert resumo["simples_corrigidas"] == 1
    mudancas = {m["chave"]: (m["de"], m["para"]) for m in relatorio.notas_alteradas}
    assert mudancas[chaves["pedido_so"]] == ("cancelada", "autorizada")
    assert mudancas[chaves["substituida_por_evento"]] == ("cancelada", "substituida")
    assert mudancas[chaves["cancelada_sem_status"]] == ("autorizada", "cancelada")
    assert mudancas[chaves["substituta"]] == ("substituida", "autorizada")
    assert mudancas[chaves["antiga_da_substituta"]] == ("autorizada", "substituida")
    assert mudancas[chaves["antiga_da_fantasma"]] == ("autorizada", "substituida")
    assert mudancas[chaves["cstat102"]] == ("cstat_102", "autorizada")


def test_aplicacao_corrige_status_eventos_e_cria_notas_escondidas(cenario):
    storage, chaves = cenario

    relatorio = corrigir_status_fiscal.executar(aplicar=True, storage=storage, workers=2)

    assert relatorio.erros == []
    assert _status(chaves["pedido_so"]) == ("autorizada", "Autorizada")
    assert _status(chaves["substituida_por_evento"]) == ("substituida", "Substituida")
    assert _status(chaves["cancelada_sem_status"]) == ("cancelada", "Cancelada")
    assert _status(chaves["substituta"]) == ("autorizada", "Autorizada")
    assert _status(chaves["antiga_da_substituta"]) == ("substituida", "Substituida")
    assert _status(chaves["antiga_da_fantasma"]) == ("substituida", "Substituida")
    assert _status(chaves["cstat102"]) == ("autorizada", "Autorizada")
    # Conferida ou sem prova: fica como estava e vai para revisao manual.
    assert _status(chaves["cstat102_conferida"]) == ("cstat_102", "Cstat_102")
    assert _status(chaves["cancelada_sem_evento"]) == ("cancelada", "Cancelada")
    # A nota que estava gravada como evento agora existe como nota.
    assert _status(chaves["fantasma"]) == ("autorizada", "Autorizada")
    assert relatorio.notas_criadas == 1
    with SessionLocal() as db:
        tipos = {e.chave_evento: e.tipo_evento for e in db.query(Evento)}
        simples = db.query(Nota).filter(Nota.chave == chaves["simples_da_tela"]).one().status_simples_nacional
    assert tipos == {"EV1": "evento", "EV2": "substituida", "EV3": "cancelada"}
    assert simples == "Informado no XML"


def test_aplicar_duas_vezes_nao_muda_mais_nada(cenario):
    storage, _ = cenario
    corrigir_status_fiscal.executar(aplicar=True, storage=storage, workers=2)
    segunda = corrigir_status_fiscal.executar(aplicar=True, storage=storage, workers=2)

    resumo = segunda.resumo()
    assert resumo["notas_alteradas"] == 0, segunda.notas_alteradas
    assert resumo["eventos_reclassificados"] == 0
    assert resumo["eventos_que_sao_notas"] == 0
    assert resumo["simples_corrigidas"] == 0
