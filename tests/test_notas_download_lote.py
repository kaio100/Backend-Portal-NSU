from __future__ import annotations

import io
import os
import zipfile
from datetime import date
from pathlib import Path

from cryptography.fernet import Fernet


os.environ["DATABASE_URL"] = "sqlite:///./data/test_consultas_api.db"
os.environ["API_WORKER_ENABLED"] = "false"
os.environ["WORKER_DRY_RUN"] = "true"
os.environ["SECRETS_KEY"] = Fernet.generate_key().decode("utf-8")

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.core.config import settings  # noqa: E402
from backend.app.db.models import (  # noqa: E402
    Arquivo,
    Certificado,
    Empresa,
    Evento,
    Job,
    LockProcessamento,
    LogProcesso,
    Nota,
    Processo,
)
from backend.app.db.session import SessionLocal, init_db  # noqa: E402
from backend.app.main import app  # noqa: E402
from backend.app.services.storage_service import get_storage_service  # noqa: E402


def _reset_db() -> None:
    init_db()
    with SessionLocal() as db:
        db.query(LogProcesso).delete()
        db.query(Job).delete()
        db.query(Evento).delete()
        db.query(Arquivo).delete()
        db.query(Nota).delete()
        db.query(Processo).delete()
        db.query(LockProcessamento).delete()
        db.query(Certificado).delete()
        db.query(Empresa).delete()
        db.commit()


def _empresa_processo(db, nome: str = "Empresa Teste", cnpj: str = "11222333000185"):
    empresa = Empresa(nome=nome, cnpj=cnpj, ambiente="producao", ativo=True)
    db.add(empresa)
    db.flush()
    processo = Processo(empresa_id=empresa.id, certificado_id=123, tipo="consulta_nfse", status="finalizado")
    db.add(processo)
    db.flush()
    return empresa, processo


def _nota(db, empresa, processo, numero: str, prestador: str, status: str = "autorizada") -> Nota:
    nota = Nota(
        empresa_id=empresa.id,
        processo_id=processo.id,
        chave=f"CHAVE-{empresa.id}-{numero}",
        numero_nfse=numero,
        data_emissao=date(2026, 7, 1),
        competencia=date(2026, 7, 1),
        prestador_cnpj="50227393000149",
        prestador_nome=prestador,
        tomador_cnpj=empresa.cnpj,
        tomador_nome=empresa.nome,
        valor_servico=100,
        valor_liquido=100,
        status_documento=status,
        status_rotulo=status.title(),
    )
    db.add(nota)
    db.flush()
    return nota


def _zip_empresa_prefix(empresa_nome: str) -> str:
    return f"notas_nfse/{empresa_nome}"


def _arquivo(db, storage, empresa, processo, nota, tipo: str, filename: str, data: bytes | None = b"data") -> Arquivo:
    key = f"test-download/{empresa.cnpj}/{nota.id}/{filename}"
    if data is not None:
        storage.put_bytes(key, data, content_type="application/pdf" if "PDF" in tipo else "application/xml")
    arquivo = Arquivo(
        empresa_id=empresa.id,
        processo_id=processo.id,
        nota_id=nota.id,
        tipo=tipo,
        storage_backend=storage.backend,
        storage_bucket=settings.storage_bucket,
        storage_key=key,
        filename=filename,
        content_type="application/pdf" if "PDF" in tipo else "application/xml",
        tamanho_bytes=len(data or b""),
        checksum="teste",
    )
    db.add(arquivo)
    db.flush()
    return arquivo


def _zip_names(response) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        return sorted(zf.namelist())


