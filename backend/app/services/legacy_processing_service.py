from __future__ import annotations

import importlib.util
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Empresa, Job, Nota, Processo
from backend.app.db.session import SessionLocal, executar_escrita_com_retry, renovar_snapshot
from backend.app.repositories import certificados_repo, empresas_repo
from backend.app.services import cnpj_enrichment_service, legacy_ingestion_service, logs_service, nsu_control_service, secrets_service
from backend.app.services.storage_service import StorageService, get_storage_service


class LegacyProcessingError(RuntimeError):
    pass


# Tempo de espera pela parada da ingestao incremental. Passado o prazo, o
# processamento aguarda indefinidamente em vez de seguir com duas threads
# gravando no mesmo banco.
INGESTAO_JOIN_TIMEOUT = 60


def _maior_nsu_importado_por_cnpj(cnpj: str) -> int:
    cnpj_digits = re.sub(r"\D+", "", str(cnpj or ""))
    if not cnpj_digits:
        return 0
    with SessionLocal() as db:
        row = (
            db.query(Nota.ultimo_nsu)
            .join(Empresa, Empresa.id == Nota.empresa_id)
            .filter(Empresa.cnpj == cnpj_digits)
            .filter(Nota.ultimo_nsu.isnot(None))
            .order_by(Nota.ultimo_nsu.desc())
            .first()
        )
        return int(row[0] or 0) if row else 0


def _ultimo_nsu_central_por_cnpj(cnpj: str, certificado_id: int | None = None) -> int:
    cnpj_digits = re.sub(r"\D+", "", str(cnpj or ""))
    if not cnpj_digits:
        return 0
    with SessionLocal() as db:
        empresa = db.query(Empresa).filter(Empresa.cnpj == cnpj_digits).first()
        if empresa is None:
            return 0
        return nsu_control_service.obter_ultimo_nsu(db, int(empresa.id), certificado_id=certificado_id)


def _processo_cancelado(processo_id: int) -> bool:
    with SessionLocal() as db:
        processo = db.get(Processo, int(processo_id))
        return processo is None or processo.status == "cancelado"


def _load_legacy_module(processo_id: int) -> Any:
    root_dir = Path(__file__).resolve().parents[3]
    legacy_path = root_dir / "adn_nfse_downloader.py"
    module_name = f"_adn_nfse_downloader_job_{processo_id}_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, legacy_path)
    if spec is None or spec.loader is None:
        raise LegacyProcessingError("Nao foi possivel carregar o motor legado.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _configure_legacy_output(legacy: Any, root_out: Path) -> None:
    legacy.ROOT_OUT = root_out
    legacy.DIR_JSON = root_out / "json"
    legacy.DIR_XML = root_out / "xml"
    legacy.DIR_RAW = root_out / "raw"
    legacy.DIR_ESTADO = root_out / "estado"
    legacy.INDEX_UNICO_FILE = root_out / "index_nfse.csv"
    legacy.OCORRENCIAS_FILE = root_out / "ocorrencias_nsu.csv"
    for folder in [
        legacy.ROOT_OUT,
        legacy.DIR_JSON,
        legacy.DIR_XML,
        legacy.DIR_RAW,
        legacy.DIR_ESTADO,
    ]:
        folder.mkdir(parents=True, exist_ok=True)


def _safe_worker_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value or "worker")


def _payload_value(payload: dict[str, Any], key: str, default: Any) -> Any:
    value = payload.get(key)
    return default if value is None else value


def _safe_legacy_result(result: Any) -> dict[str, Any] | str:
    if not isinstance(result, dict):
        return "processamento finalizado"

    allowed = {
        "empresa",
        "cnpj",
        "pasta_saida",
        "status",
        "erro",
        "ultimo_nsu",
        "xmls_baixados",
        "xmls_evento",
    }
    return {key: value for key, value in result.items() if key in allowed}


