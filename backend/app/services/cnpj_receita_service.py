from __future__ import annotations

import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.services import cnpj_cache_service


class CnpjReceitaError(RuntimeError):
    pass


def normalizar_cnpj(value: str) -> str:
    digits = re.sub(r"\D+", "", value or "")
    if len(digits) != 14:
        raise ValueError("CNPJ deve conter 14 digitos.")
    return digits


def _database_path() -> Path:
    return Path(settings.cnpj_receita_db_path).expanduser().resolve()


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or _database_path()
    if not path.is_file():
        raise CnpjReceitaError(f"Base local da Receita nao encontrada em {path}.")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    return connection


def consultar_cnpj(value: str) -> dict[str, Any] | None:
    cnpj = normalizar_cnpj(value)
    query = """
        SELECT
            e.cnpj, e.cnpj_basico, e.cnpj_ordem, e.cnpj_dv,
            e.identificador_matriz_filial, e.nome_fantasia,
            e.situacao_cadastral, e.data_situacao_cadastral,
            e.data_inicio_atividade, e.cnae_fiscal_principal,
            e.cnae_fiscal_secundaria, e.tipo_logradouro, e.logradouro,
            e.numero, e.complemento, e.bairro, e.cep, e.uf,
            e.codigo_municipio, e.ddd1, e.telefone1, e.email,
            p.razao_social, p.natureza_juridica,
            p.capital_social, p.porte_empresa,
            s.opcao_simples, s.data_opcao_simples, s.data_exclusao_simples,
            s.opcao_mei, s.data_opcao_mei, s.data_exclusao_mei
        FROM estabelecimentos e
        LEFT JOIN empresas p ON p.cnpj_basico = e.cnpj_basico
        LEFT JOIN simples s ON s.cnpj_basico = e.cnpj_basico
        WHERE e.cnpj = ?
        LIMIT 1
    """
    try:
        with _connect() as connection:
            row = connection.execute(query, (cnpj,)).fetchone()
            metadata = connection.execute(
                "SELECT valor FROM metadados WHERE chave = 'competencia'"
            ).fetchone()
    except sqlite3.Error as exc:
        raise CnpjReceitaError(f"Falha ao consultar a base local da Receita: {exc}") from exc
    if row is None:
        return None
    result = dict(row)
    result["fonte"] = "Receita Federal - Dados Abertos"
    result["competencia_base"] = metadata["valor"] if metadata else None
    return result


def consultar_cnpj_cacheado(db: Session, value: str) -> dict[str, Any] | None:
    """Consulta um CNPJ usando o cache persistente antes da base da Receita.

    Somente respostas preenchidas sao armazenadas. Cada leitura vencida e
    renovada a partir da base local pelo prazo configurado (30 dias por padrao).
    """
    cnpj = normalizar_cnpj(value)
    cache = cnpj_cache_service.get_cache_valido(
        db,
        cnpj,
        fonte=cnpj_cache_service.RECEITA_FONTE,
    )
    if cache is not None:
        payload = cache.get("json_resposta")
        if isinstance(payload, dict) and payload:
            return payload

    try:
        resultado = consultar_cnpj(cnpj)
    except CnpjReceitaError:
        from backend.app.services import cnpj_invertexto_service

        fallback = cnpj_invertexto_service.consultar_cnpj(db, cnpj)
        return fallback.get("json_resposta") if fallback is not None else None
    if resultado is None:
        return None

    cnpj_cache_service.salvar_cache(
        db,
        cnpj,
        consulta_simples_api=status_simples(resultado),
        codigo_cnae=resultado.get("cnae_fiscal_principal"),
        descricao_cnae="",
        status_consulta="Encontrado",
        json_resposta=resultado,
        fonte=cnpj_cache_service.RECEITA_FONTE,
        cache_days=settings.cnpj_receita_cache_days,
    )
    db.commit()
    return resultado