def _zip_text(response, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        return zf.read(name).decode("utf-8")


def test_download_lote_com_nota_ids_inclui_xml_e_pdf_original_sem_espelho():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db, nome="CANOPUS CONSTRUCOES BELEM LTDA")
        nota = _nota(db, empresa, processo, "1370", "9D STUDIO COMERCIO E SERVICOS LTDA")
        _arquivo(db, storage, empresa, processo, nota, "XML", "origem.xml", b"<xml/>")
        _arquivo(db, storage, empresa, processo, nota, "PDF_ORIGINAL", "original.pdf", b"%PDF original")
        _arquivo(db, storage, empresa, processo, nota, "PDF_ESPELHO", "espelho.pdf", b"%PDF espelho")
        nota_id = nota.id
        db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/notas/download-lote",
            json={"nota_ids": [nota_id], "incluir_xml": True, "incluir_pdf": True, "preferir_pdf_original": True},
        )

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert ".zip" in response.headers["content-disposition"]
    names = _zip_names(response)
    assert "notas_nfse/CANOPUS CONSTRUCOES BELEM LTDA/xml/9D STUDIO COMERCIO E SERVICOS LTDA NFS-e 1370.xml" in names
    assert "notas_nfse/CANOPUS CONSTRUCOES BELEM LTDA/pdf/9D STUDIO COMERCIO E SERVICOS LTDA NFS-e 1370.pdf" in names
    assert not any("/NFS-e_1370/" in name for name in names)
    assert not any("50227393000149" in name for name in names)
    assert not any(name.endswith("espelho.pdf") for name in names)


def test_arquivos_da_nota_exibe_apenas_xml_e_pdf_preferido():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db)
        nota = _nota(db, empresa, processo, "44", "PRESTADOR COM ORIGINAL")
        _arquivo(db, storage, empresa, processo, nota, "XML", "nota.xml", b"<xml/>")
        _arquivo(db, storage, empresa, processo, nota, "XML", "nota_duplicada.xml", b"<xml/>")
        _arquivo(db, storage, empresa, processo, nota, "PDF_ESPELHO", "espelho.pdf", b"%PDF espelho")
        _arquivo(db, storage, empresa, processo, nota, "PDF_ORIGINAL", "original.pdf", b"%PDF original")
        nota_id = nota.id
        db.commit()

    with TestClient(app) as client:
        response = client.get(f"/notas/{nota_id}/arquivos")

    assert response.status_code == 200
    payload = response.json()
    assert [item["tipo"] for item in payload] == ["XML", "PDF_ORIGINAL"]
    assert [item["filename"] for item in payload] == ["nota.xml", "original.pdf"]


def test_download_lote_por_filtros_inclui_pdf_espelho_quando_nao_ha_original():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db, cnpj="22333444000155")
        nota_match = _nota(db, empresa, processo, "5", "JORGE LUIS DINIZ SILVA", status="autorizada")
        nota_other = _nota(db, empresa, processo, "6", "OUTRO PRESTADOR", status="cancelada")
        _arquivo(db, storage, empresa, processo, nota_match, "XML", "jorge.xml", b"<xml>jorge</xml>")
        _arquivo(db, storage, empresa, processo, nota_match, "PDF_ESPELHO", "JORGE LUIS DINIZ SILVA NFS-e 5.pdf", b"%PDF espelho")
        _arquivo(db, storage, empresa, processo, nota_other, "XML", "outro.xml", b"<xml>outro</xml>")
        empresa_id = empresa.id
        db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/notas/download-lote",
            json={
                "filtros": {"empresa_id": empresa_id, "status": "autorizada", "busca": "JORGE"},
                "incluir_xml": True,
                "incluir_pdf": True,
            },
        )

    assert response.status_code == 200
    names = _zip_names(response)
    assert any(name.endswith("/pdf/JORGE LUIS DINIZ SILVA NFS-e 5.pdf") for name in names)
    assert any(name.endswith("/xml/JORGE LUIS DINIZ SILVA NFS-e 5.xml") for name in names)
    assert not any("OUTRO" in name for name in names)


def test_download_lote_get_compatibilidade_com_botao_frontend():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db, cnpj="33444555000166")
        nota = _nota(db, empresa, processo, "77", "PRESTADOR GET")
        _arquivo(db, storage, empresa, processo, nota, "XML", "get.xml", b"<xml/>")
        empresa_id = empresa.id
        db.commit()

    with TestClient(app) as client:
        response = client.get(f"/notas/download-lote?empresa_id={empresa_id}&incluir_xml=true&incluir_pdf=false")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert any(name.endswith("/xml/PRESTADOR GET NFS-e 77.xml") for name in _zip_names(response))


