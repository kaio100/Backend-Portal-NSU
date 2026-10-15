from __future__ import annotations

import base64
import json
import re
from datetime import date, datetime, timezone

from sqlalchemy import func, or_, tuple_
from sqlalchemy.orm import Session

from backend.app.db.models import Certificado, Empresa, Nota


# Notas canceladas/substituidas continuam visiveis no portal, mas nunca entram
# nas exportacoes em lote (ZIP de XML/PDF e planilha de conferencia).
STATUS_FORA_DA_EXPORTACAO = ("cancelada", "cancelado", "substituida", "substituido")


def _somente_exportaveis(query):
    # Sem o IS NULL o NOT IN do SQL descartaria tambem notas sem status gravado.
    return query.filter(
        or_(
            Nota.status_documento.is_(None),
            func.lower(func.trim(Nota.status_documento)).notin_(STATUS_FORA_DA_EXPORTACAO),
        )
    )


def _incidencia_search_term(value: str) -> str:
    text = re.sub(r"[,/\-]+", " ", value.strip())
    # O XML normalmente armazena apenas o municipio ("Imperatriz"),
    # enquanto o usuario naturalmente pesquisa "Imperatriz/MA".
    return re.sub(r"\s+[A-Za-z]{2}$", "", text).strip()


# Ordem das listagens, sempre decrescente. Nulo vira 1900-01-01: mesma ordem do
# antigo "DESC NULLS LAST" e permite paginar por cursor, continuando de onde a
# pagina anterior parou (WHERE (chaves) < (valores da ultima nota)). Com OFFSET
# o banco ordenava e descartava dezenas de milhares de linhas a cada pagina: era
# a consulta de 10 a 16 s que esgotou o pool de conexoes em 15/10/2026.
_INICIO_DATA = date(1900, 1, 1)
_INICIO = datetime(1900, 1, 1, tzinfo=timezone.utc)
_CAMPOS_ORDEM = {
    "id": ("id",),
    "emissao": ("data_emissao", "importado_em", "updated_at", "id"),
    # created_at saiu da chave: so desempatava importado_em + updated_at iguais (o id
    # ja desempata) e, no SQLite, o valor padrao sem microssegundos quebrava o cursor.
    "recentes": ("importado_em", "updated_at", "id"),
}


def _campos_ordem(sort: str) -> tuple[str, ...]:
    return _CAMPOS_ORDEM.get(sort, _CAMPOS_ORDEM["recentes"])


def _eh_data_hora(campo: str) -> bool:
    return campo not in {"id", "data_emissao"}


def chaves_ordem(sort: str, sqlite: bool = False) -> list:
    chaves = []
    for campo in _campos_ordem(sort):
        coluna = getattr(Nota, campo)
        if campo == "id":
            chaves.append(coluna)
            continue
        chave = func.coalesce(coluna, _INICIO_DATA if campo == "data_emissao" else _INICIO)
        # O SQLite guarda data e hora como texto, as vezes sem microssegundos
        # (CURRENT_TIMESTAMP): comparar como numero evita repetir nota no cursor.
        chaves.append(func.julianday(chave) if sqlite and _eh_data_hora(campo) else chave)
    return chaves


def _valores_cursor(cursor: str, sort: str, sqlite: bool) -> list:
    valores = decodificar_cursor(cursor, sort)
    if not sqlite:
        return valores
    return [func.julianday(v) if _eh_data_hora(c) else v for c, v in zip(_campos_ordem(sort), valores)]


def _valor_ordem(nota, campo: str):
    valor = getattr(nota, campo, None)
    if campo == "id":
        return int(valor)
    if valor is None:
        return _INICIO_DATA if campo == "data_emissao" else _INICIO
    return valor


def codificar_cursor(nota, sort: str) -> str:
    """Ponteiro opaco para a pagina seguinte a `nota` na ordem `sort`."""
    valores = [_valor_ordem(nota, campo) for campo in _campos_ordem(sort)]
    texto = json.dumps({"s": sort, "v": [v.isoformat() if isinstance(v, (date, datetime)) else v for v in valores]})
    return base64.urlsafe_b64encode(texto.encode("utf-8")).decode("ascii").rstrip("=")


def decodificar_cursor(cursor: str, sort: str) -> list:
    try:
        dados = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8"))
        campos = _campos_ordem(sort)
        if dados.get("s") != sort or len(dados.get("v") or []) != len(campos):
            raise ValueError
        valores = []
        for campo, valor in zip(campos, dados["v"]):
            if campo == "id":
                valores.append(int(valor))
            elif campo == "data_emissao":
                valores.append(date.fromisoformat(valor))
            else:
                valores.append(datetime.fromisoformat(valor))
        return valores
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Cursor de paginacao invalido. Recarregue a lista.") from exc


