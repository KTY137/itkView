[CmdletBinding()]
param(
    [switch]$NoBrowser,
    [switch]$ForcePortCleanup,
    [switch]$EnableProductionReads
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$BackendPort = 8000
$FrontendPort = 5173
$BindAddress = "127.0.0.1"
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDirectory = Join-Path $RepoRoot "backend"
$FrontendDirectory = Join-Path $RepoRoot "frontend"
$BackendPython = Join-Path $BackendDirectory ".venv\Scripts\python.exe"
$ViteScript = Join-Path $FrontendDirectory "node_modules\vite\bin\vite.js"
$FrontendUrl = "http://${BindAddress}:${FrontendPort}/"
$BackendHealthUrl = "http://${BindAddress}:${BackendPort}/health"
$ProxyHealthUrl = "${FrontendUrl}health"
$LogDirectory = Join-Path ([System.IO.Path]::GetTempPath()) "itkflow-dev"
$LocalDataDirectory = [Environment]::GetFolderPath(
    [Environment+SpecialFolder]::LocalApplicationData
)
if ([string]::IsNullOrWhiteSpace($LocalDataDirectory)) {
    throw "Windows did not provide a LocalApplicationData directory."
}
$CredentialDirectory = Join-Path $LocalDataDirectory "itkflow"
$CredentialKeyPath = Join-Path $CredentialDirectory "pdb-credential.key"
$RunStamp = Get-Date -Format "yyyyMMdd-HHmmss"
$ExpectedPdbInstance = "offline"
if ($EnableProductionReads) {
    $ExpectedPdbInstance = "production"
}

function Get-ListeningProcessIds {
    param([Parameter(Mandatory = $true)][int]$Port)

    if ($null -ne (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
        $connections = @(Get-NetTCPConnection `
            -State Listen `
            -LocalPort $Port `
            -ErrorAction SilentlyContinue)
        return @($connections |
            Select-Object -ExpandProperty OwningProcess -Unique |
            Sort-Object)
    }

    # Compatibility fallback for systems without the NetTCPIP module. Match
    # the zero remote endpoint so localized TCP state names do not matter.
    $escapedPort = [regex]::Escape([string]$Port)
    $pattern = "^\s*TCP\s+\S+:${escapedPort}\s+(?:0\.0\.0\.0:0|\[::\]:0)\s+\S+\s+(\d+)\s*$"
    $ownerProcessIds = @()
    foreach ($line in (& "$env:SystemRoot\System32\netstat.exe" -ano -p tcp)) {
        if ($line -match $pattern) {
            $ownerProcessIds += [int]$matches[1]
        }
    }
    return @($ownerProcessIds | Sort-Object -Unique)
}

function Get-ProcessDetails {
    param([Parameter(Mandatory = $true)][int]$OwnerProcessId)

    $processName = "unknown"
    $executablePath = ""
    $commandLine = ""
    $parentProcessId = 0
    $parentExecutablePath = ""
    $parentCommandLine = ""

    $process = Get-Process -Id $OwnerProcessId -ErrorAction SilentlyContinue
    if ($null -ne $process) {
        $processName = $process.ProcessName
        try {
            $executablePath = [string]$process.Path
        }
        catch {
            $executablePath = ""
        }
    }

    try {
        $cimProcess = Get-CimInstance `
            -ClassName Win32_Process `
            -Filter "ProcessId = $OwnerProcessId" `
            -ErrorAction Stop
        if ($null -ne $cimProcess) {
            $commandLine = [string]$cimProcess.CommandLine
            $parentProcessId = [int]$cimProcess.ParentProcessId
            if ([string]::IsNullOrWhiteSpace($executablePath)) {
                $executablePath = [string]$cimProcess.ExecutablePath
            }

            if ($parentProcessId -gt 0) {
                $parentProcess = Get-CimInstance `
                    -ClassName Win32_Process `
                    -Filter "ProcessId = $parentProcessId" `
                    -ErrorAction SilentlyContinue
                if ($null -ne $parentProcess) {
                    $parentExecutablePath = [string]$parentProcess.ExecutablePath
                    $parentCommandLine = [string]$parentProcess.CommandLine
                }
            }
        }
    }
    catch {
        # An inaccessible command line is treated as an unknown process below.
    }

    return [pscustomobject]@{
        Id = $OwnerProcessId
        Name = $processName
        ExecutablePath = $executablePath
        CommandLine = $commandLine
        ParentId = $parentProcessId
        ParentExecutablePath = $parentExecutablePath
        ParentCommandLine = $parentCommandLine
    }
}

function Test-ItkFlowListener {
    param(
        [Parameter(Mandatory = $true)][int]$Port,
        [Parameter(Mandatory = $true)]$Details
    )

    $normalizedCommandLine = ([string]$Details.CommandLine).ToLowerInvariant()
    $normalizedExecutablePath = ([string]$Details.ExecutablePath).ToLowerInvariant()
    $normalizedParentCommandLine = ([string]$Details.ParentCommandLine).ToLowerInvariant()
    $normalizedParentExecutablePath = ([string]$Details.ParentExecutablePath).ToLowerInvariant()

    if ($Port -eq $BackendPort) {
        $expectedPython = $BackendPython.ToLowerInvariant()
        return (
            ($normalizedExecutablePath -eq $expectedPython -or
                $normalizedCommandLine.Contains($expectedPython) -or
                $normalizedParentExecutablePath -eq $expectedPython -or
                $normalizedParentCommandLine.Contains($expectedPython)) -and
            $normalizedCommandLine.Contains("uvicorn") -and
            $normalizedCommandLine.Contains("app.main:create_app")
        )
    }

    if ($Port -eq $FrontendPort) {
        $expectedViteScript = $ViteScript.ToLowerInvariant()
        return (
            $normalizedCommandLine.Contains($expectedViteScript) -and
            $normalizedCommandLine.Contains("vite")
        )
    }

    return $false
}

function Stop-ProcessTreeById {
    param([Parameter(Mandatory = $true)][int]$TargetProcessId)

    if ($TargetProcessId -le 4 -or $TargetProcessId -eq $PID) {
        throw "Refusing to stop protected PID $TargetProcessId."
    }
    if ($null -eq (Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue)) {
        return
    }

    $taskkillPath = Join-Path $env:SystemRoot "System32\taskkill.exe"
    Start-Process `
        -FilePath $taskkillPath `
        -ArgumentList @("/PID", [string]$TargetProcessId, "/T", "/F") `
        -WindowStyle Hidden `
        -Wait | Out-Null

    $deadline = [DateTime]::UtcNow.AddSeconds(3)
    do {
        if ($null -eq (Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue)) {
            return
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)

    try {
        Stop-Process -Id $TargetProcessId -Force -ErrorAction Stop
    }
    catch {
        if ($null -ne (Get-Process -Id $TargetProcessId -ErrorAction SilentlyContinue)) {
            throw
        }
    }
}

function Stop-DevPortListeners {
    $listeners = @()

    foreach ($port in @($BackendPort, $FrontendPort)) {
        foreach ($ownerProcessId in @(Get-ListeningProcessIds -Port $port)) {
            if ($ownerProcessId -eq $PID -or $ownerProcessId -le 4) {
                throw "Refusing to stop protected PID $ownerProcessId on port $port."
            }

            $details = Get-ProcessDetails -OwnerProcessId $ownerProcessId
            $listeners += [pscustomobject]@{
                Port = $port
                Details = $details
                IsItkFlow = Test-ItkFlowListener -Port $port -Details $details
            }
        }
    }

    $unknownListeners = @($listeners | Where-Object { -not $_.IsItkFlow })
    if ($unknownListeners.Count -gt 0 -and -not $ForcePortCleanup) {
        $summary = @($unknownListeners | ForEach-Object {
            "port $($_.Port): PID $($_.Details.Id) ($($_.Details.Name))"
        }) -join "; "
        throw (
            "A non-itkFlow process owns a reserved dev port: $summary. " +
            "Stop it manually, or rerun with -ForcePortCleanup if it is safe to terminate."
        )
    }

    $stoppedProcessIds = @{}
    foreach ($listener in $listeners) {
        $ownerProcessId = [int]$listener.Details.Id
        if ($stoppedProcessIds.ContainsKey($ownerProcessId)) {
            continue
        }

        Write-Host (
            "Stopping listener on port {0}: PID {1} ({2})" -f
            $listener.Port,
            $ownerProcessId,
            $listener.Details.Name
        )

        $currentOwners = @(Get-ListeningProcessIds -Port $listener.Port)
        if ($currentOwners -notcontains $ownerProcessId) {
            Write-Host "PID $ownerProcessId no longer owns port $($listener.Port); skipping it."
            continue
        }
        if (-not $ForcePortCleanup) {
            $currentDetails = Get-ProcessDetails -OwnerProcessId $ownerProcessId
            if (-not (Test-ItkFlowListener -Port $listener.Port -Details $currentDetails)) {
                throw "PID $ownerProcessId changed identity before cleanup; refusing to stop it."
            }
        }

        Stop-ProcessTreeById -TargetProcessId $ownerProcessId
        $stoppedProcessIds[$ownerProcessId] = $true
    }

    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $remaining = @()
        foreach ($port in @($BackendPort, $FrontendPort)) {
            $remaining += @(Get-ListeningProcessIds -Port $port)
        }
        if ($remaining.Count -eq 0) {
            return
        }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Timed out while waiting for ports $BackendPort and $FrontendPort to become free."
}

function Wait-ForHttpEndpoint {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $lastFailure = "no response"
    do {
        try {
            $response = Invoke-WebRequest `
                -Uri $Uri `
                -UseBasicParsing `
                -TimeoutSec 2 `
                -ErrorAction Stop
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        }
        catch {
            # The process may still be starting. Retry until the deadline.
            $lastFailure = $_.Exception.Message
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)

    throw (
        "$Description did not become ready at $Uri within $TimeoutSeconds seconds. " +
        "Last check: $lastFailure"
    )
}

function Protect-PdbCredentialKeyFile {
    try {
        $currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User
        $existingAcl = Get-Acl -LiteralPath $CredentialKeyPath
        $existingRules = @($existingAcl.GetAccessRules(
            $true,
            $true,
            [Security.Principal.SecurityIdentifier]
        ))
        $alreadyRestricted = (
            $existingAcl.AreAccessRulesProtected -and
            $existingAcl.Owner -eq $currentSid.Translate(
                [Security.Principal.NTAccount]
            ).Value -and
            $existingRules.Count -eq 1 -and
            $existingRules[0].IdentityReference -eq $currentSid -and
            $existingRules[0].AccessControlType -eq (
                [Security.AccessControl.AccessControlType]::Allow
            ) -and
            (($existingRules[0].FileSystemRights -band (
                [Security.AccessControl.FileSystemRights]::FullControl
            )) -eq [Security.AccessControl.FileSystemRights]::FullControl)
        )
        if ($alreadyRestricted) {
            return
        }
        $acl = [Security.AccessControl.FileSecurity]::new()
        $acl.SetOwner($currentSid)
        $acl.SetAccessRuleProtection($true, $false)
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $currentSid,
            [Security.AccessControl.FileSystemRights]::FullControl,
            [Security.AccessControl.AccessControlType]::Allow
        )
        $acl.AddAccessRule($rule)
        Set-Acl -LiteralPath $CredentialKeyPath -AclObject $acl
    }
    catch {
        throw "Could not restrict access to the local PDB credential key file: $($_.Exception.Message)"
    }
}

function Get-OrCreate-PdbCredentialEncryptionKey {
    # The stable master key lives outside the repository. It encrypts each
    # account's personal PDB codes; it is never printed or written to a log.
    if (Test-Path -LiteralPath $CredentialKeyPath -PathType Leaf) {
        $storedKey = (Get-Content -LiteralPath $CredentialKeyPath -Raw).Trim()
        try {
            $padded = $storedKey.Replace("-", "+").Replace("_", "/")
            $padded += "=" * ((4 - ($padded.Length % 4)) % 4)
            $decoded = [Convert]::FromBase64String($padded)
        }
        catch {
            throw "The local PDB credential key file is invalid: '$CredentialKeyPath'."
        }
        if ($decoded.Length -ne 32) {
            throw "The local PDB credential key must encode exactly 32 bytes."
        }
        Protect-PdbCredentialKeyFile
        return $storedKey
    }

    New-Item -ItemType Directory -Path $CredentialDirectory -Force | Out-Null
    $keyBytes = New-Object byte[] 32
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $random.GetBytes($keyBytes)
    }
    finally {
        $random.Dispose()
    }
    $newKey = [Convert]::ToBase64String($keyBytes).TrimEnd("=").Replace("+", "-").Replace("/", "_")
    [IO.File]::WriteAllText($CredentialKeyPath, $newKey, [Text.Encoding]::ASCII)

    # Keep only the current Windows account on the newly-created key file.
    Protect-PdbCredentialKeyFile
    return $newKey
}

function Start-Backend {
    param(
        [Parameter(Mandatory = $true)][string]$StandardOutputLog,
        [Parameter(Mandatory = $true)][string]$StandardErrorLog
    )

    # Keep the inert test target by default. Production reads require the
    # explicit launcher switch; PDB write-test opt-in stays disabled either way.
    $credentialEncryptionKey = Get-OrCreate-PdbCredentialEncryptionKey
    $backendEnvironment = @{
        ITKFLOW_PDB_INSTANCE = $ExpectedPdbInstance
        ITKFLOW_ALLOW_PRODUCTION = if ($EnableProductionReads) { "true" } else { "false" }
        ITKFLOW_ALLOW_PDB_WRITES = "false"
        ITKFLOW_PDB_WRITE_SCOPE = "dummy_only"
        ITKFLOW_PDB_CREDENTIAL_ENCRYPTION_KEY = $credentialEncryptionKey
        # This launcher deliberately starts no outbox worker, so the API fires
        # due reminders itself; otherwise they would never fire in dev. Local
        # only: reminders touch the local database and the configured webhook,
        # never the PDB (docs/11).
        ITKFLOW_REMINDER_SCHEDULER = "app"
    }
    $previousEnvironment = @{}

    try {
        foreach ($name in $backendEnvironment.Keys) {
            $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
            [Environment]::SetEnvironmentVariable(
                $name,
                [string]$backendEnvironment[$name],
                "Process"
            )
        }

        $quotedBackendDirectory = '"' + $BackendDirectory + '"'
        return Start-Process `
            -FilePath $BackendPython `
            -ArgumentList @(
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--app-dir",
                $quotedBackendDirectory,
                "--host",
                $BindAddress,
                "--port",
                [string]$BackendPort
            ) `
            -WorkingDirectory $BackendDirectory `
            -WindowStyle Hidden `
            -RedirectStandardOutput $StandardOutputLog `
            -RedirectStandardError $StandardErrorLog `
            -PassThru
    }
    finally {
        foreach ($name in $backendEnvironment.Keys) {
            $previousValue = $previousEnvironment[$name]
            [Environment]::SetEnvironmentVariable($name, $previousValue, "Process")
        }
    }
}

function Stop-StartedProcessTree {
    param([Parameter(Mandatory = $true)]$StartedProcess)

    try {
        $startedProcessId = [int]$StartedProcess.Id
        Stop-ProcessTreeById -TargetProcessId $startedProcessId
    }
    catch {
        Write-Warning "Could not stop started PID $($StartedProcess.Id): $($_.Exception.Message)"
    }
}

if (-not (Test-Path -LiteralPath $BackendPython -PathType Leaf)) {
    throw (
        "Backend environment not found at '$BackendPython'. " +
        "Create it and install the project as documented in README.md."
    )
}
if (-not (Test-Path -LiteralPath $ViteScript -PathType Leaf)) {
    throw (
        "Frontend dependencies not found at '$ViteScript'. " +
        "Run 'npm.cmd install' in '$FrontendDirectory' first."
    )
}

if ($EnableProductionReads) {
    # Fail before stopping a healthy server. A partial optional installation
    # otherwise looks like a remote network outage when a user connects codes.
    & $BackendPython -c "import itkdb" 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw (
            "PDB client dependencies are incomplete. In '$BackendDirectory', run " +
            "'uv sync --extra pdb --extra dev' and start itkFlow again."
        )
    }
}

$nodeCommand = Get-Command node.exe -ErrorAction SilentlyContinue
if ($null -eq $nodeCommand) {
    throw "Node.js was not found on PATH. Install Node.js before starting itkFlow."
}

New-Item -ItemType Directory -Path $LogDirectory -Force | Out-Null
$backendOutputLog = Join-Path $LogDirectory "backend-$RunStamp.out.log"
$backendErrorLog = Join-Path $LogDirectory "backend-$RunStamp.err.log"
$frontendOutputLog = Join-Path $LogDirectory "frontend-$RunStamp.out.log"
$frontendErrorLog = Join-Path $LogDirectory "frontend-$RunStamp.err.log"
$backendProcess = $null
$frontendProcess = $null

try {
    Stop-DevPortListeners

    if ($EnableProductionReads) {
        Write-Host "PDB mode: production reads enabled; the outbox worker is not started."
    }
    else {
        Write-Host "PDB mode: offline (no PDB configured); remote sync is unavailable."
    }

    Write-Host "Starting itkFlow backend on ${BindAddress}:${BackendPort} ..."
    $backendProcess = Start-Backend `
        -StandardOutputLog $backendOutputLog `
        -StandardErrorLog $backendErrorLog
    Wait-ForHttpEndpoint `
        -Uri $BackendHealthUrl `
        -TimeoutSeconds 30 `
        -Description "The itkFlow backend"

    $health = Invoke-RestMethod `
        -Uri $BackendHealthUrl `
        -TimeoutSec 3 `
        -ErrorAction Stop
    if (
        $health.status -ne "ok" -or
        $health.pdb_instance -ne $ExpectedPdbInstance -or
        $health.pdb_write_scope -ne "dummy_only"
    ) {
        throw "Backend health returned an unexpected or unsafe configuration."
    }

    Write-Host "Starting itkFlow frontend on ${BindAddress}:${FrontendPort} ..."
    $quotedViteScript = '"' + $ViteScript + '"'
    $frontendProcess = Start-Process `
        -FilePath $nodeCommand.Source `
        -ArgumentList @(
            $quotedViteScript,
            "--host",
            $BindAddress,
            "--port",
            [string]$FrontendPort,
            "--strictPort"
        ) `
        -WorkingDirectory $FrontendDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $frontendOutputLog `
        -RedirectStandardError $frontendErrorLog `
        -PassThru

    Wait-ForHttpEndpoint `
        -Uri $FrontendUrl `
        -TimeoutSeconds 30 `
        -Description "The itkFlow frontend"
    Wait-ForHttpEndpoint `
        -Uri $ProxyHealthUrl `
        -TimeoutSeconds 30 `
        -Description "The itkFlow frontend proxy"

    Write-Host ""
    Write-Host "itkFlow is ready: $FrontendUrl" -ForegroundColor Green
    Write-Host "Backend health: $BackendHealthUrl"
    Write-Host "Backend PID: $($backendProcess.Id); frontend PID: $($frontendProcess.Id)"
    Write-Host "Logs: $LogDirectory"

    if (-not $NoBrowser) {
        try {
            Start-Process $FrontendUrl | Out-Null
        }
        catch {
            Write-Warning "The browser could not be opened automatically. Open $FrontendUrl manually."
        }
    }
}
catch {
    $failureMessage = $_.Exception.Message

    if ($null -ne $frontendProcess) {
        Stop-StartedProcessTree -StartedProcess $frontendProcess
    }
    if ($null -ne $backendProcess) {
        Stop-StartedProcessTree -StartedProcess $backendProcess
    }

    try {
        Stop-DevPortListeners
    }
    catch {
        Write-Warning "Cleanup after the startup failure was incomplete: $($_.Exception.Message)"
    }

    Write-Host ""
    Write-Host "itkFlow startup failed: $failureMessage" -ForegroundColor Red
    Write-Host "Backend logs: $backendOutputLog and $backendErrorLog"
    Write-Host "Frontend logs: $frontendOutputLog and $frontendErrorLog"
    exit 1
}
