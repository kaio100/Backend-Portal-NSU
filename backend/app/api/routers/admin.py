from __future__ import annotations

from datetime import date, datetime, time, timedelta
import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db, require_admin
from backend.app.core.security import hash_password
from backend.app.db.models import AcessoUsuario, Arquivo, Empresa, Grupo, LogProcesso, MonitoramentoConfig, Nota, Processo, Usuario

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class UsuarioAdminUpdate(BaseModel):
    nome: str | None = Field(default=None, max_length=255)
    grupo: str | None = None
    ativo: bool | None = None
    is_admin: bool | None = None


class RedefinirSenha(BaseModel):
    senha: str = Field(min_length=8, max_length=128)


class GrupoCreate(BaseModel):
    nome: str = Field(min_length=2, max_length=120)
    codigo: str | None = Field(default=None, max_length=40)


class GrupoUpdate(BaseModel):
    nome: str | None = Field(default=None, min_length=2, max_length=120)
    ativo: bool | None = None


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
    if "grupo" in data and db.query(Grupo).filter(Grupo.codigo == data["grupo"], Grupo.ativo.is_(True)).first() is None:
        raise HTTPException(status_code=422, detail="Grupo inexistente ou inativo.")
    if usuario.id == admin.id and data.get("ativo") is False:
        raise HTTPException(status_code=400, detail="Voce nao pode desativar sua propria conta.")
    if usuario.id == admin.id and data.get("is_admin") is False:
        raise HTTPException(status_code=400, detail="Voce nao pode remover sua propria permissao administrativa.")
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