def _contar_saida_legada(pasta_saida: str | None) -> dict[str, Any]:
    if not pasta_saida:
        return {
            "pasta_existe": False,
            "index_nfse_existe": False,
            "xmls_encontrados": 0,
            "pdfs_encontrados": 0,
        }
    base_dir = Path(pasta_saida)
    return {
        "pasta_saida": str(base_dir),
        "pasta_existe": base_dir.exists(),
        "index_nfse_existe": (base_dir / "index_nfse.csv").exists(),
        "xmls_encontrados": len(list(base_dir.rglob("*.xml"))) if base_dir.exists() else 0,
        "pdfs_encontrados": len(list(base_dir.rglob("*.pdf"))) if base_dir.exists() else 0,
    }


def _ingestao_tem_movimento(ingestao: dict[str, Any]) -> bool:
    chaves = (
        "notas_criadas",
        "arquivos_importados",
        "arquivos_registrados",
        "pdfs_espelho_gerados",
    )
    return any(int(ingestao.get(chave) or 0) > 0 for chave in chaves)


def _loop_ingestao_incremental(
    processo_id: int,
    job_id: int,
    pasta_saida: str,
    run_started_at: datetime,
    stop_event: threading.Event,
    intervalo: float,
) -> None:
    proxima_linha_index = 0
    while not stop_event.is_set():
        try:
            base_dir = Path(pasta_saida)
            if base_dir.exists():
                with SessionLocal() as session:
                    processo = session.get(Processo, processo_id)
                    if processo is None or processo.status == "cancelado":
                        return
                    job = session.get(Job, job_id)
                    if job is None or job.status == "cancelado":
                        return
                    ingestao = legacy_ingestion_service.ingerir_saida_legado(
                        session,
                        get_storage_service(),
                        processo,
                        base_dir,
                        updated_after=run_started_at,
                        commit_every=20,
                        start_row=proxima_linha_index,
                        gerar_pdf_espelho=bool(processo.gerar_pdf_espelho),
                        should_stop=stop_event.is_set,
                    )
                    proxima_linha_index = int(ingestao.get("proxima_linha_index") or proxima_linha_index)
                    if _ingestao_tem_movimento(ingestao):
                        logs_service.registrar_log(
                            session,
                            processo.id,
                            processo.empresa_id,
                            "info",
                            "Ingestao incremental da saida legada",
                            {"contadores": ingestao},
                        )
                    # O motor legado pode trabalhar por horas dentro de uma
                    # unica chamada. Mantenha os timestamps vivos para que o
                    # dashboard diferencie uma consulta ativa de uma travada.
                    heartbeat = datetime.now(timezone.utc)
                    processo.updated_at = heartbeat
                    job.updated_at = heartbeat
                    session.add(processo)
                    session.add(job)
                    session.commit()
        except Exception:
            # A ingestao final pos-processamento ainda roda no fluxo principal.
            pass
        stop_event.wait(max(0.5, intervalo))


def _iniciar_ingestao_incremental(
    processo_id: int,
    job_id: int,
    pasta_saida: str,
    run_started_at: datetime,
    intervalo: float = 5.0,
) -> tuple[threading.Event, threading.Thread]:
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_loop_ingestao_incremental,
        args=(processo_id, job_id, pasta_saida, run_started_at, stop_event, intervalo),
        name=f"ingestao-incremental-{processo_id}",
        daemon=True,
    )
    thread.start()
    return stop_event, thread


def _build_legacy_config(legacy: Any, empresa_item: dict[str, Any]) -> Any:
    ambiente = (empresa_item.get("ambiente") or "producao").lower().strip()
    if ambiente == "producao":
        base_contribuintes = "https://adn.nfse.gov.br/contribuintes"
    elif ambiente in {"restrita", "homologacao"}:
        base_contribuintes = "https://adn.producaorestrita.nfse.gov.br/contribuintes"
    else:
        raise LegacyProcessingError("Ambiente deve ser 'producao' ou 'restrita'.")

    cnpj = re.sub(r"\D", "", str(empresa_item.get("cnpj") or ""))
    pfx_path = str(empresa_item.get("pfx_path") or "").strip()
    pfx_password = str(empresa_item.get("pfx_password") or "")

    if len(cnpj) != 14:
        raise LegacyProcessingError("CNPJ da empresa precisa ter 14 digitos.")
    if not pfx_path:
        raise LegacyProcessingError("Caminho temporario do certificado nao foi preparado.")
    if not pfx_password:
        raise LegacyProcessingError("Senha salva do certificado nao foi encontrada.")

    cfg = legacy.Config(
        ambiente=ambiente,
        pfx_path=pfx_path,
        pfx_password=pfx_password,
        cnpj=cnpj,
        verify_ssl=bool(empresa_item.get("verify_ssl", True)),
        base_contribuintes=base_contribuintes,
    )
    cfg.validar()
    return cfg