def test_download_lote_get_aceita_nota_ids_para_lotes_em_partes():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db, cnpj="44555666000177")
        nota1 = _nota(db, empresa, processo, "1", "PRESTADOR UM")
        nota2 = _nota(db, empresa, processo, "2", "PRESTADOR DOIS")
        _arquivo(db, storage, empresa, processo, nota1, "XML", "n1.xml", b"<xml>1</xml>")
        _arquivo(db, storage, empresa, processo, nota2, "XML", "n2.xml", b"<xml>2</xml>")
        nota1_id = nota1.id
        db.commit()

    with TestClient(app) as client:
        response = client.get(f"/notas/download-lote?nota_ids={nota1_id}&incluir_xml=true&incluir_pdf=false")

    assert response.status_code == 200
    names = _zip_names(response)
    assert any(name.endswith("/xml/PRESTADOR UM NFS-e 1.xml") for name in names)
    assert not any("PRESTADOR DOIS" in name for name in names)


def test_download_lote_com_pdf_original_e_espelho_quando_nao_prefere_original():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db)
        nota = _nota(db, empresa, processo, "10", "PRESTADOR TESTE")
        _arquivo(db, storage, empresa, processo, nota, "PDF_ORIGINAL", "original.pdf", b"%PDF original")
        _arquivo(db, storage, empresa, processo, nota, "PDF_ESPELHO", "espelho.pdf", b"%PDF espelho")
        nota_id = nota.id
        db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/notas/download-lote",
            json={"nota_ids": [nota_id], "incluir_xml": False, "incluir_pdf": True, "preferir_pdf_original": False},
        )

    assert response.status_code == 200
    names = _zip_names(response)
    assert any(name.endswith("/pdf/PRESTADOR TESTE NFS-e 10.pdf") for name in names)
    assert any(name.endswith("/pdf/PRESTADOR TESTE NFS-e 10 (2).pdf") for name in names)


def test_download_lote_estrutura_empresa_xml_pdf_sem_pastas_por_nota_ou_prestador():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db, nome="CANOPUS CONSTRUCOES BELEM LTDA", cnpj="55666777000188")
        nota1 = _nota(db, empresa, processo, "5", "JORGE LUIS DINIZ SILVA")
        nota2 = _nota(db, empresa, processo, "19", "DANY ESCORCIO SILVA SOUSA")
        _arquivo(db, storage, empresa, processo, nota1, "XML", "jorge.xml", b"<xml>jorge</xml>")
        _arquivo(db, storage, empresa, processo, nota1, "PDF_ESPELHO", "jorge.pdf", b"%PDF jorge")
        _arquivo(db, storage, empresa, processo, nota2, "XML", "dany.xml", b"<xml>dany</xml>")
        _arquivo(db, storage, empresa, processo, nota2, "PDF_ESPELHO", "dany.pdf", b"%PDF dany")
        empresa_id = empresa.id
        db.commit()

    with TestClient(app) as client:
        response = client.get(f"/notas/download-lote?empresa_id={empresa_id}&incluir_xml=true&incluir_pdf=true")

    assert response.status_code == 200
    names = _zip_names(response)
    prefix = _zip_empresa_prefix("CANOPUS CONSTRUCOES BELEM LTDA")
    assert f"{prefix}/xml/JORGE LUIS DINIZ SILVA NFS-e 5.xml" in names
    assert f"{prefix}/xml/DANY ESCORCIO SILVA SOUSA NFS-e 19.xml" in names
    assert f"{prefix}/pdf/JORGE LUIS DINIZ SILVA NFS-e 5.pdf" in names
    assert f"{prefix}/pdf/DANY ESCORCIO SILVA SOUSA NFS-e 19.pdf" in names
    assert not any("/NFS-e_5/" in name or "/NFS-e_19/" in name for name in names)
    assert not any("50227393000149" in name or "55666777000188" in name for name in names)


