# run.ps1 — loads .env and runs Ontolith
# Usage:
#   .\run.ps1                       → 5 dynamic variety tests
#   .\run.ps1 --scenario SEC_001    → single test
#   .\run.ps1 --all                 → all 27 static tests
#   .\run.ps1 --category security   → one category

# Load .env
Get-Content ".env" | ForEach-Object {
    if ($_ -match "^\s*([^#=][^=]*)=(.+)$") {
        $name = $matches[1].Trim()
        $value = $matches[2].Trim()
        [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
        $env:dummy = ""  # force refresh
    }
}

# Set explicitly to make sure they land
$env:AZURE_OPENAI_ENDPOINT = (Get-Content ".env" | Select-String "AZURE_OPENAI_ENDPOINT").ToString().Split("=",2)[1].Trim()
$env:AZURE_FOUNDRY_KEY      = (Get-Content ".env" | Select-String "AZURE_FOUNDRY_KEY").ToString().Split("=",2)[1].Trim()
$env:AZURE_FOUNDRY_MODEL    = (Get-Content ".env" | Select-String "AZURE_FOUNDRY_MODEL").ToString().Split("=",2)[1].Trim()
$env:OPENROUTER_API_KEY     = (Get-Content ".env" | Select-String "OPENROUTER_API_KEY").ToString().Split("=",2)[1].Trim()
$env:PYTHONPATH             = "src"

# Verify
Write-Host "OpenRouter: $($env:OPENROUTER_API_KEY.Substring(0,[Math]::Min(15,$env:OPENROUTER_API_KEY.Length)))"
Write-Host "Azure endpoint: $($env:AZURE_OPENAI_ENDPOINT)"
Write-Host "Foundry key set: $($env:AZURE_FOUNDRY_KEY.Length -gt 0)"

# Activate venv
.\.venv\Scripts\Activate.ps1

# Run
if ($args.Count -eq 0) {
    python -m ontolith run --dynamic-only --foundry
} else {
    python -m ontolith run @args --foundry
}