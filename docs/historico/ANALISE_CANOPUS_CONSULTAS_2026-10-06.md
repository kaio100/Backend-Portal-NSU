# Por que faltam notas da Canopus de 01/10 (análise de 06/10/2026)

Fonte: logs do Railway (serviço `Backend-Portal-NSU`, deploy `f2467152`, no ar desde 30/09) e o código dessa versão. O banco (Supabase) não pôde ser consultado nesta análise: o conector estava sem permissão. Horários em Brasília (UTC−3).

## Resposta curta

**Desde 01/10 às 12h16, o portal consulta o ADN de apenas 7 empresas.** As outras 77, inclusive a Canopus Fortaleza (CNPJ 26.354.401/0001-33, empresa 1 no portal), não são consultadas há 5 dias.

A Canopus foi consultada pela última vez em 01/10 às 12h03. Por isso o portal tem as notas de 01/10 que chegaram ao ADN até esse horário, e nenhuma depois.

As notas **não estão perdidas**. O ADN guarda tudo, e quando a consulta voltar o sistema pega tudo o que ficou para trás (veja "Como o sistema busca as notas").

## O que aconteceu

| Quando (Brasília) | O que os logs mostram |
|---|---|
| 30/09 a 01/10 12h03 | Ciclo normal: todas as empresas consultadas, uma por vez, cerca de 1 vez por hora cada. Canopus sem erros. |
| 01/10 11h25 | Certificado novo cadastrado pelo "autocadastro" (`POST /certificados/autocadastrar`), que criou a empresa 80. |
| 01/10 12h16 | Fim do último ciclo completo. A partir daqui o monitor só coloca na fila a empresa 80, a cada 15 min. |
| 01/10 16h13 | Novo autocadastro: a empresa 76 entra no grupo restrito. O certificado dela venceu em 30/09, e ela falha toda vez. |
| 02/10 e 05/10 | Novos autocadastros: empresas 81, 82, 83, 84 e depois 30 entram no grupo restrito. |
| Até agora | Só essas 7 empresas são consultadas (cerca de 24 vezes a cada 6 horas). Nenhuma outra. |

## Causa (confirmada no banco em 06/10)

O monitor automático guarda um filtro (`monitoramento_config.filtros_json`) com duas listas: empresas e certificados. Lista vazia (`null`) quer dizer "todas". As duas listas se combinam: só é consultado o certificado que está **nas duas**.

Em 06/10 o filtro de produção estava assim:

- `empresa_ids = [30, 76, 80, 81, 82, 83, 84]`
- `certificado_ids` = quase todos os certificados (4 a 92)
- `automatico_ativo = true`

O que aconteceu:

1. Antes de 01/10 o filtro tinha só a lista de certificados, com praticamente todos. A lista de empresas estava vazia, ou seja, todas.
2. Em 01/10 às 11h25, o autocadastro da empresa 80 chamou `iniciar_certificado_sem_substituir_monitor`. Essa função "soma" a empresa nova às listas que já existem. Só que somar a empresa 80 a uma lista de empresas **vazia** criou a lista `[80]`.
3. Como as listas se combinam, o monitor passou a consultar só a empresa 80.
4. Cada autocadastro seguinte acrescentou mais uma empresa: 76, 81, 82, 83, 84 e 30.

Números do banco em 06/10: 78 das 84 empresas ativas sem consulta nas últimas 24 horas. As 22 empresas Canopus estão paradas. A Canopus Fortaleza teve a última consulta em 01/10 às 12h04 e tem 9 notas de 01/10 no portal (44.270 notas no total).

**Corrigido no código (branch `ajustes/f6-operacao`, ainda não publicado):** o autocadastro só soma o certificado novo às listas que já são restritas, e lista vazia continua vazia. Com o monitor parado, ele só enfileira a consulta do certificado novo, sem mexer no monitor. Testes de regressão em `tests/test_monitor_e_operacao.py`; o código antigo falha neles.

## Como resolver agora