def consultar_cnpjs(values: set[str] | list[str]) -> dict[str, dict[str, Any]]:
    """Consulta varios CNPJs em uma unica conexao com a base local."""
    cnpjs = sorted({normalizar_cnpj(value) for value in values})
    if not cnpjs:
        return {}

    columns = """
        e.cnpj, e.cnpj_basico, e.cnpj_ordem, e.cnpj_dv,
        e.identificador_matriz_filial, e.nome_fantasia,
        e.situacao_cadastral, e.data_situacao_cadastral,
        e.data_inicio_atividade, e.cnae_fiscal_principal,
        e.cnae_fiscal_secundaria, e.tipo_logradouro, e.logradouro,
        e.numero, e.complemento, e.bairro, e.cep, e.uf,
        e.codigo_municipio, e.ddd1, e.telefone1, e.email,
        p.razao_social, p.natureza_juridica, p.capital_social,
        p.porte_empresa, s.opcao_simples, s.data_opcao_simples,
        s.data_exclusao_simples, s.opcao_mei, s.data_opcao_mei,
        s.data_exclusao_mei
    """
    encontrados: dict[str, dict[str, Any]] = {}
    try:
        with _connect() as connection:
            metadata = connection.execute(
                "SELECT valor FROM metadados WHERE chave = 'competencia'"
            ).fetchone()
            competencia = metadata["valor"] if metadata else None
            for index in range(0, len(cnpjs), 800):
                group = cnpjs[index:index + 800]
                placeholders = ",".join("?" for _ in group)
                query = f"""
                    SELECT {columns}
                    FROM estabelecimentos e
                    LEFT JOIN empresas p ON p.cnpj_basico = e.cnpj_basico
                    LEFT JOIN simples s ON s.cnpj_basico = e.cnpj_basico
                    WHERE e.cnpj IN ({placeholders})
                """
                for row in connection.execute(query, group):
                    item = dict(row)
                    item["fonte"] = "Receita Federal - Dados Abertos"
                    item["competencia_base"] = competencia
                    encontrados[item["cnpj"]] = item
    except sqlite3.Error as exc:
        raise CnpjReceitaError(f"Falha ao consultar a base local da Receita: {exc}") from exc
    return encontrados


def status_simples(item: dict[str, Any]) -> str:
    if item.get("opcao_mei") == "S":
        return "MEI"
    if item.get("opcao_simples") == "S":
        return "Optante S.N"
    if item.get("opcao_simples") == "N":
        return "Não optante"
    # Regra operacional aprovada: quando a Receita possui o CNPJ no cadastro
    # de estabelecimentos, mas não possui nenhum histórico de Simples/MEI,
    # tratamos a ausência integral desses campos como não optante.
    campos_simples = (
        "opcao_simples",
        "data_opcao_simples",
        "data_exclusao_simples",
        "opcao_mei",
        "data_opcao_mei",
        "data_exclusao_mei",
    )
    if all(item.get(campo) in {None, ""} for campo in campos_simples):
        return "Não optante"
    return "Não disponível"


@lru_cache(maxsize=4)
def _status_base_cached(path_raw: str, tamanho: int, modificado_ns: int) -> dict[str, Any]:
    """Calcula o status uma vez por versao fisica da base.

    O COUNT(*) percorre dezenas de milhoes de registros na base completa. O
    tamanho e o mtime fazem o cache ser invalidado quando o importador troca o
    arquivo, sem manter uma conexao SQLite aberta entre requisicoes.
    """
    del tamanho, modificado_ns
    path = Path(path_raw)
    result: dict[str, Any] = {"disponivel": True, "caminho": path_raw}
    try:
        with _connect(path) as connection:
            result["metadados"] = {
                row["chave"]: row["valor"]
                for row in connection.execute("SELECT chave, valor FROM metadados")
            }
            result["estabelecimentos"] = connection.execute(
                "SELECT COUNT(*) FROM estabelecimentos"
            ).fetchone()[0]
    except sqlite3.Error as exc:
        result["disponivel"] = False
        result["erro"] = str(exc)
    return result


def status_base() -> dict[str, Any]:
    path = _database_path()
    try:
        stat = path.stat()
    except OSError:
        return {"disponivel": False, "caminho": str(path)}
    # Retorna uma copia para impedir que um consumidor altere o valor em cache.
    return dict(_status_base_cached(str(path), stat.st_size, stat.st_mtime_ns))
