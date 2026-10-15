# Catálogo de funções e classes

## Como ler este catálogo

Foram identificadas 823 declarações de classe/função no backend por varredura estática; funções privadas de parsing/normalização aparecem agrupadas quando têm o mesmo contrato. O mapa prioriza símbolos que têm efeitos (DB, storage, API ou processo) e registra o caminho de chamada. Para o catálogo integral de nomes, use `rg "^(async )?def |^class " backend -g '*.py'`; essa busca é intencionalmente a fonte mecânica para futuras revisões.

## Lifecycle, segurança e infraestrutura

| Símbolo | Arquivo | Entrada → saída/efeito | Chamado por / cuidados |
|---|---|---|---|
| `lifespan` | `app/main.py:170` | startup/shutdown → `init_db`, limpeza ZIP, recálculo, PDF revalidation, workers/scheduler | FastAPI; altera estado no startup e pode abrir tarefas |
| `_run_api_worker`, `_run_consultas_scheduler` | `app/main.py:98,120` | grupo/slot → loops assíncronos | lifespan; cancelamento e exceções devem ser observados |
| `init_db`, `migrate_db`, `_ensure_runtime_columns` | `db/session.py:71-92` | settings → tabelas/ALTER/índices | lifespan/scripts; schema drift e concorrência |
| `get_db` | `db/session.py:63` | request → `Session` com finally close | Depends; nunca reter sessão fora da request |
| `require_api_key` | `api/deps.py:23` | `X-API-Key` → 401/503 ou sucesso | rotas de máquina; configuração ausente vira 503 |
| `get_current_usuario`, `require_admin`, `require_operator` | `api/deps.py:41-68` | Bearer JWT → usuário/papel | routers; papel/tenant são aplicados na camada FastAPI |
| `require_*_grupo` | `api/deps.py:71-105` | id + usuário → entidade tenant-scoped | notas/processos/arquivos/certificados/empresas |
| `hash_password`, `verify_password`, `create_access_token`, `decode_access_token` | `backend/app/core/security.py` | credencial/claims → hash/JWT/claims | auth; PBKDF2 600k e HS256 |
| `check_login_rate_limit`, `register_login_attempt` | `backend/app/core/rate_limit.py` | IP+email → permitido/bloqueado | login; memória local por processo |

## Autenticação, empresas e certificados

| Símbolo | Arquivo | Fluxo real |
|---|---|---|
| `login`, `login_local`, `me` | `api/routers/auth.py` | valida credencial → usuário ativo → JWT/identidade; `local` é restrito a localhost |
| serviços de `auth_service.py` | `services/auth_service.py` | busca usuário, compara hash, serializa claims e cria usuário API | auth router/admin |
| `criar_empresa`, `listar_empresas`, `atualizar_empresa`, `excluir_empresa` | `api/routers/empresas.py` + `empresas_service.py` | valida CNPJ/grupo → `Empresa` → commit; exclusão valida dependências | frontend Empresas/Admin |
| `upload_certificado`, `autocadastrar_certificado`, `testar_certificado` | `certificados.py` + `certificados_service.py` | multipart bytes → metadata PKCS#12 → chave em storage + senha em `Secret` | telas Certificados; arquivo até limite configurado |
| `salvar_senha_certificado`, `status_senha_certificado`, `remover_senha` | `certificados.py` + `secrets_service.py` | cifra/decifra Fernet e atualiza `Certificado.senha_secret_ref` | worker depende de senha salva |
| `certificado_metadata` | `certificado_metadata_service.py` | bytes PFX → thumbprint, subject e validade | upload/autocadastro |

## Consulta, fila e worker

| Símbolo | Arquivo | Entrada → efeito |
|---|---|---|
| `get_monitoramento_config`, `montar_status`, `is_enabled` | `consultas_service.py:51-126` | grupo → configuração/status de processos e certificados |
| `list_certificados_elegiveis` | `consultas_service.py:149` | filtros de grupo/ativo/validade/storage/senha → certificados aptos |
| `_create_consulta_job`, `enqueue_consultas_pendentes` | `consultas_service.py:182-268` | certificado/opções → `Processo` + `Job`; evita duplicidade ativa |
| `iniciar_consultas_automaticas`, `iniciar_certificado_sem_substituir_monitor`, `desativar_consultas_automaticas` | `consultas_service.py:269-396` | request → configura monitor, enfileira ou cancela pendências |
| `criar_processo`, `cancelar_processo`, `listar_jobs` | `processos_service.py`/router | empresa+certificado+opções → estados e jobs; cancelamento running não interrompe motor |
| `processar_job`, `processar_job_simulado` | `worker/jobs.py:233,46` | Job → claim/lock, simulação, logs e estado final |
| `processar_job_consulta_nfse_real` | `worker/jobs.py:141` | Job → `executar_consulta_nfse_legado`, commit/rollback e liberação de lock |
| `executar_consulta_nfse_legado` | `legacy_processing_service.py:512` | processo/job → motor legado, ingestões incrementais, PDF e NSU |
| `_load_legacy_module`, `_configure_legacy_output` | `legacy_processing_service.py:61-97` | ID/path → módulo importado e diretórios de saída |
| `nsu_service` (`get_estado_nsu`, `atualizar_nsu`) | `nsu_control_service.py` | empresa+certificado → cursor monotônico e lookback horário |

## Ingestão e documentos

| Símbolo | Arquivo | Contrato e efeitos |
|---|---|---|
| `parse_xml_resumo_bytes`, `_parse_xml_resumo_root` | `legacy_ingestion_service.py:411-571` | XML bytes/path → resumo normalizado de nota, partes, valores e status |
| `_status_from_xml`, `identificar_iss_retido`, `extrair_codigo_servico_xml` | mesmo arquivo | XML → status fiscal, retenção e LC/serviço; namespaces são tratados por local-name |
| `_registrar_evento_xml`, `_aplicar_campos_fiscais_xml` | mesmo arquivo | evento/XML → upsert de `Evento` e campos fiscais da `Nota` |
| `_put_file_if_needed`, `_registrar_arquivo` | mesmo arquivo | arquivo local → hash, storage e `Arquivo` deduplicado |
| `ingerir_saida_legado`, `_ingerir_por_varredura` | `legacy_ingestion_service.py:802,1152` | diretório legado → parse, upsert de Nota/Evento/Arquivo, PDF espelho e contagens |
| `upsert_nota_by_chave` | mesmo arquivo | chave + resumo → insert/update idempotente de `Nota` |
| `listar_notas`, `listar_todas_notas`, `listar_notas_por_tipo_operacional` | `notas_service.py:278-693` | filtros → repository, classificação emitida/recebida, anotações frontend e paginação |
| `obter_nota`, `obter_nota_por_chave` | `notas_service.py:694-709` | ID/chave + tenant → detalhe ou erro |
| `atualizar_conferencia` | `notas_service.py:710` | payload de conferência → campos operacionais; bloqueia nova edição se responsável existe sem `retificar` |
| `gerar_zip_notas`, `_buscar_notas`, `_select_arquivos` | `notas_download_service.py:148-245` | filtros → notas/arquivos, bytes, nomes deduplicados e ZIP temporário |
| `listar_documentos_nota`, `listar_eventos`, `comparar_tributos_nota` | `portal_support_service.py:90-272` | DB/storage → DTOs de portal |
| `exportar_conferencia_xlsx` | `portal_support_service.py:696` e `1235` | filtros → relatório XLSX; a segunda definição sobrescreve a primeira |
| `resumo_processo`, `resumo_operacional_empresas` | mesmo arquivo | processo/empresas → contagens fiscais/operacionais |
| `calcular_retencoes_esperadas`, `calcular_liquido_com_retencoes_salvas` | `retencoes_calculo_service.py:38,116` | valores/flags → Decimal arredondado, divergências e alertas |
| `carregar_regras_retencao`, `obter_regra_por_subitem` | `retencoes_regras_service.py:186-207` | abre `Planilha2`, normaliza cabeçalhos/flags e indexa 200 regras; cache é invalidado por caminho, tamanho e `mtime` |
| `normalizar_candidato_subitem` | `retencoes_regras_service.py:121-126` | impede que códigos municipais simples de 3 dígitos sejam confundidos com subitens LC116 |
| `resolver_subitem_lc116` | `retencoes_regras_service.py:210-228` | testa candidatos LC116 e prefere o primeiro que possui regra; conserva o primeiro candidato como fallback diagnosticável |
| `extrair_codigo_servico_xml` | `legacy_ingestion_service.py:312-363` | mesma prioridade de campos, mas ignora candidato sem regra quando outro campo traz subitem presente na planilha; não usa cTribMun simples de 3 dígitos |

## Parser, storage e DANFSe

| Símbolo | Arquivo | Efeito |
|---|---|---|
| `StorageService.put/get/delete/list` | `storage_service.py` | valida chave → backend local/R2; bytes e metadados |
| `build_xml_key`, `build_pdf_key`, `build_certificate_key` | `storage_naming_service.py` | CNPJ/ano/mês/chave → caminho canônico |
| `gerar_danfse` | `danfse_service.py`/router `danfse.py` | XML limitado → subprocesso PHP → PDF temporário/FileResponse |
| `parse_nfse_nacional` | `nfse_xml_parser.py` | XML nacional → modelo detalhado para campos fiscais |
| `consultar_cnpj`, cache helpers | `cnpj_*`/`integrations` | CNPJ → cache Receita/Invertexto com status e datas |

## Frontend

`src/lib/api.ts` contém o wrapper `request`, autenticação, timeout/AbortController, serialização e todos os métodos REST. Hooks `useAuth`, `useEmpresas`, `useCertificados`, `useConsultas`, `useProcessos`, `useNotas`, `useNotasDownload`, `useNotasTotals`, `useConferenciaNotas`, `useHealth` e `useLiveStatus` são os consumidores React Query. Pages/components apenas compõem esses hooks; ao mudar um endpoint leia sempre `api.ts` + hook + página/componente.
+
## Índice mecânico de símbolos do frontend

A árvore React/TypeScript foi igualmente varrida. Componentes, hooks e helpers abaixo são os pontos de entrada; tipos/interfaces sem comportamento ficam no mapa de arquivos e em `src/types/api.ts`.

