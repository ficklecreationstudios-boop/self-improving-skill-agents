# Local Ollama verification (Windows)

The GitHub-hosted CI runner cannot reach the Ollama server on your PC. Run the following on the Windows machine where Ollama is running.

1. Open PowerShell in the repository and activate its virtual environment.
2. Set the exact model tag already installed locally. Example only:
   `$env:OLLAMA_MODEL = "qwen3:8b"`
3. If using the default local server, leave `OLLAMA_BASE_URL` unset. Otherwise set it explicitly.
4. Run `./scripts/verify-local-ollama.ps1`.

The script checks `/api/tags`, confirms the configured model exists, installs the pinned test/build dependencies into the **currently activated virtual environment**, runs the cross-platform regression suite locally, and enables the opt-in live inference test. It does not download a model, change model settings, alter skills, or apply proposals.

If this succeeds, preserve the command output and date as evidence for D2. It still does not satisfy the independent held-out quality/safety benchmark, OS-sandbox, or independent review gates.
