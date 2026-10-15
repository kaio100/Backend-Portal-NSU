# Análise de segurança — certificados

Data: 6 de outubro de 2026. Backend publicado: commit `a0cfbaf4`. Revisão do código, consultas de leitura no banco de produção, testes HTTP sem autenticação e verificação do armazenamento. Nenhuma chave, senha ou conteúdo de certificado foi exibido. Não foram alteradas configurações de segurança nem certificados.

## Conclusão

Há controles reais de proteção, mas foi confirmada exposição de credenciais ainda ativas no histórico do Git. Foram encontrados 13 blobs históricos de configuração de ambiente e 7 blobs PFX/P12. A comparação em memória identificou a SECRETS_KEY atual em 9 versões antigas e as credenciais atuais do R2 em 3 versões antigas. Não foram exibidos os valores. JWT_SECRET, DATABASE_URL e API_KEY também aparecem no histórico, mas os valores encontrados não coincidem exatamente com os atuais; isso não confirma sua revogação ou inocuidade.

Esse achado exige tratamento prioritário e rotação. Remover os arquivos do HEAD não remove os commits antigos. Não há prova de uso indevido por terceiros nesta revisão, que não equivale a um teste de invasão completo. A configuração de acesso público do bucket e as permissões das contas Cloudflare/Railway não puderam ser confirmadas no painel desses provedores.

## Controles confirmados

- 92 registros de senha criptografados com Fernet; todos puderam ser decifrados pela chave configurada, sem saída dos valores. SECRETS_KEY válida e distinta de JWT_SECRET; JWT_SECRET tem pelo menos 32 caracteres. Isso verifica configuração, não demonstra a entropia ou ausência de exposição histórica das chaves.
- Supabase: RLS ativa em `certificados`, `secrets` e `usuarios`; SELECT negado aos papéis `anon` e `authenticated` nessas tabelas.
- `/certificados`, `/certificados/1`, `/certificados/1/senha/status` e `/admin/overview` retornaram HTTP 401 sem autenticação.
- A aplicação limita acesso por grupo; schemas não devolvem a senha; download genérico bloqueia arquivo com tipo `certificado`.
- Logs estruturados removem valores de campos de senha, chave e token. As chamadas ao ADN usam HTTPS/mTLS e verificação TLS.
- Conexão de auditoria ao pooler Supabase usou TLS, confirmado na conexão libpq do cliente. O `ssl=false` de `pg_stat_ssl` corresponde ao trecho interno visto pelo banco atrás do pooler, não prova ausência de TLS no cliente.
- 26 testes locais de configuração, logs, HTTP e isolamento de contas/grupos passaram.

## Achados e ações

| Prioridade | Achado | Evidência e ação recomendada |
|---|---|---|
| Crítica | SECRETS_KEY e credenciais R2 atuais no histórico Git | Comparação de valores em memória confirmou correspondência com produção. Restringir acesso ao repositório e suas cópias; substituir/revogar credenciais do R2; rotacionar SECRETS_KEY com recifragem de todos os segredos antes de retirar a chave antiga; revisar acessos e uso dos certificados; depois remover arquivos sensíveis do histórico e coordenar limpeza de clones/artefatos. Não executar reescrita de histórico nem revogação sem preparação para preservar operação. |
| Alta | PFX armazenado no formato original, sem camada adicional de criptografia da aplicação | `certificados_service.py` envia `pfx_bytes` diretamente ao storage. A senha do PKCS#12 é a proteção interna do arquivo; não deve ser a única barreira para o material de chave privada. Adicionar criptografia autenticada ao arquivo, preferencialmente com chave gerenciada separadamente, e acesso ao bucket restrito. A força dos algoritmos internos dos 92 PFX não foi auditada individualmente. |
| Alta, conforme política de permissões | Autocadastro permite que usuário autenticado substitua certificado existente do próprio grupo | POST de autocadastro exige login, enquanto PATCH de substituição exige admin. `autocadastrar_certificado` reutiliza certificado ativo e sobrescreve PFX/senha. Não permite trocar certificado de outro grupo, mas a política de renovação é mais ampla que a de edição. Exigir autorização explícita para substituição e registrar autor/objeto/resultado em auditoria. |
| Média | Falha no construtor da sessão pode deixar PFX temporário | `SessaoCertificado.__init__` grava o PFX antes de decifrar senha e montar adapter; se uma dessas etapas falha, `fechar()` não é chamado. Encontrados 3 PFX temporários locais após a execução com 3 certificados vencidos. Usar criação segura, limpeza também em falha de inicialização, diretório privado e remoção de órfãos. |
| Média | Privilégios amplos do usuário de banco | Papel usado pelo backend tem `rolbypassrls=true`. O isolamento depende das verificações da aplicação, mesmo com RLS ativa. Usar papel de runtime com apenas permissões necessárias e separar migrações/administração. |
| Média | TLS do banco não é exigido explicitamente | DATABASE_URL sem `sslmode`; conexão observada negociou TLS. Exigir TLS e, preferencialmente, validar CA e hostname com `verify-full`, após teste de compatibilidade. |
| Operacional e validação | Certificados vencidos permanecem ativos | 92 certificados cadastrados, 83 ativos, 6 ativos vencidos, nenhum ativo sem referência de senha. Seleção de eventos não filtra validade. Bloquear vencidos antes de preparar sessão e alertar sobre renovação. O validador de upload atualmente verifica abertura do PFX e presença do certificado, mas não garante todos os requisitos de validade, chave privada, cadeia/revogação ou correspondência de CNPJ em todos os caminhos. |
| Melhoria adicional | MFA e limitação distribuída | Não encontrado MFA/TOTP/WebAuthn no fluxo próprio de autenticação. Limites de tentativa ficam em memória por processo; ficam inconsistentes com múltiplas instâncias/reinício. Priorizar MFA para administradores e armazenamento compartilhado do contador ao escalar. |

