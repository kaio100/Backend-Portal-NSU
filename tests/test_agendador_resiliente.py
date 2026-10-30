"""ARCH-001: o agendador embutido nao pode morrer na primeira excecao.

Em 08/10/2026 uma excecao (pool de conexoes esgotado) encerrou a tarefa do
agendador; ninguem a recriou e as consultas automaticas pararam por horas.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from backend.app import main
from backend.app.core.config import settings
from backend.app.services import operacao_service


@pytest.fixture(autouse=True)
def _agendador_limpo(monkeypatch):
    monkeypatch.setattr(
        operacao_service,
        "_agendador",
        {"ultimo_tick": None, "ultimo_erro": None, "ultimo_erro_em": None},
    )


def test_agendador_continua_depois_de_excecao_no_ciclo(monkeypatch):
    chamadas = []

    def ciclo():
        chamadas.append(1)
        if len(chamadas) == 1:
            raise RuntimeError("QueuePool limit of size 5 overflow 10 reached")
        return {"certificados_enfileirados": 0}

    async def dormir(_segundos):
        if len(chamadas) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(main, "_ciclo_agendador", ciclo)
    monkeypatch.setattr(main.asyncio, "sleep", dormir)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._run_consultas_scheduler())

    assert len(chamadas) == 2
    estado = operacao_service._estado_agendador(datetime.now(timezone.utc))
    assert "QueuePool" in estado["agendador_ultimo_erro"]
    assert estado["agendador_ultimo_tick_em"] is not None


def test_supervisor_recria_agendador_que_parou(monkeypatch):
    async def agendador_novo():
        await asyncio.Event().wait()

    async def cenario():
        async def morre():
            raise RuntimeError("falha fora do try")

        morta = asyncio.create_task(morre())
        await asyncio.sleep(0)
        agendador = [morta]
        assert main._recriar_agendador_se_parado(agendador) is True
        assert agendador[0] is not morta
        assert not agendador[0].done()
        # Tarefa viva: nada a fazer.
        assert main._recriar_agendador_se_parado(agendador) is False
        agendador[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await agendador[0]

    monkeypatch.setattr(main, "_run_consultas_scheduler", agendador_novo)
    asyncio.run(cenario())
    assert "falha fora do try" in operacao_service._agendador["ultimo_erro"]


def _estado(minutos_sem_tick: int) -> dict:
    agora = datetime.now(timezone.utc)
    operacao_service.registrar_tick_agendador(agora - timedelta(minutes=minutos_sem_tick))
    return operacao_service._estado_agendador(agora)


def test_vigia_avisa_agendador_sem_tick(monkeypatch):
    monkeypatch.setattr(settings, "api_worker_enabled", True)
    monkeypatch.setattr(settings, "embedded_scheduler_enabled", True)
    monkeypatch.setattr(settings, "alerta_agendador_parado_minutos", 30)

    assert "agendador_parado" in operacao_service.problemas(_estado(31))
    assert "agendador_parado" not in operacao_service.problemas(_estado(5))


def test_vigia_ignora_agendador_fora_deste_processo(monkeypatch):
    monkeypatch.setattr(settings, "api_worker_enabled", True)
    monkeypatch.setattr(settings, "embedded_scheduler_enabled", False)
    monkeypatch.setattr(settings, "alerta_agendador_parado_minutos", 30)

    assert "agendador_parado" not in operacao_service.problemas(_estado(120))


def test_health_operacao_informa_agendador(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "metrics_token", None)
    operacao_service.registrar_tick_agendador()
    with TestClient(main.app) as client:
        resposta = client.get("/health/operacao")

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["agendador_ultimo_tick_em"] is not None
    assert "agendador_minutos_sem_tick" in corpo