```text
src\app\router.tsx:10:const Dashboard = lazy(() => pageLoaders.dashboard().then((m) => ({ default: m.Dashboard })));
src\app\router.tsx:11:const Conferencia = lazy(() => pageLoaders.conferencia().then((m) => ({ default: m.Conferencia })));
src\app\router.tsx:12:const Certificados = lazy(() => pageLoaders.certificados().then((m) => ({ default: m.Certificados })));
src\app\router.tsx:13:const NotasConsultadas = lazy(() => pageLoaders.notas().then((m) => ({ default: m.NotasConsultadas })));
src\app\router.tsx:14:const Fila = lazy(() => pageLoaders.fila().then((m) => ({ default: m.Fila })));
src\app\router.tsx:15:const Processos = lazy(() => pageLoaders.processos().then((m) => ({ default: m.Processos })));
src\app\router.tsx:16:const Configuracoes = lazy(() => pageLoaders.configuracoes().then((m) => ({ default: m.Configuracoes })));
src\app\router.tsx:17:const MotorAdn = lazy(() => pageLoaders.motorAdn().then((m) => ({ default: m.MotorAdn })));
src\app\router.tsx:18:const Admin = lazy(() => pageLoaders.admin().then((m) => ({ default: m.Admin })));
src\app\page-loaders.ts:7:export function prefetchRoute(path: string) {
src\components\processos\ProcessoDrawer.tsx:14:function Row({ label, value }: { label: string; value?: string | number | null }) {
src\components\processos\ProcessoDrawer.tsx:23:function TabButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
src\components\processos\ProcessoDrawer.tsx:35:export function ProcessoDrawer({ processo, onClose }: { processo: Processo | null; onClose: () => void }) {
src\components\processos\ProcessoDrawer.tsx:289:function Loading({ label }: { label: string }) {
src\components\processos\ProcessoDrawer.tsx:297:function Fallback({ text }: { text: string }) {
src\components\processos\ProcessoDrawer.tsx:301:function Field({ label, value, onChange }: { label: string; value?: string; onChange: (value: string) => void }) {
src\components\processos\ProcessoDrawer.tsx:310:function formatBytes(value?: number | null) {
src\components\ui\ConfirmDialog.tsx:5:export function ConfirmDialog({ open, title, description, confirmLabel = 'Confirmar', tone = 'danger', onConfirm, onClose }: { open: boolean; title: string; description: string; confirmLabel?: string; tone?: 'primary' | 'danger'; onConfirm: () => void; onClose: () => void }) {
src\components\ui\Card.tsx:4:export function Card({ children, className }: { children: ReactNode; className?: string }) {
src\components\ui\Card.tsx:8:export function MetricCard({ label, value, hint, children }: { label: string; value: ReactNode; hint?: string; children?: ReactNode }) {
src\components\ui\Button.tsx:13:export function Button({
src\components\ui\Badge.tsx:14:export function statusTone(status?: string | null): Tone {
src\components\ui\Badge.tsx:23:export function Badge({ value, tone, className }: { value?: string | null; tone?: Tone; className?: string }) {
src\components\ui\InfiniteScrollSentinel.tsx:4:export function InfiniteScrollSentinel({
src\components\ui\Toaster.tsx:16:const listeners = new Set<(toasts: ToastItem[]) => void>();
src\components\ui\Toaster.tsx:18:function emit() {
src\components\ui\Toaster.tsx:22:export function dismissToast(id: number) {
src\components\ui\Toaster.tsx:27:function push(tone: ToastTone, title: string, description?: string) {
src\components\ui\Toaster.tsx:48:export function Toaster() {
src\components\ui\FilterChips.tsx:8:export function FilterChips({ chips, onRemove }: { chips: FilterChip[]; onRemove: (key: string) => void }) {
src\components\ui\Skeleton.tsx:3:export function Skeleton({ className }: { className?: string }) {
src\components\ui\Skeleton.tsx:7:export function TableSkeleton({ rows = 8, title }: { rows?: number; title?: string }) {
src\components\ui\EmptyState.tsx:3:export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
src\components\ui\SavedViews.tsx:6:export function SavedViews<T>({ storageKey, value, onApply }: { storageKey: string; value: T; onApply: (value: T) => void }) {
src\components\ui\Drawer.tsx:17:export function useDrawerExpanded() {
src\components\ui\Drawer.tsx:21:export function Drawer({ open, title, onClose, children, expandable = false, actions }: DrawerProps) {
src\components\operator\OperatorNameModal.tsx:5:export function OperatorNameModal({
src\components\ui\ResizableDataTable.tsx:35:function alignClass(align: ColumnAlign = 'left') {
src\components\ui\ResizableDataTable.tsx:41:function safeStorageGet(storageKey?: string): Record<string, number> {
src\components\ui\ResizableDataTable.tsx:57:function safeStorageSet(storageKey: string | undefined, widths: Record<string, number>) {
src\components\ui\ResizableDataTable.tsx:66:function minWidthFor<T>(column: ResizableDataColumn<T>) {
src\components\ui\ResizableDataTable.tsx:70:function maxWidthFor<T>(column: ResizableDataColumn<T>) {
src\components\ui\ResizableDataTable.tsx:74:function buildInitialWidths<T>(columns: ResizableDataColumn<T>[], storageKey?: string) {
src\components\ui\ResizableDataTable.tsx:86:export function ResizableDataTable<T>({
src\components\ui\PageHeader.tsx:4:export function PageHeader({ eyebrow, title, description, actions, className }: { eyebrow?: string; title: string; description?: string; actions?: ReactNode; className?: string }) {
src\components\ui\PageHeader.tsx:17:export function SectionHeader({ title, description, actions, className }: { title: string; description?: string; actions?: ReactNode; className?: string }) {
src\pages\Processos.tsx:17:export function Processos() {
src\pages\NotasConsultadas.tsx:16:export function NotasConsultadas() {
src\components\auth\ProtectedRoute.tsx:6:export function ProtectedRoute() {
src\components\auth\ProtectedRoute.tsx:15:export function AdminRoute() {
src\pages\MotorAdn.tsx:15:function toggleId(ids: number[], id: number) {
src\pages\MotorAdn.tsx:19:function numericValue(value: string) {
src\pages\MotorAdn.tsx:25:export function MotorAdn() {
src\components\operator\OperatorGate.tsx:5:export function OperatorGate({ children }: { children: ReactNode }) {
src\pages\Login.tsx:8:export function Login() {
src\pages\Fila.tsx:12:export function Fila() {
src\components\conferencia\conferenciaUtils.ts:3:export function displayValue(value?: string | number | null) {
src\components\conferencia\conferenciaUtils.ts:8:export function notaNumero(nota: Nota) {
src\components\conferencia\conferenciaUtils.ts:12:export function notaValor(nota: Nota) {
src\components\conferencia\conferenciaUtils.ts:16:export function conferenciaLabel(value?: string | null) {
src\components\conferencia\conferenciaUtils.ts:26:export function tipoNotaLabel(value?: string | null) {
src\components\conferencia\conferenciaUtils.ts:36:export function badgeTone(value?: string | null): 'success' | 'warning' | 'danger' | 'info' | 'muted' {
src\pages\Dashboard.tsx:16:export function Dashboard() {
src\components\conferencia\ConferenciaFilters.tsx:25:function Field({ label, children }: { label: string; children: ReactNode }) {
src\components\conferencia\ConferenciaFilters.tsx:34:export function ConferenciaFilters({
src\components\conferencia\ConferenciaTable.tsx:20:function getSlaLabel(nota: Nota) {
src\components\conferencia\ConferenciaTable.tsx:25:function getSlaTone(nota: Nota) {
src\components\conferencia\ConferenciaTable.tsx:30:function CompactBadge({ value }: { value?: string | null }) {
src\components\conferencia\ConferenciaTable.tsx:34:function CellText({ children, className = '' }: { children: ReactNode; className?: string }) {
src\components\conferencia\ConferenciaTable.tsx:38:function isConferenciaOk(nota: Nota) {
src\components\conferencia\ConferenciaTable.tsx:42:function isConferenciaPendente(nota: Nota) {
src\components\conferencia\ConferenciaTable.tsx:46:function isConferenciaObservacao(nota: Nota) {
src\components\conferencia\ConferenciaTable.tsx:50:function createConferenciaColumns(): ConferenciaColumn[] {
src\components\conferencia\ConferenciaTable.tsx:104:export function ConferenciaTable({
src\components\conferencia\ConferenciaDrawer.tsx:9:export function ConferenciaDrawer({ nota, notas = [], onSelectNota, onClose }: { nota: Nota | null; notas?: Nota[]; onSelectNota?: (nota: Nota) => void; onClose: () => void }) {
src\pages\CriarConta.tsx:10:export function CriarConta() {
src\components\conferencia\ConferenciaMobileCard.tsx:7:function conferenciaIcon(status?: string | null) {
src\components\conferencia\ConferenciaMobileCard.tsx:14:function slaLabel(nota: Nota) {
src\components\conferencia\ConferenciaMobileCard.tsx:19:function slaTone(nota: Nota) {
src\components\conferencia\ConferenciaMobileCard.tsx:24:export function ConferenciaMobileCard({ nota, onOpen }: { nota: Nota; onOpen: (nota: Nota) => void }) {
src\pages\Configuracoes.tsx:47:export function Configuracoes() {
src\components\certificados\CertificadoUploadForm.tsx:7:function isValidCertFile(file?: File | null) {
src\components\certificados\CertificadoUploadForm.tsx:13:function resultMessage(autoIniciar: boolean, processoId?: number | null, automaticoAtivo?: boolean) {
src\components\certificados\CertificadoUploadForm.tsx:20:export function CertificadoUploadForm() {
src\pages\Conferencia.tsx:23:function SummaryCard({ label, value, icon: Icon, tone }: { label: string; value: number; icon: typeof Clock; tone: string }) {
src\pages\Conferencia.tsx:39:function notaSlaTone(nota: Nota) {
src\pages\Conferencia.tsx:44:function countBy(notas: Nota[], predicate: (nota: Nota) => boolean) {
src\pages\Conferencia.tsx:48:export function Conferencia({ tipoNotaFixo, direcaoNotaFixa, titulo = 'Conferência de Notas', descricao }: ConferenciaProps) {
src\components\certificados\CertificadoExpiryTicker.tsx:10:function expiryMessage(certificado: Certificado, now: Date) {
src\components\certificados\CertificadoExpiryTicker.tsx:27:export function CertificadoExpiryTicker() {
src\pages\Certificados.tsx:14:export function Certificados() {
src\components\layout\CommandPalette.tsx:18:export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
src\components\layout\Topbar.tsx:25:export function Topbar({ onMenuClick, showMenuButton = true, sidebarCollapsed = false, onSidebarToggle, onCommandClick }: { onMenuClick: () => void; showMenuButton?: boolean; sidebarCollapsed?: boolean; onSidebarToggle?: () => void; onCommandClick?: () => void }) {
src\pages\Admin.tsx:16:export function Admin() {
src\pages\Admin.tsx:79:function Metric({ color, icon, value, label, hint }: { color: string; icon: React.ReactNode; value: number | string; label: string; hint: string }) { return <article className={`adm-metric ${color}`}><div><h2>{value}</h2><p>{label}</p>{icon}</div><footer>{hint}</footer></article>; }
src\pages\Admin.tsx:80:function CardHeader({ title, icon, action }: { title: string; icon: React.ReactNode; action?: React.ReactNode }) { return <header className="adm-card-header"><h2>{icon}{title}</h2>{action}</header>; }
src\pages\Admin.tsx:81:function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) { return <label className="adm-search"><Search /><input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} /></label>; }
src\pages\Admin.tsx:83:function ArchivePanel() {
src\components\layout\AppLayout.tsx:15:function AppLayoutContent() {
src\components\layout\AppLayout.tsx:76:export function AppLayout() {
src\components\layout\Sidebar.tsx:27:export function Sidebar({ open, onClose, hidden = false, collapsed = false }: { open: boolean; onClose: () => void; hidden?: boolean; collapsed?: boolean }) {
src\components\layout\OnboardingTour.tsx:10:export function OnboardingTour() {
src\components\dashboard\QuickTasks.tsx:11:export function QuickTasks() {
src\components\layout\FocusModeButton.tsx:5:export function FocusModeButton({ className = '' }: { className?: string }) {
src\components\live\StartConsultasButton.tsx:5:export function StartConsultasButton({ automaticoAtivo, disabled }: { automaticoAtivo?: boolean; disabled?: boolean }) {
src\components\live\LiveStatusBar.tsx:6:function formatSeconds(seconds?: number | null) {
src\components\live\LiveStatusBar.tsx:14:export function LiveStatusBar() {
src\components\live\CycleSummary.tsx:6:export function CycleSummary() {
src\hooks\queryInvalidation.ts:24:async function invalidateLocalPortalData(queryClient: QueryClient) {
src\hooks\queryInvalidation.ts:30:function notifyOtherTabs() {
src\hooks\queryInvalidation.ts:44:export async function invalidatePortalData(queryClient: QueryClient, notifyTabs = true) {
src\hooks\queryInvalidation.ts:49:export function setupPortalDataSync(queryClient: QueryClient) {
src\hooks\useAuth.tsx:18:export function AuthProvider({ children }: { children: ReactNode }) {
src\hooks\useAuth.tsx:77:export function useAuth() {
src\hooks\useCertificados.ts:6:export function useCertificados(params?: { empresa_id?: string | number; ativo?: boolean }) {
src\hooks\useCertificados.ts:14:export function useUploadCertificado() {
src\hooks\useCertificados.ts:26:export function useAutocadastrarCertificado() {
src\hooks\useCertificados.ts:37:export function useTestarSenhaSalva() {
src\hooks\useCertificados.ts:43:export function useDesativarCertificado() {
src\hooks\useConferenciaNotas.ts:8:function cleanFilters(filters?: NotasFilters): NotasFilters {
src\hooks\useConferenciaNotas.ts:20:export function useConferenciaNotas(filters?: NotasFilters) {
src\hooks\useConferenciaNotas.ts:40:export function useConferenciaNotasInfinite(filters?: NotasFilters) {
src\hooks\useConferenciaNotas.ts:80:export function useSalvarConferenciaNota() {
src\hooks\useElementWidth.ts:3:export function useElementWidth<T extends HTMLElement>() {
src\lib\auth-storage.ts:3:export function getAccessToken() {
src\lib\auth-storage.ts:7:export function setAccessToken(token: string) {
src\lib\auth-storage.ts:11:export function clearAccessToken() {
src\lib\auth-storage.ts:15:export function authHeaders(): Record<string, string> {
src\lib\api.ts:71:function buildUrl(path: string, params?: Record<string, string | number | boolean | null | undefined>) {
src\lib\api.ts:85:export function friendlyHttpMessage(status: number, detail?: unknown) {
src\lib\api.ts:108:async function request<T>(path: string, options?: RequestInit & { params?: Record<string, unknown> }): Promise<T> {
src\lib\api.ts:157:function parseDownloadFilename(contentDisposition: string | null) {
src\lib\api.ts:166:async function requestBlob(
src\lib\api.ts:220:async function requestArquivoBlob(path: string, fallbackFilename = 'arquivo'): Promise<ArquivoDownloadResponse> {
src\lib\api.ts:262:function buildNotasDownloadFiltros(filters?: NotasFilters) {
src\lib\api.ts:279:function buildNotasDownloadParams(filters: NotasFilters | undefined, options: NotasDownloadLoteOptions) {
src\lib\api.ts:290:function chunkIds(ids: number[], chunkSize: number) {
src\lib\api.ts:298:function isDownloadLimitError(error: unknown) {
src\lib\api.ts:303:function buildPartFilename(filename: string, index: number, total: number) {
src\lib\api.ts:309:async function listarTodosNotaIds(filters?: NotasFilters) {
src\lib\api.ts:326:async function downloadNotasLotePorIds(notaIds: number[], options: NotasDownloadLoteOptions, filters?: NotasFilters) {
src\lib\api.ts:339:async function downloadNotasLoteComFallback(filters: NotasFilters | undefined, options: NotasDownloadLoteOptions) {
src\lib\api.ts:368:function buildNotasListParams(filters?: NotasFilters) {
src\lib\api.ts:416:function buildProcessoNotasParams(filters?: ProcessoNotasFilters) {
src\lib\api.ts:432:function buildRelatorioConferenciaPayload(filters?: RelatorioConferenciaFilters | NotasFilters) {
src\lib\api.ts:455:function normalizeDates<T extends { created_at?: string | null; updated_at?: string | null; criado_em?: string | null; atualizado_em?: string | null }>(item: T): T {
src\lib\api.ts:465:function normalizeEmpresa(empresa: Empresa): Empresa {
src\lib\api.ts:474:function normalizeCertificado(certificado: Certificado): Certificado {
src\lib\api.ts:478:function normalizeProcesso(processo: Processo): Processo {
src\lib\api.ts:483:function normalizeSla(value: Nota['sla'], slaStatus?: string | null) {
src\lib\api.ts:490:function normalizePrioridade(value?: string | boolean | null) {
src\lib\api.ts:495:function normalizeNota(nota: Nota): Nota {
src\lib\api.ts:544:function normalizeNotasResponse(response: Nota[] | ConferenciaNotasResponse): ConferenciaNotasResponse {
src\lib\api.ts:559:function extractItems<T>(response: T[] | { items?: T[]; data?: T[]; results?: T[] } | null | undefined): T[] {
src\lib\api.ts:567:function normalizeArquivo(arquivo: Arquivo): Arquivo {
src\lib\api.ts:578:function normalizeEmpresaResumo(item: EmpresaResumoOperacional): EmpresaResumoOperacional {
src\lib\api.ts:587:function normalizeConsultaStatus(status: ConsultaStatus): ConsultaStatus {
src\lib\api.test.ts:7:function jsonResponse(body: unknown, status = 200) {
src\hooks\useEmpresas.ts:4:export function useEmpresas(ativo?: boolean) {
src\lib\smartSearch.ts:18:function normalize(value: unknown) {
src\lib\smartSearch.ts:25:function compactDigits(value: string) {
src\lib\smartSearch.ts:29:function notaHaystack(nota: Nota) {
src\lib\smartSearch.ts:60:function fieldMatches(nota: Nota, fields: Array<keyof Nota>, term: string) {
src\lib\smartSearch.ts:71:export function notaMatchesSmartSearch(nota: Nota, busca?: string) {
src\lib\smartSearch.ts:105:export function filterNotasBySmartSearch(notas: Nota[], busca?: string) {
src\hooks\useFocusMode.tsx:14:export function FocusModeProvider({ children }: { children: ReactNode }) {
src\hooks\useFocusMode.tsx:41:export function useFocusMode() {
src\lib\operator.ts:15:function uuid() {
src\lib\operator.ts:24:function canUseStorage() {
src\lib\operator.ts:37:function readRaw(key: string) {
src\lib\operator.ts:47:function writeRaw(key: string, value: string) {
src\lib\operator.ts:58:function removeRaw(key: string) {
src\lib\operator.ts:67:function normalizeName(name: string) {
src\lib\operator.ts:71:function isValidOperator(value: unknown): value is LocalOperator {
src\lib\operator.ts:77:export function getStorageWarning() {
src\lib\operator.ts:81:export function getOrCreateDeviceId() {
src\lib\operator.ts:102:export function getOperator(): LocalOperator | null {
src\lib\operator.ts:124:export function saveOperator(name: string): LocalOperator {
src\lib\operator.ts:142:export function clearOperator() {
src\lib\operator.ts:147:export function operatorHeaders(operator = getOperator()): Record<string, string> {
src\hooks\useHealth.ts:4:export function useHealth() {
src\lib\notaFilters.ts:5:function normalize(value?: string | number | null) {
src\lib\notaFilters.ts:12:function parseCurrencyInput(value?: string | number | null) {
src\lib\notaFilters.ts:26:function notaValor(nota: Nota) {
src\lib\notaFilters.ts:30:function fieldIncludes(value: string | number | null | undefined, term?: string) {
src\lib\notaFilters.ts:36:function normalizeIncidenciaTerm(value?: string | number | null) {
src\lib\notaFilters.ts:44:function digitsInclude(value: string | number | null | undefined, term?: string) {
src\lib\notaFilters.ts:50:function matchesSimpleStatus(nota: Nota, value?: string) {
src\lib\notaFilters.ts:69:export function notaMatchesPortalFilters(nota: Nota, filters?: NotasFilters) {
src\lib\notaFilters.ts:87:export function filterNotasByPortalFilters(notas: Nota[], filters?: NotasFilters) {
src\lib\notaFilters.ts:91:export function notaUniqueKey(nota: Nota) {
src\lib\notaFilters.ts:97:export function dedupeNotas(notas: Nota[]) {
src\lib\notaFilters.ts:107:export function cleanClientOnlyFiltersForApi(filters?: NotasFilters): NotasFilters {
src\hooks\useLiveStatus.ts:8:function nextCycleFromLastFinished(finishedAt?: string | null) {
src\hooks\useLiveStatus.ts:17:export function useLiveStatus() {
src\hooks\useNotas.ts:7:export function noteTimestamp(nota: Nota, sort: NotasFilters['sort']) {
src\hooks\useNotas.ts:15:export function sortNotas(notas: Nota[], sort: NotasFilters['sort'] = 'recentes') {
src\hooks\useNotas.ts:19:export function useNotas(filters?: NotasFilters, refetchInterval = 5_000) {
src\hooks\useNotas.ts:39:export function useNotasInfinite(filters?: NotasFilters, refetchInterval = 5_000) {
src\lib\format.ts:4:export function onlyDigits(value: string) {
src\lib\format.ts:8:export function formatCnpj(value?: string | null) {
src\lib\format.ts:14:export function formatServiceCode(value?: string | number | null) {
src\lib\format.ts:22:export function formatCurrency(value?: string | number | null) {
src\lib\format.ts:32:export function formatDate(value?: string | null) {
src\lib\format.ts:39:export function formatDateTime(value?: string | null) {
src\lib\format.ts:46:export function timeAgo(value?: string | null) {
src\lib\format.ts:53:export function classNames(...values: Array<string | false | null | undefined>) {
src\lib\format.ts:57:export function statusLabel(status?: string | null) {
src\components\notas\NotasTable.tsx:19:function compactTimeAgo(value?: string | null) {
src\components\notas\NotasTable.tsx:37:function slaLabel(nota: Nota) {
src\components\notas\NotasTable.tsx:42:function operationalBadgeTone(value?: string | null, dangerWhen?: boolean | null) {
src\components\notas\NotasTable.tsx:174:export function NotasTable({
src\hooks\useNotasDownload.ts:6:function saveBlob(blob: Blob, filename: string) {
src\hooks\useNotasDownload.ts:17:export function useNotasDownloadLote(filters?: NotasFilters) {
src\hooks\useNotasDownload.ts:29:export function useRelatorioConferenciaDownload(filters?: RelatorioConferenciaFilters | NotasFilters) {
src\components\notas\NotaDrawer.tsx:8:export function NotaDrawer({ nota, notas = [], onSelectNota, onClose }: { nota: Nota | null; notas?: Nota[]; onSelectNota?: (nota: Nota) => void; onClose: () => void }) {
src\components\notas\NotasFilterPanel.tsx:19:function normalizeNotasFilters(filters: NotasFilters): NotasFilters {
src\components\notas\NotasFilterPanel.tsx:23:export function NotasFilterPanel({ value, onChange }: { value: NotasFilters; onChange: (filters: NotasFilters) => void }) {
src\components\notas\NotaDetailSections.tsx:14:function displayValue(value?: string | number | null) {
src\components\notas\NotaDetailSections.tsx:19:function slaLabel(nota: Nota) {
src\components\notas\NotaDetailSections.tsx:24:function prioridadeManualValue(value?: string | boolean | null) {
src\components\notas\NotaDetailSections.tsx:29:function Row({ label, value }: { label: string; value?: string | number | null }) {
src\components\notas\NotaDetailSections.tsx:38:function fileKind(arquivo: Arquivo): 'xml' | 'pdf' | 'outro' {
src\components\notas\NotaDetailSections.tsx:45:function formatBytes(value?: number | null) {
src\components\notas\NotaDetailSections.tsx:52:function sanitizeFilename(value: string) {
src\components\notas\NotaDetailSections.tsx:56:function isAccessKeyFilename(value?: string | null) {
src\components\notas\NotaDetailSections.tsx:60:function extensionForArquivo(kind: 'xml' | 'pdf' | 'outro', arquivo?: Arquivo) {
src\components\notas\NotaDetailSections.tsx:69:function arquivoDisplayName(kind: 'xml' | 'pdf' | 'outro', arquivo: Arquivo | undefined, nota: Nota) {
src\components\notas\NotaDetailSections.tsx:90:function saveBlob(blob: Blob, filename: string) {
src\components\notas\NotaDetailSections.tsx:101:function DocumentCard({ kind, arquivo, nota }: { kind: 'xml' | 'pdf' | 'outro'; arquivo?: Arquivo; nota: Nota }) {
src\components\notas\NotaDetailSections.tsx:205:function tributoValue(...values: unknown[]): string | number {
src\components\notas\NotaDetailSections.tsx:210:function normalizeTributo(item: NotaTributoComparativo) {
src\components\notas\NotaDetailSections.tsx:221:export function NotaDetailSections({ nota }: { nota: Nota }) {
src\components\notas\NotaMobileCard.tsx:5:export function NotaMobileCard({ nota, onOpen }: { nota: Nota; onOpen: (nota: Nota) => void }) {
src\components\notas\NotasDownloadActions.tsx:7:export function NotasDownloadActions({ filters }: { filters: NotasFilters }) {
src\hooks\useNotasTotals.ts:6:function cleanCountFilters(filters?: NotasFilters): NotasFilters {
src\hooks\useNotasTotals.ts:11:function slaTone(nota: Nota) {
src\hooks\useNotasTotals.ts:16:function buildSummary(notas: Nota[]) {
src\hooks\useNotasTotals.ts:30:async function fetchAllNotasForSummary(filters?: NotasFilters, includeItems = true) {
src\hooks\useNotasTotals.ts:65:export function useNotasTotals(filters?: NotasFilters, includeItems = false) {
src\hooks\usePersistentState.ts:3:export function usePersistentState<T>(key: string, initialValue: T) {
src\hooks\usePersistentState.ts:11:export function useRestoreScroll(key: string) {
src\hooks\useTheme.ts:5:function currentTheme(): Theme {
src\hooks\useTheme.ts:9:export function useTheme() {
src\hooks\useProcessos.ts:7:export function useProcessos(params?: { empresa_id?: string | number; status?: string; limit?: number; offset?: number }) {
src\hooks\useProcessos.ts:16:export function useCancelarProcesso() {
src\hooks\useProcessos.ts:27:export function useIniciarConsultas() {
src\hooks\useProcessos.ts:39:export function useDesativarConsultas() {
src\hooks\useOperator.tsx:20:export function OperatorProvider({ children }: { children: ReactNode }) {
src\hooks\useOperator.tsx:60:export function useOperatorContext() {
```

