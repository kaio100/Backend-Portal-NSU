"""Salvar a conferencia nao grava valores calculados so para a tela.

Em producao, 1.326 notas tiveram status_simples_nacional sobrescrito pelo
valor da tela (Correto/Pendente/Divergente) e alertas_fiscais recebeu texto
montado a partir da divergencia digitada, porque o calculo fazia setattr em
colunas mapeadas e o PATCH da conferencia fazia commit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app.db.models import Arquivo, Empresa, Evento, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.main import app


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()
    with SessionLocal() as db:
        for modelo in (Evento, Arquivo, Nota, Empresa):
            db.query(modelo).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        for modelo in (Evento, Arquivo, Nota, Empresa):
            db.query(modelo).delete()
        db.commit()


def _nota() -> int:
    with SessionLocal() as db:
        empresa = Empresa(nome="Conferencia LTDA", cnpj="22333444000155", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        nota = Nota(
            empresa_id=empresa.id,
            chave="5" * 50,
            numero_nfse="10",
            prestador_cnpj="11222333000181",
            tomador_cnpj=None,  # campo obrigatorio ausente: gera alerta na tela
            valor_servico=Decimal("100.00"),
            valor_liquido=Decimal("100.00"),
            status_documento="autorizada",
            simples_xml="Optante S.N",
            simples_nacional_xml="Optante S.N",
            status_simples_nacional="Informado no XML",
            divergencia="Diferenca informada pelo operador",
            alertas_fiscais=None,
        )
        db.add(nota)
        db.commit()
        return int(nota.id)


def test_salvar_conferencia_nao_grava_campos_da_tela():
    nota_id = _nota()
    with TestClient(app) as client:
        antes = client.get(f"/notas/{nota_id}")
        resposta = client.patch(f"/notas/{nota_id}/conferencia", json={"conferencia_status": "ok"})

    assert antes.status_code == 200
    assert "Campos obrigatorios ausentes" in (antes.json()["alertas_fiscais"] or "")
    assert resposta.status_code == 200, resposta.text

    with SessionLocal() as db:
        nota = db.get(Nota, nota_id)
        assert nota.conferencia_status == "ok"
        assert nota.alertas_fiscais is None
        assert nota.status_simples_nacional == "Informado no XML"
        assert nota.simples_xml == "Optante S.N"

