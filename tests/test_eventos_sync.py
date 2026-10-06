"""Sincronizacao de eventos por nota (POST /notas/{id}/sincronizar-eventos)."""

from __future__ import annotations

import base64
import gzip
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.db.models import Arquivo, Certificado, Empresa, Evento, Job, LockProcessamento, LogProcesso, Nota, NsuControle, Processo
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app
from backend.app.services import eventos_sync_service
from backend.app.services.storage_service import get_storage_service


CHAVE = "35001081237381902000125000000000098765432101"
CHAVE_EVENTO = "EV" + CHAVE[:40]

XML_NOTA = (
    '<?xml version="1.0" encoding="utf-8"?><NFSe><infNFSe Id="NFS' + CHAVE + '">'
    "<cStat>100</cStat><nNFSe>77</nNFSe><emit><CNPJ>11111111000191</CNPJ><xNome>PRESTADOR</xNome></emit>"
    "<valores><vServPrest><vServ>10.00</vServ></vServPrest><vLiq>10.00</vLiq></valores></infNFSe></NFSe>"
).encode("utf-8")

XML_EVENTO_CANCELAMENTO = (
    '<?xml version="1.0" encoding="utf-8"?><evento><infEvento Id="' + CHAVE_EVENTO + '">'
    "<chNFSe>" + CHAVE + "</chNFSe><xDesc>Cancelamento de NFS-e</xDesc><xMotivo>Erro de emissao</xMotivo>"
    "</infEvento></evento>"
).encode("utf-8")


def _b64gz(data: bytes) -> str:
    return base64.b64encode(gzip.compress(data)).decode("ascii")


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()
    with SessionLocal() as db:
        for modelo in (Arquivo, Evento, Nota, LogProcesso, Job, LockProcessamento, NsuControle, Processo, Certificado, Empresa):
            db.query(modelo).delete()
        db.commit()
    yield


def _criar_nota_autorizada():
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa = Empresa(nome="Eventos LTDA", cnpj="22333444000155", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        xml_key = f"xml/{empresa.cnpj}/2026/01/{CHAVE}.xml"
        storage.put_bytes(xml_key, XML_NOTA, content_type="application/xml")
        nota = Nota(
            empresa_id=empresa.id,
            chave=CHAVE,
            numero_nfse="77",
            status_documento="autorizada",
            status_rotulo="Autorizada",
            xml_storage_key=xml_key,
        )
        db.add(nota)
        db.commit()
        return int(empresa.id), int(nota.id), xml_key


def test_aplicar_eventos_cancela_nota_registra_evento_e_regenera_espelho(monkeypatch):
    empresa_id, nota_id, xml_key = _criar_nota_autorizada()
    storage = get_storage_service()
    regenerados: list[str] = []

    def fake_regenerar(db, storage_, processo, nota, status):
        regenerados.append(status)

    monkeypatch.setattr(eventos_sync_service.legacy_ingestion_service, "_regenerar_pdf_espelho_evento", fake_regenerar)

    payload = {
        "StatusProcessamento": "DOCUMENTOS_LOCALIZADOS",
        "LoteDFe": [{"NSU": "915", "ChaveAcesso": CHAVE_EVENTO, "TipoDocumento": "EVENTO", "ArquivoXml": _b64gz(XML_EVENTO_CANCELAMENTO)}],
    }
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        empresa = db.get(Empresa, empresa_id)
        resultado = eventos_sync_service.aplicar_eventos_payload(db, storage, nota, empresa, payload)

        assert resultado["eventos_aplicados"] == 1
        assert resultado["status_anterior"] == "autorizada"
        assert resultado["status_atual"] == "cancelada"
        assert resultado["pdf_regenerado"] is True
        assert regenerados == ["cancelada"]

        nota = db.get(Nota, nota_id)
        assert nota.status_documento == "cancelada"
        assert nota.status_rotulo == "Cancelada"
        assert "motivo" in (nota.conferencia_observacao or "").lower()
        evento = db.query(Evento).filter(Evento.chave_afetada == CHAVE).one()
        assert evento.nota_id == nota_id
        assert evento.nsu == 915
        assert evento.tipo_evento == "cancelada"
        assert storage.exists(evento.xml_storage_key)
        assert db.query(Arquivo).filter(Arquivo.nota_id == nota_id, Arquivo.tipo == "XML").count() == 1
        storage.delete(evento.xml_storage_key)
    storage.delete(xml_key)


def test_aplicar_eventos_sem_documentos_nao_altera_nota():
    empresa_id, nota_id, xml_key = _criar_nota_autorizada()
    storage = get_storage_service()
    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        empresa = db.get(Empresa, empresa_id)
        # Resposta E2220 do ADN: nenhum evento para a chave.
        resultado = eventos_sync_service.aplicar_eventos_payload(
            db, storage, nota, empresa, {"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO"}
        )
        assert resultado["documentos"] == 0
        assert resultado["status_atual"] == "autorizada"
        assert db.query(Evento).count() == 0
    storage.delete(xml_key)


def test_rota_sincronizar_eventos_exige_operador_e_usa_o_servico(monkeypatch):
    empresa_id, nota_id, xml_key = _criar_nota_autorizada()
    chamadas: list[int] = []

    def fake_sync(db, storage, nota):
        chamadas.append(int(nota.id))
        return {"nota_id": nota.id, "status_anterior": "autorizada", "status_atual": "autorizada", "eventos_aplicados": 0}

    monkeypatch.setattr(eventos_sync_service, "sincronizar_eventos_nota", fake_sync)

    with TestClient(app) as client:
        response = client.post(f"/notas/{nota_id}/sincronizar-eventos")
        assert response.status_code == 200, response.text
        assert response.json()["nota_id"] == nota_id
        assert chamadas == [nota_id]

        inexistente = client.post("/notas/999999/sincronizar-eventos")
        assert inexistente.status_code == 404

    from backend.app.api.deps import get_current_usuario

    leitura = SimpleNamespace(id=2, empresa_id=empresa_id, email="leitura@example.com", nome="Leitura", ativo=True, grupo="planning_hub", is_admin=False, papel="leitura")
    app.dependency_overrides[get_current_usuario] = lambda: leitura
    try:
        with TestClient(app) as client:
            negado = client.post(f"/notas/{nota_id}/sincronizar-eventos")
            assert negado.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_usuario, None)
    get_storage_service().delete(xml_key)


