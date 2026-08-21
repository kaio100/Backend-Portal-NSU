from __future__ import annotations

import csv
import io
import zipfile

from backend.app.scripts import importar_base_cnpj_receita as importer
from backend.app.services import cnpj_receita_service


def _nested_zip(rows: list[list[str]]) -> bytes:
    csv_buffer = io.StringIO(newline="")
    writer = csv.writer(csv_buffer, delimiter=";", quotechar='"')
    writer.writerows(rows)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("dados.csv", csv_buffer.getvalue().encode("latin-1"))
    return output.getvalue()


def test_importa_e_consulta_cnpj(tmp_path, monkeypatch):
    source = tmp_path / "2026-08.zip"
    empresa = ["62069724", "EMPRESA TESTE LTDA", "2062", "49", "1000,00", "01", ""]
    estabelecimento = [
        "62069724", "0001", "49", "1", "TESTE", "02", "20260101", "00", "", "",
        "20200101", "6201501", "", "RUA", "DAS FLORES", "10", "", "CENTRO", "01001000",
        "SP", "7107", "11", "12345678", "", "", "", "", "teste@example.com", "", "",
    ]
    simples = ["62069724", "S", "20200101", "", "N", "", ""]
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("2026-08/Empresas0.zip", _nested_zip([empresa]))
        archive.writestr("2026-08/Estabelecimentos0.zip", _nested_zip([estabelecimento]))
        archive.writestr("2026-08/Simples.zip", _nested_zip([simples]))

    destination = tmp_path / "cnpj.sqlite3"
    counts = importer.importar(source, destination, ["62.069.724/0001-49"])
    monkeypatch.setattr(cnpj_receita_service.settings, "cnpj_receita_db_path", str(destination))

    result = cnpj_receita_service.consultar_cnpj("62.069.724/0001-49")
    assert counts == {"estabelecimentos": 1, "empresas": 1, "simples": 1}
    assert result is not None
    assert result["cnpj"] == "62069724000149"
    assert result["razao_social"] == "EMPRESA TESTE LTDA"
    assert result["opcao_simples"] == "S"
    assert result["competencia_base"] == "2026-08"


def test_rejeita_cnpj_invalido():
    try:
        cnpj_receita_service.normalizar_cnpj("123")
    except ValueError as exc:
        assert "14 digitos" in str(exc)
    else:
        raise AssertionError("CNPJ invalido deveria ser rejeitado")


def test_status_simples_sem_historico_e_nao_optante():
    assert cnpj_receita_service.status_simples({
        "opcao_simples": None,
        "data_opcao_simples": None,
        "data_exclusao_simples": None,
        "opcao_mei": None,
        "data_opcao_mei": None,
        "data_exclusao_mei": None,
    }) == "Não optante"


def test_consulta_cnpjs_em_lote(tmp_path, monkeypatch):
    destination = tmp_path / "cnpj.sqlite3"
    with importer.sqlite3.connect(destination) as connection:
        connection.execute("CREATE TABLE metadados (chave TEXT PRIMARY KEY, valor TEXT)")
        connection.execute("CREATE TABLE estabelecimentos (cnpj TEXT, cnpj_basico TEXT, cnpj_ordem TEXT, cnpj_dv TEXT, identificador_matriz_filial TEXT, nome_fantasia TEXT, situacao_cadastral TEXT, data_situacao_cadastral TEXT, data_inicio_atividade TEXT, cnae_fiscal_principal TEXT, cnae_fiscal_secundaria TEXT, tipo_logradouro TEXT, logradouro TEXT, numero TEXT, complemento TEXT, bairro TEXT, cep TEXT, uf TEXT, codigo_municipio TEXT, ddd1 TEXT, telefone1 TEXT, email TEXT)")
        connection.execute("CREATE TABLE empresas (cnpj_basico TEXT, razao_social TEXT, natureza_juridica TEXT, capital_social TEXT, porte_empresa TEXT)")
        connection.execute("CREATE TABLE simples (cnpj_basico TEXT, opcao_simples TEXT, data_opcao_simples TEXT, data_exclusao_simples TEXT, opcao_mei TEXT, data_opcao_mei TEXT, data_exclusao_mei TEXT)")
        connection.execute("INSERT INTO metadados VALUES ('competencia', '2026-08')")
        connection.execute("INSERT INTO estabelecimentos (cnpj, cnpj_basico, cnpj_ordem, cnpj_dv, cnae_fiscal_principal) VALUES ('62069724000149', '62069724', '0001', '49', '7112000')")
        connection.execute("INSERT INTO empresas VALUES ('62069724', 'EMPRESA TESTE', '2062', '1000', '01')")
        connection.execute("INSERT INTO simples VALUES ('62069724', 'S', '20200101', '', 'N', '', '')")
    monkeypatch.setattr(cnpj_receita_service.settings, "cnpj_receita_db_path", str(destination))

    result = cnpj_receita_service.consultar_cnpjs(
        {"62.069.724/0001-49", "00.000.000/0000-00"}
    )

    assert set(result) == {"62069724000149"}
    assert result["62069724000149"]["competencia_base"] == "2026-08"
    assert cnpj_receita_service.status_simples(result["62069724000149"]) == "Optante S.N"


def test_status_base_reutiliza_contagem_enquanto_arquivo_nao_muda(tmp_path, monkeypatch):
    destination = tmp_path / "cnpj.sqlite3"
    with importer.sqlite3.connect(destination) as connection:
        connection.execute("CREATE TABLE metadados (chave TEXT PRIMARY KEY, valor TEXT)")
        connection.execute("CREATE TABLE estabelecimentos (cnpj TEXT)")
        connection.execute("INSERT INTO metadados VALUES ('competencia', '2026-08')")
        connection.execute("INSERT INTO estabelecimentos VALUES ('62069724000149')")
    monkeypatch.setattr(cnpj_receita_service.settings, "cnpj_receita_db_path", str(destination))
    cnpj_receita_service._status_base_cached.cache_clear()

    primeiro = cnpj_receita_service.status_base()
    segundo = cnpj_receita_service.status_base()

    assert primeiro == segundo
    assert primeiro["estabelecimentos"] == 1
    assert cnpj_receita_service._status_base_cached.cache_info().hits == 1


def test_importador_ignora_byte_nul(tmp_path):
    nested = tmp_path / "dados.zip"
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("dados.csv", b'"62069724";"RAZAO\x00 SOCIAL"\r\n')
    outer_path = tmp_path / "outer.zip"
    with zipfile.ZipFile(outer_path, "w", zipfile.ZIP_STORED) as archive:
        archive.write(nested, "Empresas0.zip")
    (tmp_path / "temp").mkdir()
    with zipfile.ZipFile(outer_path) as outer:
        rows = list(importer._rows_from_nested_zip(outer, "Empresas0.zip", tmp_path / "temp"))
    assert rows == [["62069724", "RAZAO SOCIAL"]]
