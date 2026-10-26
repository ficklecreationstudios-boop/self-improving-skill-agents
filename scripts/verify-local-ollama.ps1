$ErrorActionPreference = "Stop"

# Run this from an activated project virtual environment on the machine hosting Ollama.
if (-not $env:VIRTUAL_ENV) {
    throw "Activate the project's Python virtual environment first (VIRTUAL_ENV is not set)."
}
if (-not $env:OLLAMA_MODEL) {
    throw "Set OLLAMA_MODEL to the exact local model tag before running this check."
}

$baseUrl = if ($env:OLLAMA_BASE_URL) { $env:OLLAMA_BASE_URL.TrimEnd("/") } else { "http://127.0.0.1:11434" }
Write-Host "Checking Ollama endpoint: $baseUrl"
$tags = Invoke-RestMethod -Uri "$baseUrl/api/tags" -Method Get -TimeoutSec 8
$available = @($tags.models | ForEach-Object { $_.name })
if ($available -notcontains $env:OLLAMA_MODEL) {
    Write-Host "Configured model '$env:OLLAMA_MODEL' was not found."
    Write-Host "Available local tags: $($available -join ', ')"
    throw "No model was downloaded or changed. Set OLLAMA_MODEL to an available tag."
}
Write-Host "Found configured model: $env:OLLAMA_MODEL"

python -m pip install -r requirements-test.lock
if ($LASTEXITCODE -ne 0) { throw "Pinned test dependencies failed to install." }
python -m pip install --no-build-isolation -e .
if ($LASTEXITCODE -ne 0) { throw "Editable package install failed." }

python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Regression suite failed." }

$previousFlag = $env:RUN_OLLAMA_INTEGRATION
try {
    $env:RUN_OLLAMA_INTEGRATION = "1"
    python -m pytest -q tests/test_ollama_live.py
    if ($LASTEXITCODE -ne 0) { throw "Live Ollama integration test failed." }
}
finally {
    $env:RUN_OLLAMA_INTEGRATION = $previousFlag
}

Write-Host "Local checks passed. This does not constitute independent quality, safety, or production-readiness approval."
