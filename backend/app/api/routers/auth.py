from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.api.deps import _eh_admin, get_current_usuario, get_db, require_admin, require_api_key, require_operator
from backend.app.core.config import settings
from backend.app.core.rate_limit import RateLimiter
from backend.app.core.rede import ip_cliente
from backend.app.core.security import verify_password
from backend.app.db.models import AcessoUsuario, Empresa, Grupo, Usuario
from backend.app.schemas.auth import (
    ConviteCreate,
    CriarContaRequest,
    EmailRequest,
    LoginRequest,
    LoginResponse,
    MensagemResponse,
    RedefinirSenhaRequest,
    TrocarSenhaRequest,
    UsuarioRead,
    VerificarEmailRequest,
)
from backend.app.schemas.usuarios import UsuarioCreate
from backend.app.services import auth_service, contas_service
from backend.app.services.auth_service import AuthError
from backend.app.services.contas_service import ContaError

router = APIRouter(prefix="/auth", tags=["auth"])

# Freios contra tentativa e erro, por IP real (atras do proxy) + e-mail.
_login_rate_limiter = RateLimiter(max_attempts=8, window_seconds=300)
_codigo_rate_limiter = RateLimiter(max_attempts=10, window_seconds=900)
_envio_rate_limiter = RateLimiter(max_attempts=3, window_seconds=900)
_cadastro_rate_limiter = RateLimiter(max_attempts=10, window_seconds=3600)

_MENSAGEM_CODIGO_ENVIADO = "Se o e-mail estiver cadastrado, enviamos um codigo. Ele vale por poucos minutos."


def _limitar(limitador: RateLimiter, chave: str) -> None:
    if not limitador.allow(chave):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Tente novamente em alguns minutos.")


