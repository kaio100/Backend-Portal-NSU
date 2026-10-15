# ADR-0004 — Status fiscal decidido só pela estrutura do XML

- **Status:** aceito
- **Data:** 2026-09-25 (`2052dd62`; correção dos dados por `corrigir_status_fiscal`, `0e019a2d`)

## Contexto
A classificação antiga procurava as palavras "cancel"/"subst" em qualquer texto do XML. Em produção: 239 notas substitutas válidas gravadas como substituídas, 15 notas de empresas de eventos tratadas como evento e sumidas do portal, solicitação de análise fiscal tratada como cancelamento.

## Decisão
`nfse_status_service.classificar_xml` decide pela raiz (`<NFSe>` × `<evento>`), pelo `cStat` e pelo código do evento, nunca por palavras de texto livre. Prioridade cancelada > substituida > demais; reprocessar nunca rebaixa (REG-014). Dados antigos corrigidos por script com simulação e relatório antes de aplicar.

## Consequências
- (+) Classificação explicável e testada com XML reais mascarados (`tests/fixtures/nfse_reais`).
- (−) Código de evento desconhecido não muda o status (só gera log): evento novo do ADN exige atualizar a tabela de códigos.
