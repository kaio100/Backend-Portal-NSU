"""Corrige o status fiscal gravado pela classificacao antiga (por palavras).

Simula por padrao e grava um relatorio JSON. So altera o banco com --aplicar:

    python -m backend.app.scripts.corrigir_status_fiscal --relatorio relatorio.json
    python -m backend.app.scripts.corrigir_status_fiscal --aplicar --relatorio relatorio.json
    python -m backend.app.scripts.corrigir_status_fiscal --aplicar --regenerar-pdf

Etapas (todas decididas pela estrutura do XML, via nfse_status_service):
1. Eventos: cada evento e reclassificado pelo proprio XML (solicitacao de
   analise fiscal, manifestacoes e indeferimento deixam de valer como
   cancelamento; cancelamento por substituicao passa a substituida). XML que e
   uma nota gravada como evento vira nota, e o registro de evento sai.
2. Notas: o status passa a ser o de maior prioridade entre o XML da propria
   nota, os eventos corrigidos e as notas substitutas (chSubstda) que apontam
   para ela. Nota ja conferida com status alterado nao e mudada: vai para a
   lista de revisao manual do relatorio.
3. Status do Simples: volta ao valor calculado do XML quando tem o valor que a
   tela gravava (Correto, Pendente, Divergente...). Alerta com o texto
   "Campos obrigatorios ausentes no XML" e recalculado pelo XML.
4. PDF espelho (--regenerar-pdf): refeito para as notas cujo status mudou,
   com ou sem carimbo conforme o status novo. Exige PHP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from xml.etree import ElementTree

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeElementTree
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.app.db.models import Arquivo, Empresa, Evento, Nota
from backend.app.db.session import SessionLocal, init_db
from backend.app.services import legacy_ingestion_service
from backend.app.services.nfse_status_service import prioridade_status
from backend.app.services.operational_fields_service import (
    calcular_status_simples_nacional_xml,
    normalizar_simples_xml,
)
from backend.app.services.storage_service import StorageService, get_storage_service

STATUS_ESPECIAIS = ("cancelada", "substituida")
ALERTA_DA_TELA = "Campos obrigatorios ausentes no XML"
ROTULOS = {"cancelada": "Cancelada", "substituida": "Substituida"}


@dataclass
class Relatorio:
    modo: str = "simulacao"
    gerado_em: str = ""
    eventos_analisados: int = 0
    eventos_reclassificados: list[dict[str, Any]] = field(default_factory=list)
    eventos_que_sao_notas: list[dict[str, Any]] = field(default_factory=list)
    notas_criadas: int = 0
    notas_analisadas: int = 0
    notas_alteradas: list[dict[str, Any]] = field(default_factory=list)
    revisao_manual: list[dict[str, Any]] = field(default_factory=list)
    simples_corrigidas: int = 0
    alertas_recalculados: int = 0
    pdfs_regenerados: int = 0
    xml_indisponivel: list[dict[str, Any]] = field(default_factory=list)
    erros: list[dict[str, Any]] = field(default_factory=list)

    def resumo(self) -> dict[str, Any]:
        mudancas: dict[str, int] = defaultdict(int)
        for item in self.notas_alteradas:
            mudancas[f"{item['de'] or '-'} -> {item['para']}"] += 1
        return {
            "modo": self.modo,
            "eventos_analisados": self.eventos_analisados,
            "eventos_reclassificados": len(self.eventos_reclassificados),
            "eventos_que_sao_notas": len(self.eventos_que_sao_notas),
            "notas_criadas": self.notas_criadas,
            "notas_analisadas": self.notas_analisadas,
            "notas_alteradas": len(self.notas_alteradas),
            "mudancas_por_status": dict(sorted(mudancas.items())),
            "revisao_manual": len(self.revisao_manual),
            "simples_corrigidas": self.simples_corrigidas,
            "alertas_recalculados": self.alertas_recalculados,
            "pdfs_regenerados": self.pdfs_regenerados,
            "xml_indisponivel": len(self.xml_indisponivel),
            "erros": len(self.erros),
        }


def _data_corte() -> date:
    return date.fromisoformat(os.getenv("NOTAS_DATA_CORTE", "2026-01-01").strip())


def _ler_xmls(storage: StorageService, chaves: list[str], workers: int) -> dict[str, bytes | None]:
    def ler(chave: str) -> tuple[str, bytes | None]:
        try:
            return chave, storage.get_bytes(chave)
        except Exception:
            return chave, None

    with ThreadPoolExecutor(max_workers=max(1, workers), thread_name_prefix="corrigir-xml") as executor:
        return dict(executor.map(ler, chaves))


def _resumo(xml: bytes | None, nome: str) -> dict[str, Any] | None:
    if not xml:
        return None
    try:
        SafeElementTree.fromstring(xml)
    except (ElementTree.ParseError, DefusedXmlException):
        return None
    return legacy_ingestion_service.parse_xml_resumo_bytes(xml, nome)


def _conferida(nota: Nota) -> bool:
    return str(nota.conferencia_status or "").strip().lower() not in {"", "pendente"}


def _corrigir_eventos(
    db: Session, storage: StorageService, relatorio: Relatorio, aplicar: bool, workers: int, empresa_id: int | None
) -> tuple[dict[tuple[int, str], str], set[tuple[int, str]]]:
    """Reclassifica eventos.

    Devolve {(empresa_id, chave): status imposto} e o conjunto de chaves que
    tem algum evento de verdade (inclusive sem efeito), usado como prova para
    tirar um cancelamento que so tinha solicitacao de analise.
    """
    query = db.query(Evento).filter(Evento.xml_storage_key.isnot(None))
    if empresa_id is not None:
        query = query.filter(Evento.empresa_id == empresa_id)
    eventos = query.order_by(Evento.id.asc()).all()
    relatorio.eventos_analisados = len(eventos)
    xmls = _ler_xmls(storage, sorted({e.xml_storage_key for e in eventos}), workers)

    impostos: dict[tuple[int, str], str] = {}
    com_evento: set[tuple[int, str]] = set()
    corte = _data_corte()
    for evento in eventos:
        resumo = _resumo(xmls.get(evento.xml_storage_key), Path(evento.xml_storage_key).name)
        if resumo is None:
            relatorio.xml_indisponivel.append({"evento_id": evento.id, "storage_key": evento.xml_storage_key})
            if str(evento.tipo_evento or "") in STATUS_ESPECIAIS and evento.chave_afetada:
                # Sem o XML nao ha como reclassificar: mantem o efeito atual.
                _impor(impostos, (evento.empresa_id, evento.chave_afetada), evento.tipo_evento)
            continue

        if resumo.get("tipo_xml") != "evento":
            data_nota = legacy_ingestion_service._parse_date(resumo.get("data_emissao") or "") or \
                legacy_ingestion_service._parse_date(resumo.get("competencia") or "")
            item = {
                "evento_id": evento.id,
                "empresa_id": evento.empresa_id,
                "chave": resumo.get("chave"),
                "storage_key": evento.xml_storage_key,
                "data_emissao": data_nota.isoformat() if data_nota else None,
                "acao": "ignorada_data_corte" if data_nota and data_nota < corte else "criar_nota",
            }
            relatorio.eventos_que_sao_notas.append(item)
            if item["acao"] == "criar_nota" and resumo.get("chave_substituida"):
                _impor(impostos, (evento.empresa_id, resumo["chave_substituida"]), "substituida")
            continue

        novo_tipo = resumo.get("status_documento") or "evento"
        if resumo.get("chave_afetada"):
            com_evento.add((evento.empresa_id, resumo["chave_afetada"]))
        if novo_tipo in STATUS_ESPECIAIS and resumo.get("chave_afetada"):
            _impor(impostos, (evento.empresa_id, resumo["chave_afetada"]), novo_tipo)
        if novo_tipo != (evento.tipo_evento or ""):
            relatorio.eventos_reclassificados.append(
                {
                    "evento_id": evento.id,
                    "codigo": resumo.get("codigo_evento"),
                    "de": evento.tipo_evento,
                    "para": novo_tipo,
                    "descricao": evento.descricao,
                }
            )
            if aplicar:
                evento.tipo_evento = novo_tipo
                db.commit()
    return impostos, com_evento


def _impor(impostos: dict[tuple[int, str], str], alvo: tuple[int, str], status: str) -> None:
    if prioridade_status(status) > prioridade_status(impostos.get(alvo)):
        impostos[alvo] = status


def _criar_notas_de_eventos(db: Session, storage: StorageService, relatorio: Relatorio, aplicar: bool) -> None:
    """Notas que foram gravadas como evento entram pela ingestao normal."""
    for item in relatorio.eventos_que_sao_notas:
        if item["acao"] != "criar_nota" or not aplicar:
            continue
        try:
            empresa = db.get(Empresa, item["empresa_id"])
            contexto = SimpleNamespace(id=None, empresa_id=int(empresa.id), empresa=empresa)
            with tempfile.TemporaryDirectory(prefix="corrigir_nota_") as pasta:
                base = Path(pasta)
                xml_path = base / Path(item["storage_key"]).name
                xml_path.write_bytes(storage.get_bytes(item["storage_key"]))
                (base / "index_nfse.csv").write_text(
                    "chave;xml_path;competencia\n" f"{item['chave']};{xml_path};{item['data_emissao'] or ''}\n",
                    encoding="utf-8",
                )
                resultado = legacy_ingestion_service.ingerir_saida_legado(
                    db, storage, contexto, base, gerar_pdf_espelho=False
                )
            if resultado.get("erros"):
                raise RuntimeError(json.dumps(resultado.get("erros_detalhes"), ensure_ascii=False)[:500])
            db.query(Evento).filter(Evento.id == item["evento_id"]).delete(synchronize_session=False)
            db.commit()
            relatorio.notas_criadas += int(resultado.get("notas_criadas") or 0)
        except Exception as exc:
            db.rollback()
            relatorio.erros.append({"etapa": "criar_nota", "evento_id": item["evento_id"], "erro": str(exc)[:500]})


def _notas_candidatas(
    db: Session, impostos: dict[tuple[int, str], str], empresa_id: int | None
) -> list[Nota]:
    query = db.query(Nota).filter(
        or_(Nota.status_documento.in_(STATUS_ESPECIAIS), Nota.status_documento.like("cstat_%"))
    )
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    notas = {int(n.id): n for n in query.all()}
    por_empresa: dict[int, list[str]] = defaultdict(list)
    for emp, chave in impostos:
        por_empresa[emp].append(chave)
    for emp, chaves in por_empresa.items():
        for inicio in range(0, len(chaves), 500):
            for nota in db.query(Nota).filter(Nota.empresa_id == emp, Nota.chave.in_(chaves[inicio : inicio + 500])):
                notas[int(nota.id)] = nota
    return sorted(notas.values(), key=lambda n: int(n.id))


def _corrigir_notas(
    db: Session,
    storage: StorageService,
    relatorio: Relatorio,
    impostos: dict[tuple[int, str], str],
    com_evento: set[tuple[int, str]],
    aplicar: bool,
    workers: int,
    empresa_id: int | None,
) -> list[int]:
    notas = _notas_candidatas(db, impostos, empresa_id)
    relatorio.notas_analisadas = len(notas)
    xmls = _ler_xmls(storage, sorted({n.xml_storage_key for n in notas if n.xml_storage_key}), workers)
    resumos = {int(n.id): _resumo(xmls.get(n.xml_storage_key), f"{n.chave}.xml") for n in notas}

    # Notas substitutas (chSubstda) impoem "substituida" a nota antiga, que
    # pode ainda nao estar entre as candidatas.
    for nota in notas:
        resumo = resumos[int(nota.id)]
        if resumo and resumo.get("chave_substituida"):
            _impor(impostos, (int(nota.empresa_id), resumo["chave_substituida"]), "substituida")
    notas = _notas_candidatas(db, impostos, empresa_id)
    faltantes = [n for n in notas if int(n.id) not in resumos]
    if faltantes:
        extra = _ler_xmls(storage, sorted({n.xml_storage_key for n in faltantes if n.xml_storage_key}), workers)
        for n in faltantes:
            resumos[int(n.id)] = _resumo(extra.get(n.xml_storage_key), f"{n.chave}.xml")
    relatorio.notas_analisadas = len(notas)

    alteradas: list[int] = []
    for nota in notas:
        resumo = resumos.get(int(nota.id))
        candidatos: list[tuple[str | None, str | None]] = []
        if resumo is not None:
            candidatos.append((resumo.get("status_documento") or None, resumo.get("status_rotulo") or None))
        else:
            relatorio.xml_indisponivel.append({"nota_id": nota.id, "storage_key": nota.xml_storage_key})
            candidatos.append((nota.status_documento, nota.status_rotulo))
        imposto = impostos.get((int(nota.empresa_id), nota.chave))
        if imposto:
            candidatos.append((imposto, ROTULOS[imposto]))
        status, rotulo = max(candidatos, key=lambda item: prioridade_status(item[0]))
        atual = str(nota.status_documento or "").strip().lower()
        if atual in STATUS_ESPECIAIS and prioridade_status(status) < prioridade_status(atual):
            # So rebaixa com prova: o XML da nota nao muda quando ela e
            # cancelada, entao "cStat 100" sozinho nao desmente um cancelamento.
            provas = {
                "cancelada": (int(nota.empresa_id), nota.chave) in com_evento,
                "substituida": bool(resumo and resumo.get("chave_substituida")),
            }
            if not provas[atual]:
                relatorio.revisao_manual.append(
                    {
                        "nota_id": nota.id,
                        "chave": nota.chave,
                        "status_atual": nota.status_documento,
                        "status_sugerido": status,
                        "motivo": "sem_evidencia_para_rebaixar",
                    }
                )
                continue
        if (status or None) == (nota.status_documento or None) and (rotulo or None) == (nota.status_rotulo or None):
            continue
        mudanca = {
            "nota_id": nota.id,
            "empresa_id": nota.empresa_id,
            "chave": nota.chave,
            "numero": nota.numero_nfse,
            "de": nota.status_documento,
            "para": status,
            "rotulo_de": nota.status_rotulo,
            "rotulo_para": rotulo,
            "motivo": "evento" if imposto and imposto == status else "xml_da_nota",
        }
        muda_status = (status or None) != (nota.status_documento or None)
        if muda_status and _conferida(nota):
            relatorio.revisao_manual.append({**mudanca, "conferencia_status": nota.conferencia_status})
            continue
        relatorio.notas_alteradas.append(mudanca)
        if aplicar:
            nota.status_documento = status
            nota.status_rotulo = rotulo
            db.commit()
        if muda_status:
            alteradas.append(int(nota.id))
    return alteradas


def _corrigir_simples_e_alertas(
    db: Session, storage: StorageService, relatorio: Relatorio, aplicar: bool, empresa_id: int | None
) -> None:
    query = db.query(Nota)
    if empresa_id is not None:
        query = query.filter(Nota.empresa_id == empresa_id)
    ultimo_id = 0
    while True:
        lote = query.filter(Nota.id > ultimo_id).order_by(Nota.id.asc()).limit(1000).all()
        if not lote:
            break
        for nota in lote:
            ultimo_id = int(nota.id)
            esperado = calcular_status_simples_nacional_xml(
                normalizar_simples_xml(nota.simples_xml or nota.simples_nacional_xml)
            )
            # A ingestao grava exatamente este calculo; diferenca e valor da tela.
            # Vazio nao e valor da tela: fica como esta.
            if nota.status_simples_nacional is not None and nota.status_simples_nacional != esperado:
                relatorio.simples_corrigidas += 1
                if aplicar:
                    nota.status_simples_nacional = esperado
            if ALERTA_DA_TELA in str(nota.alertas_fiscais or "") and nota.xml_storage_key:
                resumo = _resumo(_ler_xmls(storage, [nota.xml_storage_key], 1).get(nota.xml_storage_key), "nota.xml")
                if resumo is not None:
                    relatorio.alertas_recalculados += 1
                    if aplicar:
                        nota.alertas_fiscais = resumo.get("alertas_fiscais") or None
        if aplicar:
            db.commit()


def _regenerar_pdfs(db: Session, storage: StorageService, relatorio: Relatorio, nota_ids: list[int]) -> None:
    from backend.app.core.php_runtime import configurar_php
    from backend.app.services.danfse_service import DanfseService

    configurar_php()
    for nota_id in nota_ids:
        nota = db.get(Nota, nota_id)
        if nota is None or not nota.xml_storage_key or not nota.pdf_espelho_storage_key:
            continue
        try:
            marca = nota.status_documento if nota.status_documento in STATUS_ESPECIAIS else None
            pdf, _ = DanfseService().generate(storage.get_bytes(nota.xml_storage_key), watermark=marca)
            meta = storage.put_bytes(nota.pdf_espelho_storage_key, pdf, content_type="application/pdf")
            for arquivo in db.query(Arquivo).filter(Arquivo.storage_key == nota.pdf_espelho_storage_key):
                arquivo.tamanho_bytes = int(meta.get("size") or len(pdf))
                arquivo.checksum = hashlib.sha256(pdf).hexdigest()
            db.commit()
            relatorio.pdfs_regenerados += 1
        except Exception as exc:
            db.rollback()
            relatorio.erros.append({"etapa": "pdf", "nota_id": nota_id, "erro": str(exc)[:500]})


def executar(
    aplicar: bool = False,
    regenerar_pdf: bool = False,
    empresa_id: int | None = None,
    workers: int = 16,
    storage: StorageService | None = None,
) -> Relatorio:
    init_db()
    storage = storage or get_storage_service()
    relatorio = Relatorio(modo="aplicacao" if aplicar else "simulacao", gerado_em=datetime.now(timezone.utc).isoformat())
    with SessionLocal() as db:
        impostos, com_evento = _corrigir_eventos(db, storage, relatorio, aplicar, workers, empresa_id)
        _criar_notas_de_eventos(db, storage, relatorio, aplicar)
        alteradas = _corrigir_notas(db, storage, relatorio, impostos, com_evento, aplicar, workers, empresa_id)
        _corrigir_simples_e_alertas(db, storage, relatorio, aplicar, empresa_id)
        if aplicar and regenerar_pdf:
            _regenerar_pdfs(db, storage, relatorio, alteradas)
    return relatorio


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--aplicar", action="store_true", help="Grava as correcoes; sem esta opcao apenas simula.")
    parser.add_argument("--regenerar-pdf", action="store_true", help="Refaz o PDF espelho das notas alteradas (exige PHP).")
    parser.add_argument("--empresa-id", type=int, default=None)
    parser.add_argument("--workers", type=int, default=16, help="Leituras paralelas no storage.")
    parser.add_argument("--relatorio", default="relatorio_corrigir_status_fiscal.json")
    args = parser.parse_args(argv)

    relatorio = executar(
        aplicar=args.aplicar, regenerar_pdf=args.regenerar_pdf, empresa_id=args.empresa_id, workers=args.workers
    )
    Path(args.relatorio).write_text(
        json.dumps({"resumo": relatorio.resumo(), **relatorio.__dict__}, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(relatorio.resumo(), ensure_ascii=False, indent=2))
    print(f"Relatorio completo: {args.relatorio}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
