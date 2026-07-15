from __future__ import annotations

import os
from pathlib import Path
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet


os.environ["DATABASE_URL"] = "sqlite:///./data/test_consultas_api.db"
os.environ["API_WORKER_ENABLED"] = "false"
os.environ["WORKER_DRY_RUN"] = "true"
os.environ["CORS_ORIGINS"] = "http://localhost:5173,http://127.0.0.1:5173"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")
Path("data/test_consultas_api.db").unlink(missing_ok=True)

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.db.models import Certificado, Empresa, Job, Nota, NsuControle, Processo  # noqa: E402
from backend.app.db.session import SessionLocal, engine, init_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.services import certificado_metadata_service, certificados_service, legacy_ingestion_service, legacy_processing_service, secrets_service  # noqa: E402
from backend.app.services.certificado_metadata_service import CertificadoMetadata, CertificadoMetadataError  # noqa: E402
from backend.app.services.storage_service import get_storage_service  # noqa: E402
from backend.app.worker.worker import processar_proximo_job  # noqa: E402


def assert_consultas_contract(payload: dict) -> None:
    assert set(payload) == {
        "consultando",
        "automatico_ativo",
        "mensagem",
        "worker",
        "totais",
        "processos_rodando",
        "processos_pendentes",
    }
    assert isinstance(payload["consultando"], bool)
    assert isinstance(payload["automatico_ativo"], bool)
    assert isinstance(payload["mensagem"], str)
    assert set(payload["worker"]) == {"enabled", "dry_run", "sleep"}
    assert set(payload["totais"]) == {"pendentes", "rodando", "finalizados", "erros", "cancelados"}
    assert isinstance(payload["processos_rodando"], list)
    assert isinstance(payload["processos_pendentes"], list)


def criar_empresa(client: TestClient, cnpj: str = "11222333000181", payload_nome: str = "razao_social") -> dict:
    payload = {"cnpj": cnpj, "ativo": True}
    if payload_nome == "nome":
        payload["nome"] = "Empresa Nome LTDA"
    else:
        payload["razao_social"] = "Empresa Integracao LTDA"
        payload["nome_fantasia"] = "Integracao"
    response = client.post("/empresas", json=payload)
    assert response.status_code == 200
    return response.json()


def criar_certificado_elegivel(empresa_id: int) -> int:
    with SessionLocal() as db:
        certificado = Certificado(
            empresa_id=empresa_id,
            nome="Certificado teste",
            storage_key="certificados/teste.pfx",
            senha_secret_ref=None,
            ativo=True,
        )
        db.add(certificado)
        db.flush()
        ref = secrets_service.build_certificado_senha_ref(certificado.id)
        secrets_service.save_secret(db, ref, "pfx_password", "senha-teste")
        certificado.senha_secret_ref = ref
        db.add(certificado)
        db.commit()
        return int(certificado.id)


def fake_metadata(cnpj: str = "22333444000155", nome: str = "Empresa Auto LTDA") -> CertificadoMetadata:
    return CertificadoMetadata(
        cnpj=cnpj,
        nome=nome,
        subject_cn=f"{nome}:{cnpj}",
        thumbprint="ABC123",
        valido_de=None,
        valido_ate=None,
    )


def fake_metadata_thumb(cnpj: str, thumbprint: str, nome: str = "Empresa Auto LTDA") -> CertificadoMetadata:
    metadata = fake_metadata(cnpj=cnpj, nome=nome)
    metadata.thumbprint = thumbprint
    return metadata


def test_metadata_prefere_nome_empresarial_do_cn_quando_organizacao_e_icp_brasil():
    nome = certificado_metadata_service._extract_business_name(
        "CANOPUS CONSTRUCOES BELEM LTDA:57526860000180",
        "ICP-Brasil",
    )
    assert nome == "CANOPUS CONSTRUCOES BELEM LTDA"


