from cryptography.fernet import Fernet
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "nfse-backend"
    app_version: str = "0.1.0"
    environment: str = "local"
    railway_environment_name: str | None = None
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
    database_pool_size: int = 5
    database_max_overflow: int = 5
    database_pool_timeout: int = 30
    database_pool_recycle: int = 300
    worker_dry_run: bool = True
    worker_dry_run_sleep: float = 0.2
    worker_real_max_limite: int = 1000
    worker_real_max_pausa: float = 0.0
    worker_consulta_lote_tamanho: int = 1000
    worker_adn_lote: bool = True
    worker_pdf_official_max_per_job: int = 25
    worker_pdf_official_delay_seconds: float = 0.5
    worker_temp_dir: str = "data/tmp_worker"
    api_worker_enabled: bool = True
    embedded_scheduler_enabled: bool = True
    api_worker_sleep: float = 0.2
    api_worker_concurrency: int = 1
    consultas_scheduler_sleep: float = 1
    consultas_default_limite: int = 1000
    consultas_default_pausa: float = 0.0
    nsu_lookback_normal: int = 50
    nsu_lookback_reconciliacao: int = 1000
    nsu_reconciliacao_hora_inicio: int = 19
    nsu_reconciliacao_hora_fim: int = 5
    nsu_reconciliacao_timezone: str = "America/Sao_Paulo"
    nsu_max_vazios_consecutivos: int = 5
    notas_recebidas_dia_corte_mes_anterior: int = 3
    download_lote_max_notas: int = 10000
    download_storage_workers: int = 16
    download_temp_max_age_hours: int = 24
    pdf_status_revalidation_enabled: bool = True
    pdf_status_revalidation_batch_size: int = 200
    certificado_upload_max_bytes: int = 5 * 1024 * 1024
    danfse_library_root: str = "backend/danfse"
    danfse_php_binary: str = "php"
    danfse_xml_max_bytes: int = 5 * 1024 * 1024
    danfse_timeout_seconds: int = 60
    secrets_key: str | None = None
    api_key: str | None = None
    jwt_secret: str | None = None
    jwt_expire_minutes: int = 1440
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    invertexto_enabled: bool = False
    invertexto_token: str | None = None
    invertexto_rpm: int = 30
    invertexto_delay_seconds: float = 0.6
    invertexto_cache_days: int = 30
    cnpj_receita_db_path: str = "data/cnpj_receita.sqlite3"
    cnpj_receita_cache_days: int = 30
    alert_webhook_url: str | None = None
    log_level: str = "INFO"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str | None) -> str:
        if not value:
            return "sqlite:///./data/nfse_backend.db"
        url = str(value).strip()
        if url.startswith("postgresql://"):
            return "postgresql+psycopg://" + url.removeprefix("postgresql://")
        return url

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if not self.is_production:
            return self

        missing = [
            name
            for name, value in (
                ("API_KEY", self.api_key),
                ("JWT_SECRET", self.jwt_secret),
                ("SECRETS_KEY", self.secrets_key),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise ValueError("Configuracao de producao incompleta: " + ", ".join(missing))
        if len(str(self.api_key)) < 32:
            raise ValueError("API_KEY deve ter pelo menos 32 caracteres em producao.")
        if len(str(self.jwt_secret)) < 32:
            raise ValueError("JWT_SECRET deve ter pelo menos 32 caracteres em producao.")
        try:
            Fernet(str(self.secrets_key).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("SECRETS_KEY deve ser uma chave Fernet valida em producao.") from exc
        return self

    @property
    def is_production(self) -> bool:
        production_names = {"production", "producao", "prod"}
        environment = (self.environment or "").strip().lower()
        railway_environment = (self.railway_environment_name or "").strip().lower()
        return environment in production_names or railway_environment in production_names

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
