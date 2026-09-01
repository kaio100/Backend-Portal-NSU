from __future__ import annotations

from datetime import date

from backend.app.db.models import Arquivo, Empresa, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.repositories import arquivos_repo, notas_repo
from backend.app.services.notas_archive_service import arquivar_notas_anos_anteriores


class MemoryStorage:
    backend = "memory"

    def __init__(self):
        self.data: dict[str, bytes] = {}

    def put_bytes(self, key, content, content_type=None):
        self.data[key] = content

    def put_file(self, key, path, content_type=None):
        self.data[key] = path.read_bytes()

    def get_bytes(self, key):
        return self.data[key]

    def exists(self, key):
        return key in self.data

    def object_size(self, key):
        return len(self.data[key]) if key in self.data else None


def test_backup_confirmado_antes_de_ocultar_nota_antiga():
    init_db()
    storage = MemoryStorage()
    with SessionLocal() as db:
        empresa = Empresa(nome="Empresa Arquivo", cnpj="99888777000166", ambiente="producao", ativo=True, grupo="planning_hub")
        db.add(empresa)
        db.flush()
        antiga = Nota(empresa_id=empresa.id, chave="ARQUIVO-ANTIGA", competencia=date(2025, 12, 1), data_emissao=date(2026, 1, 5), arquivada=False)
        atual = Nota(empresa_id=empresa.id, chave="ARQUIVO-ATUAL", competencia=date(2026, 1, 1), data_emissao=date(2026, 1, 1), arquivada=False)
        futura = Nota(empresa_id=empresa.id, chave="ARQUIVO-FUTURA", competencia=date(2027, 1, 1), data_emissao=date(2027, 1, 1), arquivada=False)
        db.add_all([antiga, atual, futura])
        db.flush()
        storage.data["xml/antiga.xml"] = b"<xml />"
        arquivos_repo.create_arquivo(db, {"empresa_id": empresa.id, "nota_id": antiga.id, "tipo": "XML", "storage_backend": "memory", "storage_key": "xml/antiga.xml"})
        db.commit()

        preview = arquivar_notas_anos_anteriores(db, storage, executar=False)
        preview_empresa = next(item for item in preview["empresas"] if item["empresa_id"] == empresa.id)
        assert preview_empresa["notas"] == 1
        assert antiga.arquivada is False

        resultado = arquivar_notas_anos_anteriores(db, storage, executar=True)
        db.refresh(antiga)
        resultado_empresa = next(item for item in resultado["empresas"] if item["empresa_id"] == empresa.id)
        assert resultado_empresa["notas"] == 1
        assert antiga.arquivada is True
        assert antiga.arquivo_backup_storage_key in storage.data
        assert {nota.chave for nota in notas_repo.list_notas(db, empresa_id=empresa.id)} == {"ARQUIVO-ATUAL", "ARQUIVO-FUTURA"}
        assert [nota.chave for nota in notas_repo.list_notas(db, empresa_id=empresa.id, arquivadas="somente")] == ["ARQUIVO-ANTIGA"]

        db.query(Arquivo).filter(Arquivo.empresa_id == empresa.id).delete(synchronize_session=False)
        db.query(Nota).filter(Nota.empresa_id == empresa.id).delete(synchronize_session=False)
        db.delete(empresa)
        db.commit()
