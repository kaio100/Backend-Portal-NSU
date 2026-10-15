from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
import unicodedata

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.api.deps import (
    PAPEIS_VALIDOS,
    auditar_admin,
    eh_super_admin,
    get_db,
    require_admin,
    require_admin_sessao,
    require_super_admin,
)
from backend.app.core.security import hash_password
from backend.app.core.tempo import agora_local, data_local, hoje_local, inicio_do_dia_utc
from backend.app.db.models import AcessoUsuario, Arquivo, AuditoriaAdmin, ErroVisto, ConferenciaHistorico, Empresa, Grupo, LogProcesso, MonitoramentoConfig, Nota, Processo, Usuario
from backend.app.db.session import SessionLocal
from backend.app.services import admin_seguranca_service, volumetria_service
from backend.app.services.notas_archive_service import arquivar_notas_anos_anteriores
from backend.app.services.storage_service import get_storage_service

# Alem do papel de admin, o painel exige a sessao aberta com senha + 2FA, e toda
# alteracao fica na auditoria (deps.require_admin_sessao e deps.auditar_admin).
router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin_sessao), Depends(auditar_admin)])


class UsuarioAdminUpdate(BaseModel):
    nome: str | None = Field(default=None, max_length=255)
    grupo: str | None = None
    ativo: bool | None = None
    is_admin: bool | None = None
    papel: str | None = None


class RedefinirSenha(BaseModel):
    senha: str = Field(min_length=8, max_length=128)


class GrupoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    codigo: str | None = Field(default=None, max_length=40)


class GrupoUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=120)
    ativo: bool | None = None


class ArquivamentoExecutar(BaseModel):
    ano: int = Field(default=2026, ge=2000, le=2100)
    confirmacao: str


_arquivamento_estado: dict = {"status": "ocioso", "iniciado_em": None, "finalizado_em": None, "resultado": None, "erro": None}


def _escopo(admin: Usuario) -> str | None:
    """Grupo que o admin administra; None para o admin geral (SUPER_ADMIN_EMAILS)."""
    return None if eh_super_admin(admin) else admin.grupo


def _usuario_no_escopo(db: Session, usuario_id: int, admin: Usuario) -> Usuario:
    usuario = db.get(Usuario, usuario_id)
    grupo = _escopo(admin)
    if usuario is None or (grupo is not None and usuario.grupo != grupo):
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")
    return usuario


def _executar_arquivamento_background(ano: int, grupo: str | None) -> None:
    _arquivamento_estado.update(status="executando", iniciado_em=agora_local().isoformat(), finalizado_em=None, resultado=None, erro=None)
    try:
        with SessionLocal() as db:
            resultado = arquivar_notas_anos_anteriores(db, get_storage_service(), ano_operacional=ano, executar=True, grupo=grupo)
        _arquivamento_estado.update(status="finalizado", resultado=resultado)
    except Exception as exc:
        _arquivamento_estado.update(status="erro", erro=str(exc))
    finally:
        _arquivamento_estado["finalizado_em"] = agora_local().isoformat()


