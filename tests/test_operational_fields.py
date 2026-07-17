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

from backend.app.db.models import Arquivo, CnpjCache, Empresa, Evento, Job, LogProcesso, Nota, NsuControle, Processo  # noqa: E402
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
        db.query(CnpjCache).delete()
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
    assert calcular_status_simples_nacional("MEI", "Não optante") == "Divergente"
    assert calcular_status_simples_nacional("MEI", "MEI") == "Correto"
    assert calcular_status_simples_nacional("Simples Nacional", "Optante S.N") == "Correto"
    assert calcular_status_simples_nacional(None, "Não optante") == "Não informado no XML"
    assert calcular_status_simples_nacional("MEI", None) == "Pendente"
    assert calcular_status_simples_nacional("MEI", "Erro na consulta") == "Erro"


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


def test_status_nao_se_aplica_nao_e_tratado_como_divergente():
    # NFS-e 16446: IRRF/CSRF/INSS "Nao se aplica" (tributo nao incide para
    # o subitem/regra), ISS e valor liquido batendo com o informado, sem
    # alertas_fiscais. "Nao se aplica" e um status neutro (nao ha o que
    # reter), nao uma divergencia — mas o allowlist de status "ok" nao
    # reconhecia essa string e tratava como divergente por padrao.
    nota = Nota(
        empresa_id=1,
        chave="NFSE-16446",
        alertas_fiscais=None,
        status_irrf="Nao se aplica",
        status_csrf="Nao se aplica",
        status_inss="Nao se aplica",
        status_iss="ok",
        status_valor_liquido="OK",
    )
    assert calcular_status_fila(nota) == "correta"

    # Uma divergencia real em qualquer um desses campos continua detectada.
    nota_divergente = Nota(
        empresa_id=1,
        chave="NFSE-DIVERGENTE",
        alertas_fiscais=None,
        status_irrf="Divergente",
        status_csrf="Nao se aplica",
        status_inss="Nao se aplica",
    )
    assert calcular_status_fila(nota_divergente) == "divergente"


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
        assert item["status_simples_nacional"] == "Pendente"
        assert item["status_fila_final"] == "divergente"
        assert item["divergencia_fila_final"] is True
        assert item["divergencia_fila_label"] == "Com divergência"
        assert item["prioridade_fila"] == "media"
        assert item["entrada_fila"] is not None
        assert item["sla"]["tone"] == "ok"


def test_consulta_simples_api_preenchida_a_partir_do_cache_cnpj():
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        empresa = db.get(Empresa, empresa_id)
        db.add(
            CnpjCache(
                cnpj="22222222000182",
                fonte="Invertexto",
                consulta_simples_api="Optante S.N",
                status_consulta="OK",
                data_consulta=datetime.now(timezone.utc).date(),
                data_expiracao=datetime.now(timezone.utc).date() + timedelta(days=10),
            )
        )
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE-CONSULTA-SIMPLES",
                "numero_nfse": "20",
                "prestador_cnpj": empresa.cnpj,
                "tomador_cnpj": "22222222000182",
                "valor_servico": 100,
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        detalhe = client.get(f"/notas/{nota_id}")
        assert detalhe.status_code == 200
        assert detalhe.json()["consulta_simples_api"] == "Optante S.N"
        assert detalhe.json()["status_simples_nacional"] == "Não informado no XML"

        listagem = client.get("/notas", params={"busca": "CHAVE-CONSULTA-SIMPLES"})
        assert listagem.status_code == 200
        assert listagem.json()[0]["consulta_simples_api"] == "Optante S.N"
        assert listagem.json()[0]["status_simples_nacional"] == "Não informado no XML"


def test_consulta_simples_api_sem_cache_fica_none():
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        empresa = db.get(Empresa, empresa_id)
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE-SEM-CACHE",
                "numero_nfse": "21",
                "prestador_cnpj": empresa.cnpj,
                "tomador_cnpj": "33333333000199",
                "valor_servico": 100,
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        detalhe = client.get(f"/notas/{nota_id}")
        assert detalhe.status_code == 200
        assert detalhe.json()["consulta_simples_api"] is None


def test_conferencia_ok_tira_nota_do_status_divergente():
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE-CONFERENCIA-OK",
                "numero_nfse": "30",
                "prestador_cnpj": "00111222000133",
                "tomador_cnpj": "11222333000181",
                "valor_servico": 100,
                "status_irrf": "divergente",
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        antes = client.get(f"/notas/{nota_id}")
        assert antes.status_code == 200
        assert antes.json()["status_fila_final"] == "divergente"
        assert antes.json()["divergencia_fila_final"] is True

        patch = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Luana Assis"},
            json={"conferencia_status": "ok"},
        )
        assert patch.status_code == 200
        assert patch.json()["status_fila_final"] == "correta"
        assert patch.json()["divergencia_fila_final"] is False
        assert patch.json()["divergencia_fila_label"] == "Sem divergência"

        depois = client.get(f"/notas/{nota_id}")
        assert depois.status_code == 200
        assert depois.json()["status_fila_final"] == "correta"
        assert depois.json()["divergencia_fila_final"] is False