def test_regenerar_pdf_espelho_evento_gera_carimbo_de_verdade(monkeypatch):
    # Regressao: faltava `import tempfile` em legacy_ingestion_service e toda
    # regeneracao disparada por evento morria com NameError, engolido como
    # "aviso de PDF" (10.632 ocorrencias em producao entre 06/08 e 17/09).
    # Nenhuma nota cancelada por evento posterior recebia o carimbo.
    from types import SimpleNamespace
    from backend.app.services import legacy_ingestion_service as svc

    empresa_id, nota_id, xml_key = _criar_nota_autorizada()
    storage = get_storage_service()
    gerados: list[tuple[bytes, str | None]] = []

    class FakeDanfse:
        def generate(self, xml_bytes, watermark=None):
            gerados.append((xml_bytes, watermark))
            return b"%PDF-1.4\n%carimbado\n", "x.pdf"

    monkeypatch.setattr(svc, "DanfseService", lambda: FakeDanfse())
    monkeypatch.setattr(svc, "extrair_dados_nfse", lambda *_a, **_k: {"emit_nome": "P", "numero_nfse": "77"})

    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        empresa = db.get(Empresa, empresa_id)
        contexto = SimpleNamespace(id=None, empresa_id=empresa_id, empresa=empresa)
        svc._regenerar_pdf_espelho_evento(db, storage, contexto, nota, "cancelada")
        db.commit()
        assert gerados and gerados[0][1] == "cancelada"
        assert nota.pdf_espelho_storage_key
        assert storage.get_bytes(nota.pdf_espelho_storage_key).startswith(b"%PDF")
        storage.delete(nota.pdf_espelho_storage_key)
    storage.delete(xml_key)


def _criar_certificado(empresa_id: int) -> int:
    from backend.app.db.models import Certificado
    from backend.app.services import secrets_service

    storage = get_storage_service()
    storage.put_bytes("certificados/eventos-teste.pfx", b"PFX-FAKE", content_type="application/octet-stream")
    with SessionLocal() as db:
        certificado = Certificado(empresa_id=empresa_id, nome="Cert eventos", storage_key="certificados/eventos-teste.pfx", ativo=True)
        db.add(certificado)
        db.flush()
        ref = secrets_service.build_certificado_senha_ref(certificado.id)
        secrets_service.save_secret(db, ref, "pfx_password", "senha-teste")
        certificado.senha_secret_ref = ref
        db.commit()
        return int(certificado.id)


def test_sessao_certificado_reaproveita_pfx_e_conexao_entre_consultas(monkeypatch):
    """Um PFX e um adaptador mTLS por empresa; a chamada por nota so faz o GET."""
    empresa_id, _nota_id, _xml_key = _criar_nota_autorizada()
    _criar_certificado(empresa_id)
    adaptadores: list[dict] = []
    gets: list[dict] = []

    class FakeAdapter:
        def __init__(self, pkcs12_filename, pkcs12_password):
            adaptadores.append({"arquivo": pkcs12_filename, "senha": pkcs12_password})

    class FakeHttp:
        fechado = False

        def mount(self, prefix, adapter):
            self.prefix = prefix
            self.adapter = adapter

        def get(self, url, params=None, headers=None, timeout=None):
            gets.append({"url": url, "params": params})
            return SimpleNamespace(status_code=404, json=lambda: {"Erros": [{"Codigo": "E2220"}]})

        def close(self):
            FakeHttp.fechado = True

    monkeypatch.setattr(eventos_sync_service.requests_pkcs12, "Pkcs12Adapter", FakeAdapter)
    monkeypatch.setattr(eventos_sync_service.requests, "Session", FakeHttp)

    with SessionLocal() as db:
        empresa = db.get(Empresa, empresa_id)
        with eventos_sync_service.SessaoCertificado(db, get_storage_service(), empresa) as sessao:
            pfx = sessao.pfx_path
            assert pfx.exists() and pfx.read_bytes() == b"PFX-FAKE"
            assert sessao.consultar(CHAVE) == {"Erros": [{"Codigo": "E2220"}]}
            assert sessao.consultar("X" * 50) == {"Erros": [{"Codigo": "E2220"}]}

    assert len(adaptadores) == 1 and adaptadores[0]["senha"] == "senha-teste"
    assert sessao.http.prefix == eventos_sync_service.ADN_BASES["producao"]
    assert [g["params"] for g in gets] == [{"cnpjConsulta": "22333444000155"}] * 2
    assert gets[0]["url"].endswith(f"/NFSe/{CHAVE}/Eventos")
    assert FakeHttp.fechado and not pfx.exists()


