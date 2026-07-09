#!/usr/bin/env pwsh
# Adds outreach1 Telegram worker to verdi-connector-api on Render.
# Usage:
#   cd verdi-connector
#   $env:RENDER_API_KEY = "rnd_...."
#   pwsh -File .\scripts\render_set_outreach1_env.ps1

$ErrorActionPreference = "Stop"

if (-not $env:RENDER_API_KEY) {
  Write-Error "Set RENDER_API_KEY (Render Dashboard -> Account Settings -> API Keys)."
}

$headers = @{
  Authorization  = "Bearer $($env:RENDER_API_KEY)"
  Accept         = "application/json"
  "Content-Type" = "application/json"
}

Write-Host "Looking up verdi-connector-api service..."
$services = Invoke-RestMethod -Method GET -Uri "https://api.render.com/v1/services?limit=50" -Headers $headers
$api = $services | ForEach-Object { $_.service } | Where-Object { $_.name -eq "verdi-connector-api" } | Select-Object -First 1
if (-not $api) {
  $api = $services | Where-Object { $_.name -eq "verdi-connector-api" -or $_.service.name -eq "verdi-connector-api" } | Select-Object -First 1
  if ($api.service) { $api = $api.service }
}
if (-not $api -or -not $api.id) {
  Write-Error "Service verdi-connector-api not found for this API key."
}

$serviceId = $api.id
Write-Host "Found service id=$serviceId"

$stringCandidates = @(
  (Join-Path $PSScriptRoot "..\.telegram-sessions\outreach1.string.txt"),
  (Join-Path $PSScriptRoot "..\..\инвайтинг\.telegram-sessions\outreach1.string.txt")
)
$stringFile = $stringCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $stringFile) {
  Write-Error "outreach1.string.txt not found. Run: cd инвайтинг; .\.venv\Scripts\python.exe scripts\export_session_b64.py outreach1"
}
$sessionString = (Get-Content -Raw $stringFile).Trim()

$vars = @{
  TELEGRAM_SESSIONS               = "listener_main,tech_4,tech_5,tech_6,outreach1"
  TELEGRAM_SESSION_STRING_outreach1 = $sessionString
}

foreach ($key in $vars.Keys) {
  Write-Host "PUT env $key ..."
  $body = @{ value = [string]$vars[$key] } | ConvertTo-Json -Compress
  Invoke-RestMethod -Method PUT `
    -Uri "https://api.render.com/v1/services/$serviceId/env-vars/$key" `
    -Headers $headers `
    -Body $body | Out-Null
}

Write-Host "Triggering deploy..."
$deployBody = @{ clearCache = "do_not_clear" } | ConvertTo-Json -Compress
$deploy = Invoke-RestMethod -Method POST `
  -Uri "https://api.render.com/v1/services/$serviceId/deploys" `
  -Headers $headers `
  -Body $deployBody

Write-Host "OK. Deploy started: $($deploy.id)"
Write-Host "After deploy, inbox replies for outreach1 chats should work."
Write-Host "Do NOT run outreach1 locally and on Render at the same time (AuthKeyDuplicated)."