def _gravar_nsu_em_sessao_curta(
    empresa_id: int,
    certificado_id: int | None,
    cnpj: str,
    ultimo_nsu: int,
    origem: str,
) -> None:
    """Persiste o avanco do NSU fora da transacao longa do job.

    A gravacao e idempotente (so avanca o NSU), entao pode ser repetida com
    seguranca quando o SQLite recusa a escrita por concorrencia.
    """

    def operacao() -> None:
        with SessionLocal() as session:
            nsu_control_service.atualizar_ultimo_nsu(
                session,
                empresa_id=empresa_id,
                certificado_id=certificado_id,
                cnpj=cnpj,
                ultimo_nsu=ultimo_nsu,
                origem=origem,
            )
            session.commit()

    executar_escrita_com_retry(operacao)


def _executar_baixa_empresa_compat(
    legacy: Any,
    config: Any,
    limite: int,
    pausa: float,
    inicio: int | None,
    consulta_lote_tamanho: int,
    empresa_id: int | None = None,
    certificado_id: int | None = None,
    processo_id: int | None = None,
) -> dict[str, Any]:
    estado = legacy.carregar_estado(config.cnpj)
    nsu_estado = int(estado.get("ultimo_nsu", 0) or 0)
    if inicio is not None:
        nsu_atual = int(inicio)
    else:
        nsu_banco = _maior_nsu_importado_por_cnpj(config.cnpj)
        nsu_central = _ultimo_nsu_central_por_cnpj(config.cnpj, certificado_id=certificado_id)
        nsu_atual = max(nsu_estado, nsu_banco, nsu_central)
        if nsu_atual > nsu_estado:
            legacy.salvar_estado(config.cnpj, nsu_atual)
        if empresa_id is not None:
            _gravar_nsu_em_sessao_curta(
                empresa_id, certificado_id, config.cnpj, nsu_atual, "inicio_consulta"
            )
    vazios = 0
    max_vazios = max(1, int(settings.nsu_max_vazios_consecutivos or 5))
    xmls_baixados = 0
    ultimo_nsu = nsu_atual
    consultas_realizadas = 0
    consulta_lote_tamanho = max(1, int(consulta_lote_tamanho or 1))
    parar = False

    while consultas_realizadas < limite and not parar:
        if processo_id is not None and _processo_cancelado(processo_id):
            parar = True
            break
        consultas_no_bloco = min(consulta_lote_tamanho, limite - consultas_realizadas)

        for _ in range(consultas_no_bloco):
            if processo_id is not None and _processo_cancelado(processo_id):
                parar = True
                break
            resultado = legacy.consultar_dfe(config, nsu_atual, lote=bool(settings.worker_adn_lote))
            consultas_realizadas += 1
            raw_path = legacy.DIR_RAW / (
                f"dfe_consulta_nsu_{nsu_atual}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            legacy.salvar_json(raw_path, resultado)

            lote_dfe = resultado.get("LoteDFe") or []
            if not lote_dfe:
                if resultado.get("StatusProcessamento") == "NENHUM_DOCUMENTO_LOCALIZADO":
                    # E2220 e uma resposta final valida para o NSU consultado;
                    # repetir cinco vezes so gera cinco 404 equivalentes.
                    parar = True
                    break
                vazios += 1
                if vazios >= max_vazios:
                    parar = True
                break

            vazios = 0
            maior_nsu = nsu_atual
            for doc in lote_dfe:
                nsu_doc, documento_persistido = legacy.processar_documento(doc)
                if nsu_doc is not None:
                    if documento_persistido:
                        xmls_baixados += 1
                    if nsu_doc > maior_nsu:
                        maior_nsu = nsu_doc

            if maior_nsu <= nsu_atual:
                parar = True
                break

            nsu_atual = maior_nsu
            ultimo_nsu = nsu_atual
            legacy.salvar_estado(config.cnpj, nsu_atual)
            if empresa_id is not None:
                _gravar_nsu_em_sessao_curta(
                    empresa_id, certificado_id, config.cnpj, nsu_atual, "processamento"
                )

        if not parar and consultas_realizadas < limite and pausa > 0:
            # Ritmo entre blocos de consulta ao ADN. O PDF espelho e produzido
            # pela ingestao a partir do XML; nao ha mais busca de PDF oficial.
            time.sleep(pausa)

    return {
        "empresa": config.cnpj,
        "cnpj": config.cnpj,
        "pasta_saida": str(legacy.ROOT_OUT),
        "status": "finalizado",
        "ultimo_nsu": ultimo_nsu,
        "xmls_baixados": xmls_baixados,
        "consultas_realizadas": consultas_realizadas,
        "consulta_lote_tamanho": consulta_lote_tamanho,
        "cancelado": parar and processo_id is not None and _processo_cancelado(processo_id),
    }


def executar_consulta_nfse_legado(
    db: Session,
    storage: StorageService,
    processo: Processo,
    job: Job,
    worker_id: str,
) -> dict:
    empresa = empresas_repo.get_empresa(db, int(processo.empresa_id))
    if empresa is None or not empresa.ativo:
        raise LegacyProcessingError("Empresa nao encontrada ou inativa.")

    certificado = certificados_repo.get_certificado(db, int(processo.certificado_id or 0))
    if certificado is None or not certificado.ativo:
        raise LegacyProcessingError("Certificado nao encontrado ou inativo.")
    if certificado.empresa_id != empresa.id:
        raise LegacyProcessingError("Certificado nao pertence a empresa do processo.")
    if not certificado.storage_key:
        raise LegacyProcessingError("Certificado sem storage_key.")
    if not certificado.senha_secret_ref:
        raise LegacyProcessingError("Senha do certificado nao configurada.")

    pfx_bytes = storage.get_bytes(certificado.storage_key)
    senha = secrets_service.get_secret_value(db, certificado.senha_secret_ref)

    temp_dir = Path(settings.worker_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_pfx_path = temp_dir / (
        f"worker_{_safe_worker_id(worker_id)}_cert_{certificado.id}_{uuid.uuid4().hex}.pfx"
    )

    payload = job.payload_json or {}
    limite_payload = int(_payload_value(payload, "limite", 100))
    max_limite = int(settings.worker_real_max_limite)
    limite = max(1, limite_payload if max_limite <= 0 else min(limite_payload, max_limite))
    pausa_payload = max(0.0, float(_payload_value(payload, "pausa", settings.consultas_default_pausa)))
    max_pausa = float(settings.worker_real_max_pausa)
    pausa = pausa_payload if max_pausa <= 0 else min(pausa_payload, max_pausa)
    consulta_lote_tamanho = max(
        1,
        int(_payload_value(payload, "consulta_lote_tamanho", settings.worker_consulta_lote_tamanho)),
    )
    nsu_inicio = payload.get("nsu_inicio")
    gerar_pdf_espelho = bool(_payload_value(payload, "gerar_pdf_espelho", True))

    try:
        temp_pfx_path.write_bytes(pfx_bytes)
        run_started_at = datetime.now()
        logs_service.registrar_log(
            db,
            processo.id,
            empresa.id,
            "info",
            "Iniciando processamento real via motor legado",
            {
                "job_id": job.id,
                "worker_id": worker_id,
                "limite_efetivo": limite,
                "pausa": pausa,
                "consulta_lote_tamanho": consulta_lote_tamanho,
                "adn_lote": bool(settings.worker_adn_lote),
                "gerar_pdf_espelho": gerar_pdf_espelho,
            },
        )
        logs_service.registrar_log(
            db,
            processo.id,
            empresa.id,
            "info",
            "Empresa selecionada para processamento legado",
            {"empresa_id": empresa.id, "cnpj": empresa.cnpj},
        )
        logs_service.registrar_log(
            db,
            processo.id,
            empresa.id,
            "info",
            "Certificado selecionado para processamento legado",
            {"certificado_id": certificado.id},
        )
        logs_service.registrar_log(
            db,
            processo.id,
            empresa.id,
            "info",
            "Pasta temporaria do worker preparada",
            {"worker_temp_dir": str(temp_dir), "temp_pfx_path": str(temp_pfx_path)},
        )
        db.commit()

        legacy = _load_legacy_module(int(processo.id))
        legacy_output_dir = (
            Path("saida_adn_nfse")
            / "empresas"
            / f"empresa_{empresa.id}_cert_{certificado.id}"
        )
        _configure_legacy_output(legacy, legacy_output_dir)
        logs_service.registrar_log(
            db,
            processo.id,
            empresa.id,
            "info",
            "Saida legada isolada para processamento paralelo",
            {"legacy_output_dir": str(legacy_output_dir)},
        )
        db.commit()

        empresa_item = {
            "nome": empresa.nome,
            "cnpj": empresa.cnpj,
            "pfx_path": str(temp_pfx_path),
            "pfx_password": senha,
            "ambiente": empresa.ambiente or "producao",
            "verify_ssl": True,
        }
        config = _build_legacy_config(legacy, empresa_item)
        nsu_inicio_efetivo = nsu_inicio
        reconciliacao_profunda = False
        janela_reconciliacao = None
        if nsu_inicio_efetivo is not None:
            nsu_inicio_efetivo = int(nsu_inicio_efetivo)
            processo.nsu_inicio = nsu_inicio_efetivo
            db.add(processo)
            legacy.salvar_estado(config.cnpj, nsu_inicio_efetivo)
            nsu_control_service.atualizar_ultimo_nsu(
                db,
                empresa_id=int(empresa.id),
                certificado_id=int(certificado.id),
                cnpj=str(empresa.cnpj),
                ultimo_nsu=nsu_inicio_efetivo,
                origem="inicio_usuario",
            )
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "NSU inicial informado pelo usuario aplicado",
                {"nsu_inicio": nsu_inicio_efetivo, "certificado_id": certificado.id},
            )
            db.commit()
        else:
            plano_nsu = nsu_control_service.planejar_inicio_consulta(
                db,
                empresa_id=int(empresa.id),
                certificado_id=int(certificado.id),
            )
            nsu_inicio_efetivo = int(plano_nsu["nsu_inicio"])
            reconciliacao_profunda = bool(plano_nsu["reconciliacao_profunda"])
            janela_reconciliacao = plano_nsu["janela_reconciliacao"]
            processo.nsu_inicio = nsu_inicio_efetivo
            db.add(processo)
            legacy.salvar_estado(config.cnpj, int(nsu_inicio_efetivo or 0))
            nsu_control_service.atualizar_ultimo_nsu(
                db,
                empresa_id=int(empresa.id),
                certificado_id=int(certificado.id),
                cnpj=str(empresa.cnpj),
                ultimo_nsu=int(nsu_inicio_efetivo or 0),
                origem="inicio_consulta",
            )
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Janela de sobreposicao NSU aplicada",
                {
                    "nsu_confirmado": plano_nsu["nsu_confirmado"],
                    "nsu_inicio": nsu_inicio_efetivo,
                    "recuo": plano_nsu["recuo"],
                    "reconciliacao_profunda": reconciliacao_profunda,
                    "janela_reconciliacao": str(janela_reconciliacao) if janela_reconciliacao else None,
                },
            )
            db.commit()
        pasta_saida_incremental = str(getattr(legacy, "ROOT_OUT", "") or "")
        ingestao_stop_event: threading.Event | None = None
        ingestao_thread: threading.Thread | None = None
        if pasta_saida_incremental:
            ingestao_stop_event, ingestao_thread = _iniciar_ingestao_incremental(
                processo_id=int(processo.id),
                job_id=int(job.id),
                pasta_saida=pasta_saida_incremental,
                run_started_at=run_started_at,
                intervalo=min(max(1.0, pausa), 3.0),
            )
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Ingestao incremental ativada",
                {"pasta_saida": pasta_saida_incremental},
            )
            db.commit()

        try:
            result = _executar_baixa_empresa_compat(
                legacy=legacy,
                config=config,
                limite=limite,
                pausa=pausa,
                inicio=nsu_inicio_efetivo,
                consulta_lote_tamanho=consulta_lote_tamanho,
                empresa_id=int(empresa.id),
                certificado_id=int(certificado.id),
                processo_id=int(processo.id),
            )
        finally:
            # A thread precisa estar comprovadamente parada antes que o fluxo
            # principal volte a escrever. Uma thread sobrevivente grava em
            # paralelo com esta sessao e derruba o job com "database is
            # locked" no SQLite.
            if ingestao_stop_event is not None:
                ingestao_stop_event.set()
            if ingestao_thread is not None:
                ingestao_thread.join(timeout=INGESTAO_JOIN_TIMEOUT)
                if ingestao_thread.is_alive():
                    logs_service.registrar_log(
                        db,
                        processo.id,
                        empresa.id,
                        "warning",
                        "Ingestao incremental nao parou no prazo; ingestao final adiada",
                        {"timeout_segundos": INGESTAO_JOIN_TIMEOUT},
                    )
                    db.commit()
                    ingestao_thread.join()
        # O motor legado rodou por minutos com esta sessao parada enquanto a
        # thread de ingestao e as gravacoes de NSU escreviam. Renova o snapshot
        # antes de voltar a gravar por aqui.
        renovar_snapshot(db)
        if _processo_cancelado(int(processo.id)):
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Processamento interrompido por desativacao das consultas",
                {"job_id": job.id},
            )
            db.commit()
            return {
                "ok": False,
                "modo": "legado_real",
                "empresa_id": empresa.id,
                "certificado_id": certificado.id,
                "processo_id": processo.id,
                "job_id": job.id,
                "motivo": "cancelado",
            }
        safe_result = _safe_legacy_result(result)
        pasta_saida = safe_result.get("pasta_saida") if isinstance(safe_result, dict) else None
        saida_contagem = _contar_saida_legada(pasta_saida)
        logs_service.registrar_log(
            db,
            processo.id,
            empresa.id,
            "info",
            "Saida legada localizada",
            saida_contagem,
        )
        ingestao = None
        if pasta_saida:
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Iniciando ingestao da saida legada",
                saida_contagem,
            )
            ingestao = legacy_ingestion_service.ingerir_saida_legado(
                db,
                storage,
                processo,
                pasta_saida,
                updated_after=run_started_at,
                # Sem commits parciais, centenas de linhas ficavam flushadas
                # em uma unica transacao desta sessao, que assim segurava o
                # lock de escrita do SQLite ate o fim. A gravacao final do
                # NSU (em sessao propria, na mesma thread) esperava por esse
                # lock e o job morria com "database is locked".
                commit_every=20,
                gerar_pdf_espelho=bool(processo.gerar_pdf_espelho),
            )
            # Garante que nada desta ingestao fique pendente antes do fecho.
            db.commit()
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Ingestao pos-processamento finalizada",
                {"contadores": ingestao},
            )
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Resumo da ingestao pos-processamento",
                {
                    "notas_criadas": ingestao.get("notas_criadas"),
                    "notas_atualizadas": ingestao.get("notas_atualizadas"),
                    "arquivos_importados": ingestao.get("arquivos_importados"),
                    "arquivos_existentes": ingestao.get("arquivos_existentes"),
                    "arquivos_registrados": ingestao.get("arquivos_registrados"),
                    "erros": ingestao.get("erros"),
                },
            )
        # A ingestao pos-processamento acabou de fazer varios commits e a
        # geracao de PDF (PHP) entre eles; recomeca limpo para o fecho.
        renovar_snapshot(db)
        ultimo_nsu_result = None
        if isinstance(safe_result, dict):
            try:
                ultimo_nsu_result = int(safe_result.get("ultimo_nsu") or 0)
            except (TypeError, ValueError):
                ultimo_nsu_result = None
        ultimo_nsu_final = max(
            int(ultimo_nsu_result or 0),
            nsu_control_service.maior_nsu_importado(db, int(empresa.id)),
        )
        if ultimo_nsu_final:
            # Em sessao curta, e nao nesta transacao longa: o scheduler e a
            # ingestao gravam em paralelo durante o job, e no SQLite isso
            # invalida o snapshot da sessao principal. A escrita direta aqui
            # falhava com "database is locked" e derrubava o processo ja no
            # fim, perdendo o avanco do NSU.
            _gravar_nsu_em_sessao_curta(
                int(empresa.id),
                int(certificado.id),
                str(empresa.cnpj),
                ultimo_nsu_final,
                "final_processo",
            )
        if reconciliacao_profunda and janela_reconciliacao is not None:
            # Mesma tabela que acabou de ser gravada acima; tambem em sessao
            # propria para nao reescrever nsu_controle com snapshot antigo.
            def _marcar() -> None:
                with SessionLocal() as session:
                    nsu_control_service.marcar_reconciliacao_concluida(
                        session,
                        empresa_id=int(empresa.id),
                        certificado_id=int(certificado.id),
                        janela=janela_reconciliacao,
                    )
                    session.commit()

            executar_escrita_com_retry(_marcar)
        # As gravacoes acima aconteceram fora desta sessao: recomeca com
        # snapshot novo antes de tocar processo e logs por aqui.
        renovar_snapshot(db)
        if ultimo_nsu_final:
            processo.nsu_final = ultimo_nsu_final
            db.add(processo)
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "NSU central atualizado ao final do processo",
                {"ultimo_nsu": ultimo_nsu_final},
            )
        if reconciliacao_profunda and janela_reconciliacao is not None:
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Reconciliacao profunda de NSU concluida",
                {"janela_reconciliacao": str(janela_reconciliacao)},
            )
        db.commit()
        try:
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Enriquecimento Invertexto pos-certificado iniciado",
                {"certificado_id": certificado.id},
            )
            resumo_enriquecimento = cnpj_enrichment_service.enriquecer_cnpjs_do_processo(
                db,
                processo_id=int(processo.id),
                certificado_id=int(certificado.id),
            )
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "info",
                "Enriquecimento Invertexto pos-certificado finalizado",
                resumo_enriquecimento,
            )
        except Exception as exc:
            db.rollback()
            logs_service.registrar_log(
                db,
                processo.id,
                empresa.id,
                "warning",
                "Enriquecimento Invertexto pos-certificado falhou sem interromper a consulta ADN",
                {"erro": str(exc), "certificado_id": certificado.id},
            )
        logs_service.registrar_log(
            db,
            processo.id,
            empresa.id,
            "info",
            "Motor legado finalizou",
            {"resultado": safe_result},
        )
        db.commit()

        return {
            "ok": True,
            "modo": "legado_real",
            "empresa_id": empresa.id,
            "certificado_id": certificado.id,
            "processo_id": processo.id,
            "job_id": job.id,
            "limite_usado": limite,
            "pasta_saida": pasta_saida,
            "resultado_legado": safe_result,
            "ingestao": ingestao,
        }
    finally:
        senha = ""
        if temp_pfx_path.exists():
            temp_pfx_path.unlink()
            try:
                logs_service.registrar_log(
                    db,
                    processo.id,
                    empresa.id,
                    "info",
                    "PFX temporario removido",
                )
                db.commit()
            except Exception:
                # O PFX ja saiu do disco, que e o que importa nesta limpeza.
                # Falhar so ao gravar a linha de log nao pode transformar uma
                # consulta bem-sucedida em job com erro.
                db.rollback()