def test_lote_agrupa_por_empresa_e_usa_uma_sessao_por_empresa(monkeypatch):
    from backend.app.scripts import sincronizar_eventos_lote as lote

    empresa_id, nota_id, _xml_key = _criar_nota_autorizada()
    with SessionLocal() as db:
        outra = Empresa(nome="Outra LTDA", cnpj="33444555000166", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(outra)
        db.flush()
        for numero, chave in (("1", "A" * 50), ("2", "B" * 50)):
            db.add(Nota(empresa_id=outra.id, chave=chave, numero_nfse=numero, status_documento="autorizada", status_rotulo="Autorizada"))
        db.add(Nota(empresa_id=outra.id, chave="C" * 50, numero_nfse="3", status_documento="cancelada", status_rotulo="Cancelada"))
        db.commit()
        outra_id = int(outra.id)

    sessoes: list[int] = []
    consultas: list[tuple[int, str]] = []

    class FakeSessao:
        def __init__(self, db, storage, empresa):
            if int(empresa.id) == empresa_id:
                raise eventos_sync_service.EventosSyncError("A empresa nao possui certificado ativo com senha cadastrada.")
            sessoes.append(int(empresa.id))
            self.empresa_id = int(empresa.id)

        def consultar(self, chave):
            consultas.append((self.empresa_id, chave))
            return {}

        def fechar(self):
            sessoes.append(-self.empresa_id)

    def fake_sync(db, storage, nota, sessao=None):
        assert sessao is not None
        sessao.consultar(nota.chave)
        return {"status_anterior": "autorizada", "status_atual": "autorizada", "eventos_aplicados": 0}

    monkeypatch.setattr(eventos_sync_service, "SessaoCertificado", FakeSessao)
    monkeypatch.setattr(eventos_sync_service, "sincronizar_eventos_nota", fake_sync)

    dry = lote.executar(empresa_id=None, desde=None, limite=None, pausa=0, executar=False)
    assert dry == {"dry_run": True, "notas_alvo": 3, "empresas": 2}

    relatorio = lote.executar(empresa_id=None, desde=None, limite=None, pausa=0, executar=True, workers=4)
    assert relatorio["consultadas"] == 2 and relatorio["erros"] == 0 and relatorio["status_alterado"] == 0
    assert sessoes == [outra_id, -outra_id]
    assert sorted(c[1] for c in consultas) == ["A" * 50, "B" * 50]
    assert [e["empresa_id"] for e in relatorio["empresas_sem_certificado"]] == [empresa_id]
    assert relatorio["empresas_sem_certificado"][0]["notas"] == 1
    assert nota_id  # a nota sem certificado nao e contada como erro de consulta


def test_aplicar_eventos_mantem_cancelamento_quando_pdf_falha(monkeypatch):
    """O status vindo do ADN nao pode ser perdido por uma falha do PHP/dompdf."""
    empresa_id, nota_id, xml_key = _criar_nota_autorizada()
    storage = get_storage_service()

    def fake_regenerar(*_a, **_k):
        raise RuntimeError("Call to undefined function mime_content_type()")

    monkeypatch.setattr(eventos_sync_service.legacy_ingestion_service, "_regenerar_pdf_espelho_evento", fake_regenerar)
    payload = {"LoteDFe": [{"NSU": "916", "TipoDocumento": "EVENTO", "ArquivoXml": _b64gz(XML_EVENTO_CANCELAMENTO)}]}
    with SessionLocal() as db:
        resultado = eventos_sync_service.aplicar_eventos_payload(db, storage, db.get(Nota, nota_id), db.get(Empresa, empresa_id), payload)
        assert resultado["status_atual"] == "cancelada"
        assert resultado["pdf_regenerado"] is False
        assert resultado["erros"] and "mime_content_type" in resultado["erros"][0]
    with SessionLocal() as db:
        assert db.get(Nota, nota_id).status_documento == "cancelada"
        evento = db.query(Evento).filter(Evento.nota_id == nota_id).one()
        storage.delete(evento.xml_storage_key)
    storage.delete(xml_key)
