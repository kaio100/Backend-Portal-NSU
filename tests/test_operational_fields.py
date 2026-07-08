from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "sqlite:///./data/test_consultas_api.db"
os.environ["API_WORKER_ENABLED"] = "false"
os.environ["WORKER_DRY_RUN"] = "true"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.db.models import Arquivo, Empresa, Evento, Job, LogProcesso, Nota, NsuControle, Processo  # noqa: E402
from backend.app.db.session import SessionLocal, init_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.repositories import notas_repo  # noqa: E402
from backend.app.services import legacy_ingestion_service  # noqa: E402
from backend.app.services.operational_fields_service import (  # noqa: E402
    calcular_prioridade_fila,
    calcular_sla_operacional,
    calcular_status_fila,
    calcular_status_simples_nacional,
    calcular_status_simples_nacional_xml,
    simples_xml_from_codes,
)


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
        db.query(Empresa).delete()
        db.commit()


def _empresa() -> int:
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Operacional", cnpj="11222333000181", ambiente="producao", ativo=True)
        db.add(empresa)
        db.commit()
        db.refresh(empresa)
        return int(empresa.id)


def test_simples_xml_mapeia_codigos():
    assert simples_xml_from_codes("1") == "Não optante"
    assert simples_xml_from_codes("2") == "MEI"
    assert simples_xml_from_codes("3") == "Optante S.N"
    assert simples_xml_from_codes(None, "1") == "Simples Nacional"
    assert simples_xml_from_codes(None, "2") == "Não optante"


def test_status_simples_nacional():
    assert calcular_status_simples_nacional_xml("MEI") == "Informado no XML"
    assert calcular_status_simples_nacional_xml("Optante S.N") == "Informado no XML"
    assert calcular_status_simples_nacional_xml("Simples Nacional") == "Informado no XML"
    assert calcular_status_simples_nacional_xml("Não optante") == "Informado no XML"
    assert calcular_status_simples_nacional_xml(None) == "Não informado no XML"
    assert calcular_status_simples_nacional_xml("valor estranho") == "Indefinido no XML"
    assert calcular_status_simples_nacional("MEI", "Não optante") == "Informado no XML"


def test_xml_extrai_incidencia_e_simples(tmp_path: Path):
    xml = tmp_path / "nota.xml"
    xml.write_text(
        """
<NFSe>
  <infNFSe Id="NFS21000000000000000000000000000000000000000001">
    <prest><regTrib><opSimpNac>3</opSimpNac></regTrib></prest>
    <xLocIncid>Goiânia - GO</xLocIncid>
    <xLocPrestacao>Aparecida de Goiânia - GO</xLocPrestacao>
    <municipio>Anápolis - GO</municipio>
  </infNFSe>
</NFSe>
""",
        encoding="utf-8",
    )
    resumo = legacy_ingestion_service._parse_xml_resumo(xml)
    assert resumo["simples_xml"] == "Optante S.N"
    assert resumo["incidencia_iss"] == "Goiânia - GO"

    xml.write_text("<NFSe><prest><regTrib><opSimpNac>2</opSimpNac></regTrib></prest><xLocPrestacao>Rio Verde - GO</xLocPrestacao><municipio>Jataí - GO</municipio></NFSe>", encoding="utf-8")
    resumo = legacy_ingestion_service._parse_xml_resumo(xml)
    assert resumo["simples_xml"] == "MEI"
    assert resumo["incidencia_iss"] == "Rio Verde - GO"

    xml.write_text("<NFSe><prest><regTrib><opSimpNac>1</opSimpNac></regTrib></prest><municipio>Caldas Novas - GO</municipio></NFSe>", encoding="utf-8")
    resumo = legacy_ingestion_service._parse_xml_resumo(xml)
    assert resumo["simples_xml"] == "Não optante"
    assert resumo["incidencia_iss"] == "Caldas Novas - GO"

    xml.write_text("<NFSe><cLocIncid>5208707</cLocIncid><xLocPrestacao>Prestacao Ignorada</xLocPrestacao></NFSe>", encoding="utf-8")
    resumo = legacy_ingestion_service._parse_xml_resumo(xml)
    assert resumo["simples_xml"] == ""
    assert resumo["status_simples_nacional"] == "Não informado no XML"
    assert resumo["incidencia_iss"] == "5208707"

    xml.write_text("<NFSe><cLocPrestacao>5201405</cLocPrestacao><municipio>Municipio Ignorado</municipio></NFSe>", encoding="utf-8")
    resumo = legacy_ingestion_service._parse_xml_resumo(xml)
    assert resumo["incidencia_iss"] == "5201405"


