"""Eventos que o indice unico do motor legado esconde.

O ADN distribui o evento com a chave da nota que ele atinge. No
index_nfse.csv (uma linha por chave) o evento so atualizava o NSU da linha da
nota, e o XML dele nunca chegava a ingestao. Em producao, depois de 17/09/2026,
os cancelamentos de notas baixadas no mesmo container pararam de entrar.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import adn_nfse_downloader as motor
from backend.app.db.models import Arquivo, Empresa, Evento, Nota, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import legacy_ingestion_service
from backend.app.services.storage_service import LocalFilesystemStorage

FIXTURES = Path(__file__).parent / "fixtures" / "nfse_reais"


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
def saida_motor(tmp_path, monkeypatch):
    monkeypatch.setattr(motor, "INDEX_UNICO_FILE", tmp_path / "index_nfse.csv")
    monkeypatch.setattr(motor, "OCORRENCIAS_FILE", tmp_path / "ocorrencias_nsu.csv")
    return tmp_path


def _registrar_no_motor(saida: Path, nsu: str, chave: str, tipo: str, xml_origem: Path) -> None:
    """Mesmo registro que processar_documento faz para cada documento do ADN."""
    xml_path = saida / f"{nsu}_{chave}.xml"
    shutil.copyfile(xml_origem, xml_path)
    motor.upsert_indexes(
        {
            "chave": chave,
            "primeiro_nsu": nsu,
            "ultimo_nsu": nsu,
            "qtd_ocorrencias": "1",
            "tipo_documento": tipo,
            "competencia": "2026-09-01",
            "xml_path": str(xml_path),
            "atualizado_em": motor.agora_iso(),
        },
        {
            "nsu": nsu,
            "chave": chave,
            "tipo_documento": tipo,
            "xml_path": str(xml_path),
            "registrado_em": motor.agora_iso(),
        },
    )


def _nota_xml(tmp_path: Path, chave: str) -> Path:
    caminho = tmp_path / "nota_origem.xml"
    caminho.write_text(
        '<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse"><infNFSe Id="NFS' + chave + '">'
        "<cStat>100</cStat><nNFSe>1</nNFSe></infNFSe></NFSe>",
        encoding="utf-8",
    )
    return caminho


def _ingerir(saida: Path) -> dict:
    with SessionLocal() as db:
        empresa = Empresa(nome="Indice LTDA", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, certificado_id=None, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.flush()
        resultado = legacy_ingestion_service.ingerir_saida_legado(
            db, LocalFilesystemStorage(saida / "storage"), processo, saida, gerar_pdf_espelho=False
        )
        db.commit()
    return resultado


def test_evento_da_mesma_chave_da_nota_chega_ao_banco(saida_motor, tmp_path):
    evento = FIXTURES / "evento_e101101_cancelamento.xml"
    chave = legacy_ingestion_service._parse_xml_resumo(evento)["chave_afetada"]
    origem = tmp_path / "origem"
    origem.mkdir()
    _registrar_no_motor(saida_motor, "100", chave, "NFSE", _nota_xml(origem, chave))
    _registrar_no_motor(saida_motor, "101", chave, "EVENTO", evento)

    # O indice continua com uma linha so, apontando para o XML da nota.
    linhas = legacy_ingestion_service._read_index_rows(saida_motor / "index_nfse.csv")
    assert len(linhas) == 1 and linhas[0]["xml_path"].endswith(f"100_{chave}.xml")

    resultado = _ingerir(saida_motor)

    assert resultado["eventos_importados"] == 1
    with SessionLocal() as db:
        nota = db.query(Nota).filter(Nota.chave == chave).one()
        assert nota.status_documento == "cancelada"
        assert db.query(Evento).filter(Evento.chave_afetada == chave).count() == 1


def test_ocorrencia_ja_no_indice_nao_e_processada_duas_vezes(saida_motor, tmp_path):
    origem = tmp_path / "origem"
    origem.mkdir()
    chave = "4" * 50
    _registrar_no_motor(saida_motor, "200", chave, "NFSE", _nota_xml(origem, chave))

    resultado = _ingerir(saida_motor)

    assert resultado["linhas_index_total"] == 1
    assert resultado["notas_criadas"] == 1
