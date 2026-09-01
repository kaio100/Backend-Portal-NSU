from __future__ import annotations

from datetime import date, datetime, time, timedelta
import re
import unicodedata

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.api.deps import PAPEIS_VALIDOS, get_db, require_admin
from backend.app.core.security import hash_password
from backend.app.db.models import AcessoUsuario, Arquivo, Empresa, Grupo, LogProcesso, MonitoramentoConfig, Nota, Processo, Usuario
from backend.app.db.session import SessionLocal
from backend.app.services.notas_archive_service import arquivar_notas_anos_anteriores
from backend.app.services.storage_service import get_storage_service

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


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


def _executar_arquivamento_background(ano: int) -> None:
    _arquivamento_estado.update(status="executando", iniciado_em=datetime.now().isoformat(), finalizado_em=None, resultado=None, erro=None)
    try:
        with SessionLocal() as db:
            resultado = arquivar_notas_anos_anteriores(db, get_storage_service(), ano_operacional=ano, executar=True)
        _arquivamento_estado.update(status="finalizado", resultado=resultado)
    except Exception as exc:
        _arquivamento_estado.update(status="erro", erro=str(exc))
    finally:
        _arquivamento_estado["finalizado_em"] = datetime.now().isoformat()


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
        "created_at": usuario.created_at,
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    hoje = date.today()
    inicio_hoje = datetime.combine(hoje, time.min)
    acessos_hoje = db.query(AcessoUsuario).filter(AcessoUsuario.created_at >= inicio_hoje).count()
    usuarios_ativos_hoje = (
        db.query(func.count(func.distinct(AcessoUsuario.usuario_id)))
        .filter(AcessoUsuario.created_at >= inicio_hoje)
        .scalar()
        or 0
    )
    return {
        "usuarios": db.query(Usuario).count(),
        "usuarios_ativos": db.query(Usuario).filter(Usuario.ativo.is_(True)).count(),
        "usuarios_ativos_hoje": int(usuarios_ativos_hoje),
        "acessos_hoje": acessos_hoje,
        "notas": db.query(Nota).count(),
        "arquivos": db.query(Arquivo).count(),
        "processos": db.query(Processo).count(),
        "processos_finalizados": db.query(Processo).filter(Processo.status == "finalizado").count(),
        "erros": db.query(Processo).filter(or_(Processo.status == "erro", Processo.erro_resumo.isnot(None))).count(),
    }


@router.get("/acessos")
def acessos(dias: int = 14, db: Session = Depends(get_db)):
    dias = max(7, min(dias, 90))
    inicio = date.today() - timedelta(days=dias - 1)
    eventos = db.query(AcessoUsuario).filter(AcessoUsuario.created_at >= datetime.combine(inicio, time.min)).all()
    por_dia = {inicio + timedelta(days=i): {"acessos": 0, "usuarios": set()} for i in range(dias)}
    for evento in eventos:
        dia = evento.created_at.date()
        if dia in por_dia:
            por_dia[dia]["acessos"] += 1
            por_dia[dia]["usuarios"].add(evento.usuario_id)
    return [
        {"data": dia.isoformat(), "acessos": item["acessos"], "usuarios": len(item["usuarios"])}
        for dia, item in por_dia.items()
    ]


@router.get("/usuarios")
def usuarios(db: Session = Depends(get_db)):
    return [_usuario_dict(item) for item in db.query(Usuario).order_by(Usuario.email.asc()).all()]


@router.patch("/usuarios/{usuario_id}")
def atualizar_usuario(usuario_id: int, payload: UsuarioAdminUpdate, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")
    data = payload.model_dump(exclude_unset=True)
    if "papel" in data:
        data["papel"] = str(data["papel"] or "").strip().lower()
        if data["papel"] not in PAPEIS_VALIDOS:
            raise HTTPException(status_code=422, detail="Papel deve ser admin, operador ou leitura.")
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
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")
    if usuario.id == admin.id:
        raise HTTPException(status_code=400, detail="Voce nao pode excluir sua propria conta.")
    db.query(AcessoUsuario).filter(AcessoUsuario.usuario_id == usuario.id).delete(synchronize_session=False)
    db.delete(usuario)
    db.commit()
    return {"ok": True, "message": "Usuario excluido com sucesso."}


@router.get("/grupos")
def listar_grupos(db: Session = Depends(get_db)):
    grupos = db.query(Grupo).order_by(Grupo.nome.asc()).all()
    return [{
        "id": grupo.id, "codigo": grupo.codigo, "nome": grupo.nome, "ativo": grupo.ativo,
        "usuarios": db.query(Usuario).filter(Usuario.grupo == grupo.codigo).count(),
        "empresas": db.query(Empresa).filter(Empresa.grupo == grupo.codigo).count(),
        "created_at": grupo.created_at,
    } for grupo in grupos]


@router.post("/grupos", status_code=201)
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


@router.patch("/grupos/{grupo_id}")
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


@router.delete("/grupos/{grupo_id}")
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
def redefinir_senha(usuario_id: int, payload: RedefinirSenha, db: Session = Depends(get_db)):
    usuario = db.get(Usuario, usuario_id)
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado.")
    usuario.senha_hash = hash_password(payload.senha)
    db.commit()
    return {"ok": True, "message": "Senha redefinida com sucesso."}


@router.get("/erros")
def erros(limit: int = 50, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 200))
    processos = (
        db.query(Processo)
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
            db.query(LogProcesso)
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


@router.get("/arquivamento")
def status_arquivamento(ano: int = 2026, db: Session = Depends(get_db)):
    preview = arquivar_notas_anos_anteriores(db, get_storage_service(), ano_operacional=ano, executar=False)
    arquivadas = db.query(Nota).filter(Nota.arquivada.is_(True)).count()
    backups = (
        db.query(Arquivo)
        .filter(Arquivo.tipo == "BACKUP_NOTAS")
        .order_by(Arquivo.created_at.desc())
        .limit(100)
        .all()
    )
    return {
        "ano_operacional": ano,
        "notas_elegiveis": preview["notas"],
        "empresas": preview["empresas"],
        "notas_arquivadas": arquivadas,
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
def executar_arquivamento(payload: ArquivamentoExecutar, background_tasks: BackgroundTasks):
    if payload.confirmacao.strip().upper() != f"ARQUIVAR {payload.ano}":
        raise HTTPException(status_code=422, detail=f'Digite "ARQUIVAR {payload.ano}" para confirmar.')
    if _arquivamento_estado["status"] == "executando":
        raise HTTPException(status_code=409, detail="Ja existe um arquivamento em execucao.")
    _arquivamento_estado.update(status="agendado", iniciado_em=None, finalizado_em=None, resultado=None, erro=None)
    background_tasks.add_task(_executar_arquivamento_background, payload.ano)
    return {"status": "agendado", "ano_operacional": payload.ano}