def test_conferencia_ok_muda_status_mesmo_com_alertas_fiscais_presentes():
    """A conferencia manual e a decisao final do revisor: marcar "ok" tem
    que tirar a nota de "divergente" imediatamente, em qualquer lugar que
    mostre o status (dashboard, conferencia S/Tomados, S/Prestados) — mesmo
    que `alertas_fiscais` (somente leitura, preenchido so pelo sistema)
    ainda tenha texto de uma analise anterior."""
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE-ALERTA-PERSISTENTE",
                "numero_nfse": "32",
                "prestador_cnpj": "00111222000133",
                "tomador_cnpj": "11222333000181",
                "valor_servico": 320,
                "alertas_fiscais": "IRRF esperado R$ 10.00, informado R$ 0.00.",
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        patch = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Luana Assis"},
            json={"conferencia_status": "ok"},
        )
        assert patch.status_code == 200
        assert patch.json()["status_fila_final"] == "correta"
        assert patch.json()["divergencia_fila_final"] is False

        depois = client.get(f"/notas/{nota_id}")
        assert depois.json()["status_fila_final"] == "correta"
        assert depois.json()["divergencia_fila_final"] is False


def test_alertas_fiscais_e_observacao_interna_ignoram_payload_do_usuario():
    """`alertas_fiscais` e `observacao_interna` sao somente leitura: mesmo
    que o payload de conferencia tente definir esses campos, o valor
    existente (calculado pelo sistema) nao pode ser sobrescrito."""
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE-CAMPOS-SOMENTE-SISTEMA",
                "numero_nfse": "33",
                "prestador_cnpj": "00111222000133",
                "tomador_cnpj": "11222333000181",
                "valor_servico": 320,
                "alertas_fiscais": "IRRF esperado R$ 10.00, informado R$ 0.00.",
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        patch = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Luana Assis"},
            json={
                "conferencia_status": "ok",
                "alertas_fiscais": "Texto forjado pelo usuario",
                "observacao_interna": "Nota interna forjada pelo usuario",
            },
        )
        assert patch.status_code == 422
        detalhe_bloqueado = client.get(f"/notas/{nota_id}")
        assert detalhe_bloqueado.status_code == 200
        assert detalhe_bloqueado.json()["alertas_fiscais"] == "IRRF esperado R$ 10.00, informado R$ 0.00."
        assert detalhe_bloqueado.json()["observacao_interna"] is None
        assert detalhe_bloqueado.json()["conferencia_observacao"] is None

        apagar = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Luana Assis"},
            json={
                "conferencia_status": "ok",
                "alertas_fiscais": "",
                "observacao_interna": None,
            },
        )
        assert apagar.status_code == 422

        observacao = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Luana Assis"},
            json={
                "conferencia_status": "observacao",
                "observacao": "Comentario do revisor",
            },
        )
        assert observacao.status_code == 200
        assert observacao.json()["conferencia_observacao"] == "Comentario do revisor"
        assert observacao.json()["observacao_interna"] is None

        compat = client.put(
            f"/nfse/{nota_id}",
            json={
                "conferencia_status": "observacao",
                "observacao_interna": "Texto interno via compat",
            },
        )
        assert compat.status_code == 422
        detalhe = client.get(f"/notas/{nota_id}")
        assert detalhe.status_code == 200
        assert detalhe.json()["conferencia_observacao"] == "Comentario do revisor"
        assert detalhe.json()["observacao_interna"] is None


def test_nfse_compat_bloqueia_alertas_fiscais_e_observacao_interna():
    init_db()
    with TestClient(app) as client:
        empresa = client.post("/empresas", json={"nome": "Empresa Compat", "cnpj": "11222333000191"}).json()
        with SessionLocal() as db:
            nota = Nota(
                empresa_id=int(empresa["id"]),
                chave="CHAVE-COMPAT-READONLY",
                numero_nfse="11",
                prestador_cnpj="99888777000166",
                tomador_cnpj="11222333000191",
                valor_servico=100,
                status_documento="Autorizada",
                alertas_fiscais="Alerta gerado pelo sistema",
            )
            db.add(nota)
            db.commit()
            nota_id = nota.id

        response = client.put(
            f"/nfse/{nota_id}",
            json={
                "conferencia_status": "ok",
                "alertas_fiscais": "Texto forjado",
                "observacao_interna": "Interna forjada",
            },
        )

        assert response.status_code == 422
        detalhe = client.get(f"/notas/{nota_id}").json()
        assert detalhe["alertas_fiscais"] == "Alerta gerado pelo sistema"
        assert detalhe["observacao_interna"] is None


def test_conferencia_pendente_reabre_status_calculado_automaticamente():
    _reset_db()
    empresa_id = _empresa()
    with SessionLocal() as db:
        nota = notas_repo.create_nota(
            db,
            {
                "empresa_id": empresa_id,
                "chave": "CHAVE-CONFERENCIA-REABRE",
                "numero_nfse": "31",
                "prestador_cnpj": "00111222000133",
                "tomador_cnpj": "11222333000181",
                "valor_servico": 100,
                "status_irrf": "divergente",
                "alertas_fiscais": "IRRF esperado R$ 10.00, informado R$ 0.00.",
            },
        )
        nota_id = int(nota.id)
        db.commit()

    with TestClient(app) as client:
        client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Luana Assis"},
            json={"conferencia_status": "ok"},
        )
        reaberta = client.patch(
            f"/notas/{nota_id}/conferencia",
            headers={"X-Usuario-Nome": "Luana Assis"},
            json={"conferencia_status": "pendente"},
        )
        assert reaberta.status_code == 200
        assert reaberta.json()["status_fila_final"] == "divergente"
        assert reaberta.json()["divergencia_fila_final"] is True
