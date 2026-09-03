from types import SimpleNamespace

from backend.app.schemas.certificados import CertificadoRead
from backend.app.services import certificados_service


def test_listagem_usa_ordem_continua_sem_reaproveitar_id(monkeypatch):
    certificados = [
        SimpleNamespace(id=2),
        SimpleNamespace(id=79),
        SimpleNamespace(id=80),
    ]
    monkeypatch.setattr(
        certificados_service.certificados_repo,
        "list_certificados",
        lambda *args, **kwargs: certificados,
    )

    resultado = certificados_service.listar_certificados(SimpleNamespace())

    assert [item.id for item in resultado] == [2, 79, 80]
    assert [item.numero_ordem for item in resultado] == [1, 2, 3]


def test_schema_expoe_numero_ordem_para_o_portal():
    assert "numero_ordem" in CertificadoRead.model_fields
