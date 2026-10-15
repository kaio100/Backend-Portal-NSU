# Análise da documentação (2026-10-06)

Escopo: os 21 `.md` do projeto (README, `backend/danfse/README.md`, `docs/*.md`, `docs/ai/01–16`), cerca de 3.800 linhas, comparados com o código da branch `ajustes/f6-operacao` (último commit `26f65cb9`, F5). Ficaram de fora os 95 `.md` de terceiros em `backend/danfse/vendor/` e os do `.pytest_cache`.

## Resumo

A documentação é rica, mas foi remendada: a base descreve o snapshot `f50da548` (15/09), e as fases F1–F5 entraram como notas no meio do texto antigo. Vários documentos se contradizem, e os piores casos estão nos guias de entrada para agentes de IA (14, 15, 16), que ainda descrevem bugs já corrigidos como abertos.

## 1. Contradições entre os documentos

| Afirmação desatualizada | Onde aparece | O que vale hoje |
|---|---|---|
| "Não há Alembic versionado" | `06_DATABASE_MAP.md:7`, `02:39`, `11:34`, `14:34`, 15, 16 | Migrações `0001`–`0003` existem; a linha 5 do próprio 06 diz isso |
| "Retificação não cria histórico" | `14:26`, `15:79`, `16:53`, `05:81` | Existe `notas_conferencia_historico` (REG-022, RSK-007 resolvido) |
| `/auth/criar-conta` não existe | `07:128`, `02:91`, `11:5`, 14 | Existe: cadastro por convite (linha 138 do próprio 07) |
| `/auth/local` ativa | `07:9`, `05:16` | Removida (linha 145 do próprio 07) |
| `exportar_conferencia_xlsx` duplicada | 02, 11, 13, 15, RSK-008 | Só uma definição, `portal_support_service.py:1413` |
| Corte silencioso em 5.000 e GET do ZIP com menos filtros | 05, 11 (itens 4 e 5), 12, 13, 16, RSK-011 | Resolvido na F5 (REG-038) |
| `/db/health` exige JWT de admin | `07:56` | É público, só roda `SELECT 1` |
| "16 entidades", "88 rotas" | 01, 13 | 20 entidades, cerca de 99 rotas |

Bugs 1 a 5 do `11_BUGS_AND_TECH_DEBT.md` e os riscos RSK-008, 011, 012 e 013 do `10_RISK_REGISTER.md` já foram corrigidos, mas continuam como abertos.

## 2. Índices de arquivos e funções desatualizados

- `04_FUNCTION_MAP.md`: 773 entradas; 368 com a linha certa, 350 mudaram de linha, 55 apontam para símbolo ou arquivo removido. 163 funções novas ausentes (`contas_service`, `nfse_status_service`, `eventos_sync_service`, `corrigir_status_fiscal`...).
- `03_FILE_MAP.md`: lista 6 arquivos apagados (`legacy_adapter.py`, `pdf_status_service.py`, `revalidar_status_pdfs.py`, `baixar_pdfs_oficiais_periodo.py`, `gerar_apresentacao_resultados.py`, `diagnosticar_empresas_nsu_202608.py`); faltam `migrations/`, `php_runtime.py`, `rede.py`, `contas_service`, `email_service`; cita 32 testes (hoje 40); inventário repetido duas vezes ("Scripts" e "Outros backend").
- `12_CHANGE_IMPACT_MAP.md:29` cita `pdf_status_service.py`, que não existe.
- `13_CRITICAL_FILES.md` aponta `_status_from_xml` como decisão do status fiscal; hoje é `nfse_status_service.classificar_xml`.

## 3. Guias de operação parados antes da F2

README (último commit 17/09) e `DEPLOY_PRODUCAO.md` (03/09) não mencionam:

- migrações Alembic;
- cadastro por convite e código por e-mail (Resend);
- variáveis `RESEND_API_KEY`, `SUPER_ADMIN_EMAILS`, `FRONTEND_BASE_URL`, `RELATORIO_MAX_NOTAS`, `LEGACY_OUTPUT_DIR`, `JOBS_TRAVADOS_MINUTOS` (só no `.env.example`);
- **rodar `corrigir_status_fiscal --aplicar` no deploy**: pela REG-036, sem ele notas substitutas válidas ficam fora do ZIP e da planilha. Hoje isso só está no 08.

## 4. `REVISAO_TECNICA_MAPA.md` mistura história com estado atual

- Conclusão no topo ainda diz "não liberar para produção" (16/09).
- Linhas 62–66 dizem que segredos reais foram commitados; linhas 143–145 corrigem ("nunca foram commitados"). As duas versões convivem.
- Seção 13 diz que `.env.docker.example` foi removido; ele existe.
- Mapa mental ainda cita a fila de PDF oficial, removida do código.

## 5. Formatação

- `08_BUSINESS_RULES.md:43`: linha em branco antes da REG-037 quebra a tabela; REG-037 e REG-038 aparecem como texto solto.
- Cabeçalho do 08 diz "snapshot `f50da548`", mas o arquivo já inclui F1–F5.
- `+` soltos em `03:333`, `04:83` e `04:341`.

## O que está bom

- Tabelas de regras de negócio (08), rotas (07) e riscos (10).
- Separação entre status fiscal e status de fila.
- Regras práticas de "antes de mudar X, leia Y" (12 e 14).
- `PENDENCIAS_BACKEND_PORTAL.md` continua válido: regras de atribuição da fila não foram implementadas.

## Observação

A branch `ajustes/f6-operacao` tem alterações não commitadas (`operacao_service.py`, `tempo.py`, `rotacionar_segredos.py`, `limpar_orfaos_storage.py`); nenhum documento descreve a F6 ainda.

## Correções sugeridas, em ordem

1. Corrigir 14, 15 e 16 (guias lidos primeiro pela IA).
2. Marcar como resolvidos os itens 1–5 do 11 e RSK-008/011/012/013 no 10; tirar as frases desatualizadas de 02, 05, 06, 07 e 13.
3. Gerar os índices do 03 e 04 por script, ou apagá-los (o próprio 04 recomenda `rg`).
4. Atualizar README e DEPLOY com Alembic, variáveis novas e o passo do `corrigir_status_fiscal`.
5. Aviso de "documento histórico" no topo da REVISAO; consertar a tabela do 08.