+
## Índice mecânico completo de símbolos Python

A segunda passagem registrou cada declaração encontrada. A coluna inicial é `arquivo:linha`; a semântica, entradas/saídas e riscos dos símbolos com efeitos estão resumidos nas seções acima. Funções privadas puras de parsing têm contrato autoexplicado pelo nome e pelos chamadores; antes de alterar uma delas, leia o bloco completo e seus testes.

```text
backend\app\main.py:48:def _worker_groups() -> list[str]:
backend\app\main.py:55:def _build_api_workers(groups: list[str], workers_per_group: int) -> list[tuple[str, str]]:
backend\app\main.py:64:def _recover_stale_api_jobs(active_worker_ids: list[str]) -> int:
backend\app\main.py:98:async def _run_api_worker(slot: int, worker_id: str, grupo: str) -> None:
backend\app\main.py:120:async def _run_consultas_scheduler() -> None:
backend\app\main.py:133:def _enqueue_consultas_automaticas() -> dict:
backend\app\main.py:146:async def _revalidar_status_pdfs_salvos() -> None:
backend\app\main.py:161:async def _recalcular_valores_liquidos_salvos() -> None:
backend\app\main.py:170:async def lifespan(app: FastAPI):
backend\app\main.py:217:def _documentation_options(production: bool) -> dict[str, str | None]:
backend\app\main.py:232:async def security_headers(request, call_next):
backend\app\main.py:244:def _parse_cors_origins() -> list[str]:
backend\app\db\session.py:11:def _connect_args() -> dict:
backend\app\db\session.py:17:def _ensure_sqlite_parent() -> None:
backend\app\db\session.py:63:def get_db():
backend\app\db\session.py:71:def init_db() -> None:
backend\app\db\session.py:83:def migrate_db() -> None:
backend\app\db\session.py:92:def _ensure_runtime_columns() -> None:
backend\app\core\security.py:18:class TokenError(ValueError):
backend\app\core\security.py:22:def hash_password(password: str) -> str:
backend\app\core\security.py:28:def verify_password(password: str, encoded_hash: str) -> bool:
backend\app\core\security.py:43:def create_access_token(usuario_id: int, empresa_id: int) -> str:
backend\app\core\security.py:57:def decode_access_token(token: str) -> dict[str, Any]:
backend\app\db\models.py:23:class TimestampMixin:
backend\app\db\models.py:32:class Grupo(TimestampMixin, Base):
backend\app\db\models.py:41:class Empresa(TimestampMixin, Base):
backend\app\db\models.py:62:class Certificado(TimestampMixin, Base):
backend\app\db\models.py:120:class Processo(TimestampMixin, Base):
backend\app\db\models.py:146:class Job(TimestampMixin, Base):
backend\app\db\models.py:167:class MonitoramentoConfig(TimestampMixin, Base):
backend\app\db\models.py:179:class NsuControle(TimestampMixin, Base):
backend\app\db\models.py:194:class Nota(TimestampMixin, Base):
backend\app\db\models.py:301:class Evento(Base):
backend\app\db\models.py:320:class Arquivo(TimestampMixin, Base):
backend\app\db\models.py:340:class LogProcesso(Base):
backend\app\db\models.py:355:class LockProcessamento(TimestampMixin, Base):
backend\app\db\models.py:372:class CnpjCache(Base):
backend\app\db\models.py:392:class Secret(TimestampMixin, Base):
backend\app\db\models.py:401:class Usuario(TimestampMixin, Base):
backend\app\db\models.py:417:class AcessoUsuario(Base):
backend\app\db\base.py:4:class Base(DeclarativeBase):
backend\app\worker\worker.py:15:def build_parser() -> argparse.ArgumentParser:
backend\app\worker\worker.py:24:def processar_proximo_job(worker_id: str, grupo_worker: str | None = None) -> dict:
backend\app\worker\worker.py:56:def main() -> None:
backend\app\worker\scheduler.py:12:def enqueue_consultas() -> dict[str, int]:
backend\app\worker\scheduler.py:25:def build_parser() -> argparse.ArgumentParser:
backend\app\worker\scheduler.py:32:def main() -> None:
backend\app\worker\jobs.py:15:def _job_processavel(job: Job, worker_id: str) -> bool:
backend\app\worker\jobs.py:19:def _foi_cancelado(db: Session, processo, job: Job) -> bool:
backend\app\worker\jobs.py:25:def _devolver_job_para_fila(db: Session, job: Job) -> None:
backend\app\worker\jobs.py:29:def _registrar_job_reservado(db: Session, processo, job: Job, worker_id: str) -> None:
backend\app\worker\jobs.py:46:def processar_job_simulado(db: Session, job: Job, worker_id: str) -> dict:
backend\app\worker\jobs.py:141:def processar_job_consulta_nfse_real(db: Session, job: Job, worker_id: str) -> dict:
backend\app\worker\jobs.py:233:def processar_job(db: Session, job: Job, worker_id: str) -> dict:
backend\app\core\rate_limit.py:8:class RateLimiter:
backend\app\api\routers\storage.py:17:def storage_health():
backend\app\api\routers\storage.py:28:def storage_test_write(usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\storage.py:35:def storage_test_read(usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\storage.py:51:def storage_list(prefix: str = "", db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\relatorios.py:18:class RelatorioConferenciaRequest(BaseModel):
backend\app\api\routers\relatorios.py:30:def exportar_conferencia(payload: RelatorioConferenciaRequest, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\core\observability.py:14:class JsonFormatter(logging.Formatter):
backend\app\core\observability.py:31:class Metrics:
backend\app\core\observability.py:57:def configure_logging() -> None:
backend\app\core\observability.py:64:def alert_failure(event: str, error: Exception | str, **context: Any) -> None:
backend\app\api\routers\processos.py:23:def _handle_error(exc: ProcessoServiceError) -> None:
backend\app\api\routers\processos.py:29:def _handle_portal_error(exc: PortalSupportError) -> None:
backend\app\api\routers\processos.py:36:def create_processo(payload: ProcessoCreate, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\processos.py:44:def list_processos(
backend\app\api\routers\processos.py:70:def get_processo(processo_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\processos.py:78:def list_arquivos_processo(
backend\app\api\routers\processos.py:93:def list_notas_processo(
backend\app\api\routers\processos.py:129:def get_summary_processo(processo_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\processos.py:138:def cancelar_processo(processo_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\processos.py:152:def list_jobs_processo(processo_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\core\config.py:6:class Settings(BaseSettings):
backend\app\api\routers\nsu.py:16:def _iso(value: datetime | None) -> str | None:
backend\app\api\routers\nsu.py:20:def _nsu_payload(
backend\app\api\routers\nsu.py:62:def get_empresa_nsu(
backend\app\api\routers\nsu.py:73:def get_nsu_status(
backend\app\scripts\corrigir_integridade_certificados.py:22:def executar(confirmar: bool = False) -> dict:
backend\app\scripts\corrigir_integridade_certificados.py:70:def main() -> None:
backend\app\api\routers\notas.py:34:def _handle_error(exc: NotaServiceError) -> None:
backend\app\api\routers\notas.py:40:def _zip_response(result: notas_download_service.DownloadLoteResult) -> FileResponse:
backend\app\api\routers\notas.py:54:def _handle_download_error(exc: NotasDownloadLoteError) -> None:
backend\app\api\routers\notas.py:61:def list_notas(
backend\app\api\routers\notas.py:145:def list_todas_notas(
backend\app\api\routers\notas.py:235:def _list_notas_operacionais(
backend\app\api\routers\notas.py:288:def list_notas_emitidas(
backend\app\api\routers\notas.py:344:def list_notas_recebidas(
backend\app\api\routers\notas.py:400:def download_lote_notas(
backend\app\api\routers\notas.py:415:def download_lote_notas_get(
backend\app\api\routers\notas.py:477:def get_notas_resumo(
backend\app\api\routers\notas.py:507:def get_nota_por_chave(
backend\app\api\routers\notas.py:524:def get_nota(nota_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\notas.py:533:def list_eventos_nota(nota_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\notas.py:567:def get_tributos_comparativo(nota_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\notas.py:576:def patch_conferencia_nota(
backend\app\api\routers\notas.py:608:def list_arquivos_nota(
backend\app\scripts\baixar_pdfs_oficiais_periodo.py:22:def baixar(*, certificado_id: int, inicio: date, fim: date, pausa: float, executar: bool = False) -> dict:
backend\app\scripts\baixar_pdfs_oficiais_periodo.py:146:def main() -> None:
backend\app\api\routers\nfse_compat.py:20:def _handle_error(exc: NotaServiceError) -> None:
backend\app\api\routers\nfse_compat.py:26:def _as_int(value: object, default: int, minimum: int, maximum: int) -> int:
backend\app\api\routers\nfse_compat.py:34:def _nota_compat_dict(nota) -> dict:
backend\app\api\routers\nfse_compat.py:99:def list_nfse_compat(
backend\app\api\routers\nfse_compat.py:159:def get_nfse_compat(nota_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\nfse_compat.py:168:async def update_nfse_compat(nota_id: int, request: Request, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\nfse_compat.py:203:def get_nfse_documentos_compat(
backend\app\api\routers\logs.py:14:class LogProcessoRead(BaseModel):
backend\app\api\routers\logs.py:40:def list_logs(
backend\app\api\routers\logs.py:63:def list_logs_processo(
backend\app\api\routers\health.py:11:async def health_check():
backend\app\api\routers\health.py:20:async def metrics_endpoint():
backend\app\scripts\auditar_integridade_certificados.py:15:def executar() -> dict:
backend\app\scripts\auditar_integridade_certificados.py:126:def main() -> None:
backend\app\api\routers\execucoes.py:15:def _iso(value: datetime | None) -> str | None:
backend\app\api\routers\execucoes.py:19:def _normalizar_status(status: str | None) -> str:
backend\app\api\routers\execucoes.py:34:def _execucao_item(processo: Processo, job: Job | None = None) -> dict:
backend\app\api\routers\execucoes.py:65:def list_execucoes(
backend\app\api\routers\eventos.py:17:def list_eventos(
backend\app\scripts\arquivar_notas_antigas.py:11:def main() -> None:
backend\app\api\routers\empresas.py:19:def _handle_error(exc: EmpresaServiceError) -> None:
backend\app\api\routers\empresas.py:26:def create_empresa(payload: EmpresaCreate, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\empresas.py:34:def list_empresas(
backend\app\api\routers\empresas.py:43:def resumo_operacional_empresas(
backend\app\api\routers\empresas.py:66:def get_empresa(empresa_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\empresas.py:75:def update_empresa(empresa_id: int, payload: EmpresaUpdate, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\empresas.py:84:def delete_empresa(empresa_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\scripts\aplicar_seguranca_rls.py:39:def _identificador(nome: str) -> str:
backend\app\scripts\aplicar_seguranca_rls.py:45:def main() -> None:
backend\app\api\routers\db_health.py:11:def db_health():
backend\app\api\routers\danfse.py:16:async def gerar_danfse(
backend\app\api\routers\consultas.py:20:def get_consultas_status(
backend\app\api\routers\consultas.py:29:def iniciar_consultas(
backend\app\api\routers\consultas.py:39:def desativar_consultas(
backend\app\api\routers\cnpj.py:16:def status_base_cnpj(usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\cnpj.py:21:def consultar_cnpj(
backend\app\api\routers\certificados.py:32:async def _ler_certificado_limitado(arquivo: UploadFile) -> bytes:
backend\app\api\routers\certificados.py:43:def _limitar_tentativas_senha(certificado_id: int, request: Request) -> None:
backend\app\api\routers\certificados.py:52:def _handle_error(exc: CertificadoServiceError) -> None:
backend\app\api\routers\certificados.py:58:def _garantir_certificado_do_grupo(db: Session, certificado_id: int, usuario: Usuario) -> Certificado:
backend\app\api\routers\certificados.py:65:def _form_bool(value: object, default: bool = False) -> bool:
backend\app\api\routers\certificados.py:71:def _form_int(value: object) -> int | None:
backend\app\api\routers\certificados.py:78:def _validar_nsu_inicio(value: int | None) -> int | None:
backend\app\api\routers\certificados.py:84:def _first_form_value(form, *names: str) -> str | None:
backend\app\api\routers\certificados.py:92:def _first_upload_file(form, *names: str) -> UploadFile | None:
backend\app\api\routers\certificados.py:103:def _resolve_certificado_ref(db: Session, certificado_ref: str) -> Certificado:
backend\app\api\routers\certificados.py:121:async def create_certificado_compat(
backend\app\api\routers\certificados.py:196:async def upload_certificado(
backend\app\api\routers\certificados.py:235:async def autocadastrar_certificado(
backend\app\api\routers\certificados.py:279:async def create_certificado_empresa(
backend\app\api\routers\certificados.py:307:def list_certificados_empresa(
backend\app\api\routers\certificados.py:317:def list_certificados(
backend\app\api\routers\certificados.py:327:async def update_certificado_compat(
backend\app\api\routers\certificados.py:367:def get_certificado(certificado_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\certificados.py:379:def testar_certificado(
backend\app\api\routers\certificados.py:394:async def update_certificado(
backend\app\api\routers\certificados.py:422:def salvar_senha_certificado(
backend\app\api\routers\certificados.py:443:def status_senha_certificado(certificado_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\certificados.py:452:def remover_senha_certificado(certificado_id: int, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\certificados.py:465:def testar_senha_salva(
backend\app\api\routers\certificados.py:479:def delete_certificado(certificado_ref: str, db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\auth.py:24:def login_local(request: Request, db: Session = Depends(get_db)):
backend\app\api\routers\auth.py:47:def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
backend\app\api\routers\auth.py:76:def me(usuario: Usuario = Depends(get_current_usuario)):
backend\app\api\routers\auth.py:81:def listar_grupos_admin(db: Session = Depends(get_db), _admin: Usuario = Depends(require_admin)):
backend\app\api\routers\auth.py:86:def criar_usuario(payload: UsuarioCreate, db: Session = Depends(get_db)):
backend\app\api\routers\arquivos.py:16:def _download_status(message: str) -> int:
backend\app\api\routers\arquivos.py:24:def _arquivo_response(prepared: dict, disposition: str) -> Response:
backend\app\api\routers\arquivos.py:38:def download_arquivo(
backend\app\api\routers\arquivos.py:58:def visualizar_arquivo(
backend\app\api\routers\admin.py:22:class UsuarioAdminUpdate(BaseModel):
backend\app\api\routers\admin.py:30:class RedefinirSenha(BaseModel):
backend\app\api\routers\admin.py:34:class GrupoCreate(BaseModel):
backend\app\api\routers\admin.py:39:class GrupoUpdate(BaseModel):
backend\app\api\routers\admin.py:44:class ArquivamentoExecutar(BaseModel):
backend\app\api\routers\admin.py:52:def _executar_arquivamento_background(ano: int) -> None:
backend\app\api\routers\admin.py:64:def _slug_grupo(value: str) -> str:
backend\app\api\routers\admin.py:69:def _usuario_dict(usuario: Usuario) -> dict:
backend\app\api\routers\admin.py:83:def overview(db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:107:def acessos(dias: int = 14, db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:124:def usuarios(db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:129:def atualizar_usuario(usuario_id: int, payload: UsuarioAdminUpdate, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:157:def excluir_usuario(usuario_id: int, admin: Usuario = Depends(require_admin), db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:170:def listar_grupos(db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:181:def criar_grupo(payload: GrupoCreate, db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:195:def editar_grupo(grupo_id: int, payload: GrupoUpdate, db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:208:def excluir_grupo(grupo_id: int, db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:223:def redefinir_senha(usuario_id: int, payload: RedefinirSenha, db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:233:def erros(limit: int = 50, db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:263:def status_arquivamento(ano: int = 2026, db: Session = Depends(get_db)):
backend\app\api\routers\admin.py:293:def executar_arquivamento(payload: ArquivamentoExecutar, background_tasks: BackgroundTasks):
backend\app\api\deps.py:19:def get_storage():
backend\app\api\deps.py:23:def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
backend\app\api\deps.py:41:def get_current_usuario(
backend\app\api\deps.py:58:def require_admin(usuario: Usuario = Depends(get_current_usuario)) -> Usuario:
backend\app\api\deps.py:64:def require_operator(usuario: Usuario = Depends(get_current_usuario)) -> Usuario:
backend\app\api\deps.py:71:def require_empresa_grupo(db: Session, empresa_id: int, usuario: Usuario) -> Empresa:
backend\app\api\deps.py:78:def require_nota_grupo(db: Session, nota_id: int, usuario: Usuario) -> Nota:
backend\app\api\deps.py:85:def require_processo_grupo(db: Session, processo_id: int, usuario: Usuario) -> Processo:
backend\app\api\deps.py:92:def require_arquivo_grupo(db: Session, arquivo_id: int, usuario: Usuario) -> Arquivo:
backend\app\api\deps.py:99:def require_certificado_grupo(db: Session, certificado_id: int, usuario: Usuario) -> Certificado:
backend\app\schemas\consultas.py:9:class ConsultaIniciarRequest(BaseModel):
backend\app\schemas\consultas.py:30:class ConsultaWorkerStatus(BaseModel):
backend\app\schemas\consultas.py:36:class ConsultaTotaisStatus(BaseModel):
backend\app\schemas\consultas.py:44:class ConsultaStatusResponse(BaseModel):
backend\app\schemas\consultas.py:54:class ConsultaDesativarRequest(BaseModel):
backend\app\scripts\validar_migracao_postgres.py:39:class ValidationError(RuntimeError):
backend\app\scripts\validar_migracao_postgres.py:43:def _compare_samples(sqlite_engine, postgres_engine, table_name: str, fields: list[str] | None = None) -> list[str]:
backend\app\scripts\validar_migracao_postgres.py:62:def validar(sqlite_path: str | Path, postgres_url: str) -> dict[str, Any]:
backend\app\scripts\validar_migracao_postgres.py:107:def build_parser() -> argparse.ArgumentParser:
backend\app\scripts\validar_migracao_postgres.py:114:def main() -> None:
backend\app\scripts\testar_r2.py:9:def main() -> int:
backend\app\services\valor_liquido_backfill_service.py:10:def recalcular_notas_salvas(batch_size: int = 500) -> dict[str, int]:
backend\app\schemas\certificados.py:12:class CertificadoRead(BaseModel):
backend\app\schemas\certificados.py:38:class CertificadoTestRequest(BaseModel):
backend\app\schemas\certificados.py:42:class CertificadoTestResult(BaseModel):
backend\app\schemas\certificados.py:52:class CertificadoAutocadastroResponse(BaseModel):
backend\app\scripts\status_reprocessamento_certificados.py:13:def executar(inicio: int, fim: int) -> dict:
backend\app\scripts\status_reprocessamento_certificados.py:50:def main() -> None:
backend\app\schemas\auth.py:10:class LoginRequest(BaseModel):
backend\app\schemas\auth.py:23:class UsuarioRead(BaseModel):
backend\app\schemas\auth.py:36:class LoginResponse(BaseModel):
backend\app\services\storage_service.py:10:class StorageKeyError(ValueError):
backend\app\services\storage_service.py:14:class StorageService:
backend\app\services\storage_service.py:48:class LocalFilesystemStorage(StorageService):
backend\app\services\storage_service.py:115:class R2StorageService(StorageService):
backend\app\services\storage_service.py:244:def normalize_storage_key(key: str) -> str:
backend\app\services\storage_service.py:266:def normalize_storage_prefix(prefix: str = "") -> str:
backend\app\services\storage_service.py:273:def _is_not_found_error(exc: Exception) -> bool:
backend\app\services\storage_service.py:282:def _clean_segment(value: str, field: str) -> str:
backend\app\services\storage_service.py:289:def _date_key(kind: str, cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
backend\app\services\storage_service.py:301:def build_xml_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
backend\app\services\storage_service.py:305:def build_pdf_oficial_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
backend\app\services\storage_service.py:309:def build_pdf_espelho_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
backend\app\services\storage_service.py:313:def build_export_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
backend\app\services\storage_service.py:317:def build_raw_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
backend\app\services\storage_service.py:321:def build_json_key(cnpj_empresa: str, ano: str, mes: str, filename: str) -> str:
backend\app\services\storage_service.py:325:def build_log_key(cnpj_empresa: str, processo_id: str) -> str:
backend\app\services\storage_service.py:335:def build_certificado_key(cnpj_empresa: str, certificado_id: str, filename: str) -> str:
backend\app\services\storage_service.py:346:def get_storage_service() -> StorageService:
backend\app\scripts\sincronizar_cnpjs_portal.py:20:def _digits(value: str | None) -> str:
backend\app\scripts\sincronizar_cnpjs_portal.py:24:def _chunks(values: Sequence[str], size: int) -> Iterator[list[str]]:
backend\app\scripts\sincronizar_cnpjs_portal.py:29:def coletar_cnpjs_online(connection) -> list[str]:
backend\app\scripts\sincronizar_cnpjs_portal.py:40:def consultar_base_local(database_path: Path, cnpjs: Sequence[str]) -> tuple[list[dict], list[str]]:
backend\app\scripts\sincronizar_cnpjs_portal.py:75:def _status_simples(item: dict) -> str:
backend\app\scripts\sincronizar_cnpjs_portal.py:79:def montar_cache(item: dict, competencia: str, cache_days: int) -> dict:
backend\app\scripts\sincronizar_cnpjs_portal.py:104:def sincronizar(database_url: str, local_db: Path, *, dry_run: bool, batch_size: int, cache_days: int) -> dict:
backend\app\scripts\sincronizar_cnpjs_portal.py:161:def main() -> int:
backend\app\schemas\usuarios.py:8:class UsuarioCreate(BaseModel):
backend\app\services\storage_naming_service.py:11:def _clean_name(value: str | None, fallback: str, max_length: int) -> str:
backend\app\services\storage_naming_service.py:24:def safe_folder_name(value: str | None, fallback: str = "sem_nome") -> str:
backend\app\services\storage_naming_service.py:28:def safe_file_name(value: str | None, fallback: str = "arquivo") -> str:
backend\app\services\storage_naming_service.py:32:def build_zip_empresa_folder(empresa_nome: str | None, empresa_id: int | None) -> str:
backend\app\services\storage_naming_service.py:37:def _chave_curta(chave: str | None) -> str:
backend\app\services\storage_naming_service.py:42:def build_nota_base_filename(nota: Any) -> str:
backend\app\schemas\arquivos.py:9:def _canonical_tipo(value: str | None) -> str:
backend\app\schemas\arquivos.py:20:class ArquivoRead(BaseModel):
backend\app\schemas\arquivos.py:47:class ArquivoDownloadInfo(BaseModel):
backend\app\scripts\revalidar_status_pdfs.py:22:class Relatorio:
backend\app\scripts\revalidar_status_pdfs.py:33:def executar(empresa_id: int | None, dry_run: bool, batch_size: int = 200) -> Relatorio:
backend\app\scripts\revalidar_status_pdfs.py:86:def main(argv: list[str] | None = None) -> int:
backend\app\schemas\secrets.py:6:class SecretSetRequest(BaseModel):
backend\app\schemas\secrets.py:11:class SecretStatusResponse(BaseModel):
backend\app\scripts\restaurar_monitor_global_202608.py:14:def main() -> None:
backend\app\services\secrets_service.py:10:class SecretsServiceError(ValueError):
backend\app\services\secrets_service.py:17:def build_certificado_senha_ref(certificado_id: int) -> str:
backend\app\services\secrets_service.py:21:def _get_fernet() -> Fernet:
backend\app\services\secrets_service.py:30:def encrypt_secret(value: str) -> str:
backend\app\services\secrets_service.py:34:def decrypt_secret(encrypted_value: str) -> str:
backend\app\services\secrets_service.py:41:def save_secret(db: Session, ref: str, tipo: str, value: str):
backend\app\services\secrets_service.py:46:def get_secret_value(db: Session, ref: str) -> str:
backend\app\services\secrets_service.py:53:def delete_secret(db: Session, ref: str) -> bool:
backend\app\schemas\processos.py:13:class ProcessoCreate(BaseModel):
backend\app\schemas\processos.py:31:class ProcessoRead(BaseModel):
backend\app\schemas\processos.py:52:class ProcessoCancelResponse(BaseModel):
backend\app\scripts\regenerar_espelhos_competencia.py:21:class ItemResultado:
backend\app\scripts\regenerar_espelhos_competencia.py:34:class Relatorio:
backend\app\scripts\regenerar_espelhos_competencia.py:47:def _sha256(data: bytes) -> str:
backend\app\scripts\regenerar_espelhos_competencia.py:51:def executar(competencia: str, certificado_nome: str, dry_run: bool = True) -> Relatorio:
backend\app\scripts\regenerar_espelhos_competencia.py:143:def main(argv: list[str] | None = None) -> int:
backend\app\services\retencoes_regras_service.py:33:def _sem_acentos(value: str) -> str:
backend\app\services\retencoes_regras_service.py:38:def normalizar_flag_regra(value: str | None) -> str:
backend\app\services\retencoes_regras_service.py:51:def normalizar_subitem_lc116(value: str | None) -> str | None:
backend\app\services\retencoes_regras_service.py:71:def _decimal_or_none(value: Any) -> Decimal | None:
backend\app\services\retencoes_regras_service.py:80:def _regra_from_row(row: dict[str, Any]) -> dict[str, Any] | None:
backend\app\services\retencoes_regras_service.py:101:def carregar_regras_retencao() -> dict[str, dict[str, Any]]:
backend\app\services\retencoes_regras_service.py:116:def obter_regra_por_subitem(subitem: str | None) -> dict[str, Any] | None:
backend\app\services\retencoes_regras_service.py:131:def resolver_subitem_lc116(dados_xml: dict[str, Any]) -> str | None:
backend\app\schemas\notas.py:10:class NotaListItem(BaseModel):
backend\app\schemas\notas.py:160:class NotaDetail(NotaListItem):
backend\app\schemas\notas.py:164:class NotasTodasResponse(BaseModel):
backend\app\schemas\notas.py:169:class NotaConferenciaUpdate(BaseModel):
backend\app\schemas\notas.py:233:class NotasDownloadFiltros(BaseModel):
backend\app\schemas\notas.py:288:class NotasDownloadLoteRequest(BaseModel):
backend\app\schemas\notas.py:309:class NotaArquivoResumo(BaseModel):
backend\app\scripts\regenerar_carimbos_pdfs.py:39:class Relatorio:
backend\app\scripts\regenerar_carimbos_pdfs.py:50:def _gerar_pdf(xml_bytes: bytes, status: str, nota_id: int) -> bytes:
backend\app\scripts\regenerar_carimbos_pdfs.py:61:def executar(empresa_id: int | None = None, dry_run: bool = True, batch_size: int = 100) -> Relatorio:
backend\app\scripts\regenerar_carimbos_pdfs.py:117:def main(argv: list[str] | None = None) -> int:
backend\app\schemas\jobs.py:8:class JobRead(BaseModel):
backend\app\services\retencoes_calculo_service.py:13:def parse_decimal_xml(value: Any) -> Decimal | None:
backend\app\services\retencoes_calculo_service.py:32:def money(value: Decimal | None) -> Decimal | None:
backend\app\services\retencoes_calculo_service.py:38:def calcular_liquido_com_retencoes_salvas(nota: Any) -> Decimal:
backend\app\services\retencoes_calculo_service.py:72:def comparar_valor_fiscal(informado: Any, calculado: Any, nome: str = "") -> str:
backend\app\services\retencoes_calculo_service.py:88:def _flag(value: str | None) -> str:
backend\app\services\retencoes_calculo_service.py:92:def _is_simples(value: str | None) -> bool:
backend\app\services\retencoes_calculo_service.py:96:def extrair_base_calculo_inss(descricao: Any) -> Decimal | None:
backend\app\services\retencoes_calculo_service.py:116:def calcular_retencoes_esperadas(
backend\app\scripts\reconciliar_storage.py:13:def executar(processo_id: int | None = None) -> dict[str, object]:
backend\app\scripts\reconciliar_storage.py:35:def main(argv: list[str] | None = None) -> int:
backend\app\services\processos_service.py:15:class ProcessoServiceError(ValueError):
backend\app\services\processos_service.py:19:def criar_processo_com_job(db: Session, payload: ProcessoCreate, grupo: str | None = None) -> Processo:
backend\app\services\processos_service.py:73:def listar_processos(
backend\app\services\processos_service.py:93:def obter_processo_no_grupo(db: Session, processo_id: int, grupo: str) -> Processo:
backend\app\services\processos_service.py:100:def obter_processo(db: Session, processo_id: int) -> Processo:
backend\app\services\processos_service.py:107:def listar_jobs_processo(db: Session, processo_id: int) -> list[Job]:
backend\app\services\processos_service.py:112:def cancelar_processo(db: Session, processo_id: int) -> tuple[Processo, str]:
backend\app\schemas\empresas.py:10:def limpar_cnpj(value: str) -> str:
backend\app\schemas\empresas.py:14:class EmpresaBase(BaseModel):
backend\app\schemas\empresas.py:48:class EmpresaCreate(EmpresaBase):
backend\app\schemas\empresas.py:52:class EmpresaUpdate(BaseModel):
backend\app\schemas\empresas.py:90:class EmpresaRead(BaseModel):
backend\app\scripts\reconciliar_notas_certificados.py:21:def _read_csv(path: Path) -> list[dict[str, str]]:
backend\app\scripts\reconciliar_notas_certificados.py:28:def _xml_e_evento(path_value: str) -> bool:
backend\app\scripts\reconciliar_notas_certificados.py:41:def _restaurar_indices_nfse(base_dir: Path) -> dict[str, int]:
backend\app\scripts\reconciliar_notas_certificados.py:97:def reconciliar_certificado(certificado_id: int, batch_size: int | None = None) -> dict[str, Any]:
backend\app\scripts\reconciliar_notas_certificados.py:188:def executar(
backend\app\scripts\reconciliar_notas_certificados.py:206:def main() -> None:
backend\app\scripts\gerar_apresentacao_resultados.py:39:def number(value) -> float:
backend\app\scripts\gerar_apresentacao_resultados.py:48:def month_key(value: str, fallback: Path) -> str:
backend\app\scripts\gerar_apresentacao_resultados.py:60:def company_cnpj(path: Path) -> str:
backend\app\scripts\gerar_apresentacao_resultados.py:68:def db_metrics() -> dict[str, int | float | None]:
backend\app\scripts\gerar_apresentacao_resultados.py:101:def database_inventory():
backend\app\scripts\gerar_apresentacao_resultados.py:149:def inventory():
backend\app\scripts\gerar_apresentacao_resultados.py:194:def title(ws, text: str, subtitle: str | None = None):
backend\app\scripts\gerar_apresentacao_resultados.py:207:def kpi(ws, cell: str, label: str, value, color: str, fmt: str = "#,##0"):
backend\app\scripts\gerar_apresentacao_resultados.py:227:def table(ws, start_row: int, headers: list[str], data: list[list], name: str):
backend\app\scripts\gerar_apresentacao_resultados.py:244:def build(source: str = "local"):
backend\app\services\portal_support_service.py:30:class PortalSupportError(RuntimeError):
backend\app\services\portal_support_service.py:34:def _canonical_tipo_arquivo(tipo: str | None) -> str:
backend\app\services\portal_support_service.py:45:def _tipo_documento_frontend(tipo: str | None) -> str:
backend\app\services\portal_support_service.py:54:def _matches_tipo_arquivo(arquivo: Arquivo, tipo: str) -> bool:
backend\app\services\portal_support_service.py:75:def _nome_arquivo(arquivo: Arquivo) -> str:
backend\app\services\portal_support_service.py:81:def _arquivo_disponivel(storage: StorageService | None, arquivo: Arquivo) -> bool:
backend\app\services\portal_support_service.py:90:def arquivo_item(arquivo: Arquivo, storage: StorageService | None = None) -> dict:
backend\app\services\portal_support_service.py:110:def listar_documentos_nota(db: Session, nota_id: int, storage: StorageService | None = None) -> dict:
backend\app\services\portal_support_service.py:120:def _arquivo_id_por_storage(db: Session, storage_key: str | None) -> int | None:
backend\app\services\portal_support_service.py:127:def evento_item(db: Session, evento: Evento) -> dict:
backend\app\services\portal_support_service.py:142:def listar_eventos_nota(db: Session, nota_id: int) -> dict:
backend\app\services\portal_support_service.py:157:def listar_eventos(
backend\app\services\portal_support_service.py:205:def comparar_tributos_nota(db: Session, nota_id: int) -> dict:
backend\app\services\portal_support_service.py:273:def listar_arquivos_processo(
backend\app\services\portal_support_service.py:289:def listar_notas_processo(
backend\app\services\portal_support_service.py:336:def _tem_divergencia(nota: Nota) -> bool:
backend\app\services\portal_support_service.py:348:def _filtrar_notas_operacionais(
backend\app\services\portal_support_service.py:371:def _decimal(value) -> Decimal:
backend\app\services\portal_support_service.py:377:def resumo_processo(db: Session, processo_id: int) -> dict:
backend\app\services\portal_support_service.py:401:def resumo_operacional_empresas(
backend\app\services\portal_support_service.py:460:def _format_value(value) -> str:
backend\app\services\portal_support_service.py:470:def _xlsx_value(value):
backend\app\services\portal_support_service.py:480:def _buscar_notas_relatorio(db: Session, filtros: NotasDownloadFiltros, grupo: str | None = None) -> list[Nota]:
backend\app\services\portal_support_service.py:527:def _parse_decimal_optional(value) -> Decimal | None:
backend\app\services\portal_support_service.py:536:def _is_blank(value) -> bool:
backend\app\services\portal_support_service.py:540:def _nota_field(nota: Nota, field: str, xml_resumo: dict[str, str] | None = None, xml_key: str | None = None):
backend\app\services\portal_support_service.py:549:def _nota_decimal_field(nota: Nota, field: str, xml_resumo: dict[str, str] | None = None, xml_key: str | None = None):
backend\app\services\portal_support_service.py:558:def _status_valor_liquido(nota: Nota, xml_resumo: dict[str, str] | None = None) -> str:
backend\app\services\portal_support_service.py:573:def _nota_relatorio_row(nota: Nota, xml_resumo: dict[str, str] | None = None) -> list:
backend\app\services\portal_support_service.py:637:def _precisa_enriquecimento_xml(nota: Nota) -> bool:
backend\app\services\portal_support_service.py:656:def _xml_resumos_por_nota(db: Session, notas: list[Nota]) -> dict[int, dict[str, str]]:
backend\app\services\portal_support_service.py:696:def exportar_conferencia_xlsx(db: Session, filtros: NotasDownloadFiltros) -> tuple[bytes, str]:
backend\app\services\portal_support_service.py:891:def _relatorio_digits(value) -> str:
backend\app\services\portal_support_service.py:895:def _relatorio_decimal(value) -> Decimal:
backend\app\services\portal_support_service.py:900:def _relatorio_money(value) -> float:
backend\app\services\portal_support_service.py:904:def _relatorio_text(value) -> str:
backend\app\services\portal_support_service.py:911:def _relatorio_date(value):
backend\app\services\portal_support_service.py:925:def _relatorio_codigo_servico(value) -> str:
backend\app\services\portal_support_service.py:934:def _relatorio_status(value, default: str = "Não se aplica") -> str:
backend\app\services\portal_support_service.py:954:def _relatorio_simples(value) -> str:
backend\app\services\portal_support_service.py:968:def _relatorio_alertas(*values) -> str:
backend\app\services\portal_support_service.py:979:def _relatorio_alerta_critico(alertas: str) -> bool:
backend\app\services\portal_support_service.py:984:def _api_flag_bool(value) -> bool | None:
backend\app\services\portal_support_service.py:997:def _relatorio_status_calculado(informado, calculado, status, tributo: str) -> tuple[str, str]:
backend\app\services\portal_support_service.py:1010:def _normalizar_invertexto_payload(payload: dict | None) -> dict:
backend\app\services\portal_support_service.py:1035:def _invertexto_result(
backend\app\services\portal_support_service.py:1049:def _consultar_receita_cache_cnpjs(db: Session, cnpjs: set[str]) -> dict[str, dict]:
backend\app\services\portal_support_service.py:1073:def _receita_cache_cnpjs(db: Session, cnpjs: set[str]) -> dict[str, dict]:
backend\app\services\portal_support_service.py:1082:def _relatorio_status_simples(simples_xml: str, consulta_api: str) -> str:
backend\app\services\portal_support_service.py:1092:def _relatorio_empresa_cnpjs(db: Session, notas: list[Nota]) -> dict[int, str]:
backend\app\services\portal_support_service.py:1100:def _relatorio_party(nota: Nota, empresa_cnpj: str) -> tuple[str, str, str]:
backend\app\services\portal_support_service.py:1107:def _relatorio_row(nota: Nota, xml_resumo: dict[str, str] | None, empresa_cnpj: str, api_data: dict, gerado_em: date) -> list:
backend\app\services\portal_support_service.py:1173:def _relatorio_row_divergente(row: list) -> bool:
backend\app\services\portal_support_service.py:1180:def _add_relatorio_sheet(
backend\app\services\portal_support_service.py:1235:def exportar_conferencia_xlsx(db: Session, filtros: NotasDownloadFiltros, grupo: str | None = None) -> tuple[Path, str]:
backend\app\scripts\enfileirar_reprocessamento_certificados.py:12:def executar(confirmar: bool = False, grupo: str = "planning_hub") -> dict:
backend\app\scripts\enfileirar_reprocessamento_certificados.py:67:def main() -> None:
backend\app\scripts\recalcular_alertas_fiscais.py:33:class Relatorio:
backend\app\scripts\recalcular_alertas_fiscais.py:64:def _split_alertas(texto: str | None) -> set[str]:
backend\app\scripts\recalcular_alertas_fiscais.py:70:def _listar_lotes_de_ids(
backend\app\scripts\recalcular_alertas_fiscais.py:92:def recalcular_nota(
backend\app\scripts\recalcular_alertas_fiscais.py:161:def executar(
backend\app\scripts\recalcular_alertas_fiscais.py:189:def main(argv: list[str] | None = None) -> int:
backend\app\services\pdf_status_service.py:16:def _sem_acentos(value: str) -> str:
backend\app\services\pdf_status_service.py:21:def detectar_status_pdf_oficial(pdf_bytes: bytes) -> str | None:
backend\app\services\pdf_status_service.py:57:def aplicar_status_pdf_oficial(
backend\app\scripts\r2_common.py:7:def build_r2_storage() -> R2StorageService:
backend\app\scripts\diagnosticar_nsu_certificado.py:15:def executar(certificado_id: int, nsus: list[int], pausa: float, lote: bool = False) -> list[dict]:
backend\app\scripts\diagnosticar_nsu_certificado.py:92:def main() -> None:
backend\app\scripts\promover_usuarios_locais.py:21:def exportar_selecionados() -> list[dict]:
backend\app\scripts\promover_usuarios_locais.py:37:def executar(confirmar: bool = False) -> dict:
backend\app\scripts\promover_usuarios_locais.py:105:def main() -> None:
backend\app\services\operational_fields_service.py:32:def _strip_accents(value: str) -> str:
backend\app\services\operational_fields_service.py:39:def _norm(value: Any) -> str:
backend\app\services\operational_fields_service.py:43:def normalizar_simples_xml(value: str | None) -> str | None:
backend\app\services\operational_fields_service.py:56:def simples_xml_from_codes(op_simp_nac: str | None = None, reg_ap_trib_sn: str | None = None) -> str | None:
backend\app\services\operational_fields_service.py:80:def consulta_simples_api_from_payload(payload: dict | None) -> str:
backend\app\services\operational_fields_service.py:98:def calcular_status_simples_nacional_xml(simples_xml: str | None) -> str:
backend\app\services\operational_fields_service.py:107:def calcular_status_simples_nacional(simples_xml: str | None, consulta_simples_api: str | None = None) -> str:
backend\app\services\operational_fields_service.py:128:def normalizar_status_fila(value: str | None) -> str | None:
backend\app\services\operational_fields_service.py:145:def _contains_divergence_hint(value: str | None) -> bool:
backend\app\services\operational_fields_service.py:150:def _status_field_is_divergent(value: str | None) -> bool:
backend\app\services\operational_fields_service.py:159:def calcular_status_fila(nota) -> str:
backend\app\services\operational_fields_service.py:193:def normalizar_prioridade(value: str | None) -> str | None:
backend\app\services\operational_fields_service.py:206:def calcular_prioridade_fila(nota, status_fila_final: str) -> str:
backend\app\services\operational_fields_service.py:219:def calcular_sla_operacional(entrada_fila: datetime | None, prioridade_fila: str | None) -> dict:
backend\app\services\operational_fields_service.py:249:def montar_campos_operacionais(nota, consulta_simples_api: str | None = None) -> dict:
backend\app\services\operational_fields_service.py:275:def aplicar_campos_operacionais(nota, consulta_simples_api: str | None = None):
backend\app\scripts\diagnosticar_notas_faltantes_202608.py:43:def norm_number(value):
backend\app\services\nsu_control_service.py:14:def only_digits(value: str | None) -> str:
backend\app\services\nsu_control_service.py:18:def maior_nsu_importado(db: Session, empresa_id: int) -> int:
backend\app\services\nsu_control_service.py:28:def nsu_base_mes_anterior(db: Session, empresa_id: int, referencia: date) -> int | None:
backend\app\services\nsu_control_service.py:57:def obter_ultimo_nsu(
backend\app\services\nsu_control_service.py:72:def janela_reconciliacao(now: datetime | None = None) -> date | None:
backend\app\services\nsu_control_service.py:89:def planejar_inicio_consulta(
backend\app\services\nsu_control_service.py:126:def marcar_reconciliacao_concluida(
backend\app\services\nsu_control_service.py:143:def atualizar_ultimo_nsu(
backend\app\services\nsu_control_service.py:192:def sincronizar_com_notas(
backend\app\scripts\migrar_storage_para_r2.py:12:class MigrationReport:
backend\app\scripts\migrar_storage_para_r2.py:20:def _iter_batches(items: list[str], batch_size: int):
backend\app\scripts\migrar_storage_para_r2.py:26:def migrate(prefix: str = "", dry_run: bool = True, batch_size: int = 100) -> MigrationReport:
backend\app\scripts\migrar_storage_para_r2.py:58:def build_parser() -> argparse.ArgumentParser:
backend\app\scripts\migrar_storage_para_r2.py:68:def main(argv: list[str] | None = None) -> int:
backend\app\repositories\usuarios_repo.py:9:def create_usuario(db: Session, data: dict) -> Usuario:
backend\app\repositories\usuarios_repo.py:17:def get_usuario(db: Session, usuario_id: int) -> Usuario | None:
backend\app\repositories\usuarios_repo.py:21:def get_usuario_by_email(db: Session, email: str) -> Usuario | None:
backend\app\repositories\usuarios_repo.py:25:def list_usuarios(db: Session, empresa_id: int | None = None) -> list[Usuario]:
backend\app\services\notas_service.py:16:class NotaServiceError(RuntimeError):
backend\app\services\notas_service.py:20:def _only_digits(value: str | None) -> str:
backend\app\services\notas_service.py:24:def _previous_month(value: date) -> date:
backend\app\services\notas_service.py:30:def _next_month(value: date) -> date:
backend\app\services\notas_service.py:36:def _month_start(value: date) -> date:
backend\app\services\notas_service.py:40:def _competencia_operacional(
backend\app\services\notas_service.py:57:def _classificar_nota(nota: Nota, empresa_cnpj: str) -> str:
backend\app\services\notas_service.py:61:def normalizar_tipo_nota(value: str | None) -> str | None:
backend\app\services\notas_service.py:76:def normalizar_direcao_nota(value: str | None) -> str | None:
backend\app\services\notas_service.py:91:def tipo_para_direcao(tipo_nota: str | None) -> str | None:
backend\app\services\notas_service.py:100:def direcao_para_tipo(direcao_nota: str | None) -> str | None:
backend\app\services\notas_service.py:109:def classificar_direcao_nota(nota: Nota, empresa_cnpj: str | None) -> str:
backend\app\services\notas_service.py:126:def classificar_tipo_nota(nota: Nota, empresa_cnpj: str | None) -> str:
backend\app\services\notas_service.py:131:def _empresa_cnpj_nota(nota: Nota) -> str:
backend\app\services\notas_service.py:138:def _anotar_classificacao(
backend\app\services\notas_service.py:153:def _empresa_ou_erro(db: Session, empresa_id: int) -> Empresa:
backend\app\services\notas_service.py:160:def _canonical_tipo_arquivo(tipo: str | None) -> str:
backend\app\services\notas_service.py:171:def _selecionar_arquivos_visiveis(arquivos: list[Arquivo]) -> list[Arquivo]:
backend\app\services\notas_service.py:188:def _cnpj_contraparte(nota: Nota, direcao_nota: str) -> str | None:
backend\app\services\notas_service.py:198:def _consultas_simples_api_lote(db: Session, notas: list[Nota]) -> dict[int, str | None]:
backend\app\services\notas_service.py:238:def _anotar_detalhe_frontend(nota: Nota, consulta_simples_api: str | None = None) -> Nota:
backend\app\services\notas_service.py:278:def listar_notas(
backend\app\services\notas_service.py:389:def listar_todas_notas(
backend\app\services\notas_service.py:506:def _filtrar_notas_calculadas(
backend\app\services\notas_service.py:528:def resumo_notas_operacional(
backend\app\services\notas_service.py:570:def listar_notas_por_tipo_operacional(
backend\app\services\notas_service.py:694:def obter_nota(db: Session, nota_id: int) -> Nota:
backend\app\services\notas_service.py:702:def obter_nota_por_chave(db: Session, chave: str, empresa_id: int | None = None) -> Nota:
backend\app\services\notas_service.py:710:def atualizar_conferencia(db: Session, nota_id: int, payload) -> Nota:
backend\app\services\notas_service.py:763:def listar_arquivos_nota(db: Session, nota_id: int) -> list[Arquivo]:
backend\app\repositories\secrets_repo.py:8:def create_or_update_secret(db: Session, ref: str, tipo: str, encrypted_value: str) -> Secret:
backend\app\repositories\secrets_repo.py:22:def get_secret_by_ref(db: Session, ref: str) -> Secret | None:
backend\app\repositories\secrets_repo.py:26:def delete_secret_by_ref(db: Session, ref: str) -> bool:
backend\app\scripts\migrar_sqlite_para_postgres.py:25:class MigrationError(RuntimeError):
backend\app\scripts\migrar_sqlite_para_postgres.py:29:def migrar(
backend\app\scripts\migrar_sqlite_para_postgres.py:100:def build_parser() -> argparse.ArgumentParser:
backend\app\scripts\migrar_sqlite_para_postgres.py:110:def main() -> None:
backend\app\services\notas_download_service.py:36:class NotasDownloadLoteError(RuntimeError):
backend\app\services\notas_download_service.py:41:class DownloadLoteResult:
backend\app\services\notas_download_service.py:49:def _canonical_tipo(value: str | None) -> str:
backend\app\services\notas_download_service.py:60:def _dedupe_path(path: str, used: set[str]) -> str:
backend\app\services\notas_download_service.py:80:def _friendly_xml_filename(nota: Nota) -> str:
backend\app\services\notas_download_service.py:84:def _friendly_pdf_filename(nota: Nota) -> str:
backend\app\services\notas_download_service.py:88:def _zip_folder_for_arquivo(nota: Nota, tipo: str) -> str:
backend\app\services\notas_download_service.py:98:def _select_arquivos(
backend\app\services\notas_download_service.py:125:def _get_storage_bytes(storage: StorageService, arquivo: Arquivo) -> tuple[Arquivo, bytes | None, Exception | None]:
backend\app\services\notas_download_service.py:132:def limpar_zips_temporarios(max_age_hours: int | None = None) -> int:
backend\app\services\notas_download_service.py:148:def _buscar_notas(db: Session, payload: NotasDownloadLoteRequest, max_notas: int, grupo: str | None = None) -> list[Nota]:
backend\app\services\notas_download_service.py:199:def gerar_zip_notas(
backend\app\scripts\migrar_rbac.py:11:def _engine():
backend\app\scripts\migrar_rbac.py:18:def executar(email_admin: str, *, aplicar: bool) -> dict:
backend\app\scripts\migrar_rbac.py:67:def main() -> None:
backend\app\scripts\diagnosticar_banco.py:15:def diagnosticar(database_url: str | None = None) -> dict:
backend\app\scripts\diagnosticar_banco.py:30:def main() -> None:
backend\app\repositories\processos_repo.py:10:def create_processo(db: Session, data: dict) -> Processo:
backend\app\repositories\processos_repo.py:18:def get_processo(db: Session, processo_id: int) -> Processo | None:
backend\app\repositories\processos_repo.py:22:def list_processos(
backend\app\repositories\processos_repo.py:40:def get_processo_no_grupo(db: Session, processo_id: int, grupo: str) -> Processo | None:
backend\app\repositories\processos_repo.py:44:def update_processo(db: Session, processo: Processo, data: dict) -> Processo:
backend\app\repositories\processos_repo.py:53:def cancelar_processo(db: Session, processo: Processo) -> Processo:
backend\app\repositories\processos_repo.py:57:def mark_processo_running(db: Session, processo: Processo) -> Processo:
backend\app\repositories\processos_repo.py:68:def mark_processo_finalizado(db: Session, processo: Processo, erro_resumo: str | None = None) -> Processo:
backend\app\repositories\processos_repo.py:80:def mark_processo_erro(db: Session, processo: Processo, erro: str) -> Processo:
backend\app\services\notas_archive_service.py:19:def filtro_anos_anteriores(ano_operacional: int):
backend\app\services\notas_archive_service.py:25:def _json_value(value: Any) -> Any:
backend\app\services\notas_archive_service.py:31:def _row_dict(row: Any) -> dict[str, Any]:
backend\app\services\notas_archive_service.py:35:def _checksum_file(path: Path) -> str:
backend\app\services\notas_archive_service.py:43:def _storage_references(notas: list[Nota], arquivos: list[Arquivo], eventos: list[Evento]) -> list[dict[str, Any]]:
backend\app\services\notas_archive_service.py:66:def arquivar_notas_anos_anteriores(
backend\app\scripts\migrar_banco.py:7:def main() -> None:
backend\app\repositories\notas_repo.py:12:def _incidencia_search_term(value: str) -> str:
backend\app\repositories\notas_repo.py:19:def get_nota(db: Session, nota_id: int) -> Nota | None:
backend\app\repositories\notas_repo.py:23:def get_nota_by_chave(db: Session, empresa_id: int, chave: str) -> Nota | None:
backend\app\repositories\notas_repo.py:32:def get_nota_by_chave_optional_empresa(
backend\app\repositories\notas_repo.py:43:def list_notas(
backend\app\repositories\notas_repo.py:160:def list_notas_by_ids(db: Session, nota_ids: list[int]) -> list[Nota]:
backend\app\repositories\notas_repo.py:168:def count_notas_grupo(db: Session, grupo: str | None = None, arquivadas: str = "ativas") -> int:
backend\app\repositories\notas_repo.py:182:def create_nota(db: Session, data: dict) -> Nota:
backend\app\repositories\notas_repo.py:193:def update_nota(db: Session, nota: Nota, data: dict) -> Nota:
backend\app\repositories\notas_repo.py:221:def upsert_nota_by_chave(db: Session, empresa_id: int, chave: str, data: dict) -> tuple[Nota, bool]:
backend\app\scripts\db_migration_common.py:33:def normalize_database_url(database_url: str) -> str:
backend\app\scripts\db_migration_common.py:40:def mask_database_url(database_url: str) -> str:
backend\app\scripts\db_migration_common.py:47:def database_kind(database_url: str) -> str:
backend\app\scripts\db_migration_common.py:56:def build_engine(database_url: str) -> Engine:
backend\app\scripts\db_migration_common.py:62:def sqlite_url_from_path(sqlite_path: str | Path) -> str:
backend\app\scripts\db_migration_common.py:67:def sorted_model_tables() -> list[Table]:
backend\app\scripts\db_migration_common.py:71:def table_names_for_models() -> list[str]:
backend\app\scripts\db_migration_common.py:75:def existing_table_names(engine: Engine) -> list[str]:
backend\app\scripts\db_migration_common.py:79:def count_table(engine: Engine, table_name: str) -> int:
backend\app\scripts\db_migration_common.py:84:def count_tables(engine: Engine, table_names: Iterable[str] | None = None) -> dict[str, int]:
backend\app\scripts\db_migration_common.py:90:def has_any_data(engine: Engine, table_names: Iterable[str] | None = None) -> tuple[bool, dict[str, int]]:
backend\app\scripts\db_migration_common.py:95:def normalize_value(value: Any) -> Any:
backend\app\scripts\db_migration_common.py:107:def normalize_row(row: dict[str, Any]) -> dict[str, Any]:
backend\app\scripts\db_migration_common.py:111:def load_source_table(sqlite_engine: Engine, table_name: str) -> Table:
backend\app\scripts\db_migration_common.py:116:def read_rows(engine: Engine, table: Table, offset: int, limit: int) -> list[dict[str, Any]]:
backend\app\scripts\db_migration_common.py:122:def create_postgres_schema(postgres_engine: Engine) -> None:
backend\app\scripts\db_migration_common.py:126:def reset_postgres_sequences(postgres_engine: Engine) -> None:
backend\app\scripts\db_migration_common.py:150:def compare_values(left: Any, right: Any) -> bool:
backend\app\scripts\db_migration_common.py:160:def sample_rows_by_id(engine: Engine, table_name: str, limit: int = 5) -> list[dict[str, Any]]:
backend\app\services\nfse_xml_parser.py:71:def _local_name(tag: str) -> str:
backend\app\services\nfse_xml_parser.py:75:def _children(el: ET.Element | None, name: str | None = None) -> list[ET.Element]:
backend\app\services\nfse_xml_parser.py:83:def _child(el: ET.Element | None, *path: str) -> ET.Element | None:
backend\app\services\nfse_xml_parser.py:93:def _find_first(el: ET.Element | None, name: str) -> ET.Element | None:
backend\app\services\nfse_xml_parser.py:102:def _txt(el: ET.Element | None, *path: str, default: str = "-") -> str:
backend\app\services\nfse_xml_parser.py:109:def _raw(el: ET.Element | None, *path: str) -> str:
backend\app\services\nfse_xml_parser.py:113:def _raw_first(el: ET.Element | None, *names: str) -> str:
backend\app\services\nfse_xml_parser.py:121:def _decimal(value: str) -> Decimal | None:
backend\app\services\nfse_xml_parser.py:131:def _money_text(value: Decimal) -> str:
backend\app\services\nfse_xml_parser.py:135:def _sum_values(*values: str) -> str:
backend\app\services\nfse_xml_parser.py:147:def _fmt_cnpj_cpf(value: str) -> str:
backend\app\services\nfse_xml_parser.py:156:def _fmt_cep(value: str) -> str:
backend\app\services\nfse_xml_parser.py:163:def _fmt_fone(value: str) -> str:
backend\app\services\nfse_xml_parser.py:172:def _fmt_data(value: str) -> str:
backend\app\services\nfse_xml_parser.py:182:def _fmt_datahora(value: str) -> str:
backend\app\services\nfse_xml_parser.py:192:def _montar_endereco(end: ET.Element | None) -> str:
backend\app\services\nfse_xml_parser.py:200:def _format_codigo_tributacao(value: str) -> str:
backend\app\services\nfse_xml_parser.py:207:def _municipio_uf(nome: str, uf: str = "", codigo_municipio: str = "") -> str:
backend\app\services\nfse_xml_parser.py:218:def _extrair_chave(attr_id: str | None, prefixo: str) -> str:
backend\app\services\nfse_xml_parser.py:223:def _has_real_data(el: ET.Element | None) -> bool:
backend\app\services\nfse_xml_parser.py:232:def extrair_dados_nfse(xml_path: str | Path, prefeitura_info: dict | None = None) -> dict:
backend\app\scripts\melhorar_apresentacao_resultados.py:30:def card(ws, start_col: int, start_row: int, label: str, value, explanation: str, color: str, fmt: str = "#,##0"):
backend\app\scripts\melhorar_apresentacao_resultados.py:54:def section(ws, row: int, title: str, text: str):
backend\app\scripts\melhorar_apresentacao_resultados.py:64:def main():
backend\app\scripts\corrigir_simples_pendentes_online.py:23:def _database_url() -> str:
backend\app\scripts\corrigir_simples_pendentes_online.py:32:def corrigir(local_db: Path, cache_days: int = 30, batch_size: int = 500) -> dict:
backend\app\services\logs_service.py:34:def sanitizar_texto(value: Any, max_length: int = 4000) -> str:
backend\app\services\logs_service.py:44:def sanitizar_contexto(value: Any, depth: int = 0) -> Any:
backend\app\services\logs_service.py:68:def registrar_log(
backend\app\services\logs_service.py:88:def listar_logs(
backend\app\repositories\logs_repo.py:8:def create_log(db: Session, data: dict) -> LogProcesso:
backend\app\repositories\logs_repo.py:16:def list_logs(
backend\app\scripts\listar_consultas_simples_pendentes.py:13:def _database_url() -> str:
backend\app\scripts\listar_consultas_simples_pendentes.py:84:def listar() -> list[dict]:
backend\app\scripts\listar_consultas_simples_pendentes.py:93:def main() -> None:
backend\app\scripts\gerar_espelhos_ausentes.py:19:def main() -> int:
backend\app\services\locks_service.py:8:def adquirir_lock(
backend\app\services\locks_service.py:24:def liberar_lock(db: Session, empresa_id: int, certificado_id: int, locked_by: str) -> bool:
backend\app\services\locks_service.py:33:def renovar_lock(
backend\app\repositories\locks_repo.py:10:def get_lock(db: Session, empresa_id: int, certificado_id: int) -> LockProcessamento | None:
backend\app\repositories\locks_repo.py:19:def acquire_lock(
backend\app\repositories\locks_repo.py:52:def release_lock(db: Session, empresa_id: int, certificado_id: int, locked_by: str) -> bool:
backend\app\repositories\locks_repo.py:61:def renew_lock(
backend\app\services\cnpj_receita_service.py:15:class CnpjReceitaError(RuntimeError):
backend\app\services\cnpj_receita_service.py:19:def normalizar_cnpj(value: str) -> str:
backend\app\services\cnpj_receita_service.py:26:def _database_path() -> Path:
backend\app\services\cnpj_receita_service.py:30:def _connect(path: Path | None = None) -> sqlite3.Connection:
backend\app\services\cnpj_receita_service.py:39:def consultar_cnpj(value: str) -> dict[str, Any] | None:
backend\app\services\cnpj_receita_service.py:76:def consultar_cnpj_cacheado(db: Session, value: str) -> dict[str, Any] | None:
backend\app\services\cnpj_receita_service.py:112:def consultar_cnpjs(values: set[str] | list[str]) -> dict[str, dict[str, Any]]:
backend\app\services\cnpj_receita_service.py:158:def status_simples(item: dict[str, Any]) -> str:
backend\app\services\cnpj_receita_service.py:182:def _status_base_cached(path_raw: str, tamanho: int, modificado_ns: int) -> dict[str, Any]:
backend\app\services\cnpj_receita_service.py:207:def status_base() -> dict[str, Any]:
backend\app\repositories\jobs_repo.py:11:def create_job(db: Session, data: dict) -> Job:
backend\app\repositories\jobs_repo.py:19:def get_job(db: Session, job_id: int) -> Job | None:
backend\app\repositories\jobs_repo.py:23:def list_jobs(
backend\app\repositories\jobs_repo.py:41:def update_job(db: Session, job: Job, data: dict) -> Job:
backend\app\repositories\jobs_repo.py:50:def get_next_pending_job(db: Session) -> Job | None:
backend\app\repositories\jobs_repo.py:61:def claim_next_pending_job(db: Session, locked_by: str, grupo: str | None = None) -> Job | None:
backend\app\repositories\jobs_repo.py:91:def mark_job_running(db: Session, job: Job, locked_by: str) -> Job:
backend\app\repositories\jobs_repo.py:103:def mark_job_pending(db: Session, job: Job) -> Job:
backend\app\repositories\jobs_repo.py:115:def mark_job_finalizado(db: Session, job: Job, mensagem: str | None = None) -> Job:
backend\app\repositories\jobs_repo.py:123:def mark_job_erro(db: Session, job: Job, erro: str) -> Job:
backend\app\repositories\jobs_repo.py:134:def mark_job_cancelado(db: Session, job: Job, mensagem: str | None = None) -> Job:
backend\app\services\legacy_processing_service.py:24:class LegacyProcessingError(RuntimeError):
backend\app\services\legacy_processing_service.py:28:def _maior_nsu_importado_por_cnpj(cnpj: str) -> int:
backend\app\services\legacy_processing_service.py:44:def _ultimo_nsu_central_por_cnpj(cnpj: str, certificado_id: int | None = None) -> int:
backend\app\services\legacy_processing_service.py:55:def _processo_cancelado(processo_id: int) -> bool:
backend\app\services\legacy_processing_service.py:61:def _load_legacy_module(processo_id: int) -> Any:
backend\app\services\legacy_processing_service.py:78:def _configure_legacy_output(legacy: Any, root_out: Path) -> None:
backend\app\services\legacy_processing_service.py:98:def _safe_worker_id(value: str) -> str:
backend\app\services\legacy_processing_service.py:102:def _payload_value(payload: dict[str, Any], key: str, default: Any) -> Any:
backend\app\services\legacy_processing_service.py:107:def _safe_legacy_result(result: Any) -> dict[str, Any] | str:
backend\app\services\legacy_processing_service.py:125:def _contar_saida_legada(pasta_saida: str | None) -> dict[str, Any]:
backend\app\services\legacy_processing_service.py:143:def _ingestao_tem_movimento(ingestao: dict[str, Any]) -> bool:
backend\app\services\legacy_processing_service.py:153:def _loop_ingestao_incremental(
backend\app\services\legacy_processing_service.py:208:def _iniciar_ingestao_incremental(
backend\app\services\legacy_processing_service.py:226:def _build_legacy_config(legacy: Any, empresa_item: dict[str, Any]) -> Any:
backend\app\services\legacy_processing_service.py:261:def _executar_baixa_empresa_compat(
backend\app\services\legacy_processing_service.py:401:def _processar_pdfs_durante_pausa(
backend\app\services\legacy_processing_service.py:447:def _processar_pdfs_ao_final(
backend\app\services\legacy_processing_service.py:472:def _baixar_pdf_danfse_compat(legacy: Any, config: Any, chave: str, timeout: float = 240) -> bool:
backend\app\services\legacy_processing_service.py:500:def _registrar_pdf_no_index(legacy: Any, chave: str, pdf_path: Path, pdf_tipo: str) -> None:
backend\app\services\legacy_processing_service.py:512:def executar_consulta_nfse_legado(
backend\app\scripts\importar_base_cnpj_receita.py:36:def _digits(value: str) -> str:
backend\app\scripts\importar_base_cnpj_receita.py:40:def _targets(values: Sequence[str]) -> tuple[set[str], set[str]]:
backend\app\scripts\importar_base_cnpj_receita.py:48:def _schema(connection: sqlite3.Connection) -> None:
backend\app\scripts\importar_base_cnpj_receita.py:81:def _outer_members(archive: zipfile.ZipFile, prefix: str) -> list[str]:
backend\app\scripts\importar_base_cnpj_receita.py:86:def _rows_from_nested_zip(outer: zipfile.ZipFile, member: str, temp_dir: Path) -> Iterator[list[str]]:
backend\app\scripts\importar_base_cnpj_receita.py:107:def _chunks(rows: Iterable[tuple], size: int = 10_000) -> Iterator[list[tuple]]:
backend\app\scripts\importar_base_cnpj_receita.py:118:def _selected_rows(rows: Iterable[list[str]], columns: Sequence[str], roots: set[str]) -> Iterator[tuple]:
backend\app\scripts\importar_base_cnpj_receita.py:126:def _import_group(
backend\app\scripts\importar_base_cnpj_receita.py:154:def importar(source: Path, destination: Path, cnpjs: Sequence[str]) -> dict[str, int]:
backend\app\scripts\importar_base_cnpj_receita.py:202:def main() -> int:
backend\app\repositories\empresas_repo.py:8:def create_empresa(db: Session, data: dict) -> Empresa:
backend\app\repositories\empresas_repo.py:16:def get_empresa(db: Session, empresa_id: int) -> Empresa | None:
backend\app\repositories\empresas_repo.py:20:def get_empresa_by_cnpj(db: Session, cnpj: str) -> Empresa | None:
backend\app\repositories\empresas_repo.py:24:def list_empresas(db: Session, ativo: bool | None = None, grupo: str | None = None) -> list[Empresa]:
backend\app\repositories\empresas_repo.py:33:def update_empresa(db: Session, empresa: Empresa, data: dict) -> Empresa:
backend\app\repositories\empresas_repo.py:42:def delete_empresa(db: Session, empresa: Empresa) -> Empresa:
backend\app\services\cnpj_enrichment_service.py:12:def _only_digits(value: str | None) -> str:
backend\app\services\cnpj_enrichment_service.py:16:def coletar_cnpjs_para_enriquecimento(
backend\app\services\cnpj_enrichment_service.py:39:def enriquecer_cnpjs_do_processo(
backend\app\repositories\certificados_repo.py:8:def create_certificado(db: Session, data: dict) -> Certificado:
backend\app\repositories\certificados_repo.py:16:def get_certificado(db: Session, certificado_id: int) -> Certificado | None:
backend\app\repositories\certificados_repo.py:20:def list_certificados(
backend\app\repositories\certificados_repo.py:36:def get_certificado_no_grupo(db: Session, certificado_id: int, grupo: str) -> Certificado | None:
backend\app\repositories\certificados_repo.py:45:def update_certificado(db: Session, certificado: Certificado, data: dict) -> Certificado:
backend\app\repositories\certificados_repo.py:54:def deactivate_certificado(db: Session, certificado: Certificado) -> Certificado:
backend\app\services\danfse_service.py:14:class DanfseError(RuntimeError):
backend\app\services\danfse_service.py:18:def _local_name(tag: str) -> str:
backend\app\services\danfse_service.py:22:def _numero_nfse(xml_content: bytes) -> str:
backend\app\services\danfse_service.py:37:def friendly_pdf_filename(dados: dict) -> str:
backend\app\services\danfse_service.py:44:class DanfseService:
backend\app\services\legacy_ingestion_service.py:40:class LegacyIngestionError(RuntimeError):
backend\app\services\legacy_ingestion_service.py:44:def _parse_date(value: str) -> date | None:
backend\app\services\legacy_ingestion_service.py:57:def _parse_datetime(value: str) -> datetime | None:
backend\app\services\legacy_ingestion_service.py:67:def _parse_int(value: str) -> int | None:
backend\app\services\legacy_ingestion_service.py:77:def _parse_decimal(value: str) -> Decimal | None:
backend\app\services\legacy_ingestion_service.py:87:def _ano_mes(row: dict[str, str]) -> tuple[str, str]:
backend\app\services\legacy_ingestion_service.py:94:def _resolve_path(path_text: str, base_dir: Path) -> Path | None:
backend\app\services\legacy_ingestion_service.py:107:def _sha256(data: bytes) -> str:
backend\app\services\legacy_ingestion_service.py:111:def _canonical_tipo(tipo: str) -> str:
backend\app\services\legacy_ingestion_service.py:122:def _gerar_pdf_espelho_path(
backend\app\services\legacy_ingestion_service.py:136:def _local_name(tag: str) -> str:
backend\app\services\legacy_ingestion_service.py:140:def _find_text(root: ElementTree.Element, *names: str) -> str:
backend\app\services\legacy_ingestion_service.py:150:def _child_by_local_name(element: ElementTree.Element, name: str) -> ElementTree.Element | None:
backend\app\services\legacy_ingestion_service.py:158:def _find_path_text(root: ElementTree.Element, *path: str) -> str:
backend\app\services\legacy_ingestion_service.py:178:def _find_scoped_text(
backend\app\services\legacy_ingestion_service.py:202:def extrair_simples_nacional_xml(root: ElementTree.Element) -> str | None:
backend\app\services\legacy_ingestion_service.py:208:def extrair_incidencia_iss_xml(root: ElementTree.Element, dados_nota: dict | None = None) -> str | None:
backend\app\services\legacy_ingestion_service.py:223:def extrair_municipio_prestacao_xml(root: ElementTree.Element, dados_nota: dict | None = None) -> str | None:
backend\app\services\legacy_ingestion_service.py:235:def _sum_existing_decimals(*values: str) -> str:
backend\app\services\legacy_ingestion_service.py:250:def identificar_iss_retido(root: ElementTree.Element) -> tuple[bool, str]:
backend\app\services\legacy_ingestion_service.py:297:def _formatar_codigo_servico_display(raw: str) -> str:
backend\app\services\legacy_ingestion_service.py:311:def extrair_codigo_servico_xml(root: ElementTree.Element) -> dict[str, str]:
backend\app\services\legacy_ingestion_service.py:352:def _to_text(value) -> str:
backend\app\services\legacy_ingestion_service.py:356:def _xml_contains_text(root: ElementTree.Element, pattern: str) -> bool:
backend\app\services\legacy_ingestion_service.py:366:def _status_from_xml(root: ElementTree.Element) -> tuple[str | None, str | None]:
backend\app\services\legacy_ingestion_service.py:389:def _text_digits(value: str) -> str:
backend\app\services\legacy_ingestion_service.py:393:def _extract_chave_from_xml(xml_path: Path, root: ElementTree.Element | None = None) -> str:
backend\app\services\legacy_ingestion_service.py:411:def _parse_xml_resumo_root(root: ElementTree.Element, xml_path: Path) -> dict[str, str]:
backend\app\services\legacy_ingestion_service.py:551:def _parse_xml_resumo(xml_path: Path) -> dict[str, str]:
backend\app\services\legacy_ingestion_service.py:562:def parse_xml_resumo_bytes(data: bytes, filename: str = "nota.xml") -> dict[str, str]:
backend\app\services\legacy_ingestion_service.py:571:def _registrar_evento_xml(
backend\app\services\legacy_ingestion_service.py:626:def _regenerar_pdf_espelho_evento(
backend\app\services\legacy_ingestion_service.py:674:def _aplicar_campos_fiscais_xml(nota_data: dict[str, Any], resumo: dict[str, Any]) -> None:
backend\app\services\legacy_ingestion_service.py:722:def _find_pdf_for_chave(pdf_files: list[Path], chave: str) -> Path | None:
backend\app\services\legacy_ingestion_service.py:731:def _recent_file(path: Path, updated_after: datetime | None) -> bool:
backend\app\services\legacy_ingestion_service.py:737:def _read_index_rows(index_path: Path) -> list[dict[str, str]]:
backend\app\services\legacy_ingestion_service.py:742:def _arquivo_tipo_pdf(row: dict[str, str]) -> str:
backend\app\services\legacy_ingestion_service.py:749:def _build_pdf_key(cnpj: str, ano: str, mes: str, filename: str, tipo: str) -> str:
backend\app\services\legacy_ingestion_service.py:755:def _put_file_if_needed(storage: StorageService, storage_key: str, source_path: Path, content_type: str) -> tuple[dict[str, Any], bool]:
backend\app\services\legacy_ingestion_service.py:770:def _registrar_arquivo(
backend\app\services\legacy_ingestion_service.py:802:def ingerir_saida_legado(
backend\app\services\legacy_ingestion_service.py:1152:def _ingerir_por_varredura(
backend\app\services\cnpj_cache_service.py:19:def only_digits(value: str | None) -> str:
backend\app\services\cnpj_cache_service.py:23:def _today() -> date:
backend\app\services\cnpj_cache_service.py:27:def _cache_to_dict(cache: CnpjCache) -> dict[str, Any]:
backend\app\services\cnpj_cache_service.py:44:def get_cache_valido(db: Session, cnpj: str, fonte: str | None = None) -> dict[str, Any] | None:
backend\app\services\cnpj_cache_service.py:70:def get_caches_validos(
backend\app\services\cnpj_cache_service.py:99:def salvar_cache(
backend\app\repositories\arquivos_repo.py:10:def get_arquivo(db: Session, arquivo_id: int) -> Arquivo | None:
backend\app\repositories\arquivos_repo.py:14:def get_arquivo_by_storage_key(db: Session, storage_key: str) -> Arquivo | None:
backend\app\repositories\arquivos_repo.py:18:def list_arquivos_by_nota(db: Session, nota_id: int) -> list[Arquivo]:
backend\app\repositories\arquivos_repo.py:28:def list_arquivos_by_notas(db: Session, nota_ids: list[int]) -> list[Arquivo]:
backend\app\repositories\arquivos_repo.py:40:def list_arquivos(
backend\app\repositories\arquivos_repo.py:64:def create_arquivo(db: Session, data: dict) -> Arquivo:
backend\app\repositories\arquivos_repo.py:75:def create_arquivo_if_missing(db: Session, data: dict) -> tuple[Arquivo, bool]:
backend\app\services\consultas_service.py:24:def _now() -> datetime:
backend\app\services\consultas_service.py:28:def _as_aware(value: datetime | None) -> datetime | None:
backend\app\services\consultas_service.py:34:def _effective_limite(limite: int) -> int:
backend\app\services\consultas_service.py:39:def _effective_pausa(pausa: float) -> float:
backend\app\services\consultas_service.py:47:def _status_filter(query, statuses: tuple[str, ...]):
backend\app\services\consultas_service.py:51:def get_monitoramento_config(db: Session, grupo: str = "planning_hub") -> MonitoramentoConfig:
backend\app\services\consultas_service.py:68:def is_enabled(db: Session | None = None, grupo: str | None = None) -> bool:
backend\app\services\consultas_service.py:77:def listar_grupos_automaticos_ativos(db: Session) -> list[str]:
backend\app\services\consultas_service.py:82:def _count_processos(db: Session, statuses: tuple[str, ...], grupo: str) -> int:
backend\app\services\consultas_service.py:87:def _list_processos(db: Session, statuses: tuple[str, ...], limit: int, grupo: str) -> list[Processo]:
backend\app\services\consultas_service.py:92:def montar_status(db: Session, limit: int = 10, grupo: str = "planning_hub") -> dict[str, Any]:
backend\app\services\consultas_service.py:127:def has_active_consulta_for_certificado(db: Session, certificado_id: int) -> bool:
backend\app\services\consultas_service.py:136:def _active_consulta_certificado_ids(db: Session, certificado_ids: list[int]) -> set[int]:
backend\app\services\consultas_service.py:149:def list_certificados_elegiveis(
backend\app\services\consultas_service.py:182:def _create_consulta_job(db: Session, certificado: Certificado, options: ConsultaIniciarRequest) -> Processo:
backend\app\services\consultas_service.py:224:def enqueue_consultas_pendentes(
backend\app\services\consultas_service.py:269:def iniciar_consultas_automaticas(
backend\app\services\consultas_service.py:301:def iniciar_certificado_sem_substituir_monitor(
backend\app\services\consultas_service.py:349:def desativar_consultas_automaticas(
backend\app\services\legacy_adapter.py:1:def legacy_available() -> bool:
backend\app\services\auth_service.py:10:class AuthError(ValueError):
backend\app\services\auth_service.py:14:def autenticar(db: Session, email: str, senha: str) -> tuple[Usuario, str]:
backend\app\services\auth_service.py:24:def criar_usuario(db: Session, empresa_id: int, email: str, senha: str, nome: str | None = None) -> Usuario:
backend\app\services\certificado_metadata_service.py:12:class CertificadoMetadataError(ValueError):
backend\app\services\certificado_metadata_service.py:17:class CertificadoMetadata:
backend\app\services\certificado_metadata_service.py:26:def _digits(value: str) -> str:
backend\app\services\certificado_metadata_service.py:30:def cnpj_valido(value: str) -> bool:
backend\app\services\certificado_metadata_service.py:45:def extrair_cnpj_texto(*values: str | None) -> str | None:
backend\app\services\certificado_metadata_service.py:69:def _extract_cnpj(*values: str | None) -> str | None:
backend\app\services\certificado_metadata_service.py:73:def _first_attr(cert, oid) -> str | None:
backend\app\services\certificado_metadata_service.py:81:def _looks_like_authority_name(value: str | None) -> bool:
backend\app\services\certificado_metadata_service.py:86:def _extract_business_name(subject_cn: str | None, organization: str | None) -> str | None:
backend\app\services\certificado_metadata_service.py:96:def extrair_metadata_pfx(pfx_bytes: bytes, senha: str) -> CertificadoMetadata:
backend\app\services\empresas_service.py:10:class EmpresaServiceError(ValueError):
backend\app\services\empresas_service.py:14:def criar_empresa(db: Session, data: EmpresaCreate, grupo: str = "planning_hub") -> Empresa:
backend\app\services\empresas_service.py:23:def listar_empresas(db: Session, ativo: bool | None = None, grupo: str | None = None) -> list[Empresa]:
backend\app\services\empresas_service.py:27:def obter_empresa(db: Session, empresa_id: int) -> Empresa:
backend\app\services\empresas_service.py:34:def atualizar_empresa(db: Session, empresa_id: int, data: EmpresaUpdate) -> Empresa:
backend\app\services\empresas_service.py:45:def desativar_empresa(db: Session, empresa_id: int) -> Empresa:
backend\app\services\arquivos_service.py:13:class ArquivoServiceError(RuntimeError):
backend\app\services\arquivos_service.py:32:def preparar_download_arquivo(db: Session, storage: StorageService, arquivo_id: int) -> dict[str, Any]:
backend\app\services\certificados_service.py:25:class CertificadoServiceError(ValueError):
backend\app\services\certificados_service.py:32:def _sanitize_filename(filename: str) -> str:
backend\app\services\certificados_service.py:43:def _normalizar_ambiente(value: str) -> str:
backend\app\services\certificados_service.py:49:def _cnpj_from_text(value: str) -> str:
backend\app\services\certificados_service.py:53:def testar_certificado_pfx_bytes(pfx_bytes: bytes, senha: str) -> dict[str, Any]:
backend\app\services\certificados_service.py:91:def criar_certificado_com_upload(
backend\app\services\certificados_service.py:129:def criar_certificado_com_upload_e_senha(
backend\app\services\certificados_service.py:189:def autocadastrar_certificado(
backend\app\services\certificados_service.py:365:def atualizar_certificado_com_upload_ou_senha(
backend\app\services\certificados_service.py:428:def listar_certificados(
backend\app\services\certificados_service.py:444:def obter_certificado_no_grupo(db: Session, certificado_id: int, grupo: str) -> Certificado:
backend\app\services\certificados_service.py:451:def obter_certificado(db: Session, certificado_id: int) -> Certificado:
backend\app\services\certificados_service.py:458:def testar_certificado_salvo(
backend\app\services\certificados_service.py:469:def desativar_certificado(db: Session, certificado_id: int) -> Certificado:
backend\app\services\certificados_service.py:474:def salvar_senha_certificado(
backend\app\services\certificados_service.py:504:def status_senha_certificado(db: Session, certificado_id: int) -> dict[str, Any]:
backend\app\services\certificados_service.py:512:def remover_senha_certificado(db: Session, certificado_id: int) -> dict[str, Any]:
backend\app\services\certificados_service.py:527:def testar_certificado_com_senha_salva(
```