def _erro_conta(exc: ContaError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    ip = ip_cliente(request)
    _limitar(_login_rate_limiter, f"{ip}:{payload.email}")
    try:
        usuario, token = auth_service.autenticar(db, payload.email, payload.senha)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    db.add(AcessoUsuario(
        usuario_id=usuario.id,
        grupo=usuario.grupo,
        ip=ip,
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    ))
    db.commit()
    return LoginResponse(access_token=token, expires_in_minutes=settings.jwt_expire_minutes, usuario=usuario)


@router.get("/me", response_model=UsuarioRead)
def me(usuario: Usuario = Depends(get_current_usuario)):
    return usuario


@router.post("/trocar-senha", response_model=MensagemResponse)
def trocar_senha(payload: TrocarSenhaRequest, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
    if not verify_password(payload.senha_atual, usuario.senha_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta.")
    contas_service.trocar_senha(db, usuario, payload.nova_senha)
    return MensagemResponse(mensagem="Senha alterada. Entre novamente com a senha nova.")


# ------------------------------------------------------------- convites


@router.post("/convites", status_code=201, dependencies=[Depends(require_operator)])
def criar_convite(payload: ConviteCreate, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
    """Link para uma pessoa criar a conta no grupo de quem convidou, como operador."""
    return contas_service.criar_convite(db, usuario, payload.nome, payload.validade_dias, payload.max_usos)


@router.get("/convites", dependencies=[Depends(require_operator)])
def listar_convites(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
    return contas_service.listar_convites(db, usuario.grupo)


@router.delete("/convites/{convite_id}", dependencies=[Depends(require_operator)])
def revogar_convite(convite_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
    try:
        return contas_service.revogar_convite(db, convite_id, usuario, admin=_eh_admin(usuario))
    except ContaError as exc:
        raise _erro_conta(exc) from exc


@router.get("/convite/{token}")
def ver_convite(token: str, request: Request, db: Session = Depends(get_db)):
    """Publico: a tela de cadastro confere se o link ainda vale."""
    _limitar(_cadastro_rate_limiter, f"convite:{ip_cliente(request)}")
    try:
        return contas_service.info_convite(db, token)
    except ContaError as exc:
        raise _erro_conta(exc) from exc


# ------------------------------------------------------------- cadastro


@router.post("/criar-conta", response_model=MensagemResponse, status_code=202)
def criar_conta(payload: CriarContaRequest, request: Request, db: Session = Depends(get_db)):
    """Publico, mas so com convite valido. A conta fica pendente ate o codigo."""
    _limitar(_cadastro_rate_limiter, f"cadastro:{ip_cliente(request)}")
    try:
        contas_service.criar_conta(db, payload.convite, payload.nome, payload.email, payload.senha)
    except ContaError as exc:
        raise _erro_conta(exc) from exc
    return MensagemResponse(mensagem="Enviamos um codigo para o seu e-mail. Digite-o para ativar a conta.")


@router.post("/verificar-email", response_model=LoginResponse)
def verificar_email(payload: VerificarEmailRequest, request: Request, db: Session = Depends(get_db)):
    ip = ip_cliente(request)
    _limitar(_codigo_rate_limiter, f"verificar:{ip}:{payload.email}")
    try:
        usuario, token = contas_service.verificar_email(
            db, payload.email, payload.codigo, ip, (request.headers.get("user-agent") or "")[:512] or None
        )
    except ContaError as exc:
        raise _erro_conta(exc) from exc
    return LoginResponse(access_token=token, expires_in_minutes=settings.jwt_expire_minutes, usuario=usuario)


@router.post("/reenviar-codigo", response_model=MensagemResponse)
def reenviar_codigo(payload: EmailRequest, request: Request, db: Session = Depends(get_db)):
    _limitar(_envio_rate_limiter, f"reenviar:{ip_cliente(request)}:{payload.email}")
    try:
        contas_service.reenviar_codigo(db, payload.email)
    except ContaError as exc:
        raise _erro_conta(exc) from exc
    return MensagemResponse(mensagem=_MENSAGEM_CODIGO_ENVIADO)


# ------------------------------------------------------------- senha


@router.post("/recuperar-senha", response_model=MensagemResponse)
def recuperar_senha(payload: EmailRequest, request: Request, db: Session = Depends(get_db)):
    ip = ip_cliente(request)
    _limitar(_envio_rate_limiter, f"senha:{ip}:{payload.email}")
    try:
        contas_service.solicitar_redefinicao(db, payload.email, ip)
    except ContaError as exc:
        raise _erro_conta(exc) from exc
    return MensagemResponse(mensagem=_MENSAGEM_CODIGO_ENVIADO)


@router.post("/redefinir-senha", response_model=MensagemResponse)
def redefinir_senha(payload: RedefinirSenhaRequest, request: Request, db: Session = Depends(get_db)):
    _limitar(_codigo_rate_limiter, f"redefinir:{ip_cliente(request)}:{payload.email}")
    try:
        contas_service.redefinir_senha(db, payload.email, payload.codigo, payload.nova_senha)
    except ContaError as exc:
        raise _erro_conta(exc) from exc
    return MensagemResponse(mensagem="Senha redefinida. Entre com a senha nova.")


# ------------------------------------------------------------- administracao


@router.get("/grupos")
def listar_grupos_admin(db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
    return [{"codigo": item.codigo, "nome": item.nome} for item in db.query(Grupo).filter(Grupo.ativo.is_(True)).order_by(Grupo.nome.asc()).all()]


@router.post("/usuarios", response_model=UsuarioRead, dependencies=[Depends(require_api_key)])
def criar_usuario(payload: UsuarioCreate, db: Session = Depends(get_db)):
    """Criacao interna de usuario (API key), no grupo da empresa informada."""
    empresa = db.get(Empresa, payload.empresa_id)
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa nao encontrada.")
    try:
        return auth_service.criar_usuario(
            db,
            empresa_id=payload.empresa_id,
            email=payload.email,
            senha=payload.senha,
            nome=payload.nome,
            # Antes caia sempre em planning_hub, fosse qual fosse a empresa.
            grupo=empresa.grupo,
        )
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
