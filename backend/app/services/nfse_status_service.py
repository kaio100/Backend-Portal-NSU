"""Classificacao fiscal de um XML do ADN: nota ou evento, e qual o seu status.

A decisao usa apenas a estrutura do documento (tag raiz, cStat e codigo do
evento). Texto livre (descricao do servico, nome da empresa, motivo digitado
pelo emitente) nunca decide status: "substituicao tributaria" na descricao ou
"EVENTOS LTDA" no nome ja marcaram notas validas como substituidas ou as
esconderam do portal.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass
from xml.etree import ElementTree

logger = logging.getLogger(__name__)

STATUS_AUTORIZADA = "autorizada"
STATUS_CANCELADA = "cancelada"
STATUS_SUBSTITUIDA = "substituida"

ROTULO_AUTORIZADA = "Autorizada"
ROTULO_CANCELADA = "Cancelada"
ROTULO_SUBSTITUIDA = "Substituida"

# cStat de NFS-e emitida e valida (leiaute nacional, grupo infNFSe).
# 101 e a nota NOVA de uma substituicao; a substituida e a nota antiga.
CSTAT_VALIDOS: dict[str, str] = {
    "100": ROTULO_AUTORIZADA,  # NFS-e gerada
    "101": ROTULO_AUTORIZADA,  # NFS-e de substituicao gerada
    "102": ROTULO_AUTORIZADA,  # NFS-e de decisao judicial
    "103": ROTULO_AUTORIZADA,  # NFS-e avulsa
    "107": "MEI",  # NFS-e de MEI
}

# Efeito de cada evento sobre a nota afetada. Codigos confirmados em XML
# reais do ADN. Evento que nao cancela nem substitui nao muda o status.
EVENTOS_CANCELAM = {
    "e101101",  # Cancelamento de NFS-e
    "e105104",  # Cancelamento de NFS-e Deferido por Analise Fiscal
}
EVENTOS_SUBSTITUEM = {
    "e105102",  # Cancelamento de NFS-e por Substituicao
}
EVENTOS_SEM_EFEITO = {
    "e101103",  # Solicitacao de Analise Fiscal para Cancelamento (so o pedido)
    "e105105",  # Cancelamento de NFS-e Indeferido por Analise Fiscal
    "e203202",  # Manifestacao - Confirmacao do Tomador
    "e203206",  # Manifestacao - Rejeicao do Tomador
}

# Reserva para eventos sem o grupo e###### (XML antigos ou montados a mao):
# comparacao da descricao INTEIRA, nunca "contem a palavra".
DESCRICOES_CANCELAM = {
    "cancelamento de nfs-e",
    "cancelamento de nfs-e deferido por analise fiscal",
    "cancelamento de nfs-e por oficio",
}
DESCRICOES_SUBSTITUEM = {
    "cancelamento de nfs-e por substituicao",
}

_RAIZES_EVENTO = {"evento", "eventonfse", "procevento", "proceventonfse"}
_RAIZES_NOTA = {"nfse", "compnfse"}
_CODIGO_EVENTO = re.compile(r"^e\d{6}$")


@dataclass(frozen=True)
class ClassificacaoXml:
    tipo: str  # "nota", "evento" ou "desconhecido"
    status: str | None
    rotulo: str | None
    codigo_evento: str | None = None
    chave_afetada: str | None = None  # evento: nota que ele atinge
    chave_substituida: str | None = None  # nota substituta: nota antiga


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _texto(root: ElementTree.Element, nome: str) -> str:
    alvo = nome.lower()
    for element in root.iter():
        if _local(element.tag).lower() == alvo and (element.text or "").strip():
            return element.text.strip()
    return ""


def _digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _normalizar(valor: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", valor or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def _codigo_evento(root: ElementTree.Element) -> str | None:
    for element in root.iter():
        nome = _local(element.tag)
        if _CODIGO_EVENTO.match(nome):
            return nome
    return None


def _classificar_evento(root: ElementTree.Element) -> ClassificacaoXml:
    codigo = _codigo_evento(root)
    descricao = _normalizar(_texto(root, "xDesc"))
    chave_afetada = _digitos(_texto(root, "chNFSe")) or None

    if codigo in EVENTOS_CANCELAM:
        status, rotulo = STATUS_CANCELADA, ROTULO_CANCELADA
    elif codigo in EVENTOS_SUBSTITUEM:
        status, rotulo = STATUS_SUBSTITUIDA, ROTULO_SUBSTITUIDA
    elif codigo in EVENTOS_SEM_EFEITO:
        status, rotulo = None, None
    elif descricao in DESCRICOES_CANCELAM:
        status, rotulo = STATUS_CANCELADA, ROTULO_CANCELADA
    elif descricao in DESCRICOES_SUBSTITUEM:
        status, rotulo = STATUS_SUBSTITUIDA, ROTULO_SUBSTITUIDA
    else:
        status, rotulo = None, None
        logger.warning(
            "Evento de NFS-e desconhecido nao altera status: codigo=%s descricao=%s",
            codigo or "-",
            descricao or "-",
        )
    return ClassificacaoXml(
        tipo="evento",
        status=status,
        rotulo=rotulo,
        codigo_evento=codigo,
        chave_afetada=chave_afetada,
    )


def _classificar_nota(root: ElementTree.Element) -> ClassificacaoXml:
    cstat = _texto(root, "cStat")
    chave_substituida = _digitos(_texto(root, "chSubstda")) or None
    if cstat in CSTAT_VALIDOS:
        return ClassificacaoXml(
            tipo="nota",
            status=STATUS_AUTORIZADA,
            rotulo=CSTAT_VALIDOS[cstat],
            chave_substituida=chave_substituida,
        )
    if cstat:
        logger.warning("NFS-e com cStat desconhecido: %s", cstat)
        return ClassificacaoXml(
            tipo="nota",
            status=f"cstat_{cstat}",
            rotulo=f"Codigo {cstat}",
            chave_substituida=chave_substituida,
        )
    return ClassificacaoXml(tipo="nota", status=None, rotulo=None, chave_substituida=chave_substituida)


def classificar_xml(root: ElementTree.Element) -> ClassificacaoXml:
    raiz = _local(root.tag).lower()
    if raiz in _RAIZES_EVENTO:
        return _classificar_evento(root)
    if raiz in _RAIZES_NOTA:
        return _classificar_nota(root)
    logger.warning("XML com raiz desconhecida tratado como nota sem status: %s", raiz)
    return ClassificacaoXml(tipo="nota", status=None, rotulo=None)


def prioridade_status(status: str | None) -> int:
    """Cancelada prevalece sobre substituida, que prevalece sobre o resto."""
    return {STATUS_CANCELADA: 2, STATUS_SUBSTITUIDA: 1}.get((status or "").strip().lower(), 0)
