# Manual de handoff para agentes de IA

## O que este sistema faz

É um portal multiempresa para consultar NFS-e Nacional no ADN com certificado digital, importar XML/eventos/PDF, calcular e comparar retenções, organizar fila de conferência e exportar documentos/relatórios. Backend e frontend compatíveis são os commits listados em `01_PROJECT_OVERVIEW.md`.

## Arquivos para ler primeiro

1. `16_AGENT_QUICK_START.md` (mapa operacional de minutos).
2. `01_PROJECT_OVERVIEW.md` (escopo e snapshot).
3. `02_ARCHITECTURE.md` (fronteiras reais).
4. `13_CRITICAL_FILES.md` (raio de impacto).
5. Documento do domínio: `05_DATA_FLOW`, `06_DATABASE`, `07_API` ou `08_BUSINESS_RULES`.
6. Código: `backend/app/core/config.py`, `backend/app/main.py`, `backend/app/db/models.py`, `backend/app/db/session.py`, `backend/app/api/deps.py`; depois router → schema → service → repository → testes.

## Como a arquitetura funciona

Frontend `src/lib/api.ts` chama FastAPI. Dependencies autenticam JWT/API key e restringem grupo. Routers validam Pydantic e chamam services. Services combinam repositories/SQLAlchemy e storage. Consultas criam `Processo`/`Job`; worker chama o legado ADN; ingestão faz upsert de `Nota`, `Evento`, `Arquivo`.

## Regras que não podem ser esquecidas

- Tenant é `Empresa.grupo` e precisa ser verificado em cada leitura/mutação.
- Identidade da nota é `(empresa_id, chave)`; não use número da NFS-e sozinho.
- `status_documento` (fiscal), `status_fila_manual` (operacional), `conferencia_status` e `sla_status` são conceitos diferentes.
- Manual tem precedência no status da fila; cancelada/substituída vêm do XML/evento.
- Análise com `responsavel` não pode ser alterada sem `retificar=true`; retificação atualiza o responsável autenticado e não cria histórico.
- `observacao_interna` e `alertas_fiscais` são somente leitura no payload do usuário.
- Cálculo fiscal usa Decimal e ROUND_HALF_UP; a planilha `RETENCOES_REGRAS.xlsx` é fonte de regras.
- Certificado = bytes no storage + senha cifrada em `Secret`; nunca plaintext/log.
- `WORKER_DRY_RUN` local é verdadeiro por padrão; confirmar modo antes de testar consulta.

## Banco e storage

Não há migrations Alembic versionadas. `session.py` e scripts aplicam schema; produção deve migrar explicitamente. DB e storage não são uma transação única. Use `06_DATABASE_MAP.md` e `storage_naming_service.py` antes de mover ou excluir objetos.

## APIs e integração frontend

`07_API_MAP.md` lista todas as rotas. `src/lib/api.ts` é a fonte de consumo frontend. Bugs de contrato conhecidos: `/auth/criar-conta` é chamado pelo frontend e não existe; `/auth/grupos` requer admin. GET e POST de download têm conjuntos de filtros diferentes.

## Fluxos principais

- Consulta: `consultas_service` → `Processo/Job` → `worker/jobs` → `legacy_processing` → ADN → `legacy_ingestion` → DB/storage.
- Nota: XML → chave/status/valores → upsert → evento/arquivo → campos operacionais → tela.
- Conferência: tela → PATCH `/notas/{id}/conferencia` → valida retificação → nota atualizada.
- Download: filtros → repository → `Arquivo` → storage → ZIP.
- DANFSe: XML → subprocesso PHP → PDF.

## Armadilhas conhecidas

1. Não confiar apenas no nome das camadas: services fazem SQL diretamente.
2. Não copiar auditorias antigas/`docs/ai.zip` sem validar contra o commit.
3. Não assumir que cancelar processo interrompe o ADN.
4. Não assumir que o limite configurado de download é efetivo: repository limita 5.000.
5. Não usar `status_fila_manual` para alterar status fiscal.
6. Não alterar naming de storage sem migração e reconciliação.
7. Não executar scripts em `.env`/DB desconhecido.
8. Não tratar erro externo como sucesso só porque `Processo` foi criado.

## Como descobrir impacto antes de modificar

1. `rg` pelo símbolo, rota, coluna e chave de storage.
2. Trace o contexto completo indicado em `09_DEPENDENCY_MAP.md`.
3. Verifique consumidor frontend e aliases em `api.ts`.
4. Consulte `10_RISK_REGISTER.md` e `12_CHANGE_IMPACT_MAP.md`.
5. Escreva teste de contrato, tenant, erro e idempotência.
6. Para banco/storage, faça backup/reconciliation plan e valide em SQLite + PostgreSQL.

## Como adicionar funcionalidade

Defina contrato/schema primeiro; implemente service/repository pequeno; adicione rota com dependency de tenant/papel; atualize `api.ts`, hook e tela; crie migration explícita se houver coluna; inclua testes unitários e de integração; atualize os mapas técnicos e riscos.