def get_nota(db: Session, nota_id: int) -> Nota | None:
    return db.get(Nota, nota_id)


def get_nota_by_chave(db: Session, empresa_id: int, chave: str) -> Nota | None:
    return (
        db.query(Nota)
        .filter(Nota.empresa_id == empresa_id)
        .filter(Nota.chave == chave)
        .first()
    )


def get_nota_by_chave_optional_empresa(
    db: Session,
    chave: str,
    empresa_id: int | None = None,
    grupo: str | None = None,
) -> Nota | None:
    query = db.query(Nota).filter(Nota.chave == chave)
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    if grupo is not None:
        query = query.join(Empresa, Empresa.id == Nota.empresa_id).filter(Empresa.grupo == grupo)
    return query.order_by(Nota.id.desc()).first()


def list_notas(
    db: Session,
    grupo: str | None = None,
    empresa_id: int | None = None,
    certificado_id: int | None = None,
    processo_id: int | None = None,
    status_documento: str | None = None,
    status: str | None = None,
    numero: str | None = None,
    prestador_cnpj: str | None = None,
    tomador_cnpj: str | None = None,
    chave: str | None = None,
    busca: str | None = None,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    competencia_inicio: date | None = None,
    competencia_fim: date | None = None,
    conferencia_status: str | None = None,
    prioridade: str | None = None,
    responsavel: str | None = None,
    status_nota_pdf: str | None = None,
    simples_nacional_xml: str | None = None,
    consulta_simples_api: str | None = None,
    status_simples_nacional: str | None = None,
    incidencia_iss: str | None = None,
    divergencia: str | None = None,
    sla_status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    sort: str = "recentes",
    arquivadas: str = "ativas",
    count_only: bool = False,
    somente_exportaveis: bool = False,
    cursor: str | None = None,
) -> list[Nota] | int:
    query = db.query(Nota)
    if somente_exportaveis:
        query = _somente_exportaveis(query)
    if arquivadas == "ativas":
        query = query.filter(Nota.arquivada.is_(False))
    elif arquivadas == "somente":
        query = query.filter(Nota.arquivada.is_(True))
    elif arquivadas != "todas":
        raise ValueError("Filtro de arquivadas invalido.")
    if grupo is not None:
        query = query.join(Empresa, Empresa.id == Nota.empresa_id).filter(Empresa.grupo == grupo)
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    if certificado_id is not None:
        # Nota e da empresa, nao do processo que a baixou: pelo processo sumiam
        # as notas baixadas antes da renovacao do certificado (vira outro id)
        # e as criadas sem processo pelo script de correcao.
        empresa_do_certificado = (
            db.query(Certificado.empresa_id).filter(Certificado.id == certificado_id).scalar_subquery()
        )
        query = query.filter(Nota.empresa_id == empresa_do_certificado)
    if processo_id is not None:
        query = query.filter(Nota.processo_id == processo_id)
    effective_status = status_documento or status
    if effective_status:
        query = query.filter(Nota.status_documento == effective_status)
    if numero:
        query = query.filter(Nota.numero_nfse == numero)
    if prestador_cnpj:
        query = query.filter(Nota.prestador_cnpj == prestador_cnpj)
    if tomador_cnpj:
        query = query.filter(Nota.tomador_cnpj == tomador_cnpj)
    if chave:
        query = query.filter(Nota.chave == chave)
    if busca:
        term = f"%{busca.strip()}%"
        query = query.filter(
            or_(
                Nota.chave.ilike(term),
                Nota.numero_nfse.ilike(term),
                Nota.prestador_nome.ilike(term),
                Nota.prestador_cnpj.ilike(term),
                Nota.tomador_nome.ilike(term),
                Nota.tomador_cnpj.ilike(term),
                Nota.incidencia_iss.ilike(term),
                Nota.municipio.ilike(term),
            )
        )
    if data_inicio is not None:
        query = query.filter(Nota.data_emissao >= data_inicio)
    if data_fim is not None:
        query = query.filter(Nota.data_emissao <= data_fim)
    if competencia_inicio is not None:
        query = query.filter(Nota.competencia >= competencia_inicio)
    if competencia_fim is not None:
        query = query.filter(Nota.competencia <= competencia_fim)
    if conferencia_status:
        query = query.filter(Nota.conferencia_status == conferencia_status)
    if prioridade:
        query = query.filter(Nota.prioridade == prioridade)
    if responsavel:
        query = query.filter(Nota.responsavel.ilike(f"%{responsavel.strip()}%"))
    if status_nota_pdf:
        query = query.filter(Nota.status_nota_pdf == status_nota_pdf)
    if simples_nacional_xml:
        query = query.filter(Nota.simples_nacional_xml == simples_nacional_xml)
    if consulta_simples_api:
        query = query.filter(Nota.consulta_simples_api == consulta_simples_api)
    if status_simples_nacional:
        query = query.filter(Nota.status_simples_nacional == status_simples_nacional)
    if incidencia_iss:
        term = _incidencia_search_term(incidencia_iss)
        if term:
            query = query.filter(Nota.incidencia_iss.ilike(f"%{term}%"))
    if divergencia:
        query = query.filter(Nota.divergencia == divergencia)
    if sla_status:
        query = query.filter(Nota.sla_status == sla_status)

    if count_only:
        return int(query.count())

    # 5.000 e o tamanho maximo de uma pagina, nao do resultado: quem precisa
    # de tudo percorre com notas_service.iterar_notas.
    safe_limit = min(max(limit, 1), 5000)
    safe_offset = max(offset, 0)
    sqlite = db.get_bind().dialect.name == "sqlite"
    chaves = chaves_ordem(sort, sqlite=sqlite)
    if cursor:
        # Com cursor a pagina comeca logo depois da ultima nota entregue; o offset nao vale.
        query = query.filter(tuple_(*chaves) < tuple_(*_valores_cursor(cursor, sort, sqlite)))
        safe_offset = 0
    query = query.order_by(*[chave.desc() for chave in chaves])

    return list(query.offset(safe_offset).limit(safe_limit).all())


