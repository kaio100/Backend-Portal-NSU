from datetime import date

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
    worker_temp_dir: str = "data/tmp_worker"
    # Saida do motor legado (XML, indice, estado). Fica dentro de data/, que e
    # o volume persistente no Railway: antes ficava em /app/saida_adn_nfse e
    # sumia a cada deploy com XML baixados e ainda nao ingeridos.
    legacy_output_dir: str = "data/saida_adn_nfse"
    # Respostas brutas do ADN (raw/ e json/) mais antigas que isto sao apagadas;
    # os XML ficam, porque o indice aponta para eles.
    legacy_output_retencao_dias: int = 15
    # Documentos do ADN emitidos antes desta data sao descartados na consulta.
    notas_data_corte: date = date(2026, 1, 1)
    # Job "rodando" sem heartbeat ha mais tempo que isto volta para a fila.
    jobs_travados_minutos: int = 15
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
    # Empresa que volta depois deste numero de horas sem consulta finalizada
    # (monitor restrito, worker parado) rele na hora desde o 1o dia do mes
    # anterior, sem esperar a janela noturna. 0 = desligado.
    nsu_releitura_apos_horas_sem_consulta: int = 6
    nsu_max_vazios_consecutivos: int = 5
    notas_recebidas_dia_corte_mes_anterior: int = 3
    download_lote_max_notas: int = 10000
    # Teto da planilha de conferencia; passando disso a exportacao pede para
    # refinar o filtro em vez de cortar linhas sem avisar.
    relatorio_max_notas: int = 20000
    download_storage_workers: int = 16
    download_temp_max_age_hours: int = 24
    certificado_upload_max_bytes: int = 5 * 1024 * 1024
    danfse_library_root: str = "backend/danfse"
    danfse_php_binary: str = "php"
    danfse_xml_max_bytes: int = 5 * 1024 * 1024
    danfse_timeout_seconds: int = 60
    secrets_key: str | None = None
    api_key: str | None = None
    jwt_secret: str | None = None
    # Sessao do portal: um dia de trabalho. Antes eram 24 h.
    jwt_expire_minutes: int = 720
    # Painel administrativo: exige uma sessao propria aberta com senha + codigo de 2FA.
    # Desligar (false) so em emergencia: volta a valer apenas o papel de admin.
    admin_2fa_obrigatorio: bool = True
    admin_sessao_minutos: int = 30
    cors_origins: str = "http://localhost:8000,http://127.0.0.1:8000,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173,http://127.0.0.1:5173"
    invertexto_enabled: bool = False
    invertexto_token: str | None = None
    invertexto_rpm: int = 30
    invertexto_delay_seconds: float = 0.6
    invertexto_cache_days: int = 30
    cnpj_receita_db_path: str = "data/cnpj_receita.sqlite3"
    cnpj_receita_cache_days: int = 30
    alert_webhook_url: str | None = None
    # E-mail transacional (codigo de cadastro e de redefinicao de senha).
    resend_enabled: bool = False
    resend_api_key: str | None = None
    resend_from_email: str | None = None
    # Endereco publico do frontend, usado no link de convite.
    frontend_base_url: str | None = None
    # E-mails que administram todos os grupos; os demais admins so o proprio.
    super_admin_emails: str = ""
    convite_validade_dias: int = 7
    codigo_email_validade_minutos: int = 15
    # Fuso das datas de negocio (dia de hoje no painel, nome de arquivos,
    # data da planilha). O container roda em UTC.
    fuso_horario: str = "America/Sao_Paulo"
    # Token para /metrics e /health/operacao. Sem ele, em producao as duas
    # rotas respondem 404.
    metrics_token: str | None = None
    # Vigia da operacao: e-mails (separados por virgula) que recebem aviso de
    # fila parada ou excesso de falhas. Vazio = sem aviso por e-mail.
    alerta_emails: str = ""
    alerta_fila_parada_minutos: int = 60
    alerta_falhas_por_hora: int = 10
    alerta_intervalo_horas: int = 6
    # Avisa quando uma empresa com certificado valido fica este numero de horas
    # sem nenhuma consulta finalizada (0 = desligado). O ciclo normal passa
    # por todas as empresas em ~1h30.
    alerta_empresa_sem_consulta_horas: int = 6
    # Dias de logs_processos mantidos; 0 = nunca apaga.
    logs_retencao_dias: int = 0
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
            for chave in self.secrets_key_list:
                Fernet(chave.encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("SECRETS_KEY deve conter chaves Fernet validas em producao.") from exc
        if self.resend_enabled and not (str(self.resend_api_key or "").strip() and str(self.resend_from_email or "").strip()):
            raise ValueError("RESEND_ENABLED=true exige RESEND_API_KEY e RESEND_FROM_EMAIL.")
        return self

    @property
    def secrets_key_list(self) -> list[str]:
        # Varias chaves separadas por virgula: a primeira cifra, todas decifram
        # (troca de chave sem perder as senhas de certificado ja gravadas).
        return [chave.strip() for chave in str(self.secrets_key or "").split(",") if chave.strip()]

    @property
    def alerta_email_list(self) -> list[str]:
        return [email.strip() for email in self.alerta_emails.split(",") if email.strip()]

    @property
    def super_admin_email_set(self) -> set[str]:
        return {email.strip().lower() for email in self.super_admin_emails.split(",") if email.strip()}

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
