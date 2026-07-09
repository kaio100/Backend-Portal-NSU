from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import text
import pytest

from backend.app.db.models import Arquivo, Certificado, Empresa, Evento, Job, LockProcessamento, LogProcesso, Nota, NsuControle, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.services import legacy_ingestion_service
from backend.app.services.nfse_pdf_service import NfsePdfService
from backend.app.services.nfse_xml_parser import extrair_dados_nfse
from backend.app.services.storage_service import get_storage_service


def _xml_minimo(chave: str = "21075062250227393000149000000000000523108745783896") -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS{chave}">
    <xLocEmi>SAO LUIS</xLocEmi>
    <xLocPrestacao>SAO LUIS</xLocPrestacao>
    <nNFSe>5</nNFSe>
    <xTribNac>Servicos administrativos e apoio operacional.</xTribNac>
    <cStat>100</cStat>
    <dhProc>2023-10-09T18:40:37-03:00</dhProc>
    <emit>
      <CNPJ>50227393000149</CNPJ>
      <IM>12345</IM>
      <xNome>50.227.393 JORGE LUIS DINIZ SILVA</xNome>
      <enderNac><xLgr>RUA TESTE</xLgr><nro>10</nro><xBairro>CENTRO</xBairro><cMun>2107506</cMun><UF>MA</UF><CEP>65000000</CEP></enderNac>
      <fone>98999999999</fone>
      <email>teste@example.com</email>
    </emit>
    <DPS>
      <infDPS>
        <serie>1</serie>
        <nDPS>5</nDPS>
        <dCompet>2023-10-09</dCompet>
        <dhEmi>2023-10-09T18:40:37-03:00</dhEmi>
        <prest><CNPJ>50227393000149</CNPJ><regTrib><opSimpNac>2</opSimpNac><regEspTrib>0</regEspTrib></regTrib></prest>
        <toma><CNPJ>57526860000180</CNPJ><xNome>CANOPUS CONSTRUCOES BELEM LTDA</xNome><end><endNac><cMun>1501402</cMun><CEP>66670000</CEP></endNac><xLgr>ROD MARIO COVAS</xLgr></end></toma>
        <serv><locPrest><cLocPrestacao>2107506</cLocPrestacao></locPrest><cServ><cTribNac>170202</cTribNac><cTribMun>001</cTribMun><xDescServ>Servico prestado com descricao longa, dados bancarios, PIX e observacoes fiscais.</xDescServ><cNBS>123456</cNBS></cServ><infoCompl><xInfComp>Informacoes complementares do XML.</xInfComp></infoCompl></serv>
        <valores><vServPrest><vServ>1391.92</vServ></vServPrest><trib><tribMun><tribISSQN>1</tribISSQN><tpRetISSQN>1</tpRetISSQN><pAliq>4.17</pAliq></tribMun><tribFed><vRetIRRF>0.00</vRetIRRF><vRetCP>0.00</vRetCP><vRetCSLL>0.00</vRetCSLL><vPis>0.00</vPis><vCofins>0.00</vCofins></tribFed></trib></valores>
      </infDPS>
    </DPS>
    <valores><vBC>1391.92</vBC><vISSQN>58.03</vISSQN><vTotalRet>0.00</vTotalRet><vLiq>1391.92</vLiq><vTotTribFed>10.00</vTotTribFed><vTotTribEst>0.00</vTotTribEst><vTotTribMun>20.00</vTotTribMun></valores>
  </infNFSe>
