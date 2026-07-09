from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.app.api.deps import get_db, get_storage
from backend.app.db.models import Certificado
from backend.app.schemas.certificados import (
    CertificadoAutocadastroResponse,
    CertificadoRead,
    CertificadoTestRequest,
    CertificadoTestResult,
)
from backend.app.schemas.secrets import SecretSetRequest, SecretStatusResponse
from backend.app.services import certificados_service
from backend.app.services.certificados_service import CertificadoServiceError
from backend.app.services.storage_service import StorageService


router = APIRouter(prefix="/certificados", tags=["certificados"])
empresa_router = APIRouter(prefix="/empresas/{empresa_id}/certificados", tags=["certificados"])


def _handle_error(exc: CertificadoServiceError) -> None:
    message = str(exc)
    status_code = 404 if "nao encontrad" in message else 400
    raise HTTPException(status_code=status_code, detail=message)


def _form_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "sim", "yes", "on"}


def _form_int(value: object) -> int | None:
    try:
        return int(str(value).strip()) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _validar_nsu_inicio(value: int | None) -> int | None:
    if value is not None and value < 0:
        raise HTTPException(status_code=422, detail="nsu_inicio nao pode ser negativo.")
    return value


def _first_form_value(form, *names: str) -> str | None:
    for name in names:
        value = form.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _first_upload_file(form, *names: str) -> UploadFile | None:
    for name in names:
        value = form.get(name)
        if isinstance(value, (UploadFile, StarletteUploadFile)):
            return value
    for value in form.values():
        if isinstance(value, (UploadFile, StarletteUploadFile)):
            return value
    return None


def _resolve_certificado_ref(db: Session, certificado_ref: str) -> Certificado:
    ref = str(certificado_ref or "").strip()
    certificado = None
    if ref.isdigit():
        certificado = db.get(Certificado, int(ref))
    if certificado is None and ref:
        certificado = (
            db.query(Certificado)
            .filter(func.lower(Certificado.nome) == ref.lower())
            .order_by(Certificado.id.desc())
            .first()
        )
    if certificado is None:
        raise HTTPException(status_code=404, detail="Certificado nao encontrado.")
    return certificado


