# Correções e pós-deploy — 2026-10-06

Horários em Brasília, salvo quando indicado UTC.

## Publicação

- Commit: `a0cfbaf4e0cf20eb00638de2ded33155fc2c5bfe`, enviado para `main`.
- Railway: `4f3ad950-4044-4348-8194-9f1dacfaca1a`, status `SUCCESS`.
- `/health`, `/db/health` e `/storage/health`: HTTP 200; banco conectado e R2 ativo.
- Validação local: 322 testes passaram, 2 foram ignorados; compilação Python, `git diff --check`, sintaxe PHP e teste DANFSe passaram.

## Correções

- Heartbeat independente durante toda a execução do job, inclusive importação final; renovação condicionada ao status e proprietário do job.
- Recuperação de jobs usa bloqueio de linha com `skip_locked` no PostgreSQL.
- XML idêntico com NSU sem avanço, status coerente e arquivos completos pode ser ignorado, preservando conferência manual. Eventos, substituições, arquivos ausentes e NSU novo continuam sendo processados.
- Metadados consultados em lotes, listagem R2 reutilizada por pasta e PDF existente reutilizado sem download quando seus metadados estão completos.
- XML alterado substitui o objeto remoto quando o checksum é diferente.

## Observação em produção

O job 39113 (empresa 3) iniciou na nova versão às 12h45. A consulta ADN terminou às 12h46min48s com E2220 (sem novos documentos). Na importação posterior, o heartbeat permaneceu recente, com idade observada entre 10 e 26 segundos.

Notas da empresa 3 atualizadas depois do fim da consulta: 175 às 12h50, 322 às 12h52, 480 às 12h54 e 657 às 12h58. São notas atualizadas, não percentual do lote. Não apareceu recuperação indevida desse job pelo supervisor durante essas verificações.

O job terminou às 13h02min53s, após mais de 15 minutos de importação final, sem recuperação indevida pelo supervisor. O log final informa 1.285 linhas: 150 notas criadas, 611 atualizadas, 476 inalteradas ignoradas e 48 eventos importados; zero erros, zero arquivos ausentes e zero avisos de PDF. A contagem direta de 743 notas com `updated_at` recente difere do total de operações do log: uma mesma nota pode ser atualizada mais de uma vez.

## Manutenção fiscal

A execução nativa de `railway run` falha no Windows. A alternativa lê as variáveis pela CLI, valida destino production/Supabase/R2 e passa as credenciais apenas pela memória do subprocesso Python. O código de saída real é registrado.

Simulação concluída com código de saída 0:

- 2.668 eventos analisados; 553 reclassificações propostas.
- 16 registros de evento contêm XML de nota.
- 2.754 notas analisadas; 1.400 alterações propostas.
- 1.573 correções de Simples Nacional.
- 58 casos preservados para revisão manual; 1 XML indisponível; 0 erros.
- Sem regeneração geral dos PDFs antigos.

A aplicação iniciada às 12h48, com 8 leitores de XML, terminou com código de saída real 0 e zero erros: 553 eventos reclassificados, 13 notas criadas (outros 3 XMLs anteriores ao corte foram ignorados), 2.768 notas analisadas, 1.365 alterações de status, 1.565 correções de Simples Nacional, 73 casos preservados para revisão manual e 1 XML indisponível. Nenhuma regeneração geral de PDFs foi executada.

A diferença entre simulação e aplicação é esperada porque o worker continuou ingerindo documentos. A comparação dos 1.400 alvos iniciais encontrou 1.399 status iguais ao previsto. A nota 45860 ficou cancelada; há evento de cancelamento recebido após a simulação, que prevalece sobre a autorização prevista inicialmente.

O arquivo ausente é o XML da nota 28295, de outubro de 2025. Leitura direta retornou `NoSuchKey`. A listagem da pasta no R2 não encontrou objetos e não há cópia local encontrada; apenas uma nota do banco referencia essa pasta. Essa nota permanece pendente de recuperação por backup/origem, sem alteração fiscal inferida.

Sincronização dos eventos recentes iniciada com `--todas --desde 2026-09-17 --workers 4 --executar`: 3.151 notas alvo em 58 empresas. Resultado será acrescentado após conclusão.

Resultado final: código de saída real 0; 3.061 notas consultadas, 111 eventos aplicados, 109 status alterados, 16 notas puladas porque o status mudou durante a execução e zero erros de consulta. Três empresas sem certificado válido: 69 (56 notas), 74 (14 notas) e 76 (4 notas). Seus certificados expiraram; 74 notas ficaram pendentes de consulta. Os 3.151 alvos correspondem a 3.061 consultadas + 16 puladas + 74 pendentes.

Testes finais em produção: 15 verificações passaram, incluindo os três endpoints de saúde, autenticação obrigatória, consulta ao banco, conclusão do lote observado, heartbeat dos jobs ativos e leitura de três XMLs e três PDFs no R2 com validação de formato, checksum SHA-256 e tamanho. Não foi feito teste de navegação autenticada no frontend, pois não havia navegador/sessão disponível.

Um segundo lote do worker (39114) terminou às 13h22 sem erros: 287 notas criadas, 175 atualizadas, 739 inalteradas ignoradas e 137 eventos importados.

Relatórios detalhados estão em `data/post_deploy_2026-10-06/`, ignorado pelo Git. Não contêm credenciais; podem conter identificadores fiscais e devem permanecer locais.
