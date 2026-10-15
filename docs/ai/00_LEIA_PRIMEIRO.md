# Leia primeiro — Backend Portal NFS-e

> Verificado contra o código em 15/10/2026, commit `ae9d4e2d` (branch `ajustes/seguranca-admin-paginacao`, ainda não implantada). Produção: Railway.

## O que é

Portal interno, com várias empresas, para buscar NFS-e Nacional no ADN (Ambiente de Dados Nacional) com o certificado digital de cada empresa. O sistema importa XML, eventos e PDF espelho; calcula e compara retenções; organiza a fila de conferência fiscal; e exporta ZIP e planilha. Cada equipe (Planning Hub, Planning MA) é um **grupo** isolado.

## Arquitetura em 30 segundos

React/Vite (repo `Frontend-Portal-NSU`) chama a API FastAPI. Autenticação JWT e filtro por grupo ficam em `backend/app/api/deps.py`. Os routers chamam services e repositories (SQLAlchemy, Postgres no Supabase). A consulta ao ADN é assíncrona: `Processo` + `Job` → worker → motor `adn_nfse_downloader.py` → ingestão (`legacy_ingestion_service.py`) → `Nota`/`Evento`/`Arquivo` no banco e XML/PDF no R2. Em produção, **API, workers e agendador rodam no mesmo processo** (um container no Railway).

## Como usar estes documentos

| Preciso de… | Leia |
|---|---|
| Entender o negócio, os termos e as regras fiscais | `PROJECT_CONTEXT.md` |
| Saber como as peças se ligam, fluxos e runtime | `ARCHITECTURE_CURRENT.md` |
| Mexer em tabela, coluna ou migração | `DATABASE.md` |
| Mexer em rota ou contrato HTTP | `API.md` + `gerado/ROTAS.md` |
| Saber o que quebra se eu mudar X | `CHANGE_IMPACT.md` |
| Problemas abertos, riscos e dívida | `FINDINGS.md` |
| Plano em andamento para reduzir a CPU do banco (mapa mental) | `PLANO_CARGA_BANCO.md` |
| Segredos, certificados, permissões | `SECURITY.md` |
| Deploy, variáveis, logs, scripts e incidentes | `OPERATIONS.md` |
| Por que algo foi decidido assim | `DECISIONS/` |
| O que mudou e quando | `CHANGELOG.md` |
| Achar arquivo, função ou rota | `gerado/` (gerado do código) |
| Ferramentas de auditoria (Serena MCP, Semgrep, Ruff…) e como rodá-las | `FERRAMENTAS/` |
| Como estava antes | `../historico/` (congelado) |

Código mínimo para começar: `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/db/models.py`, `backend/app/db/session.py`, `backend/app/api/deps.py`.

## Regras que não podem ser esquecidas

1. Toda consulta de dado operacional filtra pelo **grupo do usuário** (REG-001). Rota nova sem filtro vaza dados de outra equipe.
2. **Status fiscal ≠ status da fila.** O fiscal vem só da estrutura do XML (REG-014).
3. Nota é idempotente por `(empresa_id, chave)` (REG-012). Reprocessar não pode duplicar nem rebaixar status.
4. O NSU central só avança no fim do job, até onde as notas entraram no banco (ADR-0003).
5. Mudança de esquema = nova revisão Alembic idempotente. `_ensure_runtime_columns` está congelado (ADR-0002).
6. Retificação é explícita (`retificar=true`) e vai para o histórico (REG-022).
7. O monitor global tem `empresa_ids` e `certificado_ids` nulos. Nada pode restringi-lo sem ação explícita (REG-039).
8. Chave de storage só pelos `build_*_key`, com proteção de caminho (REG-028).
9. `WORKER_DRY_RUN` vale `True` no código: em produção a variável precisa existir e valer `false`.
10. Nunca suba `uvicorn` direto com o `.env` local: ele aponta para o banco de **produção**. Use `python iniciar_local.py`.

## Como manter estes documentos (obrigatório)

Protocolo do agente Arquiteto, aplicado a este projeto:

1. **Estado atual, não diário.** `docs/ai/` descreve o que o código faz hoje. O "o que mudou" vai para o `CHANGELOG.md`. Análises datadas vão para `../historico/`. Não acrescente notas do tipo "**F4:** …" no meio do texto: reescreva a frase.
2. **Carimbo de verificação.** Cada documento tem no topo "Verificado contra o código em <data>, commit <hash>". Ao revisar uma seção, atualize o carimbo. Se não conferiu, não carimbe.
3. **Status de certeza** em todo achado: CONFIRMADO, FORTEMENTE_INDICADO, HIPOTESE ou NAO_DETERMINADO. "Não encontrei" não é "não existe": diga onde procurou.
4. **Depois de mudar código**, atualize no mesmo commit:
   - rota nova ou alterada → `API.md` (se muda regra ou contrato) e rode o gerador;
   - tabela ou coluna → `DATABASE.md` + revisão Alembic;
   - regra de negócio → `PROJECT_CONTEXT.md` (REG-xxx);
   - variável de ambiente → `OPERATIONS.md`;
   - risco novo ou resolvido → `FINDINGS.md` (resolvido sai da tabela de abertos e vai para "Resolvidos");
   - decisão difícil de reverter → novo ADR em `DECISIONS/`;
   - sempre → uma linha no `CHANGELOG.md`.
5. **Índices mecânicos** (`gerado/ARQUIVOS.md`, `SIMBOLOS.md`, `ROTAS.md`): nunca à mão. Rode `python docs/ai/gerado/gerar_indices.py` na raiz do repositório.
6. Documento que contradiz o código está errado: corrija o documento ou registre a divergência em `FINDINGS.md`.
