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

from backend.app.db.models import Arquivo, Empresa, Evento, Job, LogProcesso, Nota, NsuControle, Processo
from backend.app.db.session import SessionLocal, executar_escrita_com_retry, init_db, renovar_snapshot
from backend.app.services import legacy_ingestion_service
from backend.app.services.storage_service import get_storage_service


@pytest.fixture(autouse=True)
def _banco_limpo():
    init_db()
    with SessionLocal() as db:
        for modelo in (LogProcesso, Job, Evento, Arquivo, Nota, NsuControle, Processo, Empresa):
            db.query(modelo).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        for modelo in (LogProcesso, Job, Evento, Arquivo, Nota, NsuControle, Processo, Empresa):
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
