# Visão geral do projeto

## Estado auditado

- Data da leitura: 2026-09-15.
- Backend: `f50da548530945516cf5a2f0b4b1ea5dcecdf1e5` (`feat: adicionar retificacao de analises`).
- Frontend compatível: `0fd4b07df3a994450d36ab993a75c61f851884eb` (`feat: melhorar filtros e retificacao`), repositório `Frontend-Portal-NSU`.
- Escopo: backend e frontend efetivamente usados juntos, incluindo configuração, scripts, testes, pacote PHP DANFSe e integrações. A limpeza operacional da empresa Canopus já havia sido feita; esta auditoria não altera dados nem código funcional.
- Inventário: 255 arquivos versionados no backend, 130 módulos Python (16.587 linhas medidas), 823 declarações de classe/função detectadas por AST/regex e 88 declarações explícitas de rota (aproximadamente 89 rotas registradas). O frontend tem 83 arquivos TypeScript/TSX em `src` (7.112 linhas medidas).

## Objetivo

O Portal NFS-e consulta documentos fiscais eletrônicos no Ambiente de Dados Nacional (ADN), usando certificado digital, guarda XML/eventos/PDF em storage, persiste o índice fiscal no banco e fornece uma interface para conferência operacional. Também administra empresas, grupos, usuários, certificados, consultas NSU, filas de processamento, retenções e exportações XML/PDF/XLSX.

## Arquitetura em uma frase

O desenho pretendido é `React/React Query -> FastAPI router -> schema/dependency -> service -> repository/SQLAlchemy -> banco/storage`, mas a execução real é híbrida: os serviços grandes acessam o banco diretamente e o worker ainda chama o motor legado `adn_nfse_downloader.py` por `legacy_processing_service.py` e importa os resultados por `legacy_ingestion_service.py`.

## Componentes

| Componente | Responsabilidade | Entrada principal | Saída |
|---|---|---|---|
| Frontend React/Vite | Login, dashboard, fila, conferência, certificados, empresas e administração | HTTP JSON/arquivos da API | Estado React Query, tabelas, downloads |
| API FastAPI | Contratos HTTP, autenticação, autorização, validação e serialização | Requests, JWT/API key, multipart | JSON, FileResponse, métricas |
| Serviços Python | Regras fiscais/operacionais, orquestração de consultas, downloads e relatórios | Schemas, `Session`, storage | Entidades atualizadas, bytes, XLSX, jobs |
| Repositories | Consultas SQLAlchemy reutilizáveis | `Session`, filtros e IDs | Modelos/listas/contagens |
| Worker/scheduler | Processamento assíncrono de `Job` e ciclos automáticos | Fila no banco | `Processo`, `Job`, logs, notas e arquivos |
| Motor ADN legado | Comunicação externa com ADN via certificado PKCS#12 | CNPJ, NSU, certificado, payload | CSV/XML/PDF em diretório de saída |
| Ingestão | Leitura de XML/CSV/PDF, normalização, upsert e deduplicação | Diretório legado | `Nota`, `Evento`, `Arquivo`, storage |
| Banco | Estado transacional do portal | SQLAlchemy SQLite/PostgreSQL | Dados persistidos |
| Storage | XML, PDF espelho/oficial, certificados, exports e temporários | chave lógica + bytes | arquivo local ou Cloudflare R2 |
| DANFSe PHP | Renderização de PDF espelho a partir de XML | XML multipart/subprocesso | PDF |

## Ciclo normal

1. Usuário autentica (`/auth/login`); o frontend guarda o JWT em memória/storage próprio e envia `Authorization: Bearer`.
2. Usuário cadastra empresa/certificado ou habilita consulta automática.
3. `consultas_service` cria `Processo` e `Job`; worker reclama o job e obtém lock por empresa/certificado.
4. A ponte legada consulta o ADN por NSU, gravando CSV/XML/PDF; a ingestão identifica a chave, normaliza valores/status/eventos e faz upsert.
5. XML/PDF são colocados no storage e indexados em `arquivos`; o frontend consulta `/notas*`, `/processos*` e `/eventos`.
6. Conferência pode atualizar campos operacionais e exigir `retificar`; downloads produzem ZIP e relatórios produzem XLSX.

## Fronteiras que não devem ser confundidas

- `/api/danfse/gerar` usa PHP oficial, não o parser Python.
- `Nota.status_documento` é o status fiscal persistido; status de fila/conferência/SLA são campos distintos.
- `Processo/Job` representam execução e fila; `Nota/Evento/Arquivo` representam resultado.
- O storage não é transacional com o banco: uma chave de arquivo pode sobreviver sem linha ou vice-versa.
- `docs/ai.zip` existente no diretório é artefato externo não versionado; esta pasta contém a auditoria atual e não deve ser substituída cegamente por aquele arquivo.

## Leitura recomendada

Comece por `14_AI_HANDOFF.md` e `16_AGENT_QUICK_START.md`, depois leia `02_ARCHITECTURE.md`, `05_DATA_FLOW.md` e o documento do módulo a alterar. Consulte `10_RISK_REGISTER.md` antes de tocar em worker, migração, status ou storage.

## Relatório da segunda passagem

Foi feita uma revisão cruzada após a escrita dos mapas: os 19 routers foram enumerados, as 88 declarações explícitas de rota foram comparadas com `07_API_MAP.md`, as 16 tabelas de domínio (mais `TimestampMixin`) foram comparadas com `06_DATABASE_MAP.md`, e os arquivos de configuração, scripts, worker, DANFSe, testes e frontend foram conferidos contra o inventário Git. Resultado do snapshot: 255 arquivos versionados no backend; 130 Python/16.587 linhas; 83 fontes TS/TSX/7.112 linhas no frontend; 823 declarações de classe/função na varredura estática; 88 declarações de rota; 16 entidades de banco; 4 integrações externas principais (ADN, Receita/Invertexto, R2, PHP/Composer) e webhook opcional; 32 regras de negócio catalogadas; 5 bugs de integração/estrutura confirmados e 19 riscos adicionais (24 registros no total); 20 arquivos críticos.

O que ficou propositalmente fora da leitura linha a linha: `.git`, caches, dependências instaladas, builds, binários, fontes TTF/PNG, XML de exemplo e artefatos de backup/recovery. Eles foram identificados e classificados como não-fonte de comportamento. Nenhum código funcional, banco, API, arquivo de dados ou configuração operacional foi alterado nesta auditoria.

## Atualização após a auditoria

Em 2026-09-15 foi aplicada uma correção focada no carregamento e na identificação das regras fiscais: cabeçalhos do XLSX agora são normalizados, o cache acompanha `mtime`/tamanho, a planilha é fechada após a leitura, o extrator tenta candidatos LC116 posteriores quando o primeiro código não possui regra e ignora `cTribMun` simples de 3 dígitos para não colidir com subitens LC116. O cTribNac original é preservado quando o candidato municipal é usado como fallback. Essa alteração está fora do commit histórico restaurado e foi validada por 207 testes aprovados.