O Dockerfile não define usuário não-root. Os PFX temporários são gravados com `write_bytes`, sem modo privado explícito. Isso merece endurecimento do container e permissões de diretório/arquivo; não foi observado acesso por outro usuário no servidor.

## Armazenamento público: limite da verificação

A tentativa de leitura sem assinatura de um objeto PFX no endpoint S3 do R2 retornou HTTP 400 e não entregou o arquivo. Isso não confirma que `r2.dev` e domínios públicos personalizados estejam desativados. Conferir essa configuração no Cloudflare; separar os certificados dos documentos fiscais e limitar as credenciais de serviço ao bucket necessário.

A API do GitHub consultada sem autenticação retornou 404 para o repositório. Portanto, não foi demonstrado acesso público anônimo, mas a visibilidade e os colaboradores precisam ser confirmados com acesso autenticado. O histórico sensível está disponível no clone local; qualquer pessoa ou automação com acesso às cópias pertinentes pode recuperá-lo.

## Sequência de resposta recomendada

1. Revisar e restringir colaboradores, automações, cópias e artefatos do repositório. Preservar evidências e revisar acessos no Railway, Cloudflare e GitHub.
2. Preparar credencial R2 substituta com escopo mínimo, validar acesso, atualizar o backend e revogar a antiga.
3. Preparar nova SECRETS_KEY mantendo transitoriamente a antiga como chave secundária. Recifrar os 92 segredos com `rotacionar_segredos --aplicar`, verificar zero falhas e então retirar a chave antiga de todos os ambientes. Não simplesmente substituir a chave: isso torna as senhas antigas ilegíveis.
4. Verificar as credenciais históricas de banco/JWT/API e sua efetiva revogação. Diferirem das atuais não comprova revogação em outros ambientes.
5. Remover arquivos sensíveis do histórico, coordenar clones e caches e impedir nova inclusão com regras e verificação automatizada. Reescrita do histórico exige preparação, pois afeta quem colabora no repositório.
6. Corrigir limpeza/permissões temporárias, criptografia adicional dos PFX, autorização de substituição e trilha de auditoria.
7. Avaliar certificados possivelmente acessados. Se houve acesso ao PFX e à senha/chave privada, trocar apenas as chaves de armazenamento não desfaz o comprometimento do certificado; considerar revogação e reemissão junto ao titular/emissor, conforme evidências.

## Efeito operacional confirmado

A sincronização consultou 3.061 notas e aplicou 111 eventos, com 109 mudanças de status e zero erros de consulta. Três empresas (69, 74, 76) ficaram sem consulta por certificado vencido: 74 notas ao todo. Dezesseis notas foram puladas porque seu status mudou durante a execução. Os 15 testes finais em produção passaram, incluindo leitura e checksum de XML/PDF; isso não elimina essas pendências nem constitui auditoria completa de conformidade fiscal.

## Referências

- Cryptography, segurança do PKCS#12: https://cryptography.io/en/stable/hazmat/primitives/asymmetric/serialization/
- OWASP, gestão e privilégio mínimo de segredos: https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html
- PostgreSQL, validação de TLS: https://www.postgresql.org/docs/current/libpq-ssl.html

Relatório técnico de contagens e códigos HTTP: `data/post_deploy_2026-10-06/auditoria_seguranca.json` (ignorado pelo Git). Relatórios detalhados fiscais permanecem locais.
