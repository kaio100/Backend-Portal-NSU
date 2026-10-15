"""Numeros agregados para a secao Volumetria do painel administrativo.

Tudo e calculado no banco (GROUP BY), filtrado pelo grupo do admin (ou todos,
para o admin geral) e sem notas arquivadas. Datas fiscais usam a data de emissao;
as consultas ao ADN usam a data de criacao do processo.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.app.db.models import Certificado, Empresa, Nota, Processo


def _como_data(valor) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _dias(inicio: date, fim: date) -> list[date]:
    return [inicio + timedelta(days=i) for i in range((fim - inicio).days + 1)]


def calcular(db: Session, grupo: str | None, dias: int = 30, hoje: date | None = None) -> dict:
    dias = max(7, min(int(dias), 366))
    hoje = hoje or datetime.now(timezone.utc).date()
    inicio = hoje - timedelta(days=dias - 1)
    inicio_ano = date(hoje.year, hoje.month, 1) - timedelta(days=365)
    inicio_ano = date(inicio_ano.year, inicio_ano.month, 1)

    def notas_do_escopo(query):
        query = query.join(Empresa, Empresa.id == Nota.empresa_id).filter(Nota.arquivada.is_(False))
        return query.filter(Empresa.grupo == grupo) if grupo is not None else query

    valor = func.coalesce(func.sum(Nota.valor_servico), 0)

    # Notas por dia (periodo) e por mes (ultimos 12 meses + o atual), pela emissao.
    por_dia = dict()
    for dia, total, soma in (
        notas_do_escopo(db.query(Nota.data_emissao, func.count(Nota.id), valor))
        .filter(Nota.data_emissao >= inicio, Nota.data_emissao <= hoje)
        .group_by(Nota.data_emissao)
        .all()
    ):
        por_dia[_como_data(dia)] = (int(total), float(soma or 0))
    notas_por_dia = [
        {"data": d.isoformat(), "notas": por_dia.get(d, (0, 0.0))[0], "valor": round(por_dia.get(d, (0, 0.0))[1], 2)}
        for d in _dias(inicio, hoje)
    ]

    por_mes: dict[str, list[float]] = defaultdict(lambda: [0, 0.0])
    for dia, total, soma in (
        notas_do_escopo(db.query(Nota.data_emissao, func.count(Nota.id), valor))
        .filter(Nota.data_emissao >= inicio_ano, Nota.data_emissao <= hoje)
        .group_by(Nota.data_emissao)
        .all()
    ):
        chave = _como_data(dia).strftime("%Y-%m")
        por_mes[chave][0] += int(total)
        por_mes[chave][1] += float(soma or 0)
    meses = []
    cursor = inicio_ano
    while cursor <= hoje:
        chave = cursor.strftime("%Y-%m")
        meses.append({"mes": chave, "notas": int(por_mes[chave][0]), "valor": round(por_mes[chave][1], 2)})
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)

    no_periodo = lambda q: notas_do_escopo(q).filter(Nota.data_emissao >= inicio, Nota.data_emissao <= hoje)  # noqa: E731

    # Tomadas x prestadas: o CNPJ da empresa monitorada como tomador ou prestador.
    tipo = case(
        (Nota.tomador_cnpj == Empresa.cnpj, "tomadas"),
        (Nota.prestador_cnpj == Empresa.cnpj, "prestadas"),
        else_="outras",
    )
    tipos = {"tomadas": 0, "prestadas": 0, "outras": 0}
    for rotulo, total in no_periodo(db.query(tipo, func.count(Nota.id))).group_by(tipo).all():
        tipos[str(rotulo)] = int(total)

    status_normalizado = func.lower(func.coalesce(Nota.status_documento, "normal"))
    status = {"normal": 0, "cancelada": 0, "substituida": 0}
    for rotulo, total in no_periodo(db.query(status_normalizado, func.count(Nota.id))).group_by(status_normalizado).all():
        texto = str(rotulo)
        chave = "cancelada" if "cancel" in texto else "substituida" if "substitu" in texto else "normal"
        status[chave] += int(total)

    top_empresas = [
        {"empresa": nome, "notas": int(total), "valor": round(float(soma or 0), 2)}
        for nome, total, soma in no_periodo(db.query(Empresa.nome, func.count(Nota.id), valor))
        .group_by(Empresa.nome)
        .order_by(func.count(Nota.id).desc())
        .limit(10)
        .all()
    ]

    por_grupo = []
    if grupo is None:
        por_grupo = [
            {"grupo": g, "notas": int(total), "valor": round(float(soma or 0), 2)}
            for g, total, soma in no_periodo(db.query(Empresa.grupo, func.count(Nota.id), valor))
            .group_by(Empresa.grupo)
            .order_by(func.count(Nota.id).desc())
            .all()
        ]

    responsavel = func.coalesce(func.nullif(func.trim(Nota.responsavel), ""), "Não atribuído")
    pendentes_por_responsavel = [
        {"responsavel": nome, "notas": int(total)}
        for nome, total in no_periodo(db.query(responsavel, func.count(Nota.id)))
        .filter(func.coalesce(Nota.conferencia_status, "pendente") == "pendente")
        .group_by(responsavel)
        .order_by(func.count(Nota.id).desc())
        .limit(10)
        .all()
    ]

    # Consultas ao ADN por dia: finalizadas, com erro e as demais.
    inicio_ts = datetime.combine(inicio, time.min, tzinfo=timezone.utc)
    processos = db.query(Processo).join(Empresa, Empresa.id == Processo.empresa_id).filter(Processo.created_at >= inicio_ts)
    if grupo is not None:
        processos = processos.filter(Empresa.grupo == grupo)
    dia_processo = func.date(Processo.created_at)
    consultas: dict[date, dict] = {}
    for dia, situacao, total in (
        processos.with_entities(dia_processo, Processo.status, func.count(Processo.id)).group_by(dia_processo, Processo.status).all()
    ):
        d = _como_data(dia)
        linha = consultas.setdefault(d, {"finalizadas": 0, "erros": 0, "outras": 0})
        chave = "finalizadas" if situacao == "finalizado" else "erros" if situacao == "erro" else "outras"
        linha[chave] += int(total)
    consultas_por_dia = [{"data": d.isoformat(), **consultas.get(d, {"finalizadas": 0, "erros": 0, "outras": 0})} for d in _dias(inicio, hoje)]

    if db.get_bind().dialect.name == "sqlite":
        duracao = (func.julianday(Processo.finished_at) - func.julianday(Processo.started_at)) * 86400
    else:
        duracao = func.extract("epoch", Processo.finished_at - Processo.started_at)
    duracao_media = (
        processos.filter(Processo.started_at.isnot(None), Processo.finished_at.isnot(None), Processo.status == "finalizado")
        .with_entities(func.avg(duracao))
        .scalar()
    )

    # Certificados ativos por vencimento.
    agora = datetime.now(timezone.utc)
    certificados = db.query(Certificado).join(Empresa, Empresa.id == Certificado.empresa_id).filter(Certificado.ativo.is_(True))
    if grupo is not None:
        certificados = certificados.filter(Empresa.grupo == grupo)
    faixas = {"vencidos": 0, "ate_30_dias": 0, "ate_60_dias": 0, "ate_90_dias": 0, "mais_de_90_dias": 0, "sem_data": 0}
    for (validade,) in certificados.with_entities(Certificado.valido_ate).all():
        if validade is None:
            faixas["sem_data"] += 1
            continue
        if validade.tzinfo is None:
            validade = validade.replace(tzinfo=timezone.utc)
        restante = (validade - agora).days
        chave = (
            "vencidos" if restante < 0 else "ate_30_dias" if restante <= 30 else "ate_60_dias" if restante <= 60
            else "ate_90_dias" if restante <= 90 else "mais_de_90_dias"
        )
        faixas[chave] += 1

    total_periodo = sum(item["notas"] for item in notas_por_dia)
    valor_periodo = round(sum(item["valor"] for item in notas_por_dia), 2)
    return {
        "periodo": {"inicio": inicio.isoformat(), "fim": hoje.isoformat(), "dias": dias},
        "totais": {
            "notas": total_periodo,
            "valor": valor_periodo,
            "consultas": sum(d["finalizadas"] + d["erros"] + d["outras"] for d in consultas_por_dia),
            "consultas_com_erro": sum(d["erros"] for d in consultas_por_dia),
            "duracao_media_consulta_s": round(float(duracao_media), 1) if duracao_media is not None else None,
        },
        "notas_por_dia": notas_por_dia,
        "notas_por_mes": meses,
        "tipos": tipos,
        "status": status,
        "top_empresas": top_empresas,
        "por_grupo": por_grupo,
        "pendentes_por_responsavel": pendentes_por_responsavel,
        "consultas_por_dia": consultas_por_dia,
        "certificados": faixas,
    }
