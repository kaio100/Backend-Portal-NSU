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

O `.env` e **obrigatorio**. `iniciar_local.py` roda com `ENVIRONMENT=production`,
e nesse modo o backend exige `API_KEY`, `JWT_SECRET` e `SECRETS_KEY`. Sem essas
tres chaves o import das settings falha e a API nao chega a subir. Gere assim:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"   # API_KEY e JWT_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"  # SECRETS_KEY
```

A `SECRETS_KEY` decifra as senhas dos certificados A1. **Trocar essa chave
invalida todas as senhas ja cadastradas** e cada certificado precisa ter a
senha reenviada. Um certificado cuja senha nao pode ser lida e ignorado na
fila de consultas (com um erro no log, procure por "senha nao pode ser lida").

Para rodar os testes, instale tambem as dependencias de desenvolvimento:

```powershell
pip install -r requirements-dev.txt
```

O backend usa certificados salvos via API/banco/storage. As variaveis
`NFSE_PFX_PATH`, `NFSE_PFX_PASSWORD` e `NFSE_CNPJ` so sao necessarias quando
rodar `adn_nfse_downloader.py` diretamente pelo terminal.

## Rodar a API

Para testar consultas reais neste PC com banco SQLite e arquivos locais:

```powershell
python iniciar_local.py
```

Esse comando usa `data/local_test.db`, salva arquivos em `storage/`, inicia
worker e scheduler integrados e disponibiliza a API em `http://127.0.0.1:8000`.
Mantem as validacoes de producao e as chaves do `.env`, mas substitui a conexao
remota e o R2 por persistencia local. O PHP e o vendor do DANFSe devem estar
instalados. Consultas ao ADN continuam reais e exigem certificado cadastrado.

Para usar diretamente a configuracao do `.env`:

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
- `POST /notas/{id}/sincronizar-eventos`: consulta os eventos da nota no ADN
  (`/NFSe/{chave}/Eventos`) com o certificado da empresa e aplica
  cancelamento/substituicao, regenerando o espelho com carimbo.

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

## Onde os arquivos ficam

| | Local (sua maquina) | Producao (Railway) |
| --- | --- | --- |
| `STORAGE_BACKEND` | `local` | `r2` |
| XML e PDF | pasta `storage/` | bucket Cloudflare R2 |

Em producao o `r2` e obrigatorio: o disco do container e efemero e os arquivos
seriam perdidos a cada deploy. No ambiente local use `local` para inspecionar
os arquivos direto no disco.

## Manutencao

Notas baixadas do ADN entram no portal pela ingestao da saida legada. Se uma
consulta for interrompida no meio, as linhas restantes do `index_nfse.csv`
ficam sem nota no banco e o NSU ja avancou, entao elas nao voltam sozinhas.
Para reimportar o que ficou para tras, comparando indice e banco:

```powershell
python -m backend.app.scripts.reconciliar_notas_certificados --certificado-id 1
```

O PDF entregue pelo portal e o **espelho**, gerado na ingestao a partir do XML
pela biblioteca PHP oficial. O download do PDF oficial pelo endpoint DANFSe do
ADN foi desativado (a API deixou de existir) e removido do codigo; PDFs
oficiais ja salvos anteriormente continuam sendo listados e baixados.

Eventos de cancelamento/substituicao chegam pelo proprio fluxo de NSU e sao
aplicados automaticamente. Para uma empresa que ficou sem consulta por um
periodo, varra as notas autorizadas direto no ADN (sem `--executar` so conta):

```powershell
python -m backend.app.scripts.sincronizar_eventos_lote --todas --desde 2026-06-01 --executar
```

## Regras operacionais atuais

- NFS-e com emissao anterior a `NOTAS_DATA_CORTE` (padrao `2026-01-01`) sao
  descartadas na consulta e nao entram no portal.
- O ultimo NSU fica centralizado por empresa/certificado.
- Notas recebidas/emitidas sao classificadas comparando o CNPJ do certificado
  com tomador/prestador.
- Eventos XML sao usados para melhorar status de nota.
- PDF espelho DANFSe e gerado no backend a partir do XML pela biblioteca PHP oficial
  original.
- Downloads em lote retornam ZIP com XML e PDF espelho.
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
