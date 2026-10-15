# ADR-0003 — NSU central só avança no fim do job; releitura profunda como rede de segurança

- **Status:** aceito
- **Data:** 2026-09-25 (F3, `11c8f8bd`); releitura após parada em 2026-10-06 (F6, `171cb36a`)

## Contexto
O NSU avançava assim que o XML era salvo em disco. Uma queda entre o download e a ingestão deixava documentos para trás do cursor, sem aviso. A saída do motor ficava no disco efêmero do container.

## Decisão
1. A saída do motor fica no volume (`LEGACY_OUTPUT_DIR=data/saida_adn_nfse`).
2. Durante o job, só o estado local do motor avança. O NSU central (`nsu_controle`) é gravado no fim, depois da ingestão final, limitado ao primeiro NSU com erro de ingestão menos 1, com aviso no processo.
3. Cada consulta parte do NSU confirmado menos 50. Releitura profunda (desde antes do mês anterior, menos 1000) uma vez por noite, na volta de uma parada de 6 h e a pedido (REG-040).

## Consequências
- (+) Queda no meio do job não perde documento: o próximo job relê.
- (−) A proteção do item 2 tem limites (ARCH-005): detalhes de erro limitados a 20 e "confirmado" calculado com o maior NSU das notas. Na prática, a releitura noturna é a rede de segurança.
- (−) O volume cresce (ARCH-009).

## Validação
`tests/test_consulta_adn_confiavel.py`, `tests/test_releitura_mes_anterior.py`.
