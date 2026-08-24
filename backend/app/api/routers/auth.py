from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.api.deps import get_current_usuario, get_db, require_admin, require_api_key
from backend.app.core.config import settings
from backend.app.core.rate_limit import RateLimiter
from backend.app.db.models import AcessoUsuario, Grupo, Usuario
from backend.app.schemas.auth import LoginRequest, LoginResponse, UsuarioRead
from backend.app.schemas.usuarios import UsuarioCreate
from backend.app.services import auth_service
from backend.app.services.auth_service import AuthError

router = APIRouter(prefix="/auth", tags=["auth"])

# Freio contra tentativas de login (forca bruta de senha): no maximo 8
# tentativas a cada 5 minutos, por IP + email.
_login_rate_limiter = RateLimiter(max_attempts=8, window_seconds=300)


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    client_host = request.client.host if request.client else "unknown"
    if not _login_rate_limiter.allow(f"{client_host}:{payload.email}"):
        raise HTTPException(
            status_code=429,
            detail="Muitas tentativas de login. Tente novamente em alguns minutos.",
        )

    try:
        usuario, token = auth_service.autenticar(db, payload.email, payload.senha)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    db.add(AcessoUsuario(
        usuario_id=usuario.id,
        grupo=usuario.grupo,
        ip=client_host,
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    ))
    db.commit()

    return LoginResponse(
        access_token=token,
        expires_in_minutes=settings.jwt_expire_minutes,
        usuario=usuario,
    )


@router.get("/me", response_model=UsuarioRead)
def me(usuario: Usuario = Depends(get_current_usuario)):
    return usuario


@router.get("/grupos")
def listar_grupos_admin(db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
    return [{"codigo": item.codigo, "nome": item.nome} for item in db.query(Grupo).filter(Grupo.ativo.is_(True)).order_by(Grupo.nome.asc()).all()]


@router.post("/usuarios", response_model=UsuarioRead, dependencies=[Depends(require_api_key)])
def criar_usuario(payload: UsuarioCreate, db: Session = Depends(get_db)):
    """Cadastro de usuarios do portal do cliente.

    Protegido por API key (uso interno da equipe), nao pelo login do proprio
    cliente: hoje nao existe autocadastro, quem cria as contas e a operacao.
    """
    try:
        return auth_service.criar_usuario(
            db,
            empresa_id=payload.empresa_id,
            email=payload.email,
            senha=payload.senha,
            nome=payload.nome,
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
