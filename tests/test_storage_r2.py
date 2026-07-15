from __future__ import annotations

from io import BytesIO

import pytest

from backend.app.core.config import settings
from backend.app.services import arquivos_service
from backend.app.services.storage_service import (
    LocalFilesystemStorage,
    R2StorageService,
    StorageKeyError,
    get_storage_service,
    normalize_storage_key,
)
from backend.app.scripts import migrar_storage_para_r2


class NotFoundError(Exception):
    response = {"Error": {"Code": "NoSuchKey"}, "ResponseMetadata": {"HTTPStatusCode": 404}}


class FakeR2Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict] = {}
        self.put_calls: list[dict] = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)
        self.objects[(kwargs["Bucket"], kwargs["Key"])] = {
            "Body": kwargs["Body"],
            "ContentType": kwargs.get("ContentType"),
        }
        return {}

    def get_object(self, Bucket: str, Key: str):
        try:
            item = self.objects[(Bucket, Key)]
        except KeyError:
            raise NotFoundError()
        return {"Body": BytesIO(item["Body"])}

    def head_object(self, Bucket: str, Key: str):
        try:
            item = self.objects[(Bucket, Key)]
        except KeyError:
            raise NotFoundError()
        return {"ContentLength": len(item["Body"])}

    def delete_object(self, Bucket: str, Key: str):
        self.objects.pop((Bucket, Key), None)
        return {}

    def list_objects_v2(self, Bucket: str, Prefix: str = "", **kwargs):
        contents = [
            {"Key": key}
            for bucket, key in sorted(self.objects)
            if bucket == Bucket and key.startswith(Prefix)
        ]
        return {"Contents": contents, "IsTruncated": False}

    def generate_presigned_url(self, ClientMethod: str, Params: dict, ExpiresIn: int):
        return f"https://example.test/{Params['Bucket']}/{Params['Key']}?expires={ExpiresIn}"


def test_local_storage_put_get_exists_delete(tmp_path):
    storage = LocalFilesystemStorage(tmp_path)
    meta = storage.put_bytes("xml/empresa_1/nota.xml", b"<xml/>", content_type="application/xml")

    assert meta["backend"] == "local"
    assert storage.exists("xml/empresa_1/nota.xml") is True
    assert storage.get_bytes("xml/empresa_1/nota.xml") == b"<xml/>"
    assert storage.list_prefix("xml") == ["xml/empresa_1/nota.xml"]
    assert storage.delete("xml/empresa_1/nota.xml") is True
    assert storage.exists("xml/empresa_1/nota.xml") is False


def test_r2_storage_uses_s3_compatible_client():
    client = FakeR2Client()
    storage = R2StorageService(
        bucket="bucket",
        endpoint_url="https://account.r2.cloudflarestorage.com",
        access_key_id="access",
        secret_access_key="secret",
        client=client,
    )

    meta = storage.put_bytes("pdf-oficial/empresa_1/a.pdf", b"%PDF", content_type="application/pdf")

    assert meta["backend"] == "r2"
    assert meta["key"] == "pdf-oficial/empresa_1/a.pdf"
    assert client.put_calls[0]["ContentType"] == "application/pdf"
    assert storage.exists("pdf-oficial/empresa_1/a.pdf") is True
    assert storage.object_size("pdf-oficial/empresa_1/a.pdf") == 4
    assert storage.get_bytes("pdf-oficial/empresa_1/a.pdf") == b"%PDF"
    assert storage.list_keys("pdf-oficial") == ["pdf-oficial/empresa_1/a.pdf"]
    assert storage.generate_presigned_url("pdf-oficial/empresa_1/a.pdf", 300).startswith("https://example.test/")
    assert storage.delete("pdf-oficial/empresa_1/a.pdf") is True
    assert storage.exists("pdf-oficial/empresa_1/a.pdf") is False


def test_storage_factory_returns_local(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))

    storage = get_storage_service()

    assert isinstance(storage, LocalFilesystemStorage)
    assert storage.root == tmp_path


def test_storage_factory_returns_r2(monkeypatch):
    created = {}

    class DummyR2(R2StorageService):
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr("backend.app.services.storage_service.R2StorageService", DummyR2)
    monkeypatch.setattr(settings, "storage_backend", "r2")
    monkeypatch.setattr(settings, "r2_bucket_name", "bucket")
    monkeypatch.setattr(settings, "r2_endpoint_url", "https://account.r2.cloudflarestorage.com")
    monkeypatch.setattr(settings, "r2_access_key_id", "access")
    monkeypatch.setattr(settings, "r2_secret_access_key", "secret")
    monkeypatch.setattr(settings, "r2_region", "auto")

    storage = get_storage_service()

    assert isinstance(storage, DummyR2)
    assert created["bucket"] == "bucket"
    assert created["region_name"] == "auto"


@pytest.mark.parametrize("key", ["/app/storage/xml/a.xml", "/xml/a.xml", "C:/storage/xml/a.xml"])
def test_storage_key_must_be_relative_and_not_app_storage(key):
    with pytest.raises(StorageKeyError):
        normalize_storage_key(key)


def test_migration_dry_run_does_not_upload(monkeypatch, tmp_path):
    local = LocalFilesystemStorage(tmp_path)
    local.put_bytes("xml/empresa_1/a.xml", b"<xml/>")
    fake_client = FakeR2Client()
    fake_r2 = R2StorageService("bucket", "https://example.test", "access", "secret", client=fake_client)
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(migrar_storage_para_r2, "build_r2_storage", lambda: fake_r2)

    report = migrar_storage_para_r2.migrate(prefix="xml", dry_run=True, batch_size=1)

    assert report.total_encontrados == 1
    assert report.total_enviados == 0
    assert report.total_pulados == 1
    assert fake_client.put_calls == []


def test_migration_skips_when_remote_size_matches(monkeypatch, tmp_path):
    local = LocalFilesystemStorage(tmp_path)
    local.put_bytes("pdf-oficial/empresa_1/a.pdf", b"12345")
    fake_client = FakeR2Client()
    fake_r2 = R2StorageService("bucket", "https://example.test", "access", "secret", client=fake_client)
    fake_r2.put_bytes("pdf-oficial/empresa_1/a.pdf", b"12345")
    fake_client.put_calls.clear()
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(migrar_storage_para_r2, "build_r2_storage", lambda: fake_r2)

    report = migrar_storage_para_r2.migrate(prefix="pdf-oficial", dry_run=False, batch_size=1)

    assert report.total_encontrados == 1
    assert report.total_enviados == 0
    assert report.total_pulados == 1
    assert fake_client.put_calls == []


def test_download_arquivo_uses_storage_service(monkeypatch):
    calls: list[tuple[str, str]] = []

    class FakeArquivo:
        id = 10
        tipo = "XML"
        storage_key = "xml/empresa_1/a.xml"
        filename = "a.xml"
        content_type = "application/xml"

    class FakeStorage:
        def exists(self, key: str) -> bool:
            calls.append(("exists", key))
            return True

        def get_bytes(self, key: str) -> bytes:
            calls.append(("get_bytes", key))
            return b"<xml/>"

    monkeypatch.setattr(arquivos_service.arquivos_repo, "get_arquivo", lambda db, arquivo_id: FakeArquivo())

    prepared = arquivos_service.preparar_download_arquivo(None, FakeStorage(), 10)

    assert prepared["data"] == b"<xml/>"
    assert calls == [("exists", "xml/empresa_1/a.xml"), ("get_bytes", "xml/empresa_1/a.xml")]