def test_download_lote_sanitiza_nomes_e_impede_path_traversal():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db, nome="../CANOPUS/CONSTRUCOES\r\nBELEM LTDA", cnpj="66777888000199")
        nota = _nota(db, empresa, processo, "33/../x", "../JORGE\\LUIS\nDINIZ")
        _arquivo(db, storage, empresa, processo, nota, "XML", "evil.xml", b"<xml/>")
        nota_id = nota.id
        db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/notas/download-lote",
            json={"nota_ids": [nota_id], "incluir_xml": True, "incluir_pdf": False},
        )

    assert response.status_code == 200
    names = _zip_names(response)
    assert names == ["notas_nfse/CANOPUS CONSTRUCOES BELEM LTDA/xml/JORGE LUIS DINIZ NFS-e 33 x.xml"]
    for name in names:
        assert ".." not in name
        assert "\\" not in name
        assert not name.startswith("/")


def test_download_lote_arquivos_duplicados_recebem_sufixo_sem_sobrescrever():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db, nome="EMPRESA DUPLICADA", cnpj="77888999000100")
        nota1 = _nota(db, empresa, processo, "5", "PRESTADOR IGUAL")
        nota2 = _nota(db, empresa, processo, "5 ", "PRESTADOR IGUAL")
        _arquivo(db, storage, empresa, processo, nota1, "XML", "n1.xml", b"<xml>1</xml>")
        _arquivo(db, storage, empresa, processo, nota2, "XML", "n2.xml", b"<xml>2</xml>")
        empresa_id = empresa.id
        db.commit()

    with TestClient(app) as client:
        response = client.get(f"/notas/download-lote?empresa_id={empresa_id}&incluir_xml=true&incluir_pdf=false")

    assert response.status_code == 200
    names = _zip_names(response)
    assert "notas_nfse/EMPRESA DUPLICADA/xml/PRESTADOR IGUAL NFS-e 5.xml" in names
    assert "notas_nfse/EMPRESA DUPLICADA/xml/PRESTADOR IGUAL NFS-e 5 (2).xml" in names


def test_download_lote_continua_com_arquivo_ausente_e_relatorio():
    _reset_db()
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db)
        nota = _nota(db, empresa, processo, "20", "PRESTADOR AUSENTE")
        _arquivo(db, storage, empresa, processo, nota, "XML", "ausente.xml", None)
        nota_id = nota.id
        db.commit()

    with TestClient(app) as client:
        response = client.post("/notas/download-lote", json={"nota_ids": [nota_id], "incluir_xml": True, "incluir_pdf": False})

    assert response.status_code == 200
    names = _zip_names(response)
    assert "notas_nfse/RELATORIO_ERROS.txt" in names
    assert "indisponivel no storage" in _zip_text(response, "notas_nfse/RELATORIO_ERROS.txt")


def test_download_lote_sem_notas_retorna_erro_amigavel():
    _reset_db()
    with TestClient(app) as client:
        response = client.post("/notas/download-lote", json={"nota_ids": [999999]})

    assert response.status_code == 404
    assert response.json()["detail"] == "Nenhuma nota encontrada para os filtros informados."


def test_download_lote_respeita_limite_maximo(monkeypatch):
    _reset_db()
    monkeypatch.setattr(settings, "download_lote_max_notas", 1)
    storage = get_storage_service()
    with SessionLocal() as db:
        empresa, processo = _empresa_processo(db)
        nota1 = _nota(db, empresa, processo, "1", "PRESTADOR 1")
        nota2 = _nota(db, empresa, processo, "2", "PRESTADOR 2")
        _arquivo(db, storage, empresa, processo, nota1, "XML", "n1.xml", b"<xml/>")
        _arquivo(db, storage, empresa, processo, nota2, "XML", "n2.xml", b"<xml/>")
        empresa_id = empresa.id
        db.commit()

    with TestClient(app) as client:
        response = client.post("/notas/download-lote", json={"filtros": {"empresa_id": empresa_id}})

    assert response.status_code == 400
    assert "Limite de 1 notas por ZIP excedido" in response.json()["detail"]
