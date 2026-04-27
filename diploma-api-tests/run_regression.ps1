param(
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

Set-Location -Path $PSScriptRoot

function Parse-DotEnvFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path
    )

    $map = @{}
    if (-not (Test-Path -Path $Path)) {
        return $map
    }

    foreach ($line in Get-Content -Path $Path -ErrorAction Stop) {
        $trimmed = $line.Trim()
        if ($trimmed.Length -eq 0) { continue }
        if ($trimmed.StartsWith('#')) { continue }

        $idx = $trimmed.IndexOf('=')
        if ($idx -lt 1) { continue }

        $key = $trimmed.Substring(0, $idx).Trim()
        $value = $trimmed.Substring($idx + 1).Trim()

        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            if ($value.Length -ge 2) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        if ($key.Length -gt 0 -and -not $map.ContainsKey($key)) {
            $map[$key] = $value
        }
    }
    return $map
}

function Get-ConfigValue {
    param(
        [Parameter(Mandatory = $true)][hashtable]$DotEnv,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $envValue = [System.Environment]::GetEnvironmentVariable($Name)
    if ($null -ne $envValue -and $envValue.ToString().Trim().Length -gt 0) {
        return $envValue.ToString()
    }
    if ($DotEnv.ContainsKey($Name) -and $DotEnv[$Name].ToString().Trim().Length -gt 0) {
        return $DotEnv[$Name].ToString()
    }
    return $null
}

function Assert-RegressionConfigPresent {
    $envPath = Join-Path $PSScriptRoot '.env'
    $examplePath = Join-Path $PSScriptRoot '.env.example'
    $dotEnv = Parse-DotEnvFile -Path $envPath

    $baseUrl = Get-ConfigValue -DotEnv $dotEnv -Name 'BASE_URL'
    $password = Get-ConfigValue -DotEnv $dotEnv -Name 'WEKAN_PASSWORD'
    $username = Get-ConfigValue -DotEnv $dotEnv -Name 'WEKAN_USERNAME'
    $email = Get-ConfigValue -DotEnv $dotEnv -Name 'WEKAN_EMAIL'

    $missing = @()
    if (-not $baseUrl) { $missing += 'BASE_URL' }
    if (-not $password) { $missing += 'WEKAN_PASSWORD' }
    if ((-not $username) -and (-not $email)) { $missing += 'WEKAN_USERNAME or WEKAN_EMAIL' }

    if ($missing.Count -gt 0) {
        Write-Host ''
        Write-Host 'Regression run preflight failed: configuration is incomplete.' -ForegroundColor Red
        Write-Host ('Missing: ' + ($missing -join ', ')) -ForegroundColor Red
        Write-Host ''

        if (-not (Test-Path -Path $envPath)) {
            Write-Host ('No .env found at: ' + $envPath) -ForegroundColor Yellow
            if (Test-Path -Path $examplePath) {
                Write-Host 'Create it from the template:' -ForegroundColor Yellow
                Write-Host ('  Copy-Item "' + $examplePath + '" "' + $envPath + '"')
            } else {
                Write-Host 'Create a .env file in diploma-api-tests/.' -ForegroundColor Yellow
            }
        } else {
            Write-Host ('Found .env at: ' + $envPath) -ForegroundColor Yellow
            Write-Host 'Fill in required variables (do not commit secrets):' -ForegroundColor Yellow
        }

        Write-Host ''
        Write-Host 'Required variables:'
        Write-Host '  BASE_URL='
        Write-Host '  WEKAN_USERNAME=  (or WEKAN_EMAIL=)'
        Write-Host '  WEKAN_PASSWORD='
        Write-Host ''
        Write-Host 'You can also set them as environment variables instead of using .env.'
        Write-Host ''
        exit 2
    }
}

Assert-RegressionConfigPresent

$pythonCandidates = @(
    (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    (Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\python.exe'),
    'python'
)

$python = $null
foreach ($candidate in $pythonCandidates) {
    if ($candidate -eq 'python') {
        $python = $candidate
        break
    }
    if (Test-Path -Path $candidate) {
        $python = $candidate
        break
    }
}

$reportsDir = Join-Path $PSScriptRoot 'reports\regression'
New-Item -ItemType Directory -Force -Path $reportsDir | Out-Null

$junitPath = Join-Path $reportsDir 'junit.xml'
$summaryPath = Join-Path $reportsDir 'summary.txt'
$summaryScript = Join-Path $PSScriptRoot 'tools\junit_summary.py'

$args = @(
    '-m', 'pytest',
    '-m', 'regression',
    '--junitxml', $junitPath
)

if ($Quiet) {
    $args += '-q'
}

& $python @args
$pytestExitCode = $LASTEXITCODE

if ((Test-Path -Path $junitPath) -and (Test-Path -Path $summaryScript)) {
    try {
        & $python $summaryScript --junit $junitPath --out $summaryPath | Out-Host
    } catch {
        Write-Warning ('Failed to render JUnit summary: ' + $_.Exception.Message)
    }
}

exit $pytestExitCode
