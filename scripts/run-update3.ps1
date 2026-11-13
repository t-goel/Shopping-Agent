param(
    [ValidateSet('rules', 'claude')][string]$Agent = 'claude',
    [string]$Output = ''
)
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path $PSScriptRoot -Parent
Push-Location $repoRoot
try {
    $pythonLauncher = $null
    foreach ($candidate in @('py', 'python')) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            $pythonLauncher = $candidate
            break
        }
    }
    if (-not $pythonLauncher) {
        throw 'Install Python 3.12+ and ensure py or python is on PATH (see README).'
    }
    if ($Agent -eq 'claude' -and -not $env:ANTHROPIC_API_KEY) {
        $envPath = Join-Path $repoRoot '.env'
        if (Test-Path -LiteralPath $envPath) {
            foreach ($line in Get-Content -LiteralPath $envPath) {
                if ($line -match '^ANTHROPIC_API_KEY=(.+)$') {
                    $env:ANTHROPIC_API_KEY = $Matches[1].Trim().Trim('"').Trim("'")
                }
            }
        }
    }
    if (-not $Output) {
        $Output = 'results/' + $Agent + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.jsonl'
    }
    $taskPath = if ($Agent -eq 'rules') { 'data/tasks/harness' } else { 'data/tasks' }
    & $pythonLauncher eval.py run --agent $Agent --tasks $taskPath --repetitions 3 --seed 498 --max-calls 20 --timeout 60 --output $Output
    if ($LASTEXITCODE -ne 0) { throw 'Evaluation command failed; inspect the error above.' }
    & $pythonLauncher eval.py report $Output --markdown
    if ($LASTEXITCODE -ne 0) { throw 'Report generation failed.' }
} finally {
    Pop-Location
}
