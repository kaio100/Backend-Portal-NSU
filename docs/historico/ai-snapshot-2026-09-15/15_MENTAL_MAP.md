# Mapa mental do sistema real

```text
PORTAL NFS-e ADN
├── FRONTEND (repo Frontend-Portal-NSU @ 0fd4b07)
│   ├── app/router.tsx + pages
│   │   ├── Login / CriarConta -> auth
│   │   ├── Dashboard -> health, resumo, live
│   │   ├── NotasConsultadas -> GET /notas*
│   │   ├── Conferencia -> filtros + PATCH conferencia/retificar
│   │   ├── Fila/Processos -> processos/jobs/logs
│   │   ├── Certificados -> upload, senha, testar
│   │   ├── Configuracoes/MotorAdn -> consultas/config
│   │   └── Admin -> usuários, grupos, arquivamento, erros
│   ├── hooks React Query -> useAuth/useNotas/useProcessos/useCertificados...
│   └── lib/api.ts -> headers JWT, timeout, erros, downloads e todas rotas
│
├── API FASTAPI (backend/app)
│   ├── main.py -> lifespan, CORS, headers, routers, tarefas embutidas
│   ├── api/deps.py -> DB/storage, JWT/API key, RBAC, grupo
│   ├── routers
│   │   ├── auth/admin -> Usuario/Grupo/Acesso
│   │   ├── empresas/certificados -> cadastro + Secret + PFX storage
│   │   ├── consultas/nsu/processos/execucoes/logs -> fila/estado
│   │   ├── notas/eventos/arquivos/nfse_compat -> núcleo portal
│   │   ├── relatorios -> XLSX
│   │   ├── danfse -> subprocesso PHP
│   │   ├── cnpj -> cache/providers
│   │   └── health/db_health/storage -> operação
│   └── schemas -> contratos/aliases/validação
│
├── DOMÍNIO DE CONSULTA
│   ├── consultas_service -> elegibilidade, monitor, Processo + Job
│   ├── processos_service -> estados e cancelamento
│   ├── worker/jobs -> claim, attempts, Lock, commit/rollback
│   ├── worker/worker + scheduler -> polling/ciclos automáticos
│   ├── legacy_processing_service -> configura motor, NSU, PDFs
│   └── adn_nfse_downloader.py -> certificado -> ADN -> CSV/XML/PDF
│
├── DOMÍNIO DE INGESTÃO
│   ├── legacy_ingestion_service
│   │   ├── parse XML por local-name
│   │   ├── chave/NSU/datas/partes/valores/status
│   │   ├── eventos cancelamento/substituição
│   │   ├── retenções + operacional
│   │   ├── upsert Nota por (empresa,chave)
│   │   └── Arquivo + Storage (XML/PDF)
│   ├── nfse_xml_parser -> NFS-e Nacional detalhada
│   ├── operational_fields -> fila/prioridade/SLA/Simples
│   └── retencoes_regras + calculo -> regras XLSX + Decimal
│
├── PERSISTÊNCIA
│   ├── models.py -> Grupo, Empresa, Certificado, Processo, Job,
│   │   MonitoramentoConfig, NsuControle, Nota, Evento, Arquivo,
│   │   LogProcesso, Lock, CnpjCache, Secret, Usuario, Acesso
│   ├── repositories -> consultas reutilizáveis (não exclusivos)
│   └── session.py -> SQLite/Postgres + create_all/ALTER runtime
│
├── DOCUMENTOS
│   ├── storage_service -> local/R2, path safety
│   ├── naming -> chaves de XML/PDF/certificados/exports
│   ├── download_service -> ZIP com seleção/deduplicação
│   ├── arquivos routers/service -> download/view/preview
│   └── danfse_service -> PHP Composer -> PDF espelho
│
├── OBSERVABILIDADE/SEGURANÇA
│   ├── PBKDF2 600k + JWT HS256 + API key
│   ├── CORS/security headers
│   ├── logs JSON + métricas memória + webhook opcional
│   └── scripts operacionais/migração/testes/CI
│
└── PONTOS FRÁGEIS
    ├── DB/storage sem transação comum
    ├── worker/lock/cancelamento concorrentes
    ├── migração runtime sem Alembic history
    ├── limites/GET de download inconsistentes
    ├── contratos frontend auth desalinhados
    ├── função XLSX duplicada
    └── retificação sobrescreve sem histórico
```

