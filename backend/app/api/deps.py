import hmac

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.rede import ip_cliente
from backend.app.core.security import TokenError, decode_access_token, decode_admin_token
from backend.app.db.models import Arquivo, Certificado, Empresa, Grupo, Nota, Processo, Usuario
from backend.app.db.session import get_db
from backend.app.services.storage_service import get_storage_service

PAPEL_ADMIN = "admin"
PAPEL_OPERADOR = "operador"
# Decisao de 2026-09-25: so existem os papeis operador e admin.
PAPEIS_VALIDOS = frozenset({PAPEL_ADMIN, PAPEL_OPERADOR})


def get_storage():
    return get_storage_service()


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Exige X-API-Key e nunca libera a rota por falha de configuracao."""
    expected = settings.api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Endpoint interno indisponivel.",
        )
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key ausente ou invalida.",
        )


_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_usuario(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nao autenticado.")
    try:
        payload = decode_access_token(credentials.credentials)
        usuario_id = int(payload["sub"])
        if payload.get("escopo"):
            # Token do painel admin (X-Admin-Token) nao serve como token do portal.
            raise TokenError("Token com escopo restrito.")
    except (TokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido ou expirado.") from exc

    usuario = db.get(Usuario, usuario_id)
    if usuario is None or not usuario.ativo or not getattr(usuario, "email_verificado", True):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario nao encontrado ou inativo.")
    if int(payload.get("ver") or 0) != int(getattr(usuario, "token_version", 0) or 0):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao encerrada. Entre novamente.")
    grupo = db.query(Grupo).filter(Grupo.codigo == usuario.grupo).first()
    if grupo is not None and not grupo.ativo:
        # Desativar o grupo no admin nao bloqueava ninguem.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Grupo desativado.")
    return usuario


def eh_super_admin(usuario: Usuario) -> bool:
    """Admin listado em SUPER_ADMIN_EMAILS: administra todos os grupos."""
    email = str(getattr(usuario, "email", "") or "").strip().lower()
    return _eh_admin(usuario) and email in settings.super_admin_email_set


def _eh_admin(usuario: Usuario) -> bool:
    return bool(getattr(usuario, "is_admin", False)) or getattr(usuario, "papel", PAPEL_OPERADOR) == PAPEL_ADMIN


def require_admin(usuario: Usuario = Depends(get_current_usuario)) -> Usuario:
    if not _eh_admin(usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso exclusivo para administradores.")
    return usuario


# Resposta 403 com este texto: o frontend pede senha + codigo de 2FA e tenta de novo.
ADMIN_SESSAO_NECESSARIA = "admin_sessao_necessaria"


def require_admin_sessao(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    usuario: Usuario = Depends(require_admin),
) -> Usuario:
    """Painel administrativo: alem de ser admin, exige a sessao curta aberta com
    senha + 2FA (POST /auth/admin/sessao). ADMIN_2FA_OBRIGATORIO=false desliga."""
    if not settings.admin_2fa_obrigatorio:
        return usuario
    if not x_admin_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_SESSAO_NECESSARIA)
    try:
        payload = decode_admin_token(x_admin_token)
        mesmo_usuario = int(payload["sub"]) == int(usuario.id)
        mesma_versao = int(payload.get("ver") or 0) == int(getattr(usuario, "token_version", 0) or 0)
    except (TokenError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_SESSAO_NECESSARIA) from exc
    if not mesmo_usuario or not mesma_versao:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=ADMIN_SESSAO_NECESSARIA)
    return usuario


def auditar_admin(request: Request, usuario: Usuario = Depends(require_admin)):
    """Registra cada alteracao feita pelo painel administrativo (POST/PATCH/DELETE)."""
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        yield
        return
    from backend.app.services.admin_seguranca_service import registrar

    rota = getattr(request.scope.get("route"), "path", request.url.path)
    resultado = "ok"
    try:
        yield
    except HTTPException as exc:
        resultado = f"erro {exc.status_code}"
        raise
    except Exception:
        resultado = "erro 500"
        raise
    finally:
        registrar(usuario, f"{request.method} {rota}", resultado, ip_cliente(request), dict(request.path_params) or None)


def require_super_admin(usuario: Usuario = Depends(require_admin)) -> Usuario:
    if not eh_super_admin(usuario):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso exclusivo para o administrador geral.")
    return usuario


def require_operator(usuario: Usuario = Depends(get_current_usuario)) -> Usuario:
    papel = PAPEL_ADMIN if _eh_admin(usuario) else getattr(usuario, "papel", PAPEL_OPERADOR)
    if papel not in PAPEIS_VALIDOS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso exclusivo para operadores.")
    return usuario


def require_empresa_grupo(db: Session, empresa_id: int, usuario: Usuario) -> Empresa:
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id, Empresa.grupo == usuario.grupo).first()
    if empresa is None:
        raise HTTPException(status_code=404, detail="Recurso nao encontrado.")
    return empresa


def require_nota_grupo(db: Session, nota_id: int, usuario: Usuario) -> Nota:
    nota = db.query(Nota).join(Empresa, Empresa.id == Nota.empresa_id).filter(Nota.id == nota_id, Empresa.grupo == usuario.grupo).first()
    if nota is None:
        raise HTTPException(status_code=404, detail="Recurso nao encontrado.")
    return nota


def require_processo_grupo(db: Session, processo_id: int, usuario: Usuario) -> Processo:
    processo = db.query(Processo).join(Empresa, Empresa.id == Processo.empresa_id).filter(Processo.id == processo_id, Empresa.grupo == usuario.grupo).first()
    if processo is None:
        raise HTTPException(status_code=404, detail="Recurso nao encontrado.")
    return processo


def require_arquivo_grupo(db: Session, arquivo_id: int, usuario: Usuario) -> Arquivo:
    arquivo = db.query(Arquivo).join(Empresa, Empresa.id == Arquivo.empresa_id).filter(Arquivo.id == arquivo_id, Empresa.grupo == usuario.grupo).first()
    if arquivo is None:
        raise HTTPException(status_code=404, detail="Recurso nao encontrado.")
    return arquivo


def require_certificado_grupo(db: Session, certificado_id: int, usuario: Usuario) -> Certificado:
    certificado = db.query(Certificado).join(Empresa, Empresa.id == Certificado.empresa_id).filter(Certificado.id == certificado_id, Empresa.grupo == usuario.grupo).first()
    if certificado is None:
        raise HTTPException(status_code=404, detail="Recurso nao encontrado.")
    return certificado
