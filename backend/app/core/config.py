from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "nfse-backend"
    app_version: str = "0.1.0"
    environment: str = "local"
    storage_backend: str = "local"
    storage_root: str = "storage"
    storage_bucket: str = "nfse"
    r2_bucket_name: str | None = None
    r2_account_id: str | None = None
    r2_endpoint_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_region: str = "auto"
    r2_presigned_expires_seconds: int = 300
    database_url: str = "sqlite:///./data/nfse_backend.db"
    worker_dry_run: bool = True
    worker_dry_run_sleep: float = 0.2
    worker_real_max_limite: int = 1000
    worker_real_max_pausa: float = 0.0
    worker_consulta_lote_tamanho: int = 1000
    worker_temp_dir: str = "data/tmp_worker"
    api_worker_enabled: bool = True
    api_worker_sleep: float = 0.2
    api_worker_concurrency: int = 1
    consultas_scheduler_sleep: float = 1
    consultas_default_limite: int = 1000
    consultas_default_pausa: float = 0.0
    notas_recebidas_dia_corte_mes_anterior: int = 3
    download_lote_max_notas: int = 10000
    download_storage_workers: int = 16
    download_temp_max_age_hours: int = 24
    pdf_status_revalidation_enabled: bool = True
    pdf_status_revalidation_batch_size: int = 200
    secrets_key: str | None = None
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    invertexto_enabled: bool = False
    invertexto_token: str | None = None
    invertexto_rpm: int = 30
    invertexto_delay_seconds: float = 0.6
    invertexto_cache_days: int = 30

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str | None) -> str:
        if not value:
            return "sqlite:///./data/nfse_backend.db"
        url = str(value).strip()
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url.removeprefix("postgresql://")
        return url

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