def test_config_legada_usa_dados_salvos_sem_depender_do_env(tmp_path):
    class FakeLegacy:
        class Config:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

            def validar(self):
                assert self.cnpj == "57526860000180"
                assert self.pfx_password == "senha-salva"

    pfx_path = tmp_path / "certificado.pfx"
    pfx_path.write_bytes(b"fake")

    cfg = legacy_processing_service._build_legacy_config(
        FakeLegacy,
        {
            "cnpj": "57.526.860/0001-80",
            "pfx_path": str(pfx_path),
            "pfx_password": "senha-salva",
            "ambiente": "producao",
            "verify_ssl": True,
        },
    )

    assert cfg.cnpj == "57526860000180"
    assert cfg.pfx_path == str(pfx_path)


def post_autocadastro(client: TestClient, **data):
    payload = {
        "senha": "senha-ok",
        "ambiente": "producao",
        "auto_iniciar": "true",
    }
    payload.update({key: str(value).lower() if isinstance(value, bool) else value for key, value in data.items()})
    return client.post(
        "/certificados/autocadastrar",
        data=payload,
        files={"arquivo": ("certificado.pfx", b"fake-pfx", "application/x-pkcs12")},
    )


def test_health_endpoints_and_consultas_contract():
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/db/health").status_code == 200
        assert client.get("/storage/health").status_code == 200
        assert "monitoramento_config" in inspect(engine).get_table_names()

        empresa = criar_empresa(client)
        assert empresa["nome"] == "Empresa Integracao LTDA"
        assert empresa["razao_social"] == "Empresa Integracao LTDA"
        assert client.get("/empresas").status_code == 200

        patch_response = client.patch(
            f"/empresas/{empresa['id']}",
            json={"razao_social": "Empresa Integracao Atualizada LTDA", "ativo": True},
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["nome"] == "Empresa Integracao Atualizada LTDA"

        status_response = client.get("/consultas/status")
        assert status_response.status_code == 200
        assert_consultas_contract(status_response.json())

        iniciar_response = client.post(
            "/consultas/iniciar",
            json={
                "automatico": True,
                "intervalo_minutos": 15,
                "empresa_ids": [],
                "certificado_ids": [],
                "limite": 100,
                "forcar": False,
            },
        )
        assert iniciar_response.status_code in (200, 201)
        assert_consultas_contract(iniciar_response.json())

        desativar_response = client.post(
            "/consultas/desativar",
            json={"cancelar_pendentes": True, "cancelar_rodando": False},
        )
        assert desativar_response.status_code == 200
        assert_consultas_contract(desativar_response.json())


def test_empresas_aceitam_nome_e_razao_social_sem_422():
    with TestClient(app) as client:
        por_nome = criar_empresa(client, cnpj="11222333000182", payload_nome="nome")
        assert por_nome["nome"] == "Empresa Nome LTDA"
        assert por_nome["razao_social"] == "Empresa Nome LTDA"

        por_razao = criar_empresa(client, cnpj="11222333000183", payload_nome="razao_social")
        assert por_razao["nome"] == "Empresa Integracao LTDA"
        assert por_razao["razao_social"] == "Empresa Integracao LTDA"


def test_consultas_nao_duplicam_sem_forcar_e_permitem_com_forcar():
    with TestClient(app) as client:
        empresa = criar_empresa(client, cnpj="11222333000184", payload_nome="nome")
        certificado_id = criar_certificado_elegivel(int(empresa["id"]))
        payload = {
            "automatico": True,
            "intervalo_minutos": 15,
            "empresa_ids": [empresa["id"]],
            "certificado_ids": [certificado_id],
            "limite": 100,
            "forcar": False,
        }

        first = client.post("/consultas/iniciar", json=payload)
        assert first.status_code == 200
        assert first.json()["totais"]["pendentes"] == 1

        second = client.post("/consultas/iniciar", json=payload)
        assert second.status_code == 200
        assert second.json()["totais"]["pendentes"] == 1

        with SessionLocal() as db:
            processo = db.query(Processo).filter(Processo.certificado_id == certificado_id).first()
            assert processo is not None
            processo.status = "rodando"
            job = db.query(Job).filter(Job.certificado_id == certificado_id).first()
            assert job is not None
            job.status = "rodando"
            db.commit()

        third = client.post("/consultas/iniciar", json=payload)
        assert third.status_code == 200
        assert third.json()["totais"]["rodando"] == 1
        assert third.json()["totais"]["pendentes"] == 0

        forced = client.post("/consultas/iniciar", json={**payload, "forcar": True})
        assert forced.status_code == 200
        assert forced.json()["totais"]["rodando"] == 1
        assert forced.json()["totais"]["pendentes"] == 1


def test_desativar_consultas_cancela_pendentes_e_rodando_mesmo_com_payload_false():
    with TestClient(app) as client:
        empresa = criar_empresa(client, cnpj="11222333000194", payload_nome="nome")
        certificado_id = criar_certificado_elegivel(int(empresa["id"]))
        payload = {
            "automatico": True,
            "intervalo_minutos": 15,
            "empresa_ids": [empresa["id"]],
            "certificado_ids": [certificado_id],
            "limite": 100,
            "forcar": True,
        }

        first = client.post("/consultas/iniciar", json=payload)
        assert first.status_code == 200
        second = client.post("/consultas/iniciar", json=payload)
        assert second.status_code == 200

        with SessionLocal() as db:
            processos = (
                db.query(Processo)
                .filter(Processo.certificado_id == certificado_id)
                .order_by(Processo.id.asc())
                .all()
            )
            assert len(processos) == 2
            processo_rodando, processo_pendente = processos
            processo_rodando.status = "rodando"
            processo_pendente.status = "pendente"
            job_rodando = db.query(Job).filter(Job.processo_id == processo_rodando.id).one()
            job_pendente = db.query(Job).filter(Job.processo_id == processo_pendente.id).one()
            job_rodando.status = "rodando"
            job_pendente.status = "pendente"
            db.commit()

        response = client.post(
            "/consultas/desativar",
            json={"cancelar_pendentes": False, "cancelar_rodando": False},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["automatico_ativo"] is False
        assert payload["totais"]["rodando"] == 0
        assert payload["totais"]["pendentes"] == 0

        with SessionLocal() as db:
            statuses = {
                processo.status
                for processo in db.query(Processo).filter(Processo.certificado_id == certificado_id).all()
            }
            job_statuses = {
                job.status
                for job in db.query(Job).filter(Job.certificado_id == certificado_id).all()
            }
        assert statuses == {"cancelado"}
        assert job_statuses == {"cancelado"}


def test_worker_standalone_e_cors_localhost_5173():
    assert settings.api_worker_enabled is False
    with TestClient(app) as client:
        cors = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert cors.status_code == 200
        assert cors.headers["access-control-allow-origin"] == "http://localhost:5173"

    result = processar_proximo_job("test-worker-sem-job")
    assert "ok" in result


def test_ingestao_sem_index_cria_nota_arquivos_e_endpoints(tmp_path):
    chave = "12345678901234567890123456789012345678901234"
    with TestClient(app) as client:
        empresa = criar_empresa(client, cnpj="11222333000185", payload_nome="nome")
        certificado_id = criar_certificado_elegivel(int(empresa["id"]))
        iniciar = client.post(
            "/consultas/iniciar",
            json={
                "automatico": True,
                "intervalo_minutos": 15,
                "empresa_ids": [empresa["id"]],
                "certificado_ids": [certificado_id],
                "limite": 100,
                "forcar": True,
            },
        )
        assert iniciar.status_code == 200

        with SessionLocal() as db:
            processo = (
                db.query(Processo)
                .filter(Processo.empresa_id == empresa["id"])
                .filter(Processo.certificado_id == certificado_id)
                .order_by(Processo.id.desc())
                .first()
            )
            assert processo is not None

            xml_dir = tmp_path / "xml"
            pdf_dir = tmp_path / "danfse"
            xml_dir.mkdir()
            pdf_dir.mkdir()
            xml_path = xml_dir / f"{chave}.xml"
            pdf_path = pdf_dir / f"{chave}.pdf"
            xml_path.write_text(
                f"""<?xml version="1.0" encoding="utf-8"?>
<NFSe>
  <ChaveAcesso>{chave}</ChaveAcesso>
  <NumeroNfse>42</NumeroNfse>
  <DataEmissao>2026-06-27</DataEmissao>
  <Competencia>2026-06-01</Competencia>
  <ValorServicos>123.45</ValorServicos>
</NFSe>
""",
                encoding="utf-8",
            )
            pdf_path.write_bytes(b"%PDF-1.4\n%teste\n")

            result = legacy_ingestion_service.ingerir_saida_legado(
                db,
                get_storage_service(),
                processo,
                tmp_path,
            )
            db.commit()

        assert result["index_encontrado"] is False
        assert result["fallback_varredura"] is True
        assert result["notas_criadas"] == 1
        assert result["arquivos_registrados"] == 2

        notas = client.get("/notas", params={"chave": chave})
        assert notas.status_code == 200
        assert len(notas.json()) == 1
        assert notas.json()[0]["importado_em"] is not None
        nota_id = notas.json()[0]["id"]

        detalhe = client.get(f"/notas/{nota_id}")
        assert detalhe.status_code == 200
        assert detalhe.json()["chave"] == chave

        arquivos = client.get(f"/notas/{nota_id}/arquivos")
        assert arquivos.status_code == 200
        assert {item["tipo"] for item in arquivos.json()} == {"XML", "PDF_ORIGINAL"}
        assert all(item["filename"] for item in arquivos.json())
        assert all(item["size_bytes"] for item in arquivos.json())

        download = client.get(f"/arquivos/{arquivos.json()[0]['id']}/download")
        assert download.status_code == 200
        assert download.content
        assert download.headers["content-type"] in {"application/xml", "application/pdf"}


def test_ingestao_com_index_csv_usa_valor_liquido_realmente_calculado(tmp_path):
    # Antes desta correcao, quando a ingestao vinha pelo index_nfse.csv (o
    # fluxo mais comum), "valor_liquido_correto"/"status_valor_liquido" eram
    # calculados comparando a planilha contra o proprio XML (dois valores
    # informados, quase sempre iguais), nunca contra o valor liquido
    # REALMENTE esperado apos as retencoes (que so entrava no texto do
    # alerta fiscal). Isso fazia o "comparativo de tributos" mostrar "OK"
    # numa nota que o proprio alertas_fiscais dizia estar divergente.
    chave = "98765432109876543210987654321098765432109876"
    xml_dir = tmp_path / "xml"
    pdf_dir = tmp_path / "pdf"
    xml_dir.mkdir()
    pdf_dir.mkdir()
    xml_path = xml_dir / f"{chave}.xml"
    pdf_path = pdf_dir / f"{chave}.pdf"
    # subitem 1.02: irrf=SIM (1.5%), pcc=NAO, inss=NAO.
    # valor_servico=5700.00 -> irrf esperado = 85.50 (bate com o informado).
    # CSRF foi retido no XML (208.05) mas a regra diz que nao deveria
    # (pcc=NAO) -> "Divergente - retido indevido" e o liquido esperado tem
    # que descontar os 208.05 que de fato saem do valor (5700 - 85.50 -
    # 208.05 = 5406.45), mesmo que o vLiq informado no XML (5614.50) nao
    # reflita isso.
    xml_path.write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<NFSe>
  <infNFSe Id="NFS53001081237381902000125000000000098765432">
    <DPS>
      <infDPS>
        <serv><cServ><cTribNac>010200</cTribNac></cServ></serv>
        <valores>
          <trib>
            <tribFed><vRetIRRF>85.50</vRetIRRF><vRetCSLL>208.05</vRetCSLL></tribFed>
            <tribMun><tpRetISSQN>1</tpRetISSQN></tribMun>
          </trib>
        </valores>
      </infDPS>
    </DPS>
    <valores>
      <vServPrest><vServ>5700.00</vServ></vServPrest>
      <vBC>5700.00</vBC>
      <vISSQN>114.00</vISSQN>
      <pAliqAplic>2.00</pAliqAplic>
      <vLiq>5614.50</vLiq>
    </valores>
  </infNFSe>
</NFSe>
""",
        encoding="utf-8",
    )
    pdf_path.write_bytes(b"%PDF-1.4\n%teste\n")

    index_path = tmp_path / "index_nfse.csv"
    index_path.write_text(
        "chave;xml_path;pdf_path;valor_liquido;prestador_cnpj;prestador_nome;tomador_cnpj;tomador_nome\n"
        f"{chave};{xml_path};{pdf_path};;11222333000199;Prestador Indice;22333444000155;Tomador Indice\n",
        encoding="utf-8",
    )

    init_db()
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Indice LTDA", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, certificado_id=None, tipo="consulta_nfse", status="finalizado")
        db.add(processo)
        db.flush()

        result = legacy_ingestion_service.ingerir_saida_legado(
            db,
            get_storage_service(),
            processo,
            tmp_path,
        )
        db.commit()

        assert result["index_encontrado"] is True
        assert result["notas_criadas"] == 1

        nota = db.query(Nota).filter(Nota.chave == chave).first()
        assert nota is not None
        assert nota.status_csrf == "Divergente - retido indevido"
        assert "Valor liquido esperado R$ 5406.45, informado R$ 5614.50." in (nota.alertas_fiscais or "")

        # O bug: valor_liquido_correto ficava igual ao informado (5614.50),
        # mascarando a divergencia que o proprio alerta ja apontava.
        assert float(nota.valor_liquido_correto) == 5406.45
        assert nota.status_valor_liquido == "Divergente"


def test_notas_recentes_primeiro_por_updated_at_nao_data_emissao():
    now = datetime.now(timezone.utc)
    with TestClient(app) as client:
        empresa = criar_empresa(client, cnpj="11222333000186", payload_nome="nome")
        with SessionLocal() as db:
            antiga_importacao = Nota(
                empresa_id=empresa["id"],
                processo_id=None,
                chave="NOTA-ANTIGA-IMPORTACAO",
                numero_nfse="1",
                data_emissao=(now + timedelta(days=2)).date(),
                competencia=(now + timedelta(days=2)).date(),
                created_at=now - timedelta(days=5),
                updated_at=now - timedelta(days=5),
            )
            nova_importacao = Nota(
                empresa_id=empresa["id"],
                processo_id=None,
                chave="NOTA-NOVA-IMPORTACAO",
                numero_nfse="2",
                data_emissao=(now - timedelta(days=30)).date(),
                competencia=(now - timedelta(days=30)).date(),
                created_at=now,
                updated_at=now,
            )
            db.add_all([antiga_importacao, nova_importacao])
            db.commit()

        recentes = client.get("/notas", params={"empresa_id": empresa["id"], "sort": "recentes"})
        assert recentes.status_code == 200
        payload = recentes.json()
        assert payload[0]["chave"] == "NOTA-NOVA-IMPORTACAO"
        assert payload[0]["importado_em"] is not None

        emissao = client.get("/notas", params={"empresa_id": empresa["id"], "sort": "emissao"})
        assert emissao.status_code == 200
        assert emissao.json()[0]["chave"] == "NOTA-ANTIGA-IMPORTACAO"


def test_autocadastro_cria_empresa_certificado_e_job(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: fake_metadata(cnpj="22333444000156"),
    )
    with TestClient(app) as client:
        response = post_autocadastro(client, auto_iniciar=True, ambiente="homologacao")
        assert response.status_code == 200
        payload = response.json()
        assert payload["empresa"]["cnpj"] == "22333444000156"
        assert payload["empresa"]["ambiente"] == "homologacao"
        assert payload["certificado"]["empresa_id"] == payload["empresa"]["id"]
        assert payload["processo"] is not None
        assert payload["processo"]["certificado_id"] == payload["certificado"]["id"]
        assert payload["consulta_status"]["totais"]["pendentes"] >= 1


def test_autocadastro_reutiliza_empresa_existente(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: fake_metadata(cnpj="22333444000157", nome="Empresa Reuso LTDA"),
    )
    with TestClient(app) as client:
        empresa = criar_empresa(client, cnpj="22333444000157", payload_nome="nome")
        response = post_autocadastro(client, auto_iniciar=False)
        assert response.status_code == 200
        payload = response.json()
        assert payload["empresa"]["id"] == empresa["id"]
        assert payload["processo"] is None


def test_autocadastro_empresa_existente_usa_nsu_recomendado(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: fake_metadata(cnpj="22333444000161", nome="Empresa NSU LTDA"),
    )
    with TestClient(app) as client:
        empresa = criar_empresa(client, cnpj="22333444000161", payload_nome="nome")
        response = post_autocadastro(client, auto_iniciar=True, nsu_recomendado=345, forcar=True)
        assert response.status_code == 200
        payload = response.json()
        assert payload["empresa"]["id"] == empresa["id"]
        assert payload["processo"]["nsu_inicio"] == 345

        with SessionLocal() as db:
            job = (
                db.query(Job)
                .filter(Job.certificado_id == payload["certificado"]["id"])
                .order_by(Job.id.desc())
                .first()
            )
            assert job is not None
            assert job.payload_json["nsu_inicio"] == 345


def test_execucao_real_aplica_nsu_inicio_usuario_no_motor_e_estado(monkeypatch):
    init_db()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        def validar(self):
            return None

    class FakeLegacy:
        Config = FakeConfig
        INDEX_FIELDS = []

        def __init__(self):
            self.estados = []
            self.chamadas = []

        def salvar_estado(self, cnpj, ultimo_nsu):
            self.estados.append((cnpj, int(ultimo_nsu)))

        def executar_baixa_empresa(self, **kwargs):
            self.chamadas.append(kwargs)
            return {
                "empresa": kwargs["config"].cnpj,
                "cnpj": kwargs["config"].cnpj,
                "pasta_saida": None,
                "status": "finalizado",
                "ultimo_nsu": kwargs["inicio"],
            }

    fake_legacy = FakeLegacy()
    monkeypatch.setattr(legacy_processing_service, "_load_legacy_module", lambda processo_id: fake_legacy)
    monkeypatch.setattr(
        legacy_processing_service.cnpj_enrichment_service,
        "enriquecer_cnpjs_do_processo",
        lambda db, processo_id, certificado_id=None: {"cnpjs_total": 0},
    )

    storage = get_storage_service()
    storage_key = "certificados/teste-nsu-inicial.pfx"
    storage.put_bytes(storage_key, b"pfx-bytes", content_type="application/x-pkcs12")

    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa NSU Execucao LTDA", cnpj="22333444000163", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        certificado = Certificado(
            empresa_id=empresa.id,
            nome="Certificado NSU Execucao",
            storage_key=storage_key,
            ativo=True,
        )
        db.add(certificado)
        db.flush()
        ref = secrets_service.build_certificado_senha_ref(certificado.id)
        secrets_service.save_secret(db, ref, "pfx_password", "senha-teste")
        certificado.senha_secret_ref = ref
        processo = Processo(
            empresa_id=empresa.id,
            certificado_id=certificado.id,
            tipo="consulta_nfse",
            status="rodando",
            nsu_inicio=1000,
            limite=1,
            pausa=0,
            gerar_pdf_espelho=True,
            baixar_pdf_oficial=False,
        )
        db.add(processo)
        db.flush()
        job = Job(
            processo_id=processo.id,
            empresa_id=empresa.id,
            certificado_id=certificado.id,
            tipo="consulta_nfse",
            status="rodando",
            payload_json={
                "empresa_id": empresa.id,
                "certificado_id": certificado.id,
                "nsu_inicio": 1000,
                "limite": 1,
                "pausa": 0,
                "gerar_pdf_espelho": True,
                "baixar_pdf_oficial": False,
            },
        )
        db.add(job)
        db.commit()

        result = legacy_processing_service.executar_consulta_nfse_legado(db, storage, processo, job, "worker-nsu")
        controle = (
            db.query(NsuControle)
            .filter(NsuControle.empresa_id == empresa.id, NsuControle.certificado_id == certificado.id)
            .first()
        )

    assert result["ok"] is True
    assert fake_legacy.chamadas[0]["inicio"] == 1000
    assert fake_legacy.estados[0] == ("22333444000163", 1000)
    assert controle is not None
    assert controle.ultimo_nsu == 1000


def test_autocadastro_empresa_nova_respeita_nsu_recomendado(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: fake_metadata(cnpj="22333444000162", nome="Empresa Nova NSU LTDA"),
    )
    with TestClient(app) as client:
        response = post_autocadastro(client, auto_iniciar=True, nsu_recomendado=987, forcar=True)
        assert response.status_code == 200
        payload = response.json()
        assert payload["empresa"]["cnpj"] == "22333444000162"
        assert payload["processo"]["nsu_inicio"] == 987

        with SessionLocal() as db:
            job = (
                db.query(Job)
                .filter(Job.certificado_id == payload["certificado"]["id"])
                .order_by(Job.id.desc())
                .first()
            )
            assert job is not None
            assert job.payload_json["nsu_inicio"] == 987


def test_autocadastro_auto_iniciar_false_nao_cria_job(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: fake_metadata(cnpj="22333444000158"),
    )
    with TestClient(app) as client:
        response = post_autocadastro(client, auto_iniciar=False)
        assert response.status_code == 200
        payload = response.json()
        assert payload["processo"] is None
        with SessionLocal() as db:
            jobs = db.query(Job).filter(Job.certificado_id == payload["certificado"]["id"]).count()
            assert jobs == 0


def test_autocadastro_senha_invalida_e_sem_cnpj_retorna_erro_amigavel(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: (_ for _ in ()).throw(CertificadoMetadataError("Senha invalida ou certificado invalido.")),
    )
    with TestClient(app) as client:
        invalid = post_autocadastro(client)
        assert invalid.status_code == 400
        assert "Senha invalida" in invalid.json()["detail"]

    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: fake_metadata(cnpj=None),
    )
    with TestClient(app) as client:
        no_cnpj = post_autocadastro(client)
        assert no_cnpj.status_code == 400
        assert "identificar o CNPJ" in no_cnpj.json()["detail"]


def test_autocadastro_mesmo_thumbprint_atualiza_certificado_sem_duplicar(monkeypatch):
    monkeypatch.setattr(
        certificado_metadata_service,
        "extrair_metadata_pfx",
        lambda pfx_bytes, senha: fake_metadata_thumb(cnpj="22333444000160", thumbprint="DUP123"),
    )
    with TestClient(app) as client:
        first = post_autocadastro(client, auto_iniciar=False)
        assert first.status_code == 200
        first_cert_id = first.json()["certificado"]["id"]

        second = post_autocadastro(client, auto_iniciar=False)
        assert second.status_code == 200
        assert second.json()["certificado"]["id"] == first_cert_id

        with SessionLocal() as db:
            certificados = (
                db.query(Certificado)
                .filter(Certificado.empresa_id == first.json()["empresa"]["id"])
                .filter(Certificado.thumbprint == "DUP123")
                .filter(Certificado.ativo.is_(True))
                .all()
            )
            assert len(certificados) == 1


def test_endpoint_antigo_certificado_empresa_continua_funcionando(monkeypatch):
    monkeypatch.setattr(
        certificados_service,
        "testar_certificado_pfx_bytes",
        lambda pfx_bytes, senha: {
            "ok": True,
            "thumbprint": "OLD123",
            "subject_cn": "Certificado antigo",
            "valido_de": None,
            "valido_ate": None,
        },
    )
    with TestClient(app) as client:
        empresa = criar_empresa(client, cnpj="22333444000159", payload_nome="nome")
        response = client.post(
            f"/empresas/{empresa['id']}/certificados",
            data={"nome": "Certificado legado", "senha": "senha-ok", "ativo": "true"},
            files={"arquivo_pfx": ("legado.pfx", b"fake-pfx", "application/x-pkcs12")},
        )
        assert response.status_code == 200
        assert response.json()["empresa_id"] == empresa["id"]