def _slug_grupo(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", normalized)).strip("_")[:40]


def _usuario_dict(usuario: Usuario) -> dict:
    return {
        "id": usuario.id,
        "nome": usuario.nome,
        "email": usuario.email,
        "grupo": usuario.grupo,
        "ativo": usuario.ativo,
        "is_admin": usuario.is_admin,
        "papel": "admin" if usuario.is_admin else usuario.papel,
        "totp_ativo": bool(getattr(usuario, "totp_ativo", False)),
        "created_at": usuario.created_at,
    }


def _somente_nao_vistos(query, modelo, coluna_data):
    """Erros depois do ultimo "Limpar" do grupo da empresa (sem apagar nada)."""
    query = query.outerjoin(ErroVisto, ErroVisto.grupo == Empresa.grupo)
    return query.filter(or_(ErroVisto.visto_ate.is_(None), coluna_data > ErroVisto.visto_ate))


@router.get("/overview")
def overview(admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    grupo = _escopo(admin)
    # "Hoje" e o dia de Brasilia: com o container em UTC o contador zerava as 21h.
    inicio_hoje = inicio_do_dia_utc(hoje_local())

    def do_grupo(query, modelo):
        if grupo is None:
            return query
        if modelo is Usuario or modelo is AcessoUsuario:
            return query.filter(modelo.grupo == grupo)
        return query.join(Empresa, Empresa.id == modelo.empresa_id).filter(Empresa.grupo == grupo)

    usuarios_ativos_hoje = (
        do_grupo(db.query(func.count(func.distinct(AcessoUsuario.usuario_id))), AcessoUsuario)
        .filter(AcessoUsuario.created_at >= inicio_hoje)
        .scalar()
        or 0
    )
    return {
        "usuarios": do_grupo(db.query(Usuario), Usuario).count(),
        "usuarios_ativos": do_grupo(db.query(Usuario), Usuario).filter(Usuario.ativo.is_(True)).count(),
        "usuarios_ativos_hoje": int(usuarios_ativos_hoje),
        "acessos_hoje": do_grupo(db.query(AcessoUsuario), AcessoUsuario).filter(AcessoUsuario.created_at >= inicio_hoje).count(),
        "notas": do_grupo(db.query(Nota), Nota).count(),
        "arquivos": do_grupo(db.query(Arquivo), Arquivo).count(),
        "processos": do_grupo(db.query(Processo), Processo).count(),
        "processos_finalizados": do_grupo(db.query(Processo), Processo).filter(Processo.status == "finalizado").count(),
        "erros": _somente_nao_vistos(
            _query_processos_com_empresa(db, grupo), Processo, Processo.updated_at
        ).filter(or_(Processo.status == "erro", Processo.erro_resumo.isnot(None))).count(),
    }


@router.get("/acessos")
def acessos(dias: int = 14, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    dias = max(7, min(dias, 90))
    inicio = hoje_local() - timedelta(days=dias - 1)
    query = db.query(AcessoUsuario).filter(AcessoUsuario.created_at >= inicio_do_dia_utc(inicio))
    if _escopo(admin) is not None:
        query = query.filter(AcessoUsuario.grupo == _escopo(admin))
    eventos = query.all()
    por_dia = {inicio + timedelta(days=i): {"acessos": 0, "usuarios": set()} for i in range(dias)}
    for evento in eventos:
        dia = data_local(evento.created_at)
        if dia in por_dia:
            por_dia[dia]["acessos"] += 1
            por_dia[dia]["usuarios"].add(evento.usuario_id)
    return [
        {"data": dia.isoformat(), "acessos": item["acessos"], "usuarios": len(item["usuarios"])}
        for dia, item in por_dia.items()
    ]


@router.get("/usuarios")
def usuarios(admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    query = db.query(Usuario).order_by(Usuario.email.asc())
    if _escopo(admin) is not None:
        query = query.filter(Usuario.grupo == _escopo(admin))
    return [_usuario_dict(item) for item in query.all()]


@router.patch("/usuarios/{usuario_id}")
def atualizar_usuario(usuario_id: int, payload: UsuarioAdminUpdate, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    usuario = _usuario_no_escopo(db, usuario_id, admin)
    data = payload.model_dump(exclude_unset=True)
    if "grupo" in data and data["grupo"] != usuario.grupo and not eh_super_admin(admin):
        # Trocar de grupo e passar o usuario (ou a si mesmo) para os dados de
        # outra equipe: so o admin geral pode.
        raise HTTPException(status_code=403, detail="Somente o administrador geral move usuarios entre grupos.")
    if "papel" in data:
        data["papel"] = str(data["papel"] or "").strip().lower()
        if data["papel"] not in PAPEIS_VALIDOS:
            raise HTTPException(status_code=422, detail="Papel deve ser admin ou operador.")
        data["is_admin"] = data["papel"] == "admin"
    elif "is_admin" in data:
        data["papel"] = "admin" if data["is_admin"] else "operador"
    if "grupo" in data and db.query(Grupo).filter(Grupo.codigo == data["grupo"], Grupo.ativo.is_(True)).first() is None:
        raise HTTPException(status_code=422, detail="Grupo inexistente ou inativo.")
    if usuario.id == admin.id and data.get("ativo") is False:
        raise HTTPException(status_code=400, detail="Voce nao pode desativar sua propria conta.")
    if usuario.id == admin.id and data.get("is_admin") is False:
        raise HTTPException(status_code=400, detail="Voce nao pode remover sua propria permissao administrativa.")
    if usuario.id == admin.id and data.get("papel") not in (None, "admin"):
        raise HTTPException(status_code=400, detail="Voce nao pode rebaixar seu proprio papel administrativo.")
    for campo, valor in data.items():
        setattr(usuario, campo, valor)
    db.commit()
    db.refresh(usuario)
    return _usuario_dict(usuario)


@router.delete("/usuarios/{usuario_id}")
def excluir_usuario(usuario_id: int, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    usuario = _usuario_no_escopo(db, usuario_id, admin)
    if usuario.id == admin.id:
        raise HTTPException(status_code=400, detail="Voce nao pode excluir sua propria conta.")
    db.query(AcessoUsuario).filter(AcessoUsuario.usuario_id == usuario.id).delete(synchronize_session=False)
    # O historico da analise continua com o nome e o e-mail do autor.
    db.query(ConferenciaHistorico).filter(ConferenciaHistorico.usuario_id == usuario.id).update(
        {ConferenciaHistorico.usuario_id: None}, synchronize_session=False
    )
    db.delete(usuario)
    db.commit()
    return {"ok": True, "message": "Usuario excluido com sucesso."}


@router.get("/grupos")
def listar_grupos(admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    query = db.query(Grupo).order_by(Grupo.nome.asc())
    if _escopo(admin) is not None:
        query = query.filter(Grupo.codigo == _escopo(admin))
    grupos = query.all()
    return [{
        "id": grupo.id, "codigo": grupo.codigo, "nome": grupo.nome, "ativo": grupo.ativo,
        "usuarios": db.query(Usuario).filter(Usuario.grupo == grupo.codigo).count(),
        "empresas": db.query(Empresa).filter(Empresa.grupo == grupo.codigo).count(),
        "created_at": grupo.created_at,
    } for grupo in grupos]


@router.post("/grupos", status_code=201, dependencies=[Depends(require_super_admin)])
def criar_grupo(payload: GrupoCreate, db: Session = Depends(get_db)):
    codigo = _slug_grupo(payload.codigo or payload.nome)
    if len(codigo) < 2:
        raise HTTPException(status_code=422, detail="Informe um nome valido para o grupo.")
    if db.query(Grupo).filter(Grupo.codigo == codigo).first() is not None:
        raise HTTPException(status_code=409, detail="Ja existe um grupo com este codigo.")
    grupo = Grupo(codigo=codigo, nome=payload.nome.strip(), ativo=True)
    db.add(grupo)
    db.commit()
    db.refresh(grupo)
    return {"id": grupo.id, "codigo": grupo.codigo, "nome": grupo.nome, "ativo": grupo.ativo, "usuarios": 0, "empresas": 0, "created_at": grupo.created_at}


@router.patch("/grupos/{grupo_id}", dependencies=[Depends(require_super_admin)])
def editar_grupo(grupo_id: int, payload: GrupoUpdate, db: Session = Depends(get_db)):
    grupo = db.get(Grupo, grupo_id)
    if grupo is None:
        raise HTTPException(status_code=404, detail="Grupo nao encontrado.")
    data = payload.model_dump(exclude_unset=True)
    for campo, valor in data.items():
        setattr(grupo, campo, valor.strip() if isinstance(valor, str) else valor)
    db.commit()
    db.refresh(grupo)
    return {"id": grupo.id, "codigo": grupo.codigo, "nome": grupo.nome, "ativo": grupo.ativo}


@router.delete("/grupos/{grupo_id}", dependencies=[Depends(require_super_admin)])
def excluir_grupo(grupo_id: int, db: Session = Depends(get_db)):
    grupo = db.get(Grupo, grupo_id)
    if grupo is None:
        raise HTTPException(status_code=404, detail="Grupo nao encontrado.")
    usuarios = db.query(Usuario).filter(Usuario.grupo == grupo.codigo).count()
    empresas = db.query(Empresa).filter(Empresa.grupo == grupo.codigo).count()
    if usuarios or empresas:
        raise HTTPException(status_code=409, detail=f"O grupo possui {usuarios} usuario(s) e {empresas} empresa(s). Transfira esses dados antes de excluir.")
    db.query(MonitoramentoConfig).filter(MonitoramentoConfig.grupo == grupo.codigo).delete(synchronize_session=False)
    db.delete(grupo)
    db.commit()
    return {"ok": True, "message": "Grupo excluido com sucesso."}


@router.post("/usuarios/{usuario_id}/redefinir-senha")
def redefinir_senha(usuario_id: int, payload: RedefinirSenha, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    usuario = _usuario_no_escopo(db, usuario_id, admin)
    usuario.senha_hash = hash_password(payload.senha)
    # Derruba as sessoes abertas com a senha antiga.
    usuario.token_version = int(usuario.token_version or 0) + 1
    db.commit()
    return {"ok": True, "message": "Senha redefinida com sucesso."}


@router.get("/erros")
def erros(limit: int = 50, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    grupo = _escopo(admin)
    query_processos = _somente_nao_vistos(_query_processos_com_empresa(db, grupo), Processo, Processo.updated_at)
    query_logs = db.query(LogProcesso).outerjoin(Empresa, Empresa.id == LogProcesso.empresa_id)
    if grupo is not None:
        query_logs = query_logs.filter(Empresa.grupo == grupo)
    query_logs = _somente_nao_vistos(query_logs, LogProcesso, LogProcesso.created_at)
    processos = (
        query_processos
        .filter(or_(Processo.status == "erro", Processo.erro_resumo.isnot(None)))
        .order_by(Processo.updated_at.desc())
        .limit(limit)
        .all()
    )
    items = [{
        "id": f"processo-{p.id}", "origem": "Processo", "processo_id": p.id,
        "empresa_id": p.empresa_id, "mensagem": p.erro_resumo or "Processo finalizado com erro.",
        "created_at": p.updated_at or p.created_at,
    } for p in processos]
    if len(items) < limit:
        logs = (
            query_logs
            .filter(func.lower(LogProcesso.level).in_(["error", "erro", "critical"]))
            .order_by(LogProcesso.created_at.desc())
            .limit(limit - len(items))
            .all()
        )
        items.extend({
            "id": f"log-{log.id}", "origem": "Log", "processo_id": log.processo_id,
            "empresa_id": log.empresa_id, "mensagem": log.mensagem, "created_at": log.created_at,
        } for log in logs)
    return sorted(items, key=lambda item: item["created_at"] or datetime.min, reverse=True)[:limit]


def _query_processos_com_empresa(db: Session, grupo: str | None):
    query = db.query(Processo).join(Empresa, Empresa.id == Processo.empresa_id)
    return query.filter(Empresa.grupo == grupo) if grupo is not None else query


@router.post("/erros/limpar")
def limpar_erros(admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    """Marca os erros ate agora como vistos (do grupo do admin; de todos, para o admin geral).
    Processos e logs continuam no banco; a acao fica na auditoria."""
    grupo = _escopo(admin)
    grupos = [grupo] if grupo is not None else [g.codigo for g in db.query(Grupo).all()]
    agora = datetime.now(timezone.utc)
    for codigo in grupos:
        visto = db.get(ErroVisto, codigo)
        if visto is None:
            db.add(ErroVisto(grupo=codigo, visto_ate=agora, usuario_id=admin.id))
        else:
            visto.visto_ate = agora
            visto.usuario_id = admin.id
    db.commit()
    return {"ok": True, "visto_ate": agora.isoformat(), "grupos": grupos}


@router.get("/volumetria")
def volumetria(dias: int = 30, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    """Notas, valores, consultas ao ADN e certificados agregados para os graficos do painel."""
    return volumetria_service.calcular(db, _escopo(admin), dias)


@router.get("/arquivamento")
def status_arquivamento(ano: int = 2026, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    grupo = _escopo(admin)
    preview = arquivar_notas_anos_anteriores(db, get_storage_service(), ano_operacional=ano, executar=False, grupo=grupo)
    query_backups = db.query(Arquivo)
    if grupo is not None:
        query_backups = query_backups.join(Empresa, Empresa.id == Arquivo.empresa_id).filter(Empresa.grupo == grupo)
    backups = (
        query_backups
        .filter(Arquivo.tipo.in_(["BACKUP_NOTAS", "MANIFESTO_NOTAS_EXCLUIDAS"]))
        .order_by(Arquivo.created_at.desc())
        .limit(100)
        .all()
    )
    return {
        "ano_operacional": ano,
        "notas_elegiveis": preview["notas"],
        "empresas": preview["empresas"],
        "notas_arquivadas": 0,
        "execucao": dict(_arquivamento_estado),
        "backups": [
            {
                "id": item.id,
                "empresa_id": item.empresa_id,
                "filename": item.filename,
                "tamanho_bytes": item.tamanho_bytes,
                "checksum": item.checksum,
                "created_at": item.created_at,
            }
            for item in backups
        ],
    }


@router.post("/arquivamento", status_code=202)
def executar_arquivamento(payload: ArquivamentoExecutar, background_tasks: BackgroundTasks, admin: Usuario = Depends(require_admin)):
    confirmacao = f"EXCLUIR ANTERIORES A {payload.ano}"
    if payload.confirmacao.strip().upper() != confirmacao:
        raise HTTPException(status_code=422, detail=f'Digite "{confirmacao}" para confirmar.')
    if _arquivamento_estado["status"] == "executando":
        raise HTTPException(status_code=409, detail="Ja existe um arquivamento em execucao.")
    _arquivamento_estado.update(status="agendado", iniciado_em=None, finalizado_em=None, resultado=None, erro=None)
    # Cada admin arquiva so as empresas do proprio grupo.
    background_tasks.add_task(_executar_arquivamento_background, payload.ano, _escopo(admin))
    return {"status": "agendado", "ano_operacional": payload.ano}


@router.get("/auditoria")
def auditoria(limit: int = 100, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    """Ultimas acoes no painel e tentativas de abrir a sessao de admin."""
    query = db.query(AuditoriaAdmin)
    grupo = _escopo(admin)
    if grupo is not None:
        query = query.filter(AuditoriaAdmin.grupo == grupo)
    itens = query.order_by(AuditoriaAdmin.id.desc()).limit(max(1, min(limit, 500))).all()
    return [
        {
            "id": item.id,
            "email": item.email,
            "grupo": item.grupo,
            "acao": item.acao,
            "resultado": item.resultado,
            "detalhes": item.detalhes,
            "ip": item.ip,
            "created_at": item.created_at,
        }
        for item in itens
    ]


@router.post("/usuarios/{usuario_id}/2fa/reset", dependencies=[Depends(require_super_admin)])
def resetar_2fa_usuario(usuario_id: int, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin geral: zera o 2FA de quem perdeu o celular; a pessoa configura de novo."""
    usuario = _usuario_no_escopo(db, usuario_id, admin)
    admin_seguranca_service.resetar_2fa(db, usuario)
    return {"ok": True, "message": "Verificacao em duas etapas zerada. A pessoa precisa configurar de novo."}
