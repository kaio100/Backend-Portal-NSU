# Decisões de arquitetura (ADR)

Crie um ADR quando a decisão mexe em estrutura, dados ou dependências; muda uma característica importante; é cara de reverter; ou tem um trade-off que quem vier depois precisa entender. Modelo: `ADR_TEMPLATE.md`. ADR aceito não se reescreve: um novo o substitui (`Superseded by`).

| ADR | Decisão | Status | Data |
|---|---|---|---|
| [0001](ADR-0001-isolamento-por-grupo.md) | Equipes isoladas por grupo, com o filtro na aplicação | aceito | 2026-09-25 |
| [0002](ADR-0002-esquema-alembic-idempotente.md) | Esquema por `create_all` + Alembic idempotente; ajustes antigos congelados | aceito | 2026-09-25 |
| [0003](ADR-0003-nsu-confirmado-no-fim-do-job.md) | NSU central só avança no fim do job; releitura profunda como rede de segurança | aceito | 2026-09-25 / 2026-10-06 |
| [0004](ADR-0004-status-fiscal-pela-estrutura-do-xml.md) | Status fiscal decidido só pela estrutura do XML | aceito | 2026-09-25 |
| [0005](ADR-0005-contas-por-convite.md) | Cadastro só por convite; papéis admin e operador | aceito | 2026-09-25 |
| [0006](ADR-0006-processo-unico-api-worker-agendador.md) | API, worker e agendador no mesmo processo | aceito de fato, **revisão proposta** | 2026-10-08 |
| [0007](ADR-0007-canceladas-fora-das-exportacoes.md) | Canceladas e substituídas fora do ZIP e da planilha | aceito | 2026-09-25 |
| [0008](ADR-0008-pdf-espelho-php.md) | PDF entregue é o espelho gerado pelo PHP; PDFs antigos não são regerados | aceito | 2026-09-17 / 2026-10-06 |

Decisões pendentes (abrir ADR quando decidir): operador pode cadastrar certificado (ARCH-007); banco e aplicação na mesma região (ARCH-004); retenção dos XMLs do motor (ARCH-009); fonte única da planilha fiscal (ARCH-018).
