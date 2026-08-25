from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app.api.deps import get_current_usuario, require_admin, require_operator
from backend.app.main import app


def _usuario(papel: str, *, is_admin: bool = False):
    return SimpleNamespace(papel=papel, is_admin=is_admin)


def test_leitura_nao_pode_executar_acoes_operacionais():
    with pytest.raises(HTTPException) as exc_info:
        require_operator(_usuario("leitura"))
    assert exc_info.value.status_code == 403


def test_operador_pode_processar_mas_nao_administrar():
    operador = _usuario("operador")
    assert require_operator(operador) is operador
    with pytest.raises(HTTPException) as exc_info:
        require_admin(operador)
    assert exc_info.value.status_code == 403


def test_admin_pode_administrar_e_operar():
    admin = _usuario("admin")
    assert require_admin(admin) is admin
    assert require_operator(admin) is admin


def test_is_admin_legado_continua_compativel_durante_migracao():
    admin_legado = _usuario("operador", is_admin=True)
    assert require_admin(admin_legado) is admin_legado
    assert require_operator(admin_legado) is admin_legado


def test_leitura_enxerga_dados_mas_rotas_de_escrita_retornam_403():
    leitura = SimpleNamespace(
        id=99,
        empresa_id=1,
        email="leitura@example.com",
        nome="Leitura",
        ativo=True,
        grupo="planning_hub",
        is_admin=False,
        papel="leitura",
    )
    app.dependency_overrides[get_current_usuario] = lambda: leitura
    try:
        with TestClient(app) as client:
            listar = client.get("/empresas")
            criar_empresa = client.post(
                "/empresas",
                json={"nome": "Nao autorizada", "cnpj": "12345678000199"},
            )
            iniciar_consultas = client.post("/consultas/iniciar", json={})
            alterar_nota = client.patch("/notas/999999/conferencia", json={"conferencia_status": "ok"})
    finally:
        app.dependency_overrides.pop(get_current_usuario, None)

    assert listar.status_code == 200
    assert criar_empresa.status_code == 403
    assert iniciar_consultas.status_code == 403
    assert alterar_nota.status_code == 403


def test_leitura_pode_acessar_cadastro_de_certificado():
    leitura = SimpleNamespace(
        id=99,
        empresa_id=1,
        email="leitura@example.com",
        nome="Leitura",
        ativo=True,
        grupo="planning_hub",
        is_admin=False,
        papel="leitura",
    )
    app.dependency_overrides[get_current_usuario] = lambda: leitura
    try:
        with TestClient(app) as client:
            response = client.post("/certificados", data={})
    finally:
        app.dependency_overrides.pop(get_current_usuario, None)

    assert response.status_code == 400
    assert response.json()["detail"] == "Arquivo PFX/P12 e obrigatorio."
