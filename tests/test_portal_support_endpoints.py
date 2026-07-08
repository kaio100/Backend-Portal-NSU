from __future__ import annotations

import os
import io
from datetime import date, datetime, timezone

from cryptography.fernet import Fernet
from openpyxl import load_workbook

os.environ["DATABASE_URL"] = "sqlite:///./data/test_consultas_api.db"
os.environ["API_WORKER_ENABLED"] = "false"
os.environ["WORKER_DRY_RUN"] = "true"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.db.models import (  # noqa: E402
    Arquivo,
    Certificado,
    Empresa,
    Evento,
    Job,
    LockProcessamento,
    LogProcesso,
    Nota,
    NsuControle,
    Processo,
)
from backend.app.db.session import SessionLocal, init_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.services.storage_service import get_storage_service  # noqa: E402


def _reset_db() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(LogProcesso).delete()
        db.query(Job).delete()
        db.query(Evento).delete()
        db.query(Arquivo).delete()
        db.query(Nota).delete()
        db.query(NsuControle).delete()
        db.query(Processo).delete()
        db.query(LockProcessamento).delete()
        db.query(Certificado).delete()
        db.query(Empresa).delete()
        db.commit()


def _base_data():
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa = Empresa(nome="Guardia Teste LTDA", cnpj="26743708000126", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(
            empresa_id=empresa.id,
            certificado_id=None,
            tipo="consulta_nfse",
            status="finalizado",
            nsu_inicio=10,
            nsu_final=20,
        )
        db.add(processo)
        db.flush()
        nota = Nota(
            empresa_id=empresa.id,
            processo_id=processo.id,
            chave="CHAVE-PORTAL-1",
            numero_nfse="123",
            data_emissao=date(2026, 6, 15),
            competencia=date(2026, 6, 1),
            prestador_cnpj="11111111000191",
            prestador_nome="Prestador Portal",
            tomador_cnpj=empresa.cnpj,
            tomador_nome=empresa.nome,
            valor_servico=1000,
            valor_liquido=900,
            valor_base=1000,
            irrf=0,
            irrf_calculado=15,
            status_irrf="divergente",
            status_documento="autorizada",
        )
        db.add(nota)
        db.flush()
        xml_key = f"test-portal/{nota.id}/nota.xml"
        pdf_key = f"test-portal/{nota.id}/nota.pdf"
        storage.put_bytes(xml_key, b"<NFSe/>", content_type="application/xml")
        storage.put_bytes(pdf_key, b"%PDF-1.4", content_type="application/pdf")
        db.add(
            Arquivo(
                empresa_id=empresa.id,
                processo_id=processo.id,
                nota_id=nota.id,
                tipo="XML",
                storage_backend=storage.backend,
                storage_bucket=settings.storage_bucket,
                storage_key=xml_key,
                filename="Prestador Portal NFS-e 123.xml",
                content_type="application/xml",
                tamanho_bytes=7,
            )
        )
        db.add(
            Arquivo(
                empresa_id=empresa.id,
                processo_id=processo.id,
                nota_id=nota.id,
                tipo="PDF_ESPELHO",
                storage_backend=storage.backend,
                storage_bucket=settings.storage_bucket,
                storage_key=pdf_key,
                filename="Prestador Portal NFS-e 123.pdf",
                content_type="application/pdf",
                tamanho_bytes=8,
            )
        )
        db.add(
            Evento(
                empresa_id=empresa.id,
                nota_id=nota.id,
                chave_evento="EVENTO-1",
                chave_afetada=nota.chave,
                tipo_evento="cancelamento",
                descricao="Cancelamento de NFS-e",
                data_evento=datetime(2026, 6, 16, tzinfo=timezone.utc),
                nsu=21,
            )
        )
        db.add(NsuControle(empresa_id=empresa.id, certificado_id=None, cnpj=empresa.cnpj, ultimo_nsu=20))
        db.commit()
        return int(empresa.id), int(processo.id), int(nota.id)


def test_detalhe_documentos_eventos_e_comparativo_da_nota():
    _reset_db()
    _, _, nota_id = _base_data()
    with TestClient(app) as client:
        detalhe = client.get(f"/notas/{nota_id}")
        assert detalhe.status_code == 200
        assert detalhe.json()["empresa_nome"] == "Guardia Teste LTDA"
        assert detalhe.json()["status_nota"] == "autorizada"

        arquivos_antigo = client.get(f"/notas/{nota_id}/arquivos")
        assert arquivos_antigo.status_code == 200
        assert isinstance(arquivos_antigo.json(), list)
        assert {item["tipo"] for item in arquivos_antigo.json()} == {"XML", "PDF_ESPELHO"}

        arquivos = client.get(f"/notas/{nota_id}/arquivos", params={"detalhado": "true"})
        assert arquivos.status_code == 200
        assert arquivos.json()["nota_id"] == nota_id
        assert {item["tipo"] for item in arquivos.json()["items"]} == {"xml", "pdf"}

        eventos = client.get(f"/notas/{nota_id}/eventos")
        assert eventos.status_code == 200
        assert eventos.json()["items"][0]["descricao"] == "Cancelamento de NFS-e"

        comparativo = client.get(f"/notas/{nota_id}/tributos-comparativo")
        assert comparativo.status_code == 200
        assert comparativo.json()["items"][0]["tributo"] == "IRRF"
        assert comparativo.json()["items"][0]["status"] == "divergente"


def test_eventos_globais_conferencia_e_busca_avancada():
    _reset_db()
    _, _, nota_id = _base_data()
    with TestClient(app) as client:
        eventos = client.get("/eventos", params={"tipo_evento": "cancelamento"})
        assert eventos.status_code == 200
        assert eventos.json()["total"] == 1

        patch = client.patch(
            f"/notas/{nota_id}/conferencia",
            json={
                "conferencia_status": "corrigir",
                "observacao": "Conferir imposto",
                "responsavel": "Kaio",
                "prioridade": "alta",
                "prioridade_manual": "alta",
                "divergencia": "ISS divergente",
                "valor_liquido_correto": 850,
                "alertas_fiscais": ["Revisar retencao"],
                "atualizado_por": "Kaio",
            },
        )
        assert patch.status_code == 200
        payload = patch.json()
        assert payload["conferencia_observacao"] == "Conferir imposto"
        assert payload["responsavel"] == "Kaio"
        assert payload["divergencia"] == "ISS divergente"
        assert payload["valor_liquido_correto"] == "850.00"
        assert payload["status_valor_liquido"] == "divergente"

        busca = client.get("/notas", params={"q": "Prestador Portal", "prioridade": "alta"})
        assert busca.status_code == 200
        assert [item["id"] for item in busca.json()] == [nota_id]


def test_endpoints_de_processo_e_resumo_empresa():
    _reset_db()
    empresa_id, processo_id, nota_id = _base_data()
    with TestClient(app) as client:
        arquivos = client.get(f"/processos/{processo_id}/arquivos", params={"tipo": "pdf"})
        assert arquivos.status_code == 200
        assert arquivos.json()["total"] == 1
        assert arquivos.json()["items"][0]["nome"].endswith(".pdf")

        notas = client.get(
            f"/processos/{processo_id}/notas",
            params={"tipo_nota": "recebida", "busca": "Prestador", "valor_min": "999", "somente_divergentes": "true"},
        )
        assert notas.status_code == 200
        assert notas.json()["total"] == 1
        assert notas.json()["items"][0]["id"] == nota_id

        summary = client.get(f"/processos/{processo_id}/summary")
        assert summary.status_code == 200
        assert summary.json()["total_notas"] == 1
        assert summary.json()["total_xml"] == 1
        assert summary.json()["total_pdf"] == 1
        assert summary.json()["nsu_final"] == 20

        resumo = client.get("/empresas/resumo-operacional")
        assert resumo.status_code == 200
        item = next(item for item in resumo.json()["items"] if item["empresa_id"] == empresa_id)
        assert item["total_notas"] == 1
        assert item["ultimo_nsu"] == 20


def test_relatorio_conferencia_csv():
    _reset_db()
    empresa_id, _, _ = _base_data()
    with TestClient(app) as client:
        response = client.post("/relatorios/conferencia", json={"filtros": {"empresa_id": empresa_id}})
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        assert ".xlsx" in response.headers["content-disposition"]
        wb = load_workbook(filename=io.BytesIO(response.content), read_only=True)
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        assert ws["A1"].value == "Competencia"
        assert ws["C2"].value == "CHAVE-PORTAL-1"
        assert "Consulta Simples API" not in headers
        assert "Simples Nacional / XML" in headers
        assert "Status Simples Nacional" in headers
        assert "Incidencia ISS" in headers


def test_relatorio_conferencia_enriquece_campos_vazios_pelo_xml():
    _reset_db()
    empresa_id, _, nota_id = _base_data()
    storage = get_storage_service()
    xml = b"""
<NFSe>
  <infNFSe Id="NFS53001081237381902000125000000000012326010112345678">
    <xLocPrestacao>Brasilia</xLocPrestacao>
    <xLocIncid>Goiania</xLocIncid>
    <xTribNac>Servicos administrativos</xTribNac>
    <DPS>
      <infDPS>
        <serv><cServ><cTribNac>170601</cTribNac><xDescServ>Descricao detalhada do XML</xDescServ></cServ></serv>
        <valores><trib><tribFed><vRetIRRF>10.00</vRetIRRF><vRetCP>20.00</vRetCP><vRetCSLL>3.00</vRetCSLL><piscofins><vPis>1.00</vPis><vCofins>2.00</vCofins></piscofins></tribFed></trib></valores>
      </infDPS>
    </DPS>
    <valores><vBC>1000.00</vBC><vISSQN>50.00</vISSQN><pAliqAplic>5.00</pAliqAplic><vLiq>900.00</vLiq></valores>
  </infNFSe>
</NFSe>
"""
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        nota.municipio = None
        nota.valor_base = None
        nota.csrf = None
        nota.irrf = None
        nota.inss = None
        nota.iss = None
        nota.aliquota_iss = None
        nota.valor_liquido_correto = None
        nota.status_valor_liquido = None
        nota.incidencia_iss = None
        nota.codigo_servico = None
        nota.descricao_servico_nacional = None
        nota.descricao_servico_detalhada = None
        arquivo = db.query(Arquivo).filter(Arquivo.nota_id == nota_id, Arquivo.tipo == "XML").first()
        storage.put_bytes(arquivo.storage_key, xml, content_type="application/xml")
        arquivo.tamanho_bytes = len(xml)
        db.commit()

    with TestClient(app) as client:
        response = client.post("/relatorios/conferencia", json={"filtros": {"empresa_id": empresa_id}})
        assert response.status_code == 200
        wb = load_workbook(filename=io.BytesIO(response.content), read_only=True, data_only=True)
        ws = wb.active
        headers = [cell.value for cell in ws[1]]
        row = {header: ws.cell(row=2, column=index + 1).value for index, header in enumerate(headers)}

        assert row["Municipio"] == "Brasilia"
        assert row["Incidencia ISS"] == "Goiania"
        assert row["Codigo de servico"] == "170601"
        assert row["Descricao servico nacional"] == "Servicos administrativos"
        assert row["Descricao detalhada do servico"] == "Descricao detalhada do XML"
        assert row["Valor B/C"] == 1000
        assert row["ISS"] == 50
        assert row["Aliquota ISS"] == 5
        assert row["CSRF"] == 6
        assert row["IRRF"] == 10
        assert row["INSS"] == 20
        assert row["Valor Liquido Correto"] == 964
        assert row["Valor Liquido Calculado"] == 964
        assert row["Status Valor Liquido"] == "Divergente"
