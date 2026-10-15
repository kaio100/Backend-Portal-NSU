# Monitoramento Railway — 06/10/2026

Horários em Brasília (UTC−3). Verificação somente em leitura no Railway e no Supabase; nenhuma alteração em produção.

## Serviço e monitor

- Backend-Portal-NSU online, deploy `cef3b8ed-8357-4100-b6a0-5f1dd2f1a353`, commit `e71fc73`, concluído às 11h52.
- `/health`, `/db/health` e `/storage/health`: HTTP 200; storage R2. `/health/operacao`: HTTP 404.
- Monitor `planning_hub` ativo, filtros `empresa_ids=null`, `certificado_ids=null`, `nsu_inicio=null`, `forcar=false`: consulta global restaurada.
- Agendador executou ciclo às 12h12min06s.

## Progresso e falha observada

Processo/job `39112`, empresa `2`, certificado `4`, iniciado às 11h57min31s. Releitura após parada, NSU inicial 2256, NSU confirmado anterior 3287. A saída contém 1.069 XMLs.

O download terminou com `ADN sem novos documentos | E2220` às 11h58min32s. A ingestão final continuou atualizando notas no banco:

| Observação | Notas distintas atualizadas desde o início do lote |
| --- | ---: |
| 12h09 | 56 |
| 12h10 | 59 |
| 12h11 | 64 |
| 12h12 | 71 |
| 12h13 | 73 |
| 12h14 | 82 |
| 12h15 | 88 |
| 12h17 | 93 |
| 12h18 | 99 |
| 12h19 | 105 |

Esses números representam notas atualizadas, não notas novas nem percentual dos XMLs.

Apesar das gravações, `processos.updated_at` e `processos_jobs.updated_at` ficaram em 11h58min34s. Às 12h14min02s, o supervisor devolveu job e processo para `pendente`, removeu o proprietário do job e apagou o lock. Log Railway às 12h14min03s: `Supervisor: 1 job(s) sem heartbeat voltaram para a fila`.

Às 12h15min59s, havia 77 jobs pendentes e nenhum marcado como rodando, embora a empresa 2 tivesse nota atualizada às 12h15min52s.

Última verificação às 12h19min02s: 105 notas atualizadas, última gravação às 12h19min00s; job 39112 ainda pendente, 77 jobs pendentes e nenhum rodando. O lote não concluiu durante a janela de observação de aproximadamente 15 minutos. O monitoramento nesta conversa terminou nessa verificação; não foi instalado monitor permanente.

## Diagnóstico

A ingestão continua avançando lentamente; não há evidência de travamento total. Há uma falha confirmada de acompanhamento/lease: um job ainda ativo foi considerado abandonado por falta de heartbeat durante a ingestão final.

No código local, `legacy_processing_service` encerra a thread de ingestão incremental antes da chamada de ingestão final. O heartbeat é atualizado na thread incremental. `jobs_repo.recuperar_jobs_travados` usa a idade de `Job.updated_at`, com padrão de 15 minutos, para devolver o job à fila e remover locks. Esse fluxo é consistente com o incidente observado.

Próxima correção recomendada: manter heartbeat e lease durante todas as etapas, inclusive ingestão final, e impedir que a recuperação libere um trabalho ainda ativo. A correção não foi aplicada neste monitoramento.