1. Na tela **Motor ADN**, clicar em **Iniciar** **sem selecionar nenhuma empresa nem certificado**, com o campo **NSU inicial vazio** e **"forçar" desligado**. A tela envia `empresa_ids: []`, que o backend trata como "todas as empresas". Isso volta o monitor ao modo global.
   - **Atenção:** um NSU inicial preenchido seria aplicado a todas as empresas.
2. Em 1 a 2 horas, conferir em Fila/Processos se as empresas antigas (por exemplo, a Canopus) voltaram a ter consultas finalizadas.
3. Não é preciso reprocessar nada: cada empresa continua do último NSU que já tinha, e o primeiro ciclo traz as notas desde 01/10.
4. Resolver o certificado da empresa 76 (vencido em 30/09): renovar ou desativar. Cada tentativa prende o worker por cerca de 3,5 minutos.

## Como o sistema busca as notas (e notas que chegam depois)

- O ADN numera, para cada CNPJ, todo documento que entra (nota emitida, nota recebida, evento de cancelamento ou substituição). Esse número é o **NSU**, sequencial e sem buracos.
- O portal guarda o último NSU de cada empresa e, a cada ciclo, pergunta ao ADN: "o que chegou depois do NSU X?". **Não filtra por data.** O único descarte é de documentos com data anterior a 01/01/2026 (`NOTAS_DATA_CORTE`).
- Por isso, uma nota com data de 01/10 que chegue ao ADN depois (emitida com atraso, enviada tarde pela prefeitura, ou um cancelamento posterior) recebe um NSU novo e entra no próximo ciclo. Ela aparece no portal **com a data dela (01/10)**, como pendente de conferência, mesmo que o dia 01 já tenha sido conferido. **Não existe "dia fechado".**
- Isso só funciona se a empresa estiver sendo consultada, e é isso que quebrou desde 01/10.
- Antes de dar um dia ou competência como conferido, vale olhar a hora da última consulta da empresa.

## Download em lote (ZIP e planilha) em produção

A produção ainda roda a `f2467152`, anterior à F5:

- O ZIP e a planilha ainda têm o **corte silencioso em 5.000 notas**.
- Canceladas e substituídas ainda entram na exportação.

As correções existem nas branches F1 a F5, mas não foram publicadas.

## Recomendações e situação

1. **Imediato (pendente, feito por vocês):** restaurar o monitor global (passo 1 de "Como resolver agora") e tratar o certificado da empresa 76.
   - Esse passo é um **reparo de dado, feito uma vez**. Ele deixa o filtro com as duas listas vazias, e nesse estado nem o código antigo de produção volta a restringir o monitor num autocadastro. Ou seja, o reparo se sustenta mesmo antes do deploy.
   - Ele não corrige a causa. O autocadastro (até o deploy) e o Motor ADN com empresas selecionadas continuam podendo restringir o monitor. Por isso entram os itens 2 a 4.
2. **Código — feito** (`ajustes/f6-operacao`): o autocadastro nunca restringe o monitor. Com o monitor parado, ele só enfileira a consulta do certificado novo.
3. **Alerta — feito** (`operacao_service.empresas_sem_consulta`):
   - Aviso por e-mail e webhook para empresa com certificado válido e sem consulta finalizada há `ALERTA_EMPRESA_SEM_CONSULTA_HORAS` (padrão 6; 0 desliga). Também aparece em `/health/operacao`.
   - No banco de produção em 06/10, essa regra apontaria 71 empresas. Teria avisado em 01/10, por volta das 18h.
4. **Tela — feito** (frontend, `MotorAdn.tsx`):
   - Mostra se o monitor consulta todas as empresas ou só algumas, e lista quais.
   - Botão "Voltar a consultar todas as empresas".
   - Pede confirmação antes de restringir o monitor ou de aplicar um NSU inicial a todas as empresas.
   - O backend expõe isso em `GET /consultas/status`, no campo `monitor`.
5. **Deploy (pendente):** publicar F1 a F6, rodando `corrigir_status_fiscal --aplicar` junto.