def test_xml_nacional_alimenta_campos_do_relatorio(tmp_path: Path):
    xml = tmp_path / "nota_nacional.xml"
    xml.write_text(
        """
<NFSe>
  <infNFSe Id="NFS53001081237381902000125000000013552226031774884009">
    <xLocPrestacao>Brasilia - DF</xLocPrestacao>
    <xLocIncid>Goiania - GO</xLocIncid>
    <xTribNac>Servicos administrativos</xTribNac>
    <DPS>
      <infDPS>
        <prest><regTrib><opSimpNac>2</opSimpNac></regTrib></prest>
        <serv><cServ><cTribNac>170601</cTribNac><xDescServ>Descricao informada no XML</xDescServ></cServ></serv>
        <valores><trib><tribFed><vRetIRRF>10.00</vRetIRRF><vRetCP>20.00</vRetCP><vRetCSLL>3.00</vRetCSLL><piscofins><vPis>1.00</vPis><vCofins>2.00</vCofins></piscofins></tribFed></trib></valores>
      </infDPS>
    </DPS>
    <valores><vBC>1000.00</vBC><vISSQN>50.00</vISSQN><pAliqAplic>5.00</pAliqAplic><vLiq>915.00</vLiq></valores>
  </infNFSe>
</NFSe>
""",
        encoding="utf-8",
    )

    resumo = legacy_ingestion_service._parse_xml_resumo(xml)

    assert resumo["municipio"] == "Brasilia - DF"
    assert resumo["incidencia_iss"] == "Goiania - GO"
    assert resumo["codigo_servico"] == "170601"
    assert resumo["descricao_servico_nacional"] == "Servicos administrativos"
    assert resumo["descricao_servico_detalhada"] == "Descricao informada no XML"
    assert resumo["valor_base"] == "1000.00"
    assert resumo["iss"] == "50.00"
    assert resumo["aliquota_iss"] == "5.00"
    assert resumo["csrf"] == "6.00"
    assert resumo["irrf"] == "10.00"
    assert resumo["inss"] == "20.00"
    assert resumo["valor_liquido_correto"] == "964.00"
    assert resumo["valor_liquido_calculado"] == "964.00"
    assert resumo["status_valor_liquido"] == "Divergente"


def test_status_fila_prioridade_e_sla():
    nota = Nota(empresa_id=1, chave="A", status_irrf="divergente")
    assert calcular_status_fila(nota) == "divergente"

    nota_ok = Nota(empresa_id=1, chave="B", status_irrf="ok", status_csrf="correto", status_inss="sem divergência")
    assert calcular_status_fila(nota_ok) == "correta"

    nota_manual = Nota(empresa_id=1, chave="C", prioridade_manual="high")
    assert calcular_prioridade_fila(nota_manual, "correta") == "alta"

    nota_missing = Nota(empresa_id=1, chave="D")
    setattr(nota_missing, "campos_ausentes_xml", ["numero"])
    assert calcular_prioridade_fila(nota_missing, "divergente") == "alta"

    nota_alerta = Nota(empresa_id=1, chave="E", alertas_fiscais="esperado IRRF")
    assert calcular_prioridade_fila(nota_alerta, "divergente") == "media"
    assert calcular_prioridade_fila(Nota(empresa_id=1, chave="F"), "correta") == "baixa"

    now = datetime.now(timezone.utc)
    assert calcular_sla_operacional(now - timedelta(hours=25), "alta")["tone"] == "warn"
    assert calcular_sla_operacional(now - timedelta(hours=49), "alta")["tone"] == "danger"


def test_patch_responsavel_e_get_notas_campos_operacionais():
    _reset_db()
    empresa_id = _empresa()
    old = datetime.now(timezone.utc) - timedelta(hours=26)
    with SessionLocal() as db:
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE-OPERACIONAL",
                "numero_nfse": "10",
                "prestador_cnpj": "00111222000133",
                "tomador_cnpj": "11222333000181",
                "valor_servico": 100,
                "simples_xml": "MEI",
                "simples_nacional_xml": "MEI",
                "consulta_simples_api": "Não optante",
                "status_irrf": "divergente",
                "created_at": old,
                "updated_at": old,
                "entrada": old,
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        patch = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Kaio"},
            json={"conferencia_status": "corrigir", "observacao": "divergencia fiscal"},
        )
        assert patch.status_code == 200
        assert patch.json()["responsavel"] == "Kaio"

        response = client.get("/notas", params={"busca": "CHAVE-OPERACIONAL"})
        assert response.status_code == 200
        item = response.json()[0]
        assert item["simples_xml"] == "MEI"
        assert item["simples_nacional"] == "MEI"
        assert item["consulta_simples_api"] is None
        assert item["status_simples_nacional"] == "Informado no XML"
        assert item["status_fila_final"] == "divergente"
        assert item["divergencia_fila_final"] is True
        assert item["divergencia_fila_label"] == "Com divergência"
        assert item["prioridade_fila"] == "media"
        assert item["entrada_fila"] is not None
        assert item["sla"]["tone"] == "ok"