## Como corrigir um bug

Reproduza com fixture mínima, identifique se é contrato, regra, persistência ou side effect, registre teste que falha, corrija na camada proprietária, valide fluxos vizinhos e documente mudança/compatibilidade. Em fiscais, compare centavos e XML bruto; em worker, teste restart/duplicidade.

## Checklist obrigatório antes de commit

- [ ] Código está no branch/commit alvo correto.
- [ ] Nenhum `.env`, PFX, XML/PDF ou banco local foi incluído.
- [ ] Tenant/role/erro e limites foram testados.
- [ ] Testes Python e PHP DANFSe relevantes passam.
- [ ] Migration foi criada/testada, se necessário.
- [ ] Contrato frontend (`api.ts`, hook e página) está alinhado.
- [ ] Não há alteração acidental em status fiscal, NSU, storage naming ou segredos.
- [ ] `git diff`, `git status` e lista de arquivos foram revisados.
- [ ] Este conjunto `docs/ai` foi atualizado se a arquitetura/regra mudou.

## Estado de limpeza operacional conhecido

A empresa Canopus conserva cadastro/certificado, mas seus documentos e registros de consulta foram removidos no banco local; a recuperação ficou fora do runtime. Não use esse estado como regra para outras empresas nem apague recovery sem decisão explícita.

## Última alteração auditada (2026-09-15)

`retencoes_regras_service.py` agora normaliza cabeçalhos/percentuais, recarrega a fonte quando ela muda e aceita `RETENCOES_REGRAS_PATH`. `legacy_ingestion_service.py` não deixa um código genérico sem regra (como `990101`/`99.01`) esconder um candidato LC116 posterior que esteja na `Planilha2`, nem transforma `cTribMun` simples de 3 dígitos (como `501`) em subitem LC116. O `cTribNac` original permanece separado quando há fallback municipal. A varredura de 8.412 notas XML do projeto não encontrou subitem ausente; encontrou apenas o código inválido/sem regra `005300`→`0.53`, que deve ser corrigido na origem e não inferido pela descrição. Para dados já persistidos, execute `backend.app.scripts.recalcular_alertas_fiscais` no ambiente que tenha acesso aos XMLs; não invente o subitem apenas pelo texto da descrição.

## Estado atual do trabalho (2026-09-25)

- Plano de ajustes em fases (F0–F8), decidido com o Kaio. Auditoria de riscos e plano publicados como páginas privadas; o plano segue a ordem: status fiscal (F1), análise auditável com Alembic (F2), worker/NSU (F3), grupos e contas com convite e Resend (F4).
- `main` local: `83db9afb` (limpeza), `ebbb4a86` (revert temporário do `c43cb834`, a regra de canceladas fora da exportação), `09559ad8` (restaura este `docs/ai`, que o revert tinha removido). Nada foi enviado ao GitHub; o Railway está parado por falta de pagamento e publicaria o `main` do GitHub, que ainda está no `c43cb834`.
- Branch `ajustes/f1-status-fiscal` (F1 completa no código): classificação por estrutura (REG-014, `nfse_status_service`), eventos escondidos pelo índice único lidos de `ocorrencias_nsu.csv`, eventos já gravados aplicados à nota que chega depois, índice único em eventos, commit por linha na ingestão, tela sem gravar campos calculados, script `corrigir_status_fiscal` (simula por padrão) e a regra do `c43cb834` reaplicada. **Pendente: rodar o script em produção** (exige acesso ao banco de produção) e recuperar pelo ADN os eventos engolidos desde 17/09 (`sincronizar_eventos_lote --desde 2026-09-17`).
- Branch `ajustes/f2-analise-auditavel` (sobre a F1): Alembic com advisory lock, histórico da análise (`notas_conferencia_historico`, `GET /notas/{id}/historico`), autor do login, trava também no `PUT /nfse`, validação do payload da conferência.
- Papéis decididos: só `operador` e `admin` (o `leitura` sai); convite só por operador/admin, convidado entra como operador.
- Branch `ajustes/f3-consulta-adn` (sobre a F2): saída do motor em `data/` (volume) com limpeza de respostas brutas, NSU central só no fim do job e limitado por falhas de ingestão (aviso vai para `erro_resumo` do processo), certificado vencido fora da fila e `GET /certificados/vencimentos`, erro permanente sem repetição no motor, lock atômico renovado pelo heartbeat, recuperação de jobs travados por heartbeat (startup + a cada minuto, também no worker separado), consulta avulsa sem tocar no monitor, motor legado descarregado de `sys.modules` após cada job, limpeza de PFX temporários no startup, `NOTAS_DATA_CORTE` validada no Settings.
- Próximas fases: F4 (grupos, convite, Resend), F5 (teto de 5.000), F6 (operação). Frontend (F7) na reserva.