</NFSe>
"""


def _reset_db() -> None:
    init_db()
    with SessionLocal() as db:
        if db.bind and db.bind.dialect.name == "sqlite":
            for model in [
                LogProcesso,
                Job,
                Evento,
                Arquivo,
                Nota,
                NsuControle,
                Processo,
                LockProcessamento,
                Certificado,
                Empresa,
            ]:
                db.query(model).delete()
        else:
            db.execute(
                text(
                    """
                    TRUNCATE TABLE
                        logs_processos,
                        processos_jobs,
                        eventos,
                        arquivos,
                        notas,
                        nsu_controle,
                        processos,
                        locks_processamento,
                        certificados,
                        empresas
                    RESTART IDENTITY CASCADE
                    """
                )
            )
        db.commit()


DOWNLOADS = Path.home() / "Downloads"
NOTA_18_XML = DOWNLOADS / "CNS_PARK_ESTACIONAMENTO_LTDA NFS-e 18.xml"
NOTA_22_XML = DOWNLOADS / "CNS_PARK_ESTACIONAMENTO_LTDA NFS-e 22.xml"


def _require(path: Path) -> Path:
    if not path.exists():
        pytest.skip(f"Arquivo de referencia nao encontrado: {path}")
    return path


def _pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


def test_pdf_service_gera_danfse_v1_compacto(tmp_path: Path):
    xml_path = tmp_path / "nota.xml"
    output_path = tmp_path / "50.227.393_JORGE_LUIS_DINIZ_SILVA NFS-e 5.pdf"
    xml_path.write_text(_xml_minimo(), encoding="utf-8")

    dados = extrair_dados_nfse(xml_path)
    result = NfsePdfService().gerar_danfse_espelho(dados, output_path)

    assert result == output_path
    data = output_path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(PdfReader(output_path).pages) == 1
    assert dados["numero_nfse"] == "5"
    assert dados["chave_acesso"] == "21075062250227393000149000000000000523108745783896"
    for forbidden in [b"ESPELHO DE NFS-e", b"Rodape tecnico", b"Hash SHA-256", b"storage_key"]:
        assert forbidden not in data


def test_pdf_service_exibe_retencoes_federais_do_xml(tmp_path: Path):
    xml_path = tmp_path / "nota-retencoes.xml"
    output_path = tmp_path / "nota-retencoes.pdf"
    xml_path.write_text(
        _xml_minimo().replace(
            "<vRetIRRF>0.00</vRetIRRF><vRetCP>0.00</vRetCP><vRetCSLL>0.00</vRetCSLL><vPis>0.00</vPis><vCofins>0.00</vCofins>",
            "<vRetIRRF>90.00</vRetIRRF><vRetCP>20.00</vRetCP><vRetCSLL>3.00</vRetCSLL><vPis>1.00</vPis><vCofins>2.00</vCofins>",
        ).replace("<vTotalRet>0.00</vTotalRet>", "<vTotalRet>116.00</vTotalRet>"),
        encoding="utf-8",
    )

    dados = extrair_dados_nfse(xml_path)
    NfsePdfService().gerar_danfse_espelho(dados, output_path)

    text = _pdf_text(output_path)
    assert dados["irrf"] == "90.00"
    assert "IRRF" in text
    assert "R$ 90,00" in text
    assert "Contribui" in text
    assert "R$ 20,00" in text
    assert "PIS - Retido" in text
    assert "R$ 1,00" in text
    assert "COFINS - Retido" in text
    assert "R$ 2,00" in text
    assert "Total Reten" in text
    assert "R$ 116,00" in text


def test_pdf_gerado_nota_18_cns_park_bate_campos_fiscais(tmp_path: Path):
    dados = extrair_dados_nfse(_require(NOTA_18_XML))
    output_path = tmp_path / "nota-18.pdf"

    NfsePdfService().gerar_danfse_espelho(dados, output_path)

    text = _pdf_text(output_path)
    assert len(PdfReader(output_path).pages) == 1
    assert "DANFSe v1.0" in text
    assert "Número da NFS-e" in text
    assert "18" in text
    assert "CNS PARK ESTACIONAMENTO LTDA" in text
    assert "TOMADOR DO SERVIÇO NÃO IDENTIFICADO NA NFS-e" in text
    assert "Valor do Serviço" in text
    assert "R$ 14.016,00" in text
    assert "Desconto Incondicionado" in text
    assert "R$ 74,00" in text
    assert "BC ISSQN" in text
    assert "R$ 13.942,00" in text
    assert "Alíquota Aplicada" in text
    assert "2,50" in text
    assert "ISSQN Apurado" in text
    assert "R$ 348,55" in text
    assert "Valor Líquido da NFS-e" in text
    assert "Municipais" in text
    assert "2,50 %" in text
    assert "TOMADOR DO SERVIÇO\nCNPJ / CPF / NIF\n-" not in text


def test_pdf_gerado_nota_22_cns_park_bate_campos_fiscais_e_nbs(tmp_path: Path):
    dados = extrair_dados_nfse(_require(NOTA_22_XML))
    output_path = tmp_path / "nota-22.pdf"

    NfsePdfService().gerar_danfse_espelho(dados, output_path)

    text = _pdf_text(output_path)
    assert len(PdfReader(output_path).pages) == 1
    assert "Número da NFS-e" in text
    assert "22" in text
    assert "TOMADOR DO SERVIÇO NÃO IDENTIFICADO NA NFS-e" in text
    assert "Valor do Serviço" in text
    assert "R$ 11.229,00" in text
    assert "Desconto Incondicionado" in text
    assert "R$ 370,00" in text
    assert "BC ISSQN" in text
    assert "R$ 10.859,00" in text
    assert "ISSQN Apurado" in text
    assert "R$ 271,48" in text
    assert "NBS: 106043000" in text


def test_ingestao_gera_pdf_espelho_sem_duplicar_e_endpoints(tmp_path: Path):
    _reset_db()
    chave = "21075062250227393000149000000000000523108745783896"
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Teste", cnpj="57526860000180", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, certificado_id=None, tipo="consulta_nfse", status="pendente")
        db.add(processo)
        db.commit()
        db.refresh(processo)
        processo_id = processo.id

    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    xml_path = xml_dir / "50.227.393_JORGE_LUIS_DINIZ_SILVA NFS-e 5.xml"
    xml_path.write_text(_xml_minimo(chave), encoding="utf-8")

    with SessionLocal() as db:
        processo = db.get(Processo, processo_id)
        first = legacy_ingestion_service.ingerir_saida_legado(db, get_storage_service(), processo, tmp_path)
        db.commit()
        second = legacy_ingestion_service.ingerir_saida_legado(db, get_storage_service(), processo, tmp_path)
        db.commit()
        nota = db.query(Nota).filter(Nota.chave == chave).one()
        arquivos = db.query(Arquivo).filter(Arquivo.nota_id == nota.id).all()

    assert first["notas_criadas"] == 1
    assert second["notas_criadas"] == 0
    assert {arquivo.tipo for arquivo in arquivos} == {"XML", "PDF_ESPELHO"}
    assert len([arquivo for arquivo in arquivos if arquivo.tipo == "PDF_ESPELHO"]) == 1
    pdf = next(arquivo for arquivo in arquivos if arquivo.tipo == "PDF_ESPELHO")
    assert pdf.filename == "50.227.393_JORGE_LUIS_DINIZ_SILVA NFS-e 5.pdf"
    assert pdf.tamanho_bytes and pdf.tamanho_bytes > 1000

    with TestClient(app) as client:
        response = client.get(f"/notas/{nota.id}/arquivos")
        assert response.status_code == 200
        payload = response.json()
        assert {item["tipo"] for item in payload} == {"XML", "PDF_ESPELHO"}
        assert any(item["filename"] == "50.227.393_JORGE_LUIS_DINIZ_SILVA NFS-e 5.pdf" for item in payload)
        download = client.get(f"/arquivos/{pdf.id}/download")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/pdf"
        assert "50.227.393_JORGE_LUIS_DINIZ_SILVA NFS-e 5.pdf" in download.headers["content-disposition"]
        assert download.content.startswith(b"%PDF")
