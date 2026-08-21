from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.dialects.postgresql import insert

from backend.app.db.models import CnpjCache
from backend.app.scripts.sincronizar_cnpjs_portal import (
    _chunks,
    coletar_cnpjs_online,
    consultar_base_local,
)
from backend.app.services.cnpj_cache_service import DEFAULT_FONTE, RECEITA_FONTE
from backend.app.services.cnpj_receita_service import consultar_cnpj, status_simples


INVALIDOS = {None, "", "Não consultado", "Não disponível", "Erro na consulta", "Pendente"}


def _database_url() -> str:
    url = dotenv_values(".env").get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL online não configurada no .env.")
    if str(url).startswith("postgresql://"):
        return "postgresql+psycopg://" + str(url).removeprefix("postgresql://")
    return str(url)


def corrigir(local_db: Path, cache_days: int = 30, batch_size: int = 500) -> dict:
    engine = create_engine(_database_url(), pool_pre_ping=True)
    hoje = date.today()
    try:
        with engine.connect() as connection:
            todos = coletar_cnpjs_online(connection)
            validos = set(connection.execute(text("""
                SELECT cnpj
                  FROM cnpj_cache
                 WHERE fonte = :fonte
                   AND data_expiracao >= current_date
                   AND consulta_simples_api NOT IN (
                       'Não consultado', 'Não disponível', 'Erro na consulta', 'Pendente'
                   )
                   AND consulta_simples_api IS NOT NULL
            """), {"fonte": DEFAULT_FONTE}).scalars())

        pendentes = sorted(set(todos) - validos)
        encontrados, ausentes = consultar_base_local(local_db, pendentes)
        # Segunda passagem deliberadamente individual. Alem de atender a
        # auditoria CNPJ a CNPJ, ela elimina qualquer duvida sobre perda de
        # linha causada pelo SELECT em lote.
        reconsultados_individualmente = 0
        recuperados_individualmente: dict[str, dict] = {}
        for item in encontrados:
            if status_simples(item) != "Não disponível":
                continue
            reconsultados_individualmente += 1
            individual = consultar_cnpj(item["cnpj"])
            if individual and status_simples(individual) != "Não disponível":
                recuperados_individualmente[item["cnpj"]] = individual
        if recuperados_individualmente:
            encontrados = [
                recuperados_individualmente.get(item["cnpj"], item)
                for item in encontrados
            ]
        resolvidos = []
        sem_classificacao = []
        agora = datetime.now(timezone.utc)
        for item in encontrados:
            consulta = status_simples(item)
            if consulta == "Não disponível":
                sem_classificacao.append(item["cnpj"])
                continue
            payload = dict(item)
            payload["fonte"] = RECEITA_FONTE
            payload["origem_cache_compatibilidade"] = DEFAULT_FONTE
            resolvidos.append({
                "cnpj": item["cnpj"],
                # Compatibilidade com o backend atualmente publicado, que
                # ainda busca explicitamente esta chave de fonte.
                "fonte": DEFAULT_FONTE,
                "consulta_simples_api": consulta,
                "codigo_cnae": item.get("cnae_fiscal_principal") or "",
                "descricao_cnae": "",
                "status_consulta": "Encontrado - Receita Federal",
                "json_resposta": payload,
                "erro": None,
                "data_consulta": hoje,
                "data_expiracao": hoje + timedelta(days=max(1, cache_days)),
                "created_at": agora,
                "updated_at": agora,
                "status": "Encontrado - Receita Federal",
                "simples_status": consulta,
                "json_completo": payload,
            })

        for cnpj in ausentes:
            payload = {
                "cnpj": cnpj,
                "fonte": RECEITA_FONTE,
                "regra": "CNPJ ausente na base da Receita considerado não optante",
            }
            resolvidos.append({
                "cnpj": cnpj,
                "fonte": DEFAULT_FONTE,
                "consulta_simples_api": "Não optante",
                "codigo_cnae": "",
                "descricao_cnae": "",
                "status_consulta": "Não encontrado - regra operacional",
                "json_resposta": payload,
                "erro": None,
                "data_consulta": hoje,
                "data_expiracao": hoje + timedelta(days=max(1, cache_days)),
                "created_at": agora,
                "updated_at": agora,
                "status": "Não encontrado - regra operacional",
                "simples_status": "Não optante",
                "json_completo": payload,
            })

        table = CnpjCache.__table__
        gravados = 0
        with engine.begin() as connection:
            for group in _chunks(resolvidos, batch_size):
                statement = insert(table).values(group)
                excluded = statement.excluded
                statement = statement.on_conflict_do_update(
                    index_elements=[table.c.cnpj, table.c.fonte],
                    set_={
                        "consulta_simples_api": excluded.consulta_simples_api,
                        "codigo_cnae": excluded.codigo_cnae,
                        "descricao_cnae": excluded.descricao_cnae,
                        "status_consulta": excluded.status_consulta,
                        "json_resposta": excluded.json_resposta,
                        "erro": excluded.erro,
                        "data_consulta": excluded.data_consulta,
                        "data_expiracao": excluded.data_expiracao,
                        "updated_at": excluded.updated_at,
                        "status": excluded.status,
                        "simples_status": excluded.simples_status,
                        "json_completo": excluded.json_completo,
                    },
                )
                connection.execute(statement)
                gravados += len(group)
                print(f"Corrigidos: {gravados}/{len(resolvidos)}", flush=True)

        return {
            "cnpjs_portal": len(todos),
            "cache_invertexto_valido": len(validos),
            "pendentes_ou_erros": len(pendentes),
            "resolvidos_receita": len(resolvidos),
            "sem_classificacao_receita": len(sem_classificacao),
            "reconsultados_individualmente": reconsultados_individualmente,
            "recuperados_individualmente": len(recuperados_individualmente),
            "ausentes_receita": len(ausentes),
            "cnpjs_ausentes_receita": ausentes,
            "gravados_online": gravados,
            "validade_ate": str(hoje + timedelta(days=max(1, cache_days))),
        }
    finally:
        engine.dispose()


if __name__ == "__main__":
    print(corrigir(Path("data/cnpj_receita.sqlite3"), cache_days=30))
