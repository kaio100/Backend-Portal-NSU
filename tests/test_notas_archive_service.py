from __future__ import annotations

import json
from datetime import date

import pytest

from backend.app.db.models import Arquivo, Empresa, Evento, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.repositories import arquivos_repo
from backend.app.services.notas_archive_service import arquivar_notas_anos_anteriores


class MemoryStorage:
    backend = "memory"

    def __init__(self):
        self.data: dict[str, bytes] = {"xml/antiga.xml": b"<xml />"}

    def put_file(self, key, path, content_type=None):
        self.data[key] = path.read_bytes()

    def object_size(self, key):
        return len(self.data[key]) if key in self.data else None


def test_manifesto_confirmado_antes_de_excluir_e_preserva_storage_e_vinculos():
    init_db()
    storage = MemoryStorage()
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Manifesto", cnpj="99888777000166", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        antiga = Nota(empresa_id=empresa.id, chave="MANIFESTO-ANTIGA", competencia=date(2025, 12, 1), data_emissao=date(2026, 1, 5), xml_storage_key="xml/antiga.xml", arquivada=True)
        fallback = Nota(empresa_id=empresa.id, chave="MANIFESTO-FALLBACK", competencia=None, data_emissao=date(2025, 6, 1))
        atual = Nota(empresa_id=empresa.id, chave="MANIFESTO-ATUAL", competencia=date(2026, 1, 1), data_emissao=date(2025, 12, 31))
        sem_data = Nota(empresa_id=empresa.id, chave="MANIFESTO-SEM-DATA", competencia=None, data_emissao=None)
        db.add_all([antiga, fallback, atual, sem_data])
        db.flush()
        arquivo = arquivos_repo.create_arquivo(db, {"empresa_id": empresa.id, "nota_id": antiga.id, "tipo": "XML", "storage_backend": "memory", "storage_key": "xml/antiga.xml"})
        evento = Evento(empresa_id=empresa.id, nota_id=antiga.id, chave_evento="EVT-1", xml_storage_key="eventos/evt.xml")
        db.add(evento)
        db.commit()
        antiga_id, fallback_id, atual_id, sem_data_id = antiga.id, fallback.id, atual.id, sem_data.id

        assert arquivar_notas_anos_anteriores(db, storage, executar=False)["notas"] == 2
        resultado = arquivar_notas_anos_anteriores(db, storage, executar=True)
        assert resultado["notas"] == resultado["excluidas"] == 2
        assert db.get(Nota, antiga_id) is None and db.get(Nota, fallback_id) is None
        assert db.get(Nota, atual_id) is not None and db.get(Nota, sem_data_id) is not None
        db.refresh(arquivo)
        db.refresh(evento)
        assert arquivo.nota_id is None and evento.nota_id is None
        assert storage.data["xml/antiga.xml"] == b"<xml />"

        item = next(item for item in resultado["empresas"] if item["empresa_id"] == empresa.id)
        manifest = json.loads(storage.data[item["manifesto"]])
        assert {nota["chave"] for nota in manifest["notas"]} == {"MANIFESTO-ANTIGA", "MANIFESTO-FALLBACK"}
        assert manifest["arquivos"][0]["nota_id"] == antiga_id
        assert manifest["eventos"][0]["nota_id"] == antiga_id
        assert {ref["storage_key"] for ref in manifest["referencias_storage"]} == {"xml/antiga.xml", "eventos/evt.xml"}

        db.query(Arquivo).filter(Arquivo.empresa_id == empresa.id).delete(synchronize_session=False)
        db.query(Evento).filter(Evento.empresa_id == empresa.id).delete(synchronize_session=False)
        db.query(Nota).filter(Nota.empresa_id == empresa.id).delete(synchronize_session=False)
        db.delete(empresa)
        db.commit()


def test_falha_na_validacao_do_manifesto_nao_exclui_nota():
    init_db()

    class StorageComFalha(MemoryStorage):
        def object_size(self, key):
            return None

    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Falha", cnpj="99888777000155", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        nota = Nota(empresa_id=empresa.id, chave="NAO-EXCLUIR", competencia=date(2025, 1, 1))
        db.add(nota)
        db.commit()
        nota_id = nota.id
        with pytest.raises(RuntimeError, match="Manifesto nao confirmado"):
            arquivar_notas_anos_anteriores(db, StorageComFalha(), executar=True)
        assert db.get(Nota, nota_id) is not None
        db.delete(db.get(Nota, nota_id))
        db.delete(empresa)
        db.commit()
