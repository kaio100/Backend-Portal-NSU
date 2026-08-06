import hmac

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.security import TokenError, decode_access_token
from backend.app.db.models import Arquivo, Certificado, Empresa, Nota, Processo, Usuario
from backend.app.db.session import get_db
from backend.app.services.storage_service import get_storage_service


def get_storage():
    return get_storage_service()


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Exige o header X-API-Key quando API_KEY estiver configurada no ambiente.

    Sem API_KEY configurada (dev/local), a checagem fica desativada para nao
    quebrar o fluxo local/testes; em producao a variavel deve sempre ser definida.
    """
    expected = settings.api_key
    if not expected:
        return
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
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    usuario = db.get(Usuario, int(payload["sub"]))
    if usuario is None or not usuario.ativo:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario nao encontrado ou inativo.")
    return usuario


def require_admin(usuario: Usuario = Depends(get_current_usuario)) -> Usuario:
    if not usuario.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso exclusivo para administradores.")
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
