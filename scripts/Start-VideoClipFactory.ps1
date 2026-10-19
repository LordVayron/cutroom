param(
    [switch]$NoBrowser
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectDirectory = Split-Path -Parent $PSScriptRoot
$appUrl = "http://localhost:3000"
$apiHealthUrl = "http://localhost:8000/health"
$logDirectory = Join-Path ([Environment]::GetFolderPath("LocalApplicationData")) "Video Clip Factory"
$logPath = Join-Path $logDirectory "launcher.log"
$mutex = [Threading.Mutex]::new($false, "Local\VideoClipFactoryLauncher")
$hasMutex = $false

function Write-LauncherLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -LiteralPath $logPath -Value "[$timestamp] $Message" -Encoding UTF8
}

function Test-DockerEngine {
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
    $dockerExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    return $dockerExitCode -eq 0
}

function Test-HttpEndpoint {
    param([string]$Uri)

    try {
        $response = Invoke-WebRequest -Uri $Uri -UseBasicParsing -TimeoutSec 4
        return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
    }
    catch {
        return $false
    }
}

function Wait-ForCondition {
    param(
        [scriptblock]$Condition,
        [string]$Description,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Condition) {
            Write-LauncherLog "$Description is ready."
            return
        }
        Start-Sleep -Seconds 3
    }
    throw "Timed out waiting for $Description."
}

try {
    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    $hasMutex = $mutex.WaitOne(0)
    if (-not $hasMutex) {
        exit 0
    }
    Set-Content -LiteralPath $logPath -Value "" -Encoding UTF8
    Write-LauncherLog "Launcher started."

    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker is not installed or is not available on PATH."
    }

    if (-not (Test-DockerEngine)) {
        $dockerDesktopCandidates = @(
            (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
            (Join-Path $env:LOCALAPPDATA "Docker\Docker Desktop.exe")
        )
        $dockerDesktop = $dockerDesktopCandidates |
            Where-Object { Test-Path -LiteralPath $_ } |
            Select-Object -First 1
        if (-not $dockerDesktop) {
            throw "Docker Desktop could not be found."
        }

        Write-LauncherLog "Starting Docker Desktop."
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden
        Wait-ForCondition -Condition { Test-DockerEngine } -Description "Docker Desktop" -TimeoutSeconds 240
    }

    Write-LauncherLog "Starting the application stack."
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $composeOutput = & docker compose --project-directory $projectDirectory up -d 2>&1
    $composeExitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorActionPreference
    $composeOutput | ForEach-Object { $_.ToString() } |
        Add-Content -LiteralPath $logPath -Encoding UTF8
    if ($composeExitCode -ne 0) {
        throw "Docker Compose failed with exit code $composeExitCode."
    }

    Wait-ForCondition -Condition { Test-HttpEndpoint $apiHealthUrl } -Description "API" -TimeoutSeconds 180
    Wait-ForCondition -Condition { Test-HttpEndpoint $appUrl } -Description "website" -TimeoutSeconds 180

    if (-not $NoBrowser) {
        Start-Process $appUrl
    }
    Write-LauncherLog "Application opened successfully."
}
catch {
    Write-LauncherLog "ERROR: $($_.Exception.Message)"
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
        "Video Clip Factory could not start.`n`n$($_.Exception.Message)`n`nDetails: $logPath",
        "Video Clip Factory",
        "OK",
        "Error"
    ) | Out-Null
    exit 1
}
finally {
    if ($hasMutex) {
        $mutex.ReleaseMutex()
    }
    $mutex.Dispose()
}
