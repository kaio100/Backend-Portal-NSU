"""Classificacao de status da NFS-e com XML reais do ADN (mascarados).

Regressao dos incidentes de producao de set/2026:
- nota substituta valida (cStat 101) gravada como "substituida";
- nota com "evento" no nome ou na descricao do servico tratada como evento
  e escondida do portal;
- "Solicitacao de Analise Fiscal para Cancelamento" gravada como cancelada;
- cancelamento por substituicao gravado como cancelada.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from backend.app.db.models import Arquivo, Empresa, Evento, Nota, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import legacy_ingestion_service
from backend.app.services.nfse_status_service import classificar_xml
from backend.app.services.storage_service import LocalFilesystemStorage

FIXTURES = Path(__file__).parent / "fixtures" / "nfse_reais"


def _resumo(nome: str) -> dict:
    return legacy_ingestion_service._parse_xml_resumo(FIXTURES / nome)


@pytest.mark.parametrize(
    ("arquivo", "tipo", "status", "rotulo"),
    [
        ("nota_cstat100.xml", "nota", "autorizada", "Autorizada"),
        ("nota_cstat101_substituta.xml", "nota", "autorizada", "Autorizada"),
        ("nota_cstat102_decisao_judicial.xml", "nota", "autorizada", "Autorizada"),
        ("nota_cstat103_avulsa.xml", "nota", "autorizada", "Autorizada"),
        ("nota_cstat107_mei.xml", "nota", "autorizada", "MEI"),
        ("nota_substituta_servico_de_eventos.xml", "nota", "autorizada", "Autorizada"),
        ("evento_e101101_cancelamento.xml", "evento", "cancelada", "Cancelada"),
        ("evento_e105104_cancelamento_deferido.xml", "evento", "cancelada", "Cancelada"),
        ("evento_e105102_cancelamento_por_substituicao.xml", "evento", "substituida", "Substituida"),
        ("evento_e101103_solicitacao_analise_fiscal.xml", "evento", None, None),
        ("evento_e203202_confirmacao_tomador.xml", "evento", None, None),
        ("evento_e203206_rejeicao_tomador.xml", "evento", None, None),
    ],
)
def test_classifica_xml_real_pela_estrutura(arquivo, tipo, status, rotulo):
    classificacao = classificar_xml(ElementTree.parse(FIXTURES / arquivo).getroot())
    assert (classificacao.tipo, classificacao.status, classificacao.rotulo) == (tipo, status, rotulo)

    resumo = _resumo(arquivo)
    assert resumo["tipo_xml"] == tipo
    assert (resumo["status_documento"] or None) == status
    if tipo == "evento":
        assert len(resumo["chave_afetada"]) == 50
        assert resumo["codigo_evento"].startswith("e")


def test_nota_substituta_aponta_para_a_nota_antiga():
    for arquivo in ("nota_cstat101_substituta.xml", "nota_substituta_servico_de_eventos.xml"):
        resumo = _resumo(arquivo)
        assert len(resumo["chave_substituida"]) == 50
        assert resumo["chave_substituida"] != resumo["chave"]
        assert resumo["chave_afetada"] == ""
    assert _resumo("nota_cstat100.xml")["chave_substituida"] == ""


@pytest.mark.parametrize(
    "texto",
    [
        "Cancelamento de contrato de locacao",
        "Servico sujeito a substituicao tributaria",
        "Organizacao de evento corporativo",
        "Nota substituta emitida apos cancelamento",
    ],
)
def test_palavras_no_texto_nao_mudam_o_status_da_nota(texto):
    xml = (
        '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS' + "1" * 50 + '">'
        "<cStat>100</cStat><emit><xNome>EVENTOS E CANCELAMENTOS LTDA</xNome></emit>"
        f"<DPS><infDPS><serv><cServ><xDescServ>{texto}</xDescServ></cServ></serv></infDPS></DPS>"
        "</infNFSe></NFSe>"
    )
    classificacao = classificar_xml(ElementTree.fromstring(xml))
    assert (classificacao.tipo, classificacao.status) == ("nota", "autorizada")


def _evento(codigo: str | None, descricao: str, motivo: str = "") -> ElementTree.Element:
    grupo = (
        f"<{codigo}><xDesc>{descricao}</xDesc><xMotivo>{motivo}</xMotivo></{codigo}>"
        if codigo
        else f"<xDesc>{descricao}</xDesc><xMotivo>{motivo}</xMotivo>"
    )
    return ElementTree.fromstring(
        '<evento xmlns="http://www.sped.fazenda.gov.br/nfse"><infEvento Id="EVT1"><pedRegEvento><infPedReg Id="PRE1">'
        f"<chNFSe>{'2' * 50}</chNFSe>{grupo}</infPedReg></pedRegEvento></infEvento></evento>"
    )


def test_evento_desconhecido_nao_muda_status_mesmo_com_cancelamento_no_texto():
    classificacao = classificar_xml(
        _evento("e999999", "Cancelamento de NFS-e Indeferido por Analise Fiscal", "pedido de cancelamento")
    )
    assert classificacao.tipo == "evento"
    assert classificacao.status is None


def test_evento_indeferido_nao_cancela():
    classificacao = classificar_xml(_evento("e105105", "Cancelamento de NFS-e Indeferido por Analise Fiscal"))
    assert classificacao.status is None


def test_motivo_livre_nao_decide_o_evento():
    # O motivo e digitado pelo emitente; so o codigo do evento decide.
    classificacao = classificar_xml(
        _evento("e203206", "Manifestacao de NFS-e - Rejeicao do Tomador", "nota deve ser cancelada e substituida")
    )
    assert classificacao.status is None


def test_evento_sem_codigo_usa_a_descricao_inteira():
    assert classificar_xml(_evento(None, "Cancelamento de NFS-e")).status == "cancelada"
    assert classificar_xml(_evento(None, "Cancelamento de NFS-e por Substituição")).status == "substituida"
    assert classificar_xml(_evento(None, "Pedido de cancelamento em analise")).status is None


def test_cstat_desconhecido_fica_visivel():
    xml = '<NFSe><infNFSe Id="NFS' + "3" * 50 + '"><cStat>104</cStat></infNFSe></NFSe>'
    classificacao = classificar_xml(ElementTree.fromstring(xml))
    assert (classificacao.status, classificacao.rotulo) == ("cstat_104", "Codigo 104")


# --------------------------------------------------------------------------
# Ingestao completa: indice do motor legado + XML reais
# --------------------------------------------------------------------------


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


def _nota_xml(tmp_path: Path, chave: str) -> Path:
    caminho = tmp_path / f"nota_{chave[-6:]}.xml"
    caminho.write_text(
        '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS' + chave + '">'
        "<cStat>100</cStat><nNFSe>1</nNFSe></infNFSe></NFSe>",
        encoding="utf-8",
    )
    return caminho


def _ingerir(
    tmp_path: Path,
    arquivos: list[Path],
    notas_existentes: dict[str, str] | None = None,
    eventos_existentes: dict[str, str] | None = None,
) -> dict:
    """Ingere os XML na ordem dada; notas/eventos_existentes = {chave: status}."""
    linhas = ["chave;xml_path;pdf_path;competencia"]
    for arquivo in arquivos:
        chave = legacy_ingestion_service._parse_xml_resumo(arquivo)["chave"]
        linhas.append(f"{chave};{arquivo};;2026-08-01")
    (tmp_path / "index_nfse.csv").write_text("\n".join(linhas) + "\n", encoding="utf-8")
    with SessionLocal() as db:
        empresa = Empresa(nome="Classificacao LTDA", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        for chave, status in (notas_existentes or {}).items():
            db.add(Nota(empresa_id=empresa.id, chave=chave, status_documento=status, status_rotulo=status.capitalize()))
        for i, (chave, tipo) in enumerate((eventos_existentes or {}).items()):
            db.add(Evento(empresa_id=empresa.id, chave_evento=f"EVT{i}", chave_afetada=chave, tipo_evento=tipo))
        processo = Processo(empresa_id=empresa.id, certificado_id=None, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.flush()
        resultado = legacy_ingestion_service.ingerir_saida_legado(
            db,
            LocalFilesystemStorage(tmp_path / "storage"),
            processo,
            tmp_path,
            gerar_pdf_espelho=False,
        )
        db.commit()
    return resultado


def _status(chave: str) -> str | None:
    with SessionLocal() as db:
        nota = db.query(Nota).filter(Nota.chave == chave).one()
        return nota.status_documento


@pytest.mark.parametrize(
    ("arquivo", "status_final"),
    [
        ("evento_e101101_cancelamento.xml", "cancelada"),
        ("evento_e105104_cancelamento_deferido.xml", "cancelada"),
        ("evento_e105102_cancelamento_por_substituicao.xml", "substituida"),
        ("evento_e101103_solicitacao_analise_fiscal.xml", "autorizada"),
        ("evento_e203202_confirmacao_tomador.xml", "autorizada"),
        ("evento_e203206_rejeicao_tomador.xml", "autorizada"),
    ],
)
def test_evento_real_aplicado_a_nota_existente(tmp_path, arquivo, status_final):
    alvo = _resumo(arquivo)["chave_afetada"]
    _ingerir(tmp_path, [FIXTURES / arquivo], {alvo: "autorizada"})

    assert _status(alvo) == status_final
    with SessionLocal() as db:
        evento = db.query(Evento).one()
        assert evento.chave_afetada == alvo
        assert evento.nota_id is not None
        assert evento.tipo_evento == (status_final if status_final != "autorizada" else "evento")


def test_cancelamento_prevalece_sobre_substituicao_em_qualquer_ordem(tmp_path):
    cancelamento = FIXTURES / "evento_e101101_cancelamento.xml"
    alvo = _resumo(cancelamento.name)["chave_afetada"]
    # Evento de substituicao real, redirecionado para a mesma nota.
    original = FIXTURES / "evento_e105102_cancelamento_por_substituicao.xml"
    substituicao = tmp_path / "substituicao_mesmo_alvo.xml"
    substituicao.write_text(
        original.read_text(encoding="utf-8").replace(_resumo(original.name)["chave_afetada"], alvo),
        encoding="utf-8",
    )
    for ordem, pasta in (([cancelamento, substituicao], "a"), ([substituicao, cancelamento], "b")):
        destino = tmp_path / pasta
        destino.mkdir()
        _ingerir(destino, ordem, {alvo: "autorizada"})
        assert _status(alvo) == "cancelada"
        _banco_limpo_manual()


def _banco_limpo_manual() -> None:
    with SessionLocal() as db:
        for modelo in (Evento, Arquivo, Nota, Processo, Empresa):
            db.query(modelo).delete()
        db.commit()


def test_nota_substituta_marca_a_antiga_como_substituida(tmp_path):
    substituta = FIXTURES / "nota_cstat101_substituta.xml"
    resumo = _resumo(substituta.name)
    resultado = _ingerir(tmp_path, [substituta], {resumo["chave_substituida"]: "autorizada"})

    assert _status(resumo["chave_substituida"]) == "substituida"
    assert _status(resumo["chave"]) == "autorizada"
    assert resultado["notas_marcadas_substituidas"] == 1


@pytest.mark.parametrize("substituta_primeiro", [True, False])
def test_nota_antiga_no_mesmo_lote_fica_substituida_em_qualquer_ordem(tmp_path, substituta_primeiro):
    substituta = FIXTURES / "nota_cstat101_substituta.xml"
    resumo = _resumo(substituta.name)
    antiga = _nota_xml(tmp_path, resumo["chave_substituida"])
    ordem = [substituta, antiga] if substituta_primeiro else [antiga, substituta]
    _ingerir(tmp_path, ordem)

    assert _status(resumo["chave_substituida"]) == "substituida"
    assert _status(resumo["chave"]) == "autorizada"


def test_nota_de_empresa_de_eventos_entra_no_portal(tmp_path):
    arquivo = FIXTURES / "nota_substituta_servico_de_eventos.xml"
    resultado = _ingerir(tmp_path, [arquivo])

    assert resultado["notas_criadas"] == 1
    assert resultado.get("eventos_importados", 0) == 0
    assert _status(_resumo(arquivo.name)["chave"]) == "autorizada"
    with SessionLocal() as db:
        assert db.query(Evento).count() == 0


def test_notas_decisao_judicial_avulsa_e_mei_entram_como_autorizadas(tmp_path):
    arquivos = [
        FIXTURES / "nota_cstat102_decisao_judicial.xml",
        FIXTURES / "nota_cstat103_avulsa.xml",
        FIXTURES / "nota_cstat107_mei.xml",
    ]
    _ingerir(tmp_path, arquivos)
    with SessionLocal() as db:
        rotulos = {nota.status_documento: [] for nota in db.query(Nota).all()}
        for nota in db.query(Nota).all():
            rotulos[nota.status_documento].append(nota.status_rotulo)
    assert set(rotulos) == {"autorizada"}
    assert sorted(rotulos["autorizada"]) == ["Autorizada", "Autorizada", "MEI"]


def test_reprocessar_xml_original_nao_desfaz_cancelamento(tmp_path):
    arquivo = FIXTURES / "nota_cstat100.xml"
    chave = _resumo(arquivo.name)["chave"]
    _ingerir(tmp_path, [arquivo], {chave: "cancelada"})
    assert _status(chave) == "cancelada"


@pytest.mark.parametrize(
    ("tipo_evento", "status_final"),
    [("cancelada", "cancelada"), ("substituida", "substituida"), ("evento", "autorizada")],
)
def test_nota_que_chega_depois_do_evento_recebe_o_status_dele(tmp_path, tipo_evento, status_final):
    arquivo = FIXTURES / "nota_cstat100.xml"
    chave = _resumo(arquivo.name)["chave"]
    _ingerir(tmp_path, [arquivo], eventos_existentes={chave: tipo_evento})

    assert _status(chave) == status_final
    with SessionLocal() as db:
        nota = db.query(Nota).filter(Nota.chave == chave).one()
        evento = db.query(Evento).one()
        assert evento.nota_id == nota.id


def test_cancelamento_gravado_prevalece_sobre_substituicao_gravada(tmp_path):
    arquivo = FIXTURES / "nota_cstat100.xml"
    chave = _resumo(arquivo.name)["chave"]
    _ingerir(tmp_path, [arquivo], eventos_existentes={chave: "substituida"})
    with SessionLocal() as db:
        empresa_id = db.query(Nota).filter(Nota.chave == chave).one().empresa_id
        db.add(Evento(empresa_id=empresa_id, chave_evento="EVT-CANCEL", chave_afetada=chave, tipo_evento="cancelada"))
        db.commit()
        assert legacy_ingestion_service._status_por_eventos_gravados(db, empresa_id, chave)[0] == "cancelada"
