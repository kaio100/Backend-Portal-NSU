from sqlalchemy import func

from backend.app.db.models import Certificado, Empresa, Nota, NsuControle, Processo
from backend.app.db.session import SessionLocal


with SessionLocal() as db:
    empresas = db.query(Empresa).filter(Empresa.grupo == "planning_hub").order_by(Empresa.id).all()
    for empresa in empresas:
        nome = empresa.nome.upper()
        if any(term in nome for term in ("CANOPUS", "SOL", "BOSQUE", "FORTALEZA", "TERESINA", "BELEM", "BELÉM")):
            certs = db.query(Certificado).filter(Certificado.empresa_id == empresa.id).all()
            controls = db.query(NsuControle).filter(NsuControle.empresa_id == empresa.id).all()
            latest_note = db.query(func.max(Nota.data_emissao), func.max(Nota.importado_em), func.max(Nota.ultimo_nsu)).filter(Nota.empresa_id == empresa.id).one()
            process_counts = db.query(Processo.status, func.count(Processo.id)).filter(Processo.empresa_id == empresa.id).group_by(Processo.status).all()
            latest_processes = db.query(Processo).filter(Processo.empresa_id == empresa.id).order_by(Processo.id.desc()).limit(5).all()
            print({
                "empresa": {"id": empresa.id, "nome": empresa.nome, "cnpj": empresa.cnpj, "ativo": empresa.ativo},
                "certificados": [{"id": c.id, "nome": c.nome, "ativo": c.ativo, "valido_ate": str(c.valido_ate)} for c in certs],
                "nsu": [{"certificado_id": n.certificado_id, "ultimo_nsu": n.ultimo_nsu, "origem": n.origem, "reconciliacao": str(n.ultima_reconciliacao_em), "updated_at": str(n.updated_at)} for n in controls],
                "ultima_nota": {"emissao_max": str(latest_note[0]), "importacao_max": str(latest_note[1]), "nsu_max": latest_note[2]},
                "processos_status": dict(process_counts),
                "ultimos_processos": [{"id": p.id, "status": p.status, "inicio": str(p.started_at), "fim": str(p.finished_at), "nsu_inicio": p.nsu_inicio, "nsu_final": p.nsu_final, "erro": p.erro_resumo} for p in latest_processes],
            })
