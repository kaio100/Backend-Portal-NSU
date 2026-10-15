# Deploy de producao

## Backend

1. Crie o arquivo `.env.docker` a partir de `.env.docker.example` somente no ambiente de deploy.
2. Configure `ENVIRONMENT=production`.
3. Use PostgreSQL gerenciado em `DATABASE_URL`.
4. Configure `SECRETS_KEY`, `API_KEY` e `JWT_SECRET` no gerenciador de secrets.
5. Configure `CORS_ORIGINS` com a origem exata do frontend, sem `localhost`.
6. Use volume persistente e backup externo para `/app/storage` e `/app/data`, ou configure um storage de objetos.
7. Suba API, worker e scheduler como processos separados. A API deve manter `API_WORKER_ENABLED=false` e `EMBEDDED_SCHEDULER_ENABLED=false`.

O container executa a migracao do banco antes de iniciar a API. Execute uma unica instancia da API durante a primeira migracao ou use o mecanismo de migracao do provedor.

## Frontend

1. Configure `VITE_API_BASE_URL` com a URL HTTPS publica da API.
2. Execute `npm ci` e `npm run check` no pipeline.
3. Publique o diretorio `dist` usando `npm run build`.

## Validacao pos-deploy

- `GET /health` deve retornar HTTP 200.
- `GET /db/health` deve retornar HTTP 200.
- `GET /metrics` deve estar acessivel somente conforme a politica de exposicao do provedor.
- O login deve funcionar a partir da origem configurada no CORS.
- Gere um DANFSe autorizado, um cancelado e um substituido antes de liberar o portal.
