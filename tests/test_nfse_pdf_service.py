from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import text

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
