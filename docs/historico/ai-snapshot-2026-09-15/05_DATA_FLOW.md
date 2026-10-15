# Fluxos de dados ponta a ponta

## 1. Login e contexto de tenant

```text
Frontend Login.tsx
  -> src/lib/api.ts:login()
  -> POST /auth/login (backend/app/api/routers/auth.py)
  -> auth_service: busca Usuario por email, verifica PBKDF2 e ativo
  -> JWT HS256 {sub, grupo, papel/is_admin, exp}
  -> frontend request(): Authorization Bearer
  -> deps.get_current_usuario() -> usuário + grupo
  -> require_*_grupo() -> Empresa/Nota/Processo/Arquivo/Certificado do mesmo grupo
```

O token não é uma transação de banco: revogação é feita desativando o usuário e validando isso em cada request. A rota local é uma exceção de compatibilidade, limitada a origem local.

## 2. Cadastro de empresa e certificado

```text
Página Empresas/Certificados
  -> POST /empresas ou /certificados/upload (multipart)
  -> router valida schema, papel e grupo
  -> empresas_service / certificados_service
  -> certificado_metadata_service lê PKCS#12 (thumbprint, CN, validade)
  -> secrets_service cifra senha em Secret (Fernet)
  -> storage_service.put(build_certificate_key(...), bytes)
  -> INSERT Empresa/Certificado/Secret
  -> resposta DTO; frontend invalida queries React Query
```

A empresa mantém apenas CNPJ normalizado de 14 dígitos. O worker só considera certificado ativo com storage key real, validade aplicável e senha recuperável.

## 3. Consulta manual e automática

```text
POST /consultas/iniciar ou scheduler
  -> consultas_service.iniciar_*()
  -> valida empresa/grupo/certificado e limites (NSU, pausa, PDFs)
  -> INSERT processos(status=pendente)
  -> INSERT processos_jobs(status=pendente, payload_json)
  -> worker/jobs.processar_job()
  -> claim atômico + LockProcessamento(empresa_id, certificado_id)
  -> legacy_processing_service.executar_consulta_nfse_legado()
  -> adn_nfse_downloader consulta ADN com certificado
  -> saída local: CSV, XML e PDF
  -> legacy_ingestion_service.ingerir_saida_legado()
  -> Nota/Evento/Arquivo + StorageService + NsuControle
  -> Job/Processo/logs finalizados
```

No modo padrão local (`WORKER_DRY_RUN=true`), o job é simulado. Em real, o cliente legado pode executar chamadas externas por dezenas de minutos; timeout/cancelamento de request HTTP não interrompe o processo já iniciado.

## 4. Ingestão de XML, evento e PDF

```text
arquivo XML
  -> parse XML/local-name e extrair chave, NSU, partes, datas, valores e cStat
  -> _status_from_xml() -> status_documento/status_rotulo
  -> _aplicar_campos_fiscais_xml() -> retenções, serviço, município, Simples
  -> upsert_nota_by_chave(empresa_id, chave)
  -> cada evento -> _registrar_evento_xml() (chave/tipo/data/NSU)
  -> XML/PDF -> _put_file_if_needed() (SHA-256 + storage)
  -> _registrar_arquivo() e Nota.*_storage_key
```

A chave única é `(empresa_id, chave)`. Arquivos são deduplicados por chave/tipo/checksum de forma aplicada pelo serviço; não há uma constraint global equivalente no modelo. PDF espelho pode ser gerado pelo PHP DANFSe e PDF oficial é apenas indexado quando o legado o entrega.

## 5. Listagem, classificação e conferência

```text
GET /notas, /notas/emitidas, /notas/recebidas
  -> notas_service.listar_notas()/listar_notas_por_tipo_operacional()
  -> notas_repo.list_notas() com filtros SQL, limite e tenant
  -> classificar_direcao_nota(): certificado CNPJ vs prestador/tomador
  -> operational_fields_service normaliza prioridade, fila, SLA, alertas
  -> _anotar_detalhe_frontend() acrescenta campos de apresentação
  -> schemas.NotaListItem -> React Query -> tabela
```

`PATCH /notas/{id}/conferencia` chama `atualizar_conferencia`: valida tenant, evita sobrescrever `responsavel` sem `retificar=true`, atualiza operador/status/observação e timestamps. A confirmação é persistida na mesma sessão, mas a operação não é uma trilha imutável.

## 6. Download e relatório

```text
POST/GET /notas/download-lote
  -> NotasDownloadFiltros -> notas_download_service._buscar_notas()
  -> notas_repo + seleção Arquivo por tipo
  -> storage.get() para cada bytes
  -> nomes amigáveis/deduplicados -> ZIP temporário -> FileResponse

POST /relatorios/conferencia
  -> portal_support_service._buscar_notas_relatorio()
  -> enriquece XML/CNPJ quando necessário
  -> _relatorio_row() + openpyxl -> XLSX temporário/bytes
```

Ambos os fluxos consultam com `somente_exportaveis=True`: notas canceladas/substituídas são descartadas no SQL e nunca entram no ZIP nem no XLSX (REG-036). O endpoint GET reconstrói filtros com menos campos que o POST. O repository limita listagem a 5.000 e o relatório pede limite fixo; universos maiores podem ser truncados sem erro explícito.

## 7. DANFSe

```text
Frontend -> POST /api/danfse/gerar (multipart XML)
  -> danfse router/deps
  -> DanfseService valida tamanho/extensão e cria tempfile
  -> subprocess PHP backend/danfse/generate.php
  -> DanfseGenerator + parser/template/assets
  -> PDF bytes -> FileResponse
```

O PHP é um subprocesso separado e exige runtime Composer instalado. Falha de ambiente é devolvida como erro de serviço, não como fallback Python.

## 8. Estado operacional da limpeza Canopus

Após a limpeza anterior, a empresa `CANOPUS CONSTRUCOES LTDA` permaneceu com a empresa e o certificado; notas, arquivos, eventos, processos, jobs, logs, locks e controle NSU foram removidos. XML/PDF foram movidos para recovery antes da exclusão física. Isso é estado do banco/storage local, não regra de aplicação e não deve ser usado como dado de teste implícito.

