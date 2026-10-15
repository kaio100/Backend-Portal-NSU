# Backend Portal NFS-e — instruções para agentes

Antes de mexer no código, leia `docs/ai/00_LEIA_PRIMEIRO.md` e, conforme a tarefa, o documento indicado na tabela "Como usar estes documentos". Problemas conhecidos: `docs/ai/FINDINGS.md`.

- `docs/ai/` = estado atual. `docs/historico/` = congelado: não edite, não trate como verdade atual.
- Depois de mudar código, siga "Como manter estes documentos" em `docs/ai/00_LEIA_PRIMEIRO.md` (atualizar o doc certo, `CHANGELOG.md`, e rodar `python docs/ai/gerado/gerar_indices.py`).
- Achados com status de certeza (CONFIRMADO, FORTEMENTE_INDICADO, HIPOTESE, NAO_DETERMINADO) e evidência (arquivo:linha, log, teste). Não afirme que algo funciona ou que um teste passou sem ter executado.
- O `.env` desta máquina aponta para o banco e o storage de **produção**. Não suba `uvicorn` direto; use `python iniciar_local.py`. Scripts de `backend/app/scripts/` que escrevem: rode a simulação antes de `--aplicar`/`--executar`.
- Push na `main` = deploy no Railway.
