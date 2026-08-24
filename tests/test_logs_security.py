from __future__ import annotations

from backend.app.api.routers.logs import LogProcessoRead
from backend.app.services.logs_service import sanitizar_contexto, sanitizar_texto


def test_sanitizar_contexto_remove_segredos_e_traceback():
    contexto = {
        "senha": "segredo",
        "nested": {
            "authorization": "Bearer abc.def",
            "traceback": "File /app/backend/app/main.py, line 10",
        },
        "mensagem": "falhou em postgresql://usuario:senha@host/db?token=abc123",
    }

    sanitized = sanitizar_contexto(contexto)

    assert sanitized["senha"] == "[REDACTED]"
    assert sanitized["nested"]["authorization"] == "[REDACTED]"
    assert sanitized["nested"]["traceback"] == "[REMOVIDO]"
    assert "usuario:senha" not in sanitized["mensagem"]
    assert "abc123" not in sanitized["mensagem"]


def test_sanitizar_texto_preserva_mensagem_operacional():
    assert sanitizar_texto("Senha do certificado nao configurada") == "Senha do certificado nao configurada"


def test_schema_de_log_sanitiza_historico_antes_da_resposta():
    item = LogProcessoRead.model_validate(
        {
            "id": 1,
            "processo_id": 2,
            "empresa_id": 3,
            "level": "error",
            "mensagem": "Erro com Bearer token-secreto",
            "contexto_json": {"traceback": "caminho interno", "api_key": "valor"},
        }
    )

    assert item.mensagem == "Erro com Bearer [REDACTED]"
    assert item.contexto_json == {"traceback": "[REMOVIDO]", "api_key": "[REDACTED]"}
