$ErrorActionPreference = "Stop"

# Run this from an activated project virtual environment on the machine hosting Ollama.
if (-not $env:VIRTUAL_ENV) {
    throw "Activate the project's Python virtual environment first (VIRTUAL_ENV is not set)."
}
if (-not $env:OLLAMA_MODEL) {
    throw "Set OLLAMA_MODEL to the exact local model tag before running this check."
}

$baseUrl = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL.TrimEnd("/") } else { "http://127.0.0.1:11434" }
$configuredModel = $env:OLLAMA_MODEL
Write-Host "Checking Ollama endpoint: $baseUrl"
$tags = Invoke-RestMethod -Uri "$baseUrl/api/tags" -Method Get -TimeoutSec 8
$available = @($tags.models | ForEach-Object { $_.name })
if ($available -notcontains $configuredModel) {
    Write-Host "Configured model '$configuredModel' was not found."
    Write-Host "Available local tags: $($available -join ', ')"
    throw "No model was downloaded or changed. Set OLLAMA_MODEL to an available tag."
}
Write-Host "Found configured model: $configuredModel"

python -m pip install -r requirements-test.lock
if ($LASTEXITCODE -ne 0) { throw "Pinned test dependencies failed to install." }
python -m pip install --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw "Editable package install failed." }

# Keep live-model settings out of the ordinary regression suite so it remains deterministic.
$hadModel = Test-Path Env:OLLAMA_MODEL
$previousModel = $env:OLLAMA_MODEL
$hadFlag = Test-Path Env:RUN_OLLAMA_INTEGRATION
$previousFlag = $env:RUN_OLLAMA_INTEGRATION
try {
    Remove-Item Env:OLLAMA_MODEL -ErrorAction SilentlyContinue
    Remove-Item Env:RUN_OLLAMA_INTEGRATION -ErrorAction SilentlyContinue
    python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Regression suite failed." }

    $env:OLLAMA_MODEL = $configuredModel
    $env:RUN_OLLAMA_INTEGRATION = "1"
    python -m pytest -q tests/test_ollama_live.py
    if ($LASTEXITCODE -ne 0) { throw "Live Ollama integration test failed." }
}
finally {
    if ($hadModel) { $env:OLLAMA_MODEL = $previousModel }
    else { Remove-Item Env:OLLAMA_MODEL -ErrorAction SilentlyContinue }
    if ($hadFlag) { $env:RUN_OLLAMA_INTEGRATION = $previousFlag }
    else { Remove-Item Env:RUN_OLLAMA_INTEGRATION -ErrorAction SilentlyContinue }
}

Write-Host "Local checks passed. This does not constitute independent quality, safety, or production-readiness approval."