@router.post("")
async def create_certificado_compat(
    request: Request,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    """Compatibilidade com o portal antigo: POST /certificados com alias/password/file."""
    form = await request.form()
    arquivo = _first_upload_file(form, "arquivo", "arquivo_pfx", "file", "pfx", "certificado")
    senha = _first_form_value(form, "senha", "password", "senha_teste")
    if arquivo is None:
        raise HTTPException(status_code=400, detail="Arquivo PFX/P12 e obrigatorio.")
    if not senha:
        raise HTTPException(status_code=400, detail="Senha do certificado e obrigatoria.")

    ambiente = _first_form_value(form, "ambiente") or "producao"
    limite = _form_int(form.get("limite"))
    nsu_inicio = _validar_nsu_inicio(
        _form_int(_first_form_value(form, "nsu_inicio", "nsu_recomendado", "nsu_recomendado_usuario", "recommended_nsu"))
    )
    forcar = _form_bool(form.get("forcar"), default=False)
    auto_iniciar = _form_bool(form.get("auto_iniciar"), default=True)
    alias = _first_form_value(form, "alias", "nome", "client_name")
    client_name = _first_form_value(form, "client_name")

    try:
        pfx_bytes = await arquivo.read()
        result = certificados_service.autocadastrar_certificado(
            db=db,
            storage=storage,
            filename=arquivo.filename or alias or "certificado.pfx",
            pfx_bytes=pfx_bytes,
            senha=senha,
            ambiente=ambiente,
            auto_iniciar=auto_iniciar,
            limite=limite,
            nsu_inicio=nsu_inicio,
            forcar=forcar,
        )
        certificado = result["certificado"]
        empresa = result["empresa"]
        changed = False
        if alias and alias.strip():
            certificado.nome = alias.strip()
            changed = True
        if client_name and client_name.strip():
            empresa.nome = client_name.strip()
            changed = True
        if changed:
            db.add(empresa)
            db.add(certificado)
            db.commit()
            db.refresh(empresa)
            db.refresh(certificado)
        return {
            "ok": True,
            "success": True,
            "empresa": empresa,
            "certificado": certificado,
            "processo": result.get("processo"),
            "consulta_status": result.get("consulta_status"),
            "id": certificado.id,
            "alias": certificado.nome,
            "client_name": empresa.nome,
            "file_name": certificado.file_name,
            "status": certificado.status,
            "nome": certificado.nome,
            "empresa_id": empresa.id,
        }
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.post("/upload", response_model=CertificadoRead)
async def upload_certificado(
    empresa_id: int | None = Form(default=None),
    nome: str | None = Form(default=None),
    arquivo_pfx: UploadFile = File(...),
    senha_teste: str | None = Form(default=None),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        pfx_bytes = await arquivo_pfx.read()
        if empresa_id is None:
            if not senha_teste:
                raise CertificadoServiceError("Senha do certificado e obrigatoria para identificar a empresa automaticamente.")
            result = certificados_service.autocadastrar_certificado(
                db=db,
                storage=storage,
                filename=arquivo_pfx.filename or "",
                pfx_bytes=pfx_bytes,
                senha=senha_teste,
                auto_iniciar=False,
            )
            return result["certificado"]
        return certificados_service.criar_certificado_com_upload(
            db=db,
            storage=storage,
            empresa_id=empresa_id,
            nome=nome or "",
            filename=arquivo_pfx.filename or "",
            pfx_bytes=pfx_bytes,
            senha_teste=senha_teste,
        )
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.post("/autocadastrar", response_model=CertificadoAutocadastroResponse)
async def autocadastrar_certificado(
    arquivo: UploadFile = File(...),
    senha: str = Form(...),
    ambiente: str = Form(default="producao"),
    auto_iniciar: bool = Form(default=True),
    limite: int | None = Form(default=None),
    nsu_inicio: int | None = Form(default=None),
    nsu_recomendado: int | None = Form(default=None),
    nsu_recomendado_usuario: int | None = Form(default=None),
    recommended_nsu: int | None = Form(default=None),
    forcar: bool = Form(default=False),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        pfx_bytes = await arquivo.read()
        nsu_inicial = _validar_nsu_inicio(
            nsu_inicio
            if nsu_inicio is not None
            else nsu_recomendado
            if nsu_recomendado is not None
            else nsu_recomendado_usuario
            if nsu_recomendado_usuario is not None
            else recommended_nsu
        )
        return certificados_service.autocadastrar_certificado(
            db=db,
            storage=storage,
            filename=arquivo.filename or "",
            pfx_bytes=pfx_bytes,
            senha=senha,
            ambiente=ambiente,
            auto_iniciar=auto_iniciar,
            limite=limite,
            nsu_inicio=nsu_inicial,
            forcar=forcar,
        )
    except CertificadoServiceError as exc:
        _handle_error(exc)


@empresa_router.post("", response_model=CertificadoRead)
async def create_certificado_empresa(
    empresa_id: int,
    nome: str = Form(...),
    arquivo_pfx: UploadFile = File(...),
    senha: str = Form(...),
    ativo: bool = Form(default=True),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        pfx_bytes = await arquivo_pfx.read()
        return certificados_service.criar_certificado_com_upload_e_senha(
            db=db,
            storage=storage,
            empresa_id=empresa_id,
            nome=nome,
            filename=arquivo_pfx.filename or "",
            pfx_bytes=pfx_bytes,
            senha=senha,
            ativo=ativo,
        )
    except CertificadoServiceError as exc:
        _handle_error(exc)


@empresa_router.get("", response_model=list[CertificadoRead])
def list_certificados_empresa(
    empresa_id: int,
    ativo: bool | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return certificados_service.listar_certificados(db, empresa_id=empresa_id, ativo=ativo)


@router.get("", response_model=list[CertificadoRead])
def list_certificados(
    empresa_id: int | None = Query(default=None),
    ativo: bool | None = Query(default=True),
    db: Session = Depends(get_db),
):
    return certificados_service.listar_certificados(db, empresa_id=empresa_id, ativo=ativo)


@router.put("/{certificado_ref}", response_model=CertificadoRead)
async def update_certificado_compat(
    certificado_ref: str,
    request: Request,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    certificado = _resolve_certificado_ref(db, certificado_ref)
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    alias = str(payload.get("alias") or "").strip()
    client_name = str(payload.get("client_name") or "").strip()
    password = str(payload.get("password") or "").strip()

    try:
        if password:
            certificados_service.salvar_senha_certificado(db, storage, certificado.id, password)
            certificado = _resolve_certificado_ref(db, str(certificado.id))
        changed = False
        if alias:
            certificado.nome = alias
            changed = True
        if client_name and certificado.empresa is not None:
            certificado.empresa.nome = client_name
            db.add(certificado.empresa)
            changed = True
        if changed:
            db.add(certificado)
            db.commit()
            db.refresh(certificado)
        return certificado
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.get("/{certificado_id}", response_model=CertificadoRead)
def get_certificado(certificado_id: int, db: Session = Depends(get_db)):
    try:
        return certificados_service.obter_certificado(db, certificado_id)
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.post("/{certificado_id}/testar", response_model=CertificadoTestResult)
def testar_certificado(
    certificado_id: int,
    payload: CertificadoTestRequest,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        return certificados_service.testar_certificado_salvo(db, storage, certificado_id, payload.senha)
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.patch("/{certificado_id}", response_model=CertificadoRead)
async def update_certificado(
    certificado_id: int,
    nome: str | None = Form(default=None),
    arquivo_pfx: UploadFile | None = File(default=None),
    senha: str | None = Form(default=None),
    ativo: bool | None = Form(default=None),
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        pfx_bytes = await arquivo_pfx.read() if arquivo_pfx is not None else None
        return certificados_service.atualizar_certificado_com_upload_ou_senha(
            db=db,
            storage=storage,
            certificado_id=certificado_id,
            nome=nome,
            filename=(arquivo_pfx.filename if arquivo_pfx is not None else None),
            pfx_bytes=pfx_bytes,
            senha=senha,
            ativo=ativo,
        )
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.post("/{certificado_id}/senha", response_model=SecretStatusResponse)
def salvar_senha_certificado(
    certificado_id: int,
    payload: SecretSetRequest,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        return certificados_service.salvar_senha_certificado(
            db=db,
            storage=storage,
            certificado_id=certificado_id,
            senha=payload.senha,
            testar_antes=payload.testar_antes,
        )
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.get("/{certificado_id}/senha/status", response_model=SecretStatusResponse)
def status_senha_certificado(certificado_id: int, db: Session = Depends(get_db)):
    try:
        return certificados_service.status_senha_certificado(db, certificado_id)
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.delete("/{certificado_id}/senha", response_model=SecretStatusResponse)
def remover_senha_certificado(certificado_id: int, db: Session = Depends(get_db)):
    try:
        return certificados_service.remover_senha_certificado(db, certificado_id)
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.post("/{certificado_id}/testar-senha-salva", response_model=CertificadoTestResult)
def testar_senha_salva(
    certificado_id: int,
    db: Session = Depends(get_db),
    storage: StorageService = Depends(get_storage),
):
    try:
        return certificados_service.testar_certificado_com_senha_salva(db, storage, certificado_id)
    except CertificadoServiceError as exc:
        _handle_error(exc)


@router.delete("/{certificado_ref}", response_model=CertificadoRead)
def delete_certificado(certificado_ref: str, db: Session = Depends(get_db)):
    try:
        certificado = _resolve_certificado_ref(db, certificado_ref)
        return certificados_service.desativar_certificado(db, certificado.id)
    except CertificadoServiceError as exc:
        _handle_error(exc)
