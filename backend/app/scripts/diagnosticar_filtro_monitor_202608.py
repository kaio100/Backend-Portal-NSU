from backend.app.db.models import Certificado, Empresa, Job, LogProcesso, MonitoramentoConfig, Processo
from backend.app.db.session import SessionLocal


with SessionLocal() as db:
    for config in db.query(MonitoramentoConfig).all():
        print("CONFIG", {"grupo": config.grupo, "ativo": config.automatico_ativo, "intervalo": config.intervalo_minutos, "filtros": config.filtros_json})
    print("ULTIMOS_PROCESSOS")
    for processo in db.query(Processo).order_by(Processo.id.desc()).limit(100).all():
        empresa = db.get(Empresa, processo.empresa_id)
        cert = db.get(Certificado, processo.certificado_id) if processo.certificado_id else None
        if processo.status == "erro" or processo.id >= 6990:
            job = db.query(Job).filter(Job.processo_id == processo.id).first()
            logs = db.query(LogProcesso).filter(LogProcesso.processo_id == processo.id).order_by(LogProcesso.id.desc()).limit(4).all()
            print({
                "processo": processo.id,
                "status": processo.status,
                "empresa": empresa.nome if empresa else None,
                "empresa_id": processo.empresa_id,
                "certificado": cert.nome if cert else None,
                "certificado_id": processo.certificado_id,
                "created_at": str(processo.created_at),
                "started_at": str(processo.started_at),
                "finished_at": str(processo.finished_at),
                "erro": processo.erro_resumo,
                "job_erro": job.erro_resumo if job else None,
                "logs": [{"level": l.level, "mensagem": l.mensagem, "contexto": l.contexto_json} for l in logs],
            })
