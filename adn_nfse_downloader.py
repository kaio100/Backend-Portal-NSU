# -*- coding: utf-8 -*-
"""
ADN NFS-e Downloader
====================

Baixa NFS-e do Ambiente de Dados Nacional usando certificado A1/A3 e CNPJ.

Uso principal:
  python adn_nfse_downloader.py baixar --limite 500 --pausa 8
  python adn_nfse_downloader.py baixar --inicio 400 --limite 300 --pausa 8
  python adn_nfse_downloader.py eventos --chave 2111300...
  python adn_nfse_downloader.py info-cert

Este arquivo substitui os scripts de teste antigos:
- nfse_fetcher.py
- baixar_nfse_adn.py
- ler_xml_adn.py
- teste_*.py
- ver_certificado.py
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import os
import re
import sys
import time
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from xml.etree import ElementTree as ET

import requests_pkcs12
from dotenv import load_dotenv

try:
    from cryptography.hazmat.backends import default_backend
    from cryptography.hazmat.primitives.serialization import pkcs12
except Exception:  # pragma: no cover
    pkcs12 = None
    default_backend = None


# =============================================================================
# Pastas de saída
# =============================================================================

ROOT_OUT = Path("saida_adn_nfse")
DIR_JSON = ROOT_OUT / "json"
DIR_XML = ROOT_OUT / "xml"
DIR_DANFSE = ROOT_OUT / "danfse"
DIR_RAW = ROOT_OUT / "raw"
DIR_ESTADO = ROOT_OUT / "estado"

# index_nfse.csv = notas únicas por chave.
INDEX_UNICO_FILE = ROOT_OUT / "index_nfse.csv"

# ocorrencias_nsu.csv = trilha completa de distribuição por NSU, inclusive chave repetida.
OCORRENCIAS_FILE = ROOT_OUT / "ocorrencias_nsu.csv"

for folder in [ROOT_OUT, DIR_JSON, DIR_XML, DIR_DANFSE, DIR_RAW, DIR_ESTADO]:
    folder.mkdir(parents=True, exist_ok=True)


OFICIAL_LINKS = {
    "gov_docs_apis": "https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/apis-prod-restrita-e-producao",
    "adn_contribuintes_producao_docs": "https://adn.nfse.gov.br/contribuintes/docs/index.html",
    "adn_contribuintes_restrita_docs": "https://adn.producaorestrita.nfse.gov.br/contribuintes/docs/index.html",
    "adn_danfse_producao_docs": "https://adn.nfse.gov.br/danfse/docs/index.html",
    "adn_danfse_restrita_docs": "https://adn.producaorestrita.nfse.gov.br/danfse/docs/index.html",
    "parametros_municipais_producao_docs": "https://adn.nfse.gov.br/parametrizacao/docs/index.html",
    "parametros_municipais_restrita_docs": "https://adn.producaorestrita.nfse.gov.br/parametrizacao/docs/index.html",
}


# =============================================================================
# Utilitários
# =============================================================================


def limpar(valor: Optional[str]) -> str:
    return (valor or "").strip().strip('"').strip("'")


def so_digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def str_bool(valor: Optional[str], default: bool = True) -> bool:
    if valor is None or str(valor).strip() == "":
        return default
    return str(valor).strip().lower() in {"1", "true", "sim", "s", "yes", "y"}


def agora_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def salvar_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# =============================================================================
# Configuração
# =============================================================================


load_dotenv()


@dataclass
class Config:
    ambiente: str
    pfx_path: str
    pfx_password: str
    cnpj: str
    verify_ssl: bool
    base_contribuintes: str
    base_danfse: str

    @staticmethod
    def from_env(ambiente_cli: Optional[str] = None) -> "Config":
        ambiente = limpar(ambiente_cli or os.getenv("NFSE_AMBIENTE", "producao")).lower()
        if ambiente not in {"producao", "restrita"}:
            raise ValueError("NFSE_AMBIENTE precisa ser 'producao' ou 'restrita'.")

        if ambiente == "producao":
            base_contribuintes = "https://adn.nfse.gov.br/contribuintes"
            base_danfse = "https://adn.nfse.gov.br/danfse"
        else:
            base_contribuintes = "https://adn.producaorestrita.nfse.gov.br/contribuintes"
            base_danfse = "https://adn.producaorestrita.nfse.gov.br/danfse"

        cfg = Config(
            ambiente=ambiente,
            pfx_path=limpar(os.getenv("NFSE_PFX_PATH", "")),
            pfx_password=limpar(os.getenv("NFSE_PFX_PASSWORD", "")),
            cnpj=so_digitos(os.getenv("NFSE_CNPJ", "")),
            verify_ssl=str_bool(os.getenv("NFSE_VERIFY_SSL", "true"), default=True),
            base_contribuintes=base_contribuintes,
            base_danfse=base_danfse,
        )
        cfg.validar()
        return cfg

    def validar(self) -> None:
        if not self.pfx_path:
            raise RuntimeError("NFSE_PFX_PATH não configurado no .env")
        if not self.pfx_password:
            raise RuntimeError("NFSE_PFX_PASSWORD não configurado no .env")
        if not self.cnpj or len(self.cnpj) != 14:
            raise RuntimeError("NFSE_CNPJ precisa ter 14 dígitos no .env")
        if not Path(self.pfx_path).exists():
            raise RuntimeError(f"Certificado não encontrado: {self.pfx_path}")


# =============================================================================
# Estado por CNPJ
# =============================================================================


def state_file(cnpj: str) -> Path:
    return DIR_ESTADO / f"estado_nsu_{so_digitos(cnpj)}.json"


def carregar_estado(cnpj: str) -> Dict[str, Any]:
    path = state_file(cnpj)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("cnpj") == cnpj:
                return data
        except Exception:
            pass

    # Compatibilidade com versões antigas que gravavam em saida_adn_nfse/estado_nsu.json.
    legacy = ROOT_OUT / "estado_nsu.json"
    if legacy.exists():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            if data.get("cnpj") == cnpj:
                return data
        except Exception:
            pass

    return {"cnpj": cnpj, "ultimo_nsu": 0, "atualizado_em": None}


def salvar_estado(cnpj: str, ultimo_nsu: int) -> None:
    data = {"cnpj": cnpj, "ultimo_nsu": int(ultimo_nsu), "atualizado_em": agora_iso()}
    salvar_json(state_file(cnpj), data)
    # Arquivo legado para facilitar visualização rápida.
    salvar_json(ROOT_OUT / "estado_nsu.json", data)


# =============================================================================
# HTTP ADN com mTLS
# =============================================================================


TEMPORARY_STATUS = {429, 502, 503, 504}


def mtls_get(
    cfg: Config,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    accept: str = "application/json, text/plain, */*",
    timeout: int = 240,
):
    headers = {
        "Accept": accept,
        "User-Agent": "Mozilla/5.0 ADN-NFSe-Downloader/2.0",
    }
    return requests_pkcs12.get(
        url,
        params=params or {},
        headers=headers,
        pkcs12_filename=cfg.pfx_path,
        pkcs12_password=cfg.pfx_password,
        timeout=timeout,
        verify=cfg.verify_ssl,
    )


def requisicao_json_com_retry(
    cfg: Config,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    tentativas: int = 5,
    pausa_base: int = 20,
) -> Dict[str, Any]:
    ultimo_texto = ""

    for tentativa in range(1, tentativas + 1):
        print(f"Tentativa {tentativa}/{tentativas}: {url}")
        if params:
            print(f"Params: {params}")

        try:
            resp = mtls_get(cfg, url, params=params)
            status = resp.status_code
            ctype = resp.headers.get("content-type", "")
            ultimo_texto = resp.text or ""
            print(f"HTTP {status} | {ctype}")

            if status in TEMPORARY_STATUS:
                retry_after = resp.headers.get("Retry-After")
                espera = int(retry_after) if retry_after and retry_after.isdigit() else min(pausa_base * tentativa, 300)
                print(f"Erro temporário {status}. Aguardando {espera}s...\n")
                time.sleep(espera)
                continue

            if status not in {200, 400, 404}:
                raise RuntimeError(f"Erro HTTP {status}: {ultimo_texto[:1500]}")

            try:
                return resp.json()
            except Exception as exc:
                raise RuntimeError(f"Resposta não veio em JSON. HTTP {status}: {ultimo_texto[:1500]}") from exc

        except KeyboardInterrupt:
            raise
        except Exception as exc:
            if tentativa >= tentativas:
                raise
            espera = min(pausa_base * tentativa, 300)
            print(f"Erro: {exc}")
            print(f"Aguardando {espera}s...\n")
            time.sleep(espera)

    raise RuntimeError(f"Falhou após {tentativas} tentativas. Última resposta: {ultimo_texto[:1500]}")


# =============================================================================
# XML / Índices
# =============================================================================


def decode_xml_gzip_base64(valor_base64: str) -> str:
    bruto = base64.b64decode(valor_base64)
    xml_bytes = gzip.decompress(bruto)
    return xml_bytes.decode("utf-8", errors="replace")


def local_name(tag: str) -> str:
    nome = tag.split("}", 1)[-1] if "}" in tag else tag
    return nome.split(":", 1)[-1] if ":" in nome else nome


def find_first_text(root: ET.Element, tag_name: str) -> str:
    alvo = tag_name.lower()
    for elem in root.iter():
        if local_name(elem.tag).lower() == alvo and elem.text and elem.text.strip():
            return elem.text.strip()
    return ""


def first_text(root: ET.Element, nomes: Iterable[str]) -> str:
    nomes_set = {n.lower() for n in nomes}
    for elem in root.iter():
        if local_name(elem.tag).lower() in nomes_set and elem.text and elem.text.strip():
            return elem.text.strip()
    return ""


def child_text(parent: ET.Element, nomes: Iterable[str]) -> str:
    nomes_set = {n.lower() for n in nomes}
    for elem in parent.iter():
        if elem is parent:
            continue
        if local_name(elem.tag).lower() in nomes_set and elem.text and elem.text.strip():
            return elem.text.strip()
    return ""


def find_group(root: ET.Element, group_names: Iterable[str]) -> Optional[ET.Element]:
    names = {n.lower() for n in group_names}
    for elem in root.iter():
        if local_name(elem.tag).lower() in names:
            return elem
    return None


def find_text_inside(root: ET.Element, parent_names: Iterable[str], child_name: str) -> str:
    pais = {n.lower() for n in parent_names}
    filho = child_name.lower()
    for elem in root.iter():
        if local_name(elem.tag).lower() not in pais:
            continue
        for child in elem.iter():
            if child is elem:
                continue
            if local_name(child.tag).lower() == filho and child.text and child.text.strip():
                return child.text.strip()
    return ""


def extract_prestador_nome(root: ET.Element) -> str:
    nome_emit = find_text_inside(root, ["emit"], "xNome")
    if nome_emit:
        return nome_emit

    nome_prestador = find_text_inside(
        root,
        ["prest", "Prestador", "prestador", "PrestadorServico"],
        "xNome",
    )
    if nome_prestador:
        return nome_prestador

    prest = find_group(root, ["prest", "prestador", "PrestadorServico", "Prestador"])
    if prest is not None:
        return child_text(prest, ["xNome", "RazaoSocial", "Nome", "nome"])

    return ""


def parse_xml_resumo(xml_texto: str) -> Dict[str, str]:
    resumo = {
        "numero_nfse": "",
        "data_emissao": "",
        "competencia": "",
        "valor_servico": "",
        "valor_liquido": "",
        "prestador_cnpj": "",
        "prestador_nome": "",
        "tomador_cnpj": "",
        "tomador_nome": "",
        "municipio_prestacao": "",
    }

    try:
        root = ET.fromstring(xml_texto)
    except Exception:
        return resumo

    resumo["numero_nfse"] = find_first_text(root, "nNFSe")
    resumo["data_emissao"] = first_text(root, ["dhEmi", "dhProc", "DataEmissao", "dataEmissao"])
    resumo["competencia"] = first_text(root, ["dCompet", "Competencia", "competencia"])
    resumo["valor_servico"] = first_text(root, ["vServ", "ValorServicos", "ValorServico", "valorServico"])
    resumo["valor_liquido"] = first_text(root, ["vLiq", "ValorLiquidoNfse", "ValorLiquido", "valorLiquido"])
    resumo["municipio_prestacao"] = first_text(root, ["cLocPrestacao", "xLocPrestacao", "LocalPrestacao"])

    prest = find_group(root, ["prest", "prestador", "PrestadorServico", "Prestador"])
    toma = find_group(root, ["toma", "tomador", "TomadorServico", "Tomador"])

    resumo["prestador_nome"] = extract_prestador_nome(root)

    if prest is not None:
        resumo["prestador_cnpj"] = child_text(prest, ["CNPJ", "Cnpj", "cnpj"])

    if toma is not None:
        resumo["tomador_cnpj"] = child_text(toma, ["CNPJ", "Cnpj", "cnpj"])
        resumo["tomador_nome"] = child_text(toma, ["xNome", "RazaoSocial", "Nome", "nome"])

    return resumo


def sanitize_filename_part(value: str, max_length: int = 120, replace_spaces: bool = False) -> str:
    texto = unicodedata.normalize("NFKD", value or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r'[<>:"/\\|?*]', "", texto)
    texto = re.sub(r"[\r\n\t]+", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    texto = texto.rstrip(" .")
    if replace_spaces:
        texto = texto.replace(" ", "_")
    texto = re.sub(r"_+", "_", texto)
    texto = texto[:max_length].rstrip(" ._")
    return texto


def build_xml_filename(nsu: str, chave: str, xml_texto: str) -> Tuple[str, Dict[str, str], bool]:
    resumo = parse_xml_resumo(xml_texto)
    prestador = sanitize_filename_part(resumo.get("prestador_nome", ""), replace_spaces=True)
    numero = sanitize_filename_part(resumo.get("numero_nfse", ""), max_length=40)

    if prestador and numero:
        return f"{prestador} NFS-e {numero}.xml", resumo, True

    fallback = f"{sanitize_filename_part(nsu, max_length=40)}_{sanitize_filename_part(chave, max_length=80)}.xml"
    return fallback, resumo, False


def resolve_xml_path(filename: str, nsu: str, chave: str, xml_texto: str) -> Path:
    path = DIR_XML / filename
    if not path.exists():
        return path

    try:
        if path.read_text(encoding="utf-8", errors="replace") == xml_texto:
            return path
    except Exception:
        pass

    stem = path.stem
    suffix = path.suffix
    candidatos = [
        DIR_XML / f"{stem}_NSU{sanitize_filename_part(nsu, max_length=40)}{suffix}",
        DIR_XML / f"{stem}_{sanitize_filename_part(chave[-8:], max_length=20)}{suffix}",
    ]
    for candidato in candidatos:
        if not candidato.exists():
            return candidato
        try:
            if candidato.read_text(encoding="utf-8", errors="replace") == xml_texto:
                return candidato
        except Exception:
            pass

    contador = 2
    while True:
        candidato = DIR_XML / f"{stem}_{contador}{suffix}"
        if not candidato.exists():
            return candidato
        try:
            if candidato.read_text(encoding="utf-8", errors="replace") == xml_texto:
                return candidato
        except Exception:
            pass
        contador += 1


def save_xml_file(nsu: str, chave: str, xml_texto: str) -> Tuple[Path, Dict[str, str], bool]:
    filename, resumo, nome_bonito = build_xml_filename(nsu, chave, xml_texto)
    xml_path = resolve_xml_path(filename, nsu, chave, xml_texto)
    if not xml_path.exists():
        xml_path.write_text(xml_texto, encoding="utf-8")
    return xml_path, resumo, nome_bonito


INDEX_FIELDS = [
    "chave",
    "primeiro_nsu",
    "ultimo_nsu",
    "qtd_ocorrencias",
    "tipo_documento",
    "numero_nfse",
    "data_emissao",
    "competencia",
    "prestador_cnpj",
    "prestador_nome",
    "tomador_cnpj",
    "tomador_nome",
    "valor_servico",
    "valor_liquido",
    "arquivo_xml",
    "json_path",
    "xml_path",
    "atualizado_em",
]

OCORRENCIA_FIELDS = [
    "nsu",
    "chave",
    "tipo_documento",
    "json_path",
    "xml_path",
    "registrado_em",
]


def carregar_csv_por_chave(path: Path, chave_col: str) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {}
    rows: Dict[str, Dict[str, str]] = {}
    text = path.read_text(encoding="utf-8-sig", errors="replace").replace("\x00", "")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        chave = row.get(chave_col, "")
        if chave:
            rows[chave] = row
    return rows


def salvar_index_unico(rows: Dict[str, Dict[str, str]]) -> None:
    def sort_key(item: Tuple[str, Dict[str, str]]):
        nsu = item[1].get("primeiro_nsu", "")
        return int(nsu) if str(nsu).isdigit() else 0

    with INDEX_UNICO_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=INDEX_FIELDS, delimiter=";")
        writer.writeheader()
        for _, row in sorted(rows.items(), key=sort_key):
            writer.writerow({k: row.get(k, "") for k in INDEX_FIELDS})


def carregar_ocorrencias() -> Dict[Tuple[str, str], Dict[str, str]]:
    if not OCORRENCIAS_FILE.exists():
        return {}
    rows: Dict[Tuple[str, str], Dict[str, str]] = {}
    text = OCORRENCIAS_FILE.read_text(encoding="utf-8-sig", errors="replace").replace("\x00", "")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        key = (row.get("nsu", ""), row.get("chave", ""))
        rows[key] = row
    return rows


def salvar_ocorrencias(rows: Dict[Tuple[str, str], Dict[str, str]]) -> None:
    def sort_key(item: Tuple[Tuple[str, str], Dict[str, str]]):
        nsu = item[0][0]
        return int(nsu) if str(nsu).isdigit() else 0

    with OCORRENCIAS_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OCORRENCIA_FIELDS, delimiter=";")
        writer.writeheader()
        for _, row in sorted(rows.items(), key=sort_key):
            writer.writerow({k: row.get(k, "") for k in OCORRENCIA_FIELDS})


def upsert_indexes(row_unico: Dict[str, str], ocorrencia: Dict[str, str]) -> None:
    index_rows = carregar_csv_por_chave(INDEX_UNICO_FILE, "chave")
    ocorrencias = carregar_ocorrencias()
    chave = row_unico["chave"]
    ocorrencia_key = (ocorrencia["nsu"], ocorrencia["chave"])

    existente = index_rows.get(chave)
    if existente:
        # Mantém a nota como única por chave, mas atualiza último NSU e contador.
        existente_qtd = int(existente.get("qtd_ocorrencias") or "1")
        existente["ultimo_nsu"] = row_unico.get("ultimo_nsu", existente.get("ultimo_nsu", ""))
        if ocorrencia_key not in ocorrencias:
            existente["qtd_ocorrencias"] = str(max(existente_qtd, 1) + 1)
        else:
            existente["qtd_ocorrencias"] = str(max(existente_qtd, 1))
        existente["atualizado_em"] = agora_iso()
        # Se a linha antiga não tinha caminhos/resumo, preenche com o novo.
        campos_atualizaveis = {
            "numero_nfse",
            "data_emissao",
            "competencia",
            "prestador_cnpj",
            "prestador_nome",
            "tomador_cnpj",
            "tomador_nome",
            "valor_servico",
            "valor_liquido",
            "arquivo_xml",
            "json_path",
            "xml_path",
        }
        for k, v in row_unico.items():
            if v and (k in campos_atualizaveis or not existente.get(k)):
                existente[k] = v
        index_rows[chave] = existente
    else:
        index_rows[chave] = row_unico

    salvar_index_unico(index_rows)

    ocorrencias[ocorrencia_key] = ocorrencia
    salvar_ocorrencias(ocorrencias)


def salvar_documento(doc: Dict[str, Any]) -> Optional[int]:
    nsu = str(doc.get("NSU") or "").strip()
    chave = str(doc.get("ChaveAcesso") or "").strip()
    tipo = str(doc.get("TipoDocumento") or "NFSE").strip()
    arquivo_xml = doc.get("ArquivoXml")

    if not nsu or not chave:
        print("Documento sem NSU ou ChaveAcesso. Pulando.")
        return None

    json_path = DIR_JSON / f"{nsu}_{chave}.json"
    xml_path: Optional[Path] = None

    salvar_json(json_path, doc)

    resumo: Dict[str, str] = {}
    if arquivo_xml:
        try:
            xml_texto = decode_xml_gzip_base64(arquivo_xml)
            xml_path, resumo, _ = save_xml_file(nsu, chave, xml_texto)
            print(f"XML salvo: {xml_path}")
        except Exception as exc:
            print(f"Falha ao decodificar XML do NSU {nsu}: {exc}")
    else:
        print(f"NSU {nsu} não trouxe ArquivoXml.")

    row_unico = {
        "chave": chave,
        "primeiro_nsu": nsu,
        "ultimo_nsu": nsu,
        "qtd_ocorrencias": "1",
        "tipo_documento": tipo,
        "numero_nfse": resumo.get("numero_nfse", ""),
        "data_emissao": resumo.get("data_emissao", ""),
        "competencia": resumo.get("competencia", ""),
        "prestador_cnpj": resumo.get("prestador_cnpj", ""),
        "prestador_nome": resumo.get("prestador_nome", ""),
        "tomador_cnpj": resumo.get("tomador_cnpj", ""),
        "tomador_nome": resumo.get("tomador_nome", ""),
        "valor_servico": resumo.get("valor_servico", ""),
        "valor_liquido": resumo.get("valor_liquido", ""),
        "arquivo_xml": xml_path.name if xml_path and xml_path.exists() else "",
        "json_path": str(json_path),
        "xml_path": str(xml_path) if xml_path and xml_path.exists() else "",
        "atualizado_em": agora_iso(),
    }

    ocorrencia = {
        "nsu": nsu,
        "chave": chave,
        "tipo_documento": tipo,
        "json_path": str(json_path),
        "xml_path": str(xml_path) if xml_path and xml_path.exists() else "",
        "registrado_em": agora_iso(),
    }

    upsert_indexes(row_unico, ocorrencia)
    return int(nsu) if nsu.isdigit() else None


# =============================================================================
# Comandos
# =============================================================================


def cmd_links(_: argparse.Namespace) -> None:
    print("Links oficiais cadastrados:\n")
    for nome, url in OFICIAL_LINKS.items():
        print(f"- {nome}: {url}")


def cmd_info_cert(args: argparse.Namespace) -> None:
    cfg = Config.from_env(args.ambiente)

    if pkcs12 is None:
        print("Instale cryptography: pip install cryptography")
        return

    data = Path(cfg.pfx_path).read_bytes()
    _, cert, _ = pkcs12.load_key_and_certificates(
        data,
        cfg.pfx_password.encode("utf-8"),
        backend=default_backend(),
    )

    subject = cert.subject.rfc4514_string()
    issuer = cert.issuer.rfc4514_string()

    print("=" * 100)
    print("SUBJECT:")
    print(subject)
    print("=" * 100)
    print("ISSUER:")
    print(issuer)
    print("=" * 100)

    texto = subject + " " + issuer
    cnpjs = sorted(set(re.findall(r"\d{14}", texto)))
    print("Possíveis CNPJs encontrados:")
    for cnpj in cnpjs:
        print("-", cnpj)


def consultar_dfe(cfg: Config, nsu: int, lote: bool) -> Dict[str, Any]:
    url = f"{cfg.base_contribuintes}/DFe/{nsu}"
    params = {"cnpjConsulta": cfg.cnpj, "lote": str(lote).lower()}
    return requisicao_json_com_retry(cfg, url, params=params)


def cmd_baixar(args: argparse.Namespace) -> None:
    cfg = Config.from_env(args.ambiente)
    estado = carregar_estado(cfg.cnpj)

    nsu_atual = int(args.inicio if args.inicio is not None else estado.get("ultimo_nsu", 0))
    limite = int(args.limite)
    pausa = float(args.pausa)
    lote = bool(args.lote)
    max_vazios = int(args.vazios)

    print("=" * 100)
    print("BAIXADOR ADN NFS-e")
    print("=" * 100)
    print(f"Ambiente: {cfg.ambiente}")
    print(f"CNPJ: {cfg.cnpj}")
    print(f"NSU inicial: {nsu_atual}")
    print(f"Limite de consultas: {limite}")
    print(f"Pausa: {pausa}s")
    print(f"lote: {lote}")
    print(f"verify SSL: {cfg.verify_ssl}")
    print("=" * 100)

    vazios = 0

    for rodada in range(1, limite + 1):
        print("\n" + "-" * 100)
        print(f"Rodada {rodada}/{limite} | consultando a partir do NSU {nsu_atual}")
        print("-" * 100)

        resultado = consultar_dfe(cfg, nsu_atual, lote=lote)
        raw_path = DIR_RAW / f"dfe_consulta_nsu_{nsu_atual}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        salvar_json(raw_path, resultado)

        status_proc = resultado.get("StatusProcessamento")
        lote_dfe = resultado.get("LoteDFe") or []

        print(f"StatusProcessamento: {status_proc}")
        print(f"Documentos no lote: {len(lote_dfe)}")

        if not lote_dfe:
            vazios += 1
            print(f"Nenhum documento localizado. Vazios seguidos: {vazios}/{max_vazios}")
            if vazios >= max_vazios:
                print("Encerrando por excesso de respostas vazias.")
                break
            time.sleep(pausa)
            continue

        vazios = 0
        maior_nsu = nsu_atual

        for doc in lote_dfe:
            nsu_doc = salvar_documento(doc)
            if nsu_doc is not None and nsu_doc > maior_nsu:
                maior_nsu = nsu_doc

        if maior_nsu <= nsu_atual:
            print("A API não avançou o NSU. Encerrando para evitar loop infinito.")
            break

        nsu_atual = maior_nsu
        salvar_estado(cfg.cnpj, nsu_atual)
        print(f"Último NSU salvo: {nsu_atual}")
        print(f"Index notas únicas: {INDEX_UNICO_FILE}")
        print(f"Ocorrências NSU: {OCORRENCIAS_FILE}")

        time.sleep(pausa)

    print("\nFinalizado.")
    print(f"Último NSU: {nsu_atual}")
    print(f"XMLs: {DIR_XML}")
    print(f"Index notas únicas: {INDEX_UNICO_FILE}")
    print(f"Ocorrências NSU: {OCORRENCIAS_FILE}")


def cmd_eventos(args: argparse.Namespace) -> None:
    cfg = Config.from_env(args.ambiente)
    chave = so_digitos(args.chave)
    if not chave:
        raise RuntimeError("Informe --chave")

    url = f"{cfg.base_contribuintes}/NFSe/{chave}/Eventos"
    params = {"cnpjConsulta": cfg.cnpj}

    print(f"Consultando eventos da chave {chave}")
    resultado = requisicao_json_com_retry(cfg, url, params=params)

    raw_path = DIR_RAW / f"eventos_{chave}.json"
    salvar_json(raw_path, resultado)
    print(f"JSON bruto salvo: {raw_path}")

    print("StatusProcessamento:", resultado.get("StatusProcessamento"))
    lote_dfe = resultado.get("LoteDFe") or []
    print("Documentos:", len(lote_dfe))

    for doc in lote_dfe:
        salvar_documento(doc)

    if resultado.get("Erros"):
        print("Erros retornados:")
        print(json.dumps(resultado.get("Erros"), ensure_ascii=False, indent=2))


def cmd_danfse(args: argparse.Namespace) -> None:
    cfg = Config.from_env(args.ambiente)
    chave = so_digitos(args.chave)
    if not chave:
        raise RuntimeError("Informe --chave")

    url = f"{cfg.base_danfse}/{chave}"
    print(f"Baixando DANFSe: {url}")

    resp = mtls_get(
        cfg,
        url,
        accept="application/pdf, application/json, text/plain, */*",
        timeout=240,
    )
    ctype = resp.headers.get("content-type", "")
    print(f"HTTP {resp.status_code} | {ctype}")

    if resp.status_code in TEMPORARY_STATUS:
        print(resp.text[:1500])
        print("Erro temporário do ADN/DANFSe. Tente novamente com pausa.")
        return

    if "pdf" in ctype.lower() or resp.content[:4] == b"%PDF":
        path = DIR_DANFSE / f"{chave}.pdf"
        path.write_bytes(resp.content)
        print(f"PDF salvo: {path}")
        return

    path = DIR_DANFSE / f"{chave}.txt"
    path.write_text(resp.text or "", encoding="utf-8", errors="ignore")
    print(resp.text[:3000])
    print(f"Resposta salva: {path}")


def cmd_decode(args: argparse.Namespace) -> None:
    print(f"Decodificando JSONs em: {DIR_JSON}")
    total = 0
    for path in sorted(DIR_JSON.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data.get("ArquivoXml"):
                continue
            salvar_documento(data)
            total += 1
        except Exception as exc:
            print(f"Erro em {path}: {exc}")
    print(f"Documentos processados: {total}")
    print(f"XMLs: {DIR_XML}")
    print(f"Index notas únicas: {INDEX_UNICO_FILE}")
    print(f"Ocorrências NSU: {OCORRENCIAS_FILE}")


def cmd_resumo(_: argparse.Namespace) -> None:
    print("=" * 100)
    print("RESUMO LOCAL")
    print("=" * 100)
    print(f"Pasta: {ROOT_OUT.resolve()}")
    print(f"JSONs XML individuais: {len(list(DIR_JSON.glob('*.json')))}")
    print(f"XMLs salvos: {len(list(DIR_XML.glob('*.xml')))}")
    print(f"Raw responses: {len(list(DIR_RAW.glob('*.json')))}")

    if INDEX_UNICO_FILE.exists():
        with INDEX_UNICO_FILE.open("r", encoding="utf-8-sig", newline="") as f:
            qtd = max(sum(1 for _ in f) - 1, 0)
        print(f"Notas únicas no index_nfse.csv: {qtd}")
    else:
        print("Notas únicas no index_nfse.csv: 0")

    if OCORRENCIAS_FILE.exists():
        with OCORRENCIAS_FILE.open("r", encoding="utf-8-sig", newline="") as f:
            qtd = max(sum(1 for _ in f) - 1, 0)
        print(f"Ocorrências NSU no ocorrencias_nsu.csv: {qtd}")
    else:
        print("Ocorrências NSU no ocorrencias_nsu.csv: 0")


# =============================================================================
# CLI
# =============================================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ADN NFS-e Downloader")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("links", help="Lista links oficiais/documentações cadastradas")
    p.set_defaults(func=cmd_links)

    p = sub.add_parser("info-cert", help="Mostra CNPJ/subject do certificado configurado")
    p.add_argument("--ambiente", choices=["producao", "restrita"], default=None)
    p.set_defaults(func=cmd_info_cert)

    p = sub.add_parser("baixar", help="Baixa NFS-e por distribuição NSU")
    p.add_argument("--ambiente", choices=["producao", "restrita"], default=None)
    p.add_argument("--inicio", type=int, default=None, help="NSU inicial. Se omitido, usa estado salvo")
    p.add_argument("--limite", type=int, default=500, help="Máximo de consultas")
    p.add_argument("--pausa", type=float, default=8, help="Pausa entre consultas em segundos")
    p.add_argument("--vazios", type=int, default=8, help="Parar após N respostas vazias seguidas")
    p.add_argument("--lote", action="store_true", help="Usa lote=true. Por padrão usa lote=false")
    p.set_defaults(func=cmd_baixar)

    p = sub.add_parser("eventos", help="Consulta eventos/documentos vinculados a uma chave")
    p.add_argument("--ambiente", choices=["producao", "restrita"], default=None)
    p.add_argument("--chave", required=True)
    p.set_defaults(func=cmd_eventos)

    p = sub.add_parser("danfse", help="Tenta baixar DANFSe PDF por chave usando mTLS")
    p.add_argument("--ambiente", choices=["producao", "restrita"], default=None)
    p.add_argument("--chave", required=True)
    p.set_defaults(func=cmd_danfse)

    p = sub.add_parser("decode", help="Reprocessa JSONs salvos e gera XML/index")
    p.set_defaults(func=cmd_decode)

    p = sub.add_parser("resumo", help="Mostra contagem local de JSON/XML/index")
    p.set_defaults(func=cmd_resumo)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrompido pelo usuário.")
        sys.exit(130)
    except Exception as exc:
        print(f"\nERRO: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
