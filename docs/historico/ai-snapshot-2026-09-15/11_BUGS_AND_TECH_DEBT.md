# Bugs visíveis, bugs potenciais e dívida técnica

## Bugs de integração confirmados

1. **Cadastro frontend sem endpoint:** `frontend/src/lib/api.ts` implementa `criarConta()` para `POST /auth/criar-conta` e `pages/CriarConta.tsx` usa-o; `backend/app/api/routers/auth.py` não registra essa rota no commit auditado. Resultado esperado: falha de cadastro.
2. **Grupos com contrato incompatível:** o método frontend `listarGruposPublicos()` chama `GET /auth/grupos`; no backend a função tem dependência `require_admin`. Usuário não administrador recebe 403.
3. **Função duplicada:** `portal_support_service.py` define `exportar_conferencia_xlsx` em aproximadamente 696 e 1235. O segundo símbolo substitui o primeiro no módulo; importadores não escolhem explicitamente qual contrato pretendiam.
4. **Limite de exportação inconsistente:** `notas_repo.list_notas` aplica teto 5.000, mas `Settings.download_lote_max_notas` permite 10.000; o caminho de lote pode não alcançar o limite configurado.
5. **Filtro GET incompleto:** `/notas/download-lote` GET não expõe todos os campos aceitos pelo POST/schema (conferência, prioridade, SLA, valores e divergência entre eles). A mesma tela pode exportar universos diferentes conforme método.

6. **Subitem genérico antes de subitem válido (corrigido nesta alteração):** o extrator parava em qualquer primeiro código normalizável, mesmo que a planilha não o conhecesse. Agora ele continua pelos demais campos quando encontra um candidato sem regra; o primeiro continua sendo usado somente como fallback quando nenhum candidato tem regra.

7. **Cache/cópia da planilha (corrigido nesta alteração):** o carregador mantinha uma única leitura em memória e priorizava sempre `data/`, fazendo edição da cópia raiz ou alteração após startup parecer ignorada. O carregamento agora fecha o workbook, escolhe fonte configurável/mais recente e invalida cache por `mtime`/tamanho.

8. **Colisão com código municipal de 3 dígitos (corrigido nesta alteração):** `cTribMun=501` era normalizado como subitem LC116 `5.01`, podendo aplicar silenciosamente a regra de medicina veterinária a uma nota de locação sem incidência. Códigos municipais simples de 3 dígitos agora não são convertidos em subitem; o código nacional é preservado separadamente.

9. **Classificação de status por palavra-chave (corrigido em 2026-09-25, branch `ajustes/f1-status-fiscal`):** `_status_from_xml` procurava "cancel"/"subst" em qualquer texto e tratava como evento todo XML com `chSubstda` e a palavra "evento". Em produção: nota substituta válida (cStat 101) gravada como `substituida` (239 notas), notas de empresas/serviços de eventos gravadas como evento e ausentes do portal (15), "Solicitação de Análise Fiscal" (e101103) gravada como cancelamento, cancelamento por substituição (e105102) gravado como `cancelada`, cStat 102/103 sem rótulo. Substituído por `nfse_status_service.classificar_xml` (REG-014). **Os dados já gravados em produção ainda precisam do script de correção da Fase 1.**

## Bugs potenciais sustentados pela leitura

- **Duplicidade de evento:** `eventos` não possui unique composto; a idempotência depende de `_registrar_evento_xml` e de suas buscas. Reprocessamento concorrente merece teste.
- **Job órfão:** processo pode morrer entre claim, chamada legada e commit; recuperação de jobs stale é feita no startup, não como garantia distribuída contínua.
- **Cancelamento sem efeito externo:** marcar `Processo` cancelado não interrompe chamada já em execução; notas podem chegar após o cancelamento.
- **Truncamento silencioso de relatório:** `_buscar_notas_relatorio` usa limite fixo e filtro posterior em memória.
- **Desalinhamento de timezone:** `calcular_sla_operacional` assume UTC para datetime sem tz, enquanto dados locais podem ser São Paulo.
- **Falha parcial DB/storage:** escrita de arquivo e persistência de índice ocorrem em operações separadas.
- **Rate limit não distribuído:** várias instâncias permitem mais tentativas do que a política aparenta.
- **Contratos legados paralelos:** `/nfse` e `/notas` podem divergir em campos e semântica de atualização.

## Dívida técnica/arquitetura

- Serviços de milhares de linhas concentram parsing, SQL, storage e regra fiscal; a cobertura de unidade precisa acompanhar qualquer extração.
- A ponte dinâmica para `adn_nfse_downloader.py` reduz tipagem e torna imports/paths parte do contrato oculto.
- Não há histórico Alembic versionado; alterações de banco ficam espalhadas por `session.py` e scripts.
- Alguns repositories existem, mas muitos services fazem `db.query` direto; transações e escopo não são uniformes.
- Flags e estados são strings livres (`status`, `tipo`, `papel`) apesar de conjuntos finitos; typo pode ser persistido.
- Observabilidade é parcial (contadores em memória, logs opcionais e webhook síncrono com timeout).
- Scripts operacionais e one-offs convivem em `app/scripts`, sem catálogo de risco/ambiente.
- A regra fiscal depende de XLSX externo ao código; versão/ checksum da planilha não é persistida na nota.
- `docs/ai.zip` e backups de operação podem confundir agentes se tratados como fonte de verdade.

## Código morto/duplicado a investigar (sem apagar)

- Funções de compatibilidade em `routers/certificados.py` e `nfse_compat.py` permanecem por contratos antigos.
- `consulta_simples_api_from_payload` é marcada deprecated, mas ainda está disponível para chamadas históricas.
- Há aliases de campos e rotas (`view/preview/visualizar`, status/data/CNPJ) para compatibilidade; não remover sem busca no frontend e testes.
- O catálogo completo deve ser rechecado com `ruff`/pyflakes e cobertura dinâmica antes de classificar imports como mortos; esta auditoria não apagou nenhum.
