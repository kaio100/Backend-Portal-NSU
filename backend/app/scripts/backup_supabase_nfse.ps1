[CmdletBinding()]
param(
    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$ProjectRef = "xiqiuumoaqhxajqtppmf",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$DatabaseHost = "aws-0-ca-central-1.pooler.supabase.com",

    [Parameter()]
    [ValidateRange(1, 65535)]
    [int]$DatabasePort = 5432,

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$DatabaseName = "postgres",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$OutputRoot = ".\backup_supabase",

    [Parameter()]
    [ValidateNotNullOrEmpty()]
    [string]$DockerImage = "public.ecr.aws/supabase/postgres:17.6.1.143"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step {
    param([Parameter(Mandatory)][string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}
function Invoke-Docker {
    param(
        [Parameter(Mandatory)]
        [string[]]$Arguments,

        [Parameter()]
        [switch]$CaptureOutput
    )

    if ($CaptureOutput) {
        $result = & docker @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        if ($exitCode -ne 0) {
            throw ($result -join [Environment]::NewLine)
        }
        return $result
    }

    & docker @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "O Docker encerrou a operação com código $LASTEXITCODE."
    }
}

function ConvertFrom-SecureStringPlainText {
    param([Parameter(Mandatory)][Security.SecureString]$SecureValue)

    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureValue)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

$databaseUser = "postgres.$ProjectRef"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outputDirectory = Join-Path $OutputRoot "nfse_$timestamp"
$dumpFileName = "nfse_public_$timestamp.dump"
$manifestFileName = "nfse_public_$timestamp.manifest.txt"
$hashFileName = "nfse_public_$timestamp.sha256.txt"
$countsFileName = "nfse_public_$timestamp.counts.csv"

$dumpPath = Join-Path $outputDirectory $dumpFileName
$manifestPath = Join-Path $outputDirectory $manifestFileName
$hashPath = Join-Path $outputDirectory $hashFileName
$countsPath = Join-Path $outputDirectory $countsFileName

$plainPassword = $null
$previousPgPassword = $env:PGPASSWORD

try {
    Write-Step "Verificando o Docker Desktop"
    & docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "O Docker Desktop não está iniciado. Abra-o, aguarde o Engine ficar ativo e execute novamente."
    }

    Write-Step "Preparando a pasta do backup"
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
    $resolvedOutputDirectory = (Resolve-Path $outputDirectory).Path

    Write-Host "Projeto: $ProjectRef"
    Write-Host "Usuário: $databaseUser"
    Write-Host "Host: $DatabaseHost"
    Write-Host "Porta: $DatabasePort"
    Write-Host "Destino: $resolvedOutputDirectory"

    Write-Step "Solicitando a senha do PostgreSQL"
    $securePassword = Read-Host "Digite a senha atual do banco (ela não será exibida)" -AsSecureString
    $plainPassword = ConvertFrom-SecureStringPlainText -SecureValue $securePassword

    if ([string]::IsNullOrWhiteSpace($plainPassword)) {
        throw "A senha não pode ficar vazia."
    }

    # O Docker recebe a senha pelo ambiente do processo, sem gravá-la no script
    # nem colocá-la como valor visível na lista de argumentos.
    $env:PGPASSWORD = $plainPassword

    Write-Step "Garantindo que a imagem PostgreSQL está disponível"
    Invoke-Docker -Arguments @("pull", $DockerImage)

    $connectionArguments = @(
        "--host=$DatabaseHost",
        "--port=$DatabasePort",
        "--username=$databaseUser",
        "--dbname=$DatabaseName"
    )

    Write-Step "Testando a autenticação antes do backup"
    try {
        $testResult = Invoke-Docker -CaptureOutput -Arguments (
            @(
                "run", "--rm",
                "-e", "PGPASSWORD",
                $DockerImage,
                "psql"
            ) +
            $connectionArguments +
            @(
                "--no-password",
                "--tuples-only",
                "--no-align",
                "--command=SELECT current_database() || '|' || current_user;"
            )
        )
    }
    catch {
        throw @"
Não foi possível autenticar no banco antigo.

Confira se a senha digitada pertence ao projeto:
  $ProjectRef

Nenhum backup válido foi criado. Erro original:
$($_.Exception.Message)
"@
    }

    Write-Host "Conexão confirmada: $($testResult -join '')" -ForegroundColor Green

    Write-Step "Registrando as contagens das tabelas principais"
    $countQuery = @"
SELECT 'logs_processos' AS tabela, count(*) AS quantidade FROM public.logs_processos
UNION ALL SELECT 'arquivos', count(*) FROM public.arquivos
UNION ALL SELECT 'notas', count(*) FROM public.notas
UNION ALL SELECT 'processos', count(*) FROM public.processos
UNION ALL SELECT 'processos_jobs', count(*) FROM public.processos_jobs
UNION ALL SELECT 'cnpj_cache', count(*) FROM public.cnpj_cache
UNION ALL SELECT 'eventos', count(*) FROM public.eventos
UNION ALL SELECT 'certificados', count(*) FROM public.certificados
UNION ALL SELECT 'nsu_controle', count(*) FROM public.nsu_controle
UNION ALL SELECT 'empresas', count(*) FROM public.empresas
ORDER BY tabela;
"@

    $counts = Invoke-Docker -CaptureOutput -Arguments (
        @(
            "run", "--rm",
            "-e", "PGPASSWORD",
            $DockerImage,
            "psql"
        ) +
        $connectionArguments +
        @(
            "--no-password",
            "--csv",
            "--command=$countQuery"
        )
    )
    $counts | Set-Content -Path $countsPath -Encoding utf8

    Write-Step "Criando o backup completo do schema public"
    try {
        Invoke-Docker -Arguments (
            @(
                "run", "--rm",
                "-e", "PGPASSWORD",
                "-v", "${resolvedOutputDirectory}:/backup",
                $DockerImage,
                "pg_dump"
            ) +
            $connectionArguments +
            @(
                "--no-password",
                "--format=custom",
                "--compress=6",
                "--schema=public",
                "--no-owner",
                "--no-acl",
                "--verbose",
                "--file=/backup/$dumpFileName"
            )
        )
    }
    catch {
        if (Test-Path $dumpPath) {
            Remove-Item -Force $dumpPath
        }
        throw
    }

    if (-not (Test-Path $dumpPath)) {
        throw "O arquivo de backup não foi criado."
    }

    $dumpInfo = Get-Item $dumpPath
    if ($dumpInfo.Length -le 0) {
        Remove-Item -Force $dumpPath
        throw "O arquivo de backup ficou vazio e foi removido."
    }

    Write-Step "Validando o conteúdo com pg_restore"
    $manifest = Invoke-Docker -CaptureOutput -Arguments @(
        "run", "--rm",
        "-v", "${resolvedOutputDirectory}:/backup",
        $DockerImage,
        "pg_restore",
        "--list",
        "/backup/$dumpFileName"
    )
    $manifest | Set-Content -Path $manifestPath -Encoding utf8

    $manifestText = $manifest -join [Environment]::NewLine
    $requiredEntries = @(
        "TABLE DATA public notas",
        "TABLE DATA public arquivos",
        "TABLE DATA public processos"
    )

    foreach ($entry in $requiredEntries) {
        if ($manifestText -notmatch [regex]::Escape($entry)) {
            throw "O dump foi criado, mas a validação não encontrou: $entry"
        }
    }

    Write-Step "Calculando o hash SHA-256"
    $hash = Get-FileHash -Algorithm SHA256 -Path $dumpPath
    "$($hash.Hash)  $dumpFileName" | Set-Content -Path $hashPath -Encoding ascii

    Write-Host ""
    Write-Host "BACKUP CONCLUÍDO E VALIDADO" -ForegroundColor Green
    Write-Host "Arquivo: $($dumpInfo.FullName)"
    Write-Host "Tamanho: $([math]::Round($dumpInfo.Length / 1MB, 2)) MB"
    Write-Host "Manifesto: $manifestPath"
    Write-Host "Contagens: $countsPath"
    Write-Host "SHA-256: $($hash.Hash)"
    Write-Host ""
    Write-Host "Nenhuma restauração foi executada e nenhum dado do banco foi alterado."
}
catch {
    Write-Host ""
    Write-Host "BACKUP NÃO CONCLUÍDO" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
finally {
    if ($null -eq $previousPgPassword) {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
    else {
        $env:PGPASSWORD = $previousPgPassword
    }

    $plainPassword = $null
}