def list_notas_by_ids(db: Session, nota_ids: list[int], somente_exportaveis: bool = False) -> list[Nota]:
    if not nota_ids:
        return []
    order = {nota_id: index for index, nota_id in enumerate(nota_ids)}
    query = db.query(Nota).filter(Nota.id.in_(nota_ids))
    if somente_exportaveis:
        query = _somente_exportaveis(query)
    notas = list(query.all())
    return sorted(notas, key=lambda nota: order.get(int(nota.id), len(order)))


def count_notas_grupo(db: Session, grupo: str | None = None, arquivadas: str = "ativas") -> int:
    """Conta o acervo sem materializar milhares de registros em memoria."""
    query = db.query(Nota.id)
    if arquivadas == "ativas":
        query = query.filter(Nota.arquivada.is_(False))
    elif arquivadas == "somente":
        query = query.filter(Nota.arquivada.is_(True))
    elif arquivadas != "todas":
        raise ValueError("Filtro de arquivadas invalido.")
    if grupo is not None:
        query = query.join(Empresa, Empresa.id == Nota.empresa_id).filter(Empresa.grupo == grupo)
    return int(query.count())


def create_nota(db: Session, data: dict) -> Nota:
    now = datetime.now(timezone.utc)
    data.setdefault("importado_em", now)
    data.setdefault("updated_at", now)
    nota = Nota(**data)
    db.add(nota)
    db.flush()
    db.refresh(nota)
    return nota


def update_nota(db: Session, nota: Nota, data: dict) -> Nota:
    now = datetime.now(timezone.utc)
    data = dict(data)
    importado_em_recebido = data.pop("importado_em", None)
    # A data de importacao define a ordem estavel do dashboard. Reprocessar a
    # janela de NSU nao transforma uma nota antiga em nota nova; alterar este
    # campo durante a paginacao faz o mesmo ID aparecer em offsets diferentes.
    if nota.importado_em is None:
        data["importado_em"] = importado_em_recebido or now
    requested_updated_at = data.pop("updated_at", None)
    changed = {
        key: value
        for key, value in data.items()
        if getattr(nota, key, None) != value
    }
    if not changed:
        return nota
    changed["updated_at"] = requested_updated_at or now
    for key, value in changed.items():
        setattr(nota, key, value)
    db.add(nota)
    db.flush()
    # Mantem a normalizacao de timezone do dialeto (especialmente SQLite) e
    # o contrato historico retornado aos chamadores apos uma alteracao real.
    db.refresh(nota)
    return nota


def upsert_nota_by_chave(db: Session, empresa_id: int, chave: str, data: dict) -> tuple[Nota, bool]:
    nota = get_nota_by_chave(db, empresa_id, chave)
    if nota is None:
        return create_nota(db, data), True
    data = dict(data)
    # O processo original representa quando a nota entrou no acervo. Troca-lo
    # a cada janela de reconciliacao gera UPDATEs e disputa de locks sem mudar
    # qualquer dado fiscal exibido no portal.
    data.pop("processo_id", None)
    # Uma nova leitura do XML pode atualizar os campos fiscais de origem, mas
    # nao pode desfazer a decisao de um usuario que ja conferiu/corrigiu a
    # nota. Quando a conferencia for reaberta como "pendente", o valor volta
    # a ser calculado automaticamente na proxima ingestao.
    conferencia_status = str(nota.conferencia_status or "").strip().lower()
    if conferencia_status and conferencia_status != "pendente":
        data.pop("valor_liquido_correto", None)
        data.pop("status_valor_liquido", None)
    return update_nota(db, nota, data), False
