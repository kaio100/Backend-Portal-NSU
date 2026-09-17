"""Sincronizacao de eventos por nota (POST /notas/{id}/sincronizar-eventos)."""

from __future__ import annotations

import base64
import gzip
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app.db.models import Arquivo, Empresa, Evento, Nota
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
        for modelo in (Arquivo, Evento, Nota, Empresa):
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
