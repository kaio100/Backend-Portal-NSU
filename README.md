# Backend NFS-e ADN / Nota Flow

Backend FastAPI para cadastro de certificados, consultas ADN por NSU,
ingestao de XML/PDF, controle de ultimo NSU, arquivos de notas e endpoints
consumidos pelo frontend do Portal NFS-e.

## Estrutura principal

- `backend/`: API, models, repositories, services e worker.
- `backend/danfse/`: biblioteca oficial PHP `DanfseGenerator`, template e bridge interno.
- `storage/`: arquivos vinculados a certificados/notas. Nao subir para Git.
- `data/nfse_backend.db`: banco SQLite local.
- `data/consultas_auto.json`: estado do agendador local.
- `adn_nfse_downloader.py`: motor legado ainda usado pelo backend para consultar o ADN.
- `tests/`: testes automatizados do backend.

Arquivos grandes de execucao local, exports antigos e ferramentas manuais foram
movidos para uma pasta `_limpeza_archive_*` na raiz externa do projeto.

## Instalar

```powershell
pip install -r requirements.txt
copy .env.example .env
notepad .env
```

O backend usa certificados salvos via API/banco/storage. As variaveis
`NFSE_PFX_PATH`, `NFSE_PFX_PASSWORD` e `NFSE_CNPJ` so sao necessarias quando
rodar `adn_nfse_downloader.py` diretamente pelo terminal.

## Rodar a API

```powershell
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

Por padrao, a API inicia tambem o worker interno quando
`API_WORKER_ENABLED=true`.

Para rodar worker separado:

```powershell
python -m backend.app.worker.worker --sleep 5
```

Para rodar o scheduler separado:

```powershell
python -m backend.app.worker.scheduler
```

Se usar worker separado, configure `API_WORKER_ENABLED=false` na API para evitar
dois consumidores da mesma fila.

Em producao, mantenha tambem `EMBEDDED_SCHEDULER_ENABLED=false` na API. O
`docker-compose.yml` ja sobe API, worker e scheduler como processos separados.

## Endpoints importantes

- `GET /health`
- `GET /notas`
- `GET /notas/emitidas`
- `GET /notas/recebidas`
- `GET /notas/{id}`
- `GET /notas/{id}/arquivos`
- `PATCH /notas/{id}/conferencia`
- `POST /notas/download-lote`
- `GET /arquivos/{id}/download`
- `POST /consultas/iniciar`
- `POST /consultas/cancelar`
- `GET /cnpj/status`
- `GET /cnpj/{cnpj}`
- `POST /api/danfse/gerar`: recebe `arquivo_xml` e retorna o DANFSe em PDF.

## Base local de CNPJ da Receita Federal

O importador le o ZIP mensal da Receita em fluxo e cria um SQLite indexado,
sem manter os CSVs descompactados. Para validar CNPJs especificos antes da
carga completa:

```powershell
python -m backend.app.scripts.importar_base_cnpj_receita `
  "C:\caminho\2026-08.zip" `
  --destino data\cnpj_receita.sqlite3 `
  --cnpj 62069724000149
```

Repita `--cnpj` para importar mais de um. Sem `--cnpj`, todos os registros de
Empresas, Estabelecimentos e Simples sao importados; essa operacao exige
dezenas de GB livres e pode demorar. Configure `CNPJ_RECEITA_DB_PATH` com o
caminho do SQLite. Os endpoints exigem o mesmo JWT Bearer do portal.

Para copiar ao cache online somente os CNPJs usados pelo portal, configure
`ONLINE_DATABASE_URL` localmente e valide primeiro sem gravar:

```powershell
python -m backend.app.scripts.sincronizar_cnpjs_portal --dry-run
python -m backend.app.scripts.sincronizar_cnpjs_portal
```

O sincronizador altera somente `cnpj_cache`, em lotes, e prioriza os dados
oficiais da Receita sem remover o cache anterior da Invertexto.

## Regras operacionais atuais

- O ultimo NSU fica centralizado por empresa/certificado.
- Notas recebidas/emitidas sao classificadas comparando o CNPJ do certificado
  com tomador/prestador.
- Eventos XML sao usados para melhorar status de nota.
- PDF espelho DANFSe e gerado no backend a partir do XML pela biblioteca PHP oficial
  original.
- Downloads em lote retornam ZIP com XML e PDF selecionado.
- A geracao local e da API usa exclusivamente `DanfseService`, que chama
  `backend/danfse/generate.php` e `GuilhermeViana\\Nfsenacional\\Danfse\\DanfseGenerator`.
- O backend nao gera DANFSe com ReportLab, HTML/CSS do frontend ou conversao Python.
- Nao existe gerador alternativo de DANFSe no runtime.

## Dependencia do DANFSe oficial

O container instala PHP 8.2, extensoes XML/mbstring e Composer e executa:

```powershell
composer install --no-dev --optimize-autoloader
```

Para desenvolvimento local, instale PHP 8.1 ou superior, Composer e as extensoes
`dom`, `fileinfo`, `libxml`, `mbstring` e `simplexml`. Depois execute o comando
acima em `backend\\danfse`. Sem `vendor/autoload.php`, a rota retorna um
erro claro e nao usa um gerador alternativo.

## Validar

```powershell
python -m pytest tests -q
python -m compileall backend/app -q
python -m backend.app.scripts.reconciliar_storage --json
```

## Cuidados

Nao versionar `.env`, certificados `.pfx/.p12`, `storage/`,
`saida_adn_nfse/`, bancos locais, logs ou `data/tmp_worker/`.

Em producao, monte `data/` e `storage/` em volumes persistentes externos ao
container. O compose local usa os volumes `nfse_data` e `nfse_storage`.
