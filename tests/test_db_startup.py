from __future__ import annotations

from backend.app.db import session


def test_init_db_aplica_schema_no_sqlite(monkeypatch):
    chamadas: list[str] = []
    monkeypatch.setattr(session, "_is_sqlite", True)
    monkeypatch.setattr(session, "migrate_db", lambda: chamadas.append("migrate"))

    session.init_db()

    assert chamadas == ["migrate"]


def test_init_db_nao_aplica_schema_no_postgresql(monkeypatch):
    chamadas: list[str] = []
    monkeypatch.setattr(session, "_is_sqlite", False)
    monkeypatch.setattr(session, "migrate_db", lambda: chamadas.append("migrate"))

    session.init_db()

    assert chamadas == []
