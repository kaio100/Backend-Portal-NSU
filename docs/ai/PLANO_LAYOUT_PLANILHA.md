# Plano — layout "Relação de NFS-e e retenções" (modelo VS Engenharia)

> Criado em 20/10/2026. **Implementado em 20/10/2026** (sem commit/deploy): `backend/app/services/relatorio_layouts_service.py`, testes em `tests/test_relatorio_layout_planning_hub.py`. Fonte: `VS Engenharia - Relação NFS-e e Retenções 2026.xlsx` (planilha feita à mão pelo escritório, 250 notas de jan a set/2026).

## Objetivo

Ter um seletor "Layout" no menu Baixar. "Conferência" continua sendo o padrão de hoje (3 abas, 31 colunas). O novo layout gera a planilha no formato que o escritório já entrega ao cliente.

## Estrutura do modelo

Uma aba (`Planilha1`). A coluna A fica vazia (largura 5,7) e a tabela começa em B. Fonte Century Gothic 10 em tudo; cabeçalho em 9, negrito, fundo verde `#00FF99`, bordas finas (`hair`). Sem painéis congelados; autofiltro na linha 7.

| Linha | Conteúdo |
|---|---|
| 1 | `Relação de NFSe e retenções <ano>` (negrito) |
| 2 | `Nome do Cliente: <razão social da empresa>` |
| 3 | `CNPJ: <CNPJ com máscara>` |
| 4 | Mês de referência: `=TODAY()-30` com formato `mmm-yy` |
| 6–7 | Cabeçalho em duas linhas. Tudo mesclado na vertical, menos "Retenções" (J6:M6), que se abre em CSRF / IRRF / INSS / ISS na linha 7 |
| 8… | Uma linha por nota |
| última + 2 | Totais com `SUBTOTAL(9; …)` de Valor Total, das 4 retenções e do Líquido |
| última + 4 | `Emitido por: <escritório> CNPJ: <cnpj>` e o quadro de DARF: `CSRF 5952`, `IRRF 1708`, `INSS 1162`, cada um apontando para o total da coluna, e a soma dos três |

## Colunas e de onde vem cada uma

| Col | Cabeçalho | No modelo | Origem no portal (`_relatorio_row`) |
|---|---|---|---|
| B | Competência | `=D` (mês da emissão), formato `mmm-yy` | `Competência` — **decidir**: mês da emissão (igual ao modelo) ou competência da NFS-e |
| C | Município | texto livre e inconsistente ("Rio De Janeiro", "Rio de Janeiro -RJ"…) | `Município`, padronizado como `Cidade - UF` |
| D | Data de Emissão | data | `Data de Emissão` |
| E | CNPJ/CPF | metade número com máscara, metade texto | `CNPJ/CPF` do prestador, sempre texto com máscara (número perde o zero à esquerda) |
| F | Razão Social | texto | `Razão Social` |
| G | Nº Documento | número | `N° Documento` |
| H | Cód. Serviço | texto `01.07` (item LC 116) | `Código de serviço`, sempre texto `NN.NN` |
| I | Valor Total | número contábil | `Valor Total` |
| J | CSRF | `=4,65%*I` ou 0 | `CSRF` |
| K | IRRF | `=1,5%*I` (às vezes 1%) ou 0 | `IRRF` |
| L | INSS | 11% de uma base digitada à mão (mão de obra) ou 3,5% de I | `INSS` |
| M | ISS | `=5%*I` ou 0 | `ISS RET. – SERV. TOMADOS` |
| N | Valor Líquido | `=I-J-K-L-M` | fórmula (mantém editável) |
| O | "Enviado" | `=SE(I>N;"Contém Retenção";"Sem Retenção")`, fonte vermelha | fórmula por linha (o modelo usa coluna inteira `I:I>N:N`) |
| P | Incidência do ISS | `-` ou o município onde o ISS é devido | `Incidência do ISS`, `-` quando é o próprio município |
| Q | Data do pagamento | sempre `-` (preenchido à mão) | `Data do pagamento` ou `-` |
| R | CNO | número da obra (`90.017.20321/75`) ou `-` | **não existe no portal** |

## Problemas do modelo que não vamos copiar

- Título diz 2025 com dados de 2026.
- Total de Valor Total soma só `I228:I263`, não a coluna toda. O total da coluna O soma texto (dá 0).
- 6 linhas vazias no meio (256–261), só com a fórmula da competência.
- Fórmula matricial perdida em F182 (`=UPPER(F120:F160)`).
- Notas fora de ordem de data.
- Formato de data em colunas de texto (P, Q, R e parte de F); código de serviço com formato `d-mmm`, que o Excel pode converter em data.
- Cabeçalho "Enviado" não bate com o conteúdo (retenção sim/não).

## Diferenças em relação ao relatório de conferência

- Sai: Valor B/C, Retenção CSRF, Percentual IRRF, ISS prestados, NBS, CNAE, Simples, status e alertas, dia processado, abas Divergentes/Corretas.
- Entra: bloco de cabeçalho do cliente, cabeçalho de 2 linhas, Contém retenção, CNO, totais e quadro de DARF.
- Valores de retenção: no modelo são calculados por alíquota; no portal vêm do XML (o que foi de fato retido). Proposta: valores do XML; Líquido e "Contém retenção" como fórmula.

## Decisões (20/10/2026)

1. Competência: **mês da emissão**, como no modelo (`=D`).
2. CNO: **fica em branco**. (130 XMLs reais da A IDEAL testados: nenhum tem `serv/obra`.)
3. Nomes: o relatório atual vira o layout **Planning MA**; o modelo novo, **Planning HUB**. "Emitido por" fixo: PLANNING MAROX CONSULTORIA S/S LTDA, CNPJ 30.459.798/0001-03.
4. Planning HUB **só com uma empresa no filtro** (backend devolve 400; o menu desabilita as opções com planilha). Cabeçalho com o nome e o CNPJ da empresa filtrada. Uma aba por empresa foi descartada: com todas as empresas o processamento travaria.

## Como ficou

- Coluna O se chama "Retenção" (no modelo, "Enviado"). Fórmulas por linha (`N`, `O`), não de coluna inteira.
- Município e Incidência: quando a prefeitura manda o código IBGE no lugar do nome (ex.: `xLocPrestacao=5221403`), o nome vem de `backend/danfse/src/Danfse/Data/Municipios.php`. Incidência igual ao município (ignorando acento e UF) vira `-`.
- Linhas por data de emissão; totais com `SUBTOTAL` cobrindo todas as linhas; quadro de DARF com `SUM`.
- Notas com valor 0 no XML (ex.: EMPRESA BRASILEIRA DE BENEFICIOS, 15 notas da A IDEAL) saem com 0: é o que está no XML.
- Notas prestadas também saem (CNPJ/Razão = tomador), mas o layout foi pensado para tomadas.
