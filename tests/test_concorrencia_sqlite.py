"""Regressao dos incidentes de concorrencia local (SQLite).

Reproduzem os dois mecanismos que derrubavam consultas reais com
"database is locked": a thread de ingestao incremental que sobrevivia ao fim
do job e gravava em paralelo com a sessao principal, e a escrita de uma
transacao longa com snapshot defasado (SQLITE_BUSY_SNAPSHOT), que o SQLite
recusa na hora sem respeitar busy_timeout.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy.exc import OperationalError

from backend.app.db.models import Arquivo, Empresa, Evento, Job, LockProcessamento, LogProcesso, Nota, NsuControle, Processo
from backend.app.db.session import SessionLocal, executar_escrita_com_retry, init_db, renovar_snapshot
from backend.app.services import legacy_ingestion_service
from backend.app.services.storage_service import get_storage_service


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()
    with SessionLocal() as db:
        for modelo in (LockProcessamento, LogProcesso, Job, Evento, Arquivo, Nota, NsuControle, Processo, Empresa):
            db.query(modelo).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        for modelo in (LockProcessamento, LogProcesso, Job, Evento, Arquivo, Nota, NsuControle, Processo, Empresa):
            db.query(modelo).delete()
        db.commit()


def _index_com_notas(tmp_path, quantidade: int) -> None:
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    linhas = ["chave;xml_path;pdf_path;valor_liquido;prestador_cnpj;prestador_nome;tomador_cnpj;tomador_nome"]
    for i in range(quantidade):
        chave = f"{i:044d}"
        xml_path = xml_dir / f"{chave}.xml"
        xml_path.write_text(
            '<?xml version="1.0" encoding="utf-8"?><NFSe><infNFSe Id="NFS'
            + chave
            + '"><valores><vServPrest><vServ>10.00</vServ></vServPrest><vLiq>10.00</vLiq></valores></infNFSe></NFSe>',
            encoding="utf-8",
        )
        linhas.append(f"{chave};{xml_path};;;11222333000199;P;22333444000155;T")
    (tmp_path / "index_nfse.csv").write_text("\n".join(linhas) + "\n", encoding="utf-8")


def test_ingestao_para_no_ponto_de_parada_e_informa_proxima_linha(tmp_path):
    # A thread de ingestao incremental so consultava o stop_event entre
    # chamadas, e cada chamada percorria o lote inteiro (com PDF via PHP entre
    # as linhas). Ela sobrevivia ao join(timeout=10) e continuava gravando
    # depois do fim do job. Agora a parada e cooperativa, linha a linha.
    _index_com_notas(tmp_path, 6)
    chamadas = {"n": 0}

    def should_stop() -> bool:
        chamadas["n"] += 1
        # Deixa 2 linhas passarem e pede parada na terceira.
        return chamadas["n"] > 2

    with SessionLocal() as db:
        empresa = Empresa(nome="Concorrencia LTDA", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, certificado_id=None, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.flush()

        result = legacy_ingestion_service.ingerir_saida_legado(
            db,
            get_storage_service(),
            processo,
            tmp_path,
            gerar_pdf_espelho=False,
            should_stop=should_stop,
        )
        db.commit()

    assert result["interrompido"] is True
    assert result["notas_criadas"] == 2
    # A proxima rodada retoma exatamente da linha em que parou.
    assert result["proxima_linha_index"] == 2


def test_retry_reexecuta_escrita_quando_sqlite_recusa_por_concorrencia():
    tentativas = {"n": 0}

    def operacao():
        tentativas["n"] += 1
        if tentativas["n"] < 3:
            raise OperationalError("UPDATE x", {}, sqlite3.OperationalError("database is locked"))
        return "ok"

    assert executar_escrita_com_retry(operacao, tentativas=5, pausa_base=0.0) == "ok"
    assert tentativas["n"] == 3


def test_retry_nao_mascara_outros_erros():
    def operacao():
        raise OperationalError("UPDATE x", {}, sqlite3.OperationalError("no such table: x"))

    with pytest.raises(OperationalError):
        executar_escrita_com_retry(operacao, tentativas=5, pausa_base=0.0)


def test_snapshot_defasado_e_o_mecanismo_do_database_is_locked(tmp_path):
    # Prova isolada do incidente: A le (snapshot), B grava e commita, A tenta
    # gravar a mesma linha -> recusa imediata, mesmo com busy_timeout alto.
    db = tmp_path / "t.db"
    boot = sqlite3.connect(db)
    boot.execute("pragma journal_mode=WAL")
    boot.execute("create table t(id integer primary key, v int)")
    boot.execute("insert into t values(1, 0)")
    boot.commit()
    boot.close()

    a = sqlite3.connect(db, timeout=5)
    b = sqlite3.connect(db, timeout=5)
    a.execute("pragma busy_timeout=5000")
    b.execute("pragma busy_timeout=5000")
    a.execute("begin")
    assert a.execute("select v from t where id=1").fetchone() == (0,)
    b.execute("begin immediate")
    b.execute("update t set v=650 where id=1")
    b.commit()
    with pytest.raises(sqlite3.OperationalError, match="database is locked"):
        a.execute("update t set v=650 where id=1")
    a.rollback()
    # Com o snapshot renovado a mesma escrita passa.
    a.execute("update t set v=700 where id=1")
    a.commit()
    assert b.execute("select v from t where id=1").fetchone() == (700,)


def test_renovar_snapshot_nao_descarta_mudancas_pendentes():
    with SessionLocal() as db:
        empresa = Empresa(nome="Pendente LTDA", cnpj="22333444000156", ambiente="producao", ativo=True)
        db.add(empresa)
        # Ha objeto novo pendente: renovar nao pode fazer rollback.
        renovar_snapshot(db)
        assert empresa in db.new
        db.commit()
        # Sem pendencias, encerra a transacao de leitura.
        db.query(Empresa).count()
        assert db.in_transaction()
        renovar_snapshot(db)
        assert not db.in_transaction()


def test_ingestao_nao_chama_php_quando_pdf_espelho_ja_existe(tmp_path, monkeypatch):
    # A ingestao pos-processamento revisita as linhas ja ingeridas pela
    # incremental. Gerar o PDF (PHP, 1-2 s) para depois descarta-lo por ja
    # existir no storage custava ~40 minutos por job de 1.600 notas e deixava
    # o processo "rodando" sem nenhum contador avancar.
    from backend.app.services import legacy_ingestion_service as svc
    from backend.app.services.storage_service import build_pdf_espelho_key

    _index_com_notas(tmp_path, 1)
    storage = get_storage_service()
    chamadas = {"php": 0}

    def _php_proibido(*args, **kwargs):
        chamadas["php"] += 1
        raise AssertionError("PHP nao deveria ser chamado para PDF ja existente")

    monkeypatch.setattr(svc, "_gerar_pdf_espelho_path", _php_proibido)
    monkeypatch.setattr(svc, "extrair_dados_nfse", lambda *_a, **_k: {"emit_nome": "P", "numero_nfse": "1"})

    with SessionLocal() as db:
        empresa = Empresa(nome="Reuso LTDA", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, certificado_id=None, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.flush()
        # PDF ja presente no storage, como deixado pela ingestao incremental.
        # Sem data no indice, _ano_mes devolve "0000"/"00".
        chave_pdf = build_pdf_espelho_key(empresa.cnpj, "0000", "00", "P NFS-e 1.pdf")
        storage.put_bytes(chave_pdf, b"%PDF-1.4\n%existente\n", content_type="application/pdf")
        try:
            result = svc.ingerir_saida_legado(db, storage, processo, tmp_path, gerar_pdf_espelho=True)
            db.commit()
        finally:
            storage.delete(chave_pdf)

    assert chamadas["php"] == 0
    assert result["notas_criadas"] == 1
    assert result["avisos_pdf"] == 0
    assert result["arquivos_existentes"] >= 1


def test_recalculo_limpa_alerta_de_regra_nao_encontrada_quando_regra_existe():
    # Regressao: `_aplicar_campos_fiscais_xml` ignorava texto vazio, entao um
    # alerta antigo ("Regra fiscal nao encontrada para subitem LC116 17.02")
    # nunca era apagado quando o recalculo passava a encontrar a regra. Em
    # producao havia milhares de notas com regra_irrf=SIM e o alerta antigo.
    from backend.app.services.legacy_ingestion_service import _aplicar_campos_fiscais_xml

    nota_data: dict = {}
    _aplicar_campos_fiscais_xml(nota_data, {"regra_irrf": "SIM", "alertas_fiscais": ""})
    assert "alertas_fiscais" in nota_data and nota_data["alertas_fiscais"] is None

    nota_data = {}
    _aplicar_campos_fiscais_xml(nota_data, {"alertas_fiscais": "Regra fiscal nao encontrada para subitem LC116 99.01."})
    assert nota_data["alertas_fiscais"].startswith("Regra fiscal nao encontrada")

    nota_data = {}
    _aplicar_campos_fiscais_xml(nota_data, {"regra_irrf": "SIM"})
    assert "alertas_fiscais" not in nota_data


def test_lock_orfao_sem_fuso_nao_quebra_aquisicao():
    """SQLite devolve expires_at sem tzinfo; um lock vencido deve ser retomado."""
    from datetime import datetime, timedelta

    from backend.app.db.models import LockProcessamento
    from backend.app.db.session import SessionLocal, init_db
    from backend.app.repositories import locks_repo

    init_db()
    with SessionLocal() as db:
        db.query(LockProcessamento).filter(LockProcessamento.empresa_id == 9901).delete()
        db.add(LockProcessamento(empresa_id=9901, certificado_id=1, locked_by="morto", locked_at=datetime(2026, 1, 1), expires_at=datetime(2026, 1, 1) + timedelta(hours=1)))
        db.commit()
        assert locks_repo.acquire_lock(db, 9901, 1, "novo") is True
        db.commit()
        assert locks_repo.get_lock(db, 9901, 1).locked_by == "novo"
        db.query(LockProcessamento).filter(LockProcessamento.empresa_id == 9901).delete()
        db.commit()


def test_falha_em_uma_nota_nao_desfaz_as_anteriores(tmp_path, monkeypatch):
    # Com commits a cada 20 linhas, o rollback da linha com erro desfazia as
    # linhas boas ainda nao confirmadas do bloco. Elas ja tinham sido contadas
    # como criadas e o cursor da ingestao incremental ja tinha passado delas.
    _index_com_notas(tmp_path, 6)
    chave_com_erro = f"{2:044d}"
    upsert_original = legacy_ingestion_service.notas_repo.upsert_nota_by_chave

    def upsert_com_falha(db, empresa_id, chave, data):
        if chave == chave_com_erro:
            raise RuntimeError("falha simulada")
        return upsert_original(db, empresa_id, chave, data)

    monkeypatch.setattr(legacy_ingestion_service.notas_repo, "upsert_nota_by_chave", upsert_com_falha)
    with SessionLocal() as db:
        empresa = Empresa(nome="Bloco LTDA", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, certificado_id=None, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.commit()
        result = legacy_ingestion_service.ingerir_saida_legado(
            db, get_storage_service(), processo, tmp_path, gerar_pdf_espelho=False, commit_every=20
        )
        db.rollback()  # nada pendente pode depender do chamador

    with SessionLocal() as db:
        chaves = sorted(chave for (chave,) in db.query(Nota.chave).all())
    assert result["erros"] == 1
    assert result["notas_criadas"] == 5
    assert chaves == [f"{i:044d}" for i in range(6) if i != 2]


def test_releitura_identica_preserva_conferencia_sem_baixar_pdfs(tmp_path, monkeypatch):
    from backend.app.services.storage_service import LocalFilesystemStorage, build_pdf_espelho_key
    from backend.app.repositories import arquivos_repo

    class R2Contado(LocalFilesystemStorage):
        backend = "r2"
        listagens = 0
        downloads = 0

        def list_keys(self, prefix=""):
            self.listagens += 1
            return super().list_keys(prefix)

        def get_bytes(self, key):
            self.downloads += 1
            return super().get_bytes(key)

    _index_com_notas(tmp_path, 4)
    storage = R2Contado(tmp_path / "storage")
    for xml in (tmp_path / "xml").glob("*.xml"):
        xml.write_text(xml.read_text().replace("<valores>", "<cStat>100</cStat><valores>"))
    with SessionLocal() as db:
        empresa = Empresa(nome="Releitura", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.commit()
        legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path, gerar_pdf_espelho=False)
        for nota in db.query(Nota).all():
            key = build_pdf_espelho_key(empresa.cnpj, "0000", "00", f"{nota.chave}.pdf")
            storage.put_bytes(key, b"%PDF existente", "application/pdf")
            arquivos_repo.create_arquivo(db, dict(empresa_id=empresa.id, nota_id=nota.id, tipo="pdf_espelho",
                storage_backend="r2", storage_key=key, checksum="checksum-pdf", tamanho_bytes=14))
            nota.pdf_espelho_storage_key = key
            nota.conferencia_status = "conferida"
            nota.responsavel = "Operador"
            nota.conferencia_observacao = "Nao alterar"
        db.commit()
        antes = {n.id: n.updated_at for n in db.query(Nota).all()}
        storage.listagens = storage.downloads = 0
        monkeypatch.setattr(legacy_ingestion_service.notas_repo, "upsert_nota_by_chave",
                            lambda *_a, **_k: pytest.fail("XML identico nao deve passar pelo upsert"))
        resultado = legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path)
        assert resultado["notas_inalteradas"] == 4
        assert resultado["erros"] == 0
        assert storage.listagens == 2  # XML e PDF: nao cresce com o numero de notas.
        assert storage.downloads == 0
        for nota in db.query(Nota).all():
            assert nota.updated_at == antes[nota.id]
            assert (nota.conferencia_status, nota.responsavel, nota.conferencia_observacao) == (
                "conferida", "Operador", "Nao alterar")


def test_xml_alterado_atualiza_banco_e_storage_e_xml_ausente_e_reparado(tmp_path):
    from backend.app.services.storage_service import LocalFilesystemStorage
    _index_com_notas(tmp_path, 1)
    storage = LocalFilesystemStorage(tmp_path / "storage")
    with SessionLocal() as db:
        empresa = Empresa(nome="Alteracao", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.commit()
        legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path, gerar_pdf_espelho=False)
        nota = db.query(Nota).one()
        key = nota.xml_storage_key
        xml = tmp_path / "xml" / f"{0:044d}.xml"
        xml.write_text(xml.read_text().replace("10.00", "25.00"))
        resultado = legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path, gerar_pdf_espelho=False)
        assert resultado["notas_inalteradas"] == 0
        assert resultado["erros"] == 0
        assert b"25.00" in storage.get_bytes(key)
        assert float(db.query(Nota).one().valor_servico) == 25
        storage.delete(key)
        resultado = legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path, gerar_pdf_espelho=False)
        assert resultado["notas_inalteradas"] == 0
        assert storage.exists(key)


def test_nsu_novo_com_xml_identico_avanca_e_pdf_ausente_e_reposto(tmp_path, monkeypatch):
    import hashlib
    from backend.app.services.storage_service import LocalFilesystemStorage, build_pdf_espelho_key
    from backend.app.repositories import arquivos_repo

    _index_com_notas(tmp_path, 1)
    indice = tmp_path / "index_nfse.csv"
    linhas = indice.read_text().splitlines()
    indice.write_text(linhas[0] + ";ultimo_nsu\n" + linhas[1] + ";7\n")
    storage = LocalFilesystemStorage(tmp_path / "storage")
    monkeypatch.setattr(legacy_ingestion_service, "extrair_dados_nfse",
                        lambda *_a, **_k: {"emit_nome": "P", "numero_nfse": "1"})
    with SessionLocal() as db:
        empresa = Empresa(nome="NSU", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, tipo="consulta_nfse", status="rodando")
        db.add(processo)
        db.commit()
        legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path, gerar_pdf_espelho=False)
        nota = db.query(Nota).one()
        key = build_pdf_espelho_key(empresa.cnpj, "0000", "00", "P NFS-e 1.pdf")
        conteudo = b"%PDF existente"
        storage.put_bytes(key, conteudo, "application/pdf")
        arquivos_repo.create_arquivo(db, dict(empresa_id=empresa.id, nota_id=nota.id, tipo="PDF_ESPELHO",
            storage_backend="local", storage_key=key, checksum=hashlib.sha256(conteudo).hexdigest(),
            tamanho_bytes=len(conteudo)))
        nota.pdf_espelho_storage_key = key
        db.commit()
        indice.write_text(linhas[0] + ";ultimo_nsu\n" + linhas[1] + ";8\n")
        monkeypatch.setattr(storage, "get_bytes", lambda *_a: pytest.fail("PDF registrado nao deve ser baixado"))
        result = legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path)
        assert result["erros"] == 0
        assert result["notas_inalteradas"] == 0
        assert db.query(Nota).one().ultimo_nsu == 8
        storage.delete(key)
        novo_pdf = tmp_path / "novo.pdf"
        novo_pdf.write_bytes(b"%PDF reparado")
        monkeypatch.setattr(legacy_ingestion_service, "_gerar_pdf_espelho_path", lambda *_a, **_k: novo_pdf)
        result = legacy_ingestion_service.ingerir_saida_legado(db, storage, processo, tmp_path)
        assert result["erros"] == 0
        assert result["notas_inalteradas"] == 0
        assert storage.exists(key)


def test_heartbeat_independente_impede_recuperacao_enquanto_ingestao_esta_bloqueada(monkeypatch):
    import threading
    from datetime import datetime, timedelta, timezone
    from backend.app.services import job_lease_service
    from backend.app.repositories.jobs_repo import recuperar_jobs_travados

    velho = datetime.now(timezone.utc) - timedelta(hours=2)
    with SessionLocal() as db:
        empresa = Empresa(nome="Heartbeat", cnpj="22333444000155", ambiente="producao", ativo=True)
        db.add(empresa)
        db.flush()
        processo = Processo(empresa_id=empresa.id, tipo="consulta_nfse", status="rodando", updated_at=velho)
        db.add(processo)
        db.flush()
        job = Job(empresa_id=empresa.id, processo_id=processo.id, tipo="consulta_nfse",
                  status="rodando", locked_by="worker-teste", updated_at=velho)
        db.add(job)
        db.add(LockProcessamento(empresa_id=empresa.id, certificado_id=123, locked_by="worker-teste",
                               locked_at=velho, expires_at=velho))
        job.certificado_id = 123
        db.commit()
        ids = job.id, processo.id
    renovado = threading.Event()
    original = job_lease_service.renovar_lease

    def renovar(*args):
        result = original(*args)
        renovado.set()
        return result

    monkeypatch.setattr(job_lease_service, "renovar_lease", renovar)
    with job_lease_service.manter_lease(*ids, "worker-teste", intervalo=0.02):
        # Simula ingestao ocupada: o chamador nao executa nenhum heartbeat.
        assert renovado.wait(3)
        with SessionLocal() as db:
            assert recuperar_jobs_travados(db, 15) == 0
            assert db.get(Job, ids[0]).status == "rodando"
            assert db.query(LockProcessamento).one().expires_at.replace(tzinfo=timezone.utc) > datetime.now(timezone.utc)
            db.get(Job, ids[0]).status = "cancelado"
            db.commit()
    assert not original(*ids, "worker-teste")
    assert not any(t.name == f"heartbeat-job-{ids[0]}" for t in threading.enumerate())
