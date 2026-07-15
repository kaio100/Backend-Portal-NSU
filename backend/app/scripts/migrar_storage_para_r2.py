from __future__ import annotations

import argparse
from dataclasses import dataclass

from backend.app.core.config import settings
from backend.app.scripts.r2_common import build_r2_storage
from backend.app.services.storage_service import LocalFilesystemStorage, normalize_storage_prefix


@dataclass
class MigrationReport:
    total_encontrados: int = 0
    total_enviados: int = 0
    total_pulados: int = 0
    total_erros: int = 0
    bytes_enviados: int = 0


def _iter_batches(items: list[str], batch_size: int):
    safe_size = max(1, int(batch_size or 100))
    for index in range(0, len(items), safe_size):
        yield items[index : index + safe_size]


def migrate(prefix: str = "", dry_run: bool = True, batch_size: int = 100) -> MigrationReport:
    local = LocalFilesystemStorage(settings.storage_root)
    r2 = None if dry_run else build_r2_storage()
    normalized_prefix = normalize_storage_prefix(prefix)
    keys = local.list_keys(normalized_prefix)
    report = MigrationReport(total_encontrados=len(keys))

    for batch in _iter_batches(keys, batch_size):
        for key in batch:
            try:
                local_path = local.get_path(key)
                local_size = local_path.stat().st_size
                if dry_run:
                    report.total_pulados += 1
                    print(f"DRY-RUN upload {key} ({local_size} bytes)")
                    continue
                remote_size = r2.object_size(key)
                if remote_size == local_size:
                    report.total_pulados += 1
                    print(f"SKIP size-match {key}")
                    continue
                data = local_path.read_bytes()
                r2.put_bytes(key, data)
                report.total_enviados += 1
                report.bytes_enviados += len(data)
                print(f"UPLOAD {key} ({len(data)} bytes)")
            except Exception as exc:
                report.total_erros += 1
                print(f"ERROR {key}: {exc}")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migra arquivos do storage local para Cloudflare R2.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Lista acoes sem enviar arquivos.")
    mode.add_argument("--all", action="store_true", help="Envia todos os arquivos encontrados.")
    parser.add_argument("--prefix", default="", help="Prefixo relativo para migrar, ex.: xml ou pdf-oficial.")
    parser.add_argument("--batch-size", type=int, default=100, help="Quantidade de arquivos por lote.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = migrate(prefix=args.prefix, dry_run=bool(args.dry_run), batch_size=args.batch_size)
    print("")
    print("Relatorio final")
    print(f"total encontrados: {report.total_encontrados}")
    print(f"total enviados: {report.total_enviados}")
    print(f"total pulados: {report.total_pulados}")
    print(f"total com erro: {report.total_erros}")
    print(f"bytes enviados: {report.bytes_enviados}")
    return 1 if report.total_erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
