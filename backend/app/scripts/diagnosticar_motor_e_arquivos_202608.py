from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_

from backend.app.db.models import Arquivo, Job, LogProcesso, MonitoramentoConfig, Nota, Processo
from backend.app.db.session import SessionLocal
from backend.app.scripts.diagnosticar_notas_faltantes_202608 import TARGETS, norm_number


with SessionLocal() as db:
    print("MONITOR")
    for item in db.query(MonitoramentoConfig).all():
        print({"id": item.id, "grupo": item.grupo, "ativo": item.automatico_ativo, "intervalo": item.intervalo_minutos, "ultimo": str(item.ultimo_ciclo_em), "proximo": str(item.proximo_ciclo_em), "updated_at": str(item.updated_at)})
    print("PROCESSOS_MAX", db.query(func.max(Processo.id), func.max(Processo.created_at), func.max(Processo.finished_at)).one())
    print("JOBS", db.query(Job.status, func.count(Job.id)).group_by(Job.status).all())
    print("PROCESSOS", db.query(Processo.status, func.count(Processo.id)).group_by(Processo.status).all())
    print("ULTIMOS_LOGS_ERRO")
    for log in db.query(LogProcesso).filter(LogProcesso.level.in_(("error", "erro", "warning"))).order_by(LogProcesso.id.desc()).limit(20):
        print({"id": log.id, "processo": log.processo_id, "level": log.level, "data": str(log.created_at), "mensagem": log.mensagem[:500]})

    print("BUSCA_AMPLA_AUSENTES")
    for number, cnpj, label, amount_text, issue_text in TARGETS:
        amount = Decimal(amount_text)
        issue = date.fromisoformat(issue_text)
        exact_prestador = db.query(Nota.id).filter(
            Nota.prestador_cnpj == cnpj,
            Nota.numero_nfse == number,
            Nota.data_emissao == issue,
        ).first()
        if exact_prestador:
            continue
        possible = db.query(Nota).filter(
            Nota.data_emissao == issue,
            Nota.valor_servico.between(amount - Decimal("0.01"), amount + Decimal("0.01")),
        ).all()
        same_number = db.query(Nota).filter(Nota.numero_nfse == number).all()
        files = db.query(Arquivo).filter(
            or_(Arquivo.filename.ilike(f"%{number}%"), Arquivo.storage_key.ilike(f"%{number}%"))
        ).order_by(Arquivo.id.desc()).limit(10).all()
        print({
            "solicitada": number,
            "cnpj": cnpj,
            "destino": label,
            "possiveis_data_valor": [{"id": n.id, "numero": n.numero_nfse, "prestador_cnpj": n.prestador_cnpj, "empresa_id": n.empresa_id} for n in possible[:10]],
            "mesmo_numero": [{"id": n.id, "emissao": str(n.data_emissao), "valor": str(n.valor_servico), "prestador_cnpj": n.prestador_cnpj, "empresa_id": n.empresa_id} for n in same_number[:10]],
            "arquivos": [{"id": a.id, "nota_id": a.nota_id, "empresa_id": a.empresa_id, "tipo": a.tipo, "filename": a.filename, "key": a.storage_key} for a in files],
        })
