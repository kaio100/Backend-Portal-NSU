# Pendencias Backend Portal

## Regras de atribuicao da fila

O backend antigo expunha:

- `GET /fila-regras-atribuicao`
- `POST /fila-regras-atribuicao`
- `PUT /fila-regras-atribuicao/{regra_id}`
- `DELETE /fila-regras-atribuicao/{regra_id}`
- `POST /fila-regras-atribuicao/reaplicar`

Essas rotas dependiam de uma tabela propria de regras e de aplicacao automatica sobre a fila antiga.
No backend novo ainda nao existe modelo dedicado para regras de atribuicao, e implementar isso agora
exigiria uma decisao de dominio maior: quais campos podem disparar regra, precedencia, auditoria,
escopo por empresa/certificado e quando reaplicar sem sobrescrever escolhas manuais.

Contrato sugerido para migracao futura:

```http
GET /fila-regras-atribuicao
POST /fila-regras-atribuicao
PATCH /fila-regras-atribuicao/{regra_id}
DELETE /fila-regras-atribuicao/{regra_id}
POST /fila-regras-atribuicao/reaplicar?somente_sem_responsavel=true
```

Payload sugerido:

```json
{
  "campo": "prestador_cnpj",
  "operador": "igual",
  "valor": "00000000000000",
  "responsavel": "Fiscal",
  "prioridade": "alta",
  "empresa_id": null,
  "ativo": true
}
```

Regra de seguranca funcional:

- Nunca sobrescrever `responsavel` ou `prioridade_manual` quando ja preenchidos manualmente, salvo acao explicita.
- Registrar operador e data da reaplicacao.
- Preservar filtros e endpoints atuais de notas, processos e downloads.
