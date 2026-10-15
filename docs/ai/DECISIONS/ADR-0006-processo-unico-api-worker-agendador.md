# ADR-0006 — API, worker e agendador no mesmo processo

- **Status:** aceito de fato (nunca formalizado); **revisão proposta** em 2026-10-08
- **Data:** registrado em 2026-10-08

## Contexto
Em produção há um serviço Railway com uma réplica. Com `API_WORKER_ENABLED` e `EMBEDDED_SCHEDULER_ENABLED` no padrão `True`, o mesmo processo serve a API, roda um worker por grupo (threads via `asyncio.to_thread`), o supervisor e o agendador. O `docker-compose.yml` e o README já descrevem a alternativa com processos separados.

## Evidência (08/10/2026)
- O pool de conexões (5 + 10) se esgotou com `GET /notas` lento enquanto o worker processava; um job falhou por falta de conexão (ARCH-002).
- Logo depois, o agendador embutido parou e não voltou: a tarefa não tem `try/except` e o supervisor não a recria (ARCH-001).

## Opções
| Opção | Benefícios | Custos / riscos |
|---|---|---|
| A. Manter um processo, corrigindo o laço do agendador, o supervisor e o pool | Mudança pequena; um serviço só | API e worker continuam disputando CPU, threads e conexões |
| B. Serviço `worker` separado no Railway (mesma imagem, `CMD` do worker + agendador avulso), API com os dois flags `false` | Falha de um não derruba o outro; pools separados; o agendador avulso já tem `try/except` | Dois serviços, custo e variáveis duplicadas; o volume `/app/data` precisa estar no worker |
| C. B + engine/pool próprios por papel | Isola de vez o consumo de conexões | Mais configuração |

## Recomendação (proposta)
A agora (correção pequena e urgente), B quando houver janela: é a opção que a base já suporta (`worker/worker.py`, `worker/scheduler.py`, compose).

## Validação
Teste que injeta exceção no agendador; alerta de "último tick" com mais de 30 min; zero `QueuePool` por 7 dias.
