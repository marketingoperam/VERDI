#!/usr/bin/env pwsh
# Updates verdi-connector-api env on Render and triggers a deploy.
# Usage:
#   $env:RENDER_API_KEY = "rnd_...."
#   $env:TELEGRAM_API_HASH = "from ShadowChat .env LISTENER_API_HASH"
#   pwsh -File .\scripts\render_set_andf1n_env.ps1

$ErrorActionPreference = "Stop"

if (-not $env:RENDER_API_KEY) {
  Write-Error "Set RENDER_API_KEY first (Render Dashboard → Account Settings → API Keys)."
}
if (-not $env:TELEGRAM_API_HASH) {
  Write-Error "Set TELEGRAM_API_HASH (same as LISTENER_API_HASH in shadowchat .env)."
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

$b64File = Join-Path $PSScriptRoot "..\.telegram-sessions\listener_main.b64.txt"
$sessionPath = Join-Path $PSScriptRoot "..\.telegram-sessions\listener_main.session"
if (Test-Path $b64File) {
  $b64 = (Get-Content -Raw $b64File).Trim()
} elseif (Test-Path $sessionPath) {
  $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $sessionPath)))
} else {
  $shadowSession = "C:\Users\Karim\Desktop\Verdi\Клонер чатов\shadowchat\sessions\listener_main.session"
  if (-not (Test-Path $shadowSession)) {
    Write-Error "listener_main session not found. Export to .telegram-sessions/ or shadowchat/sessions/."
  }
  $b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Resolve-Path $shadowSession)))
}

$vars = @{
  TELEGRAM_API_HASH      = $env:TELEGRAM_API_HASH
  TELEGRAM_API_ID        = "30268202"
  TELEGRAM_SESSION_B64   = $b64
  TELEGRAM_USE_STUB      = "false"
  TELEGRAM_SESSION       = "listener_main"
  TELEGRAM_SYNC_ON_START = "true"
  CORS_ORIGIN            = "https://verdi-connector-web.onrender.com"
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
Write-Host "Watch logs for: Telegram worker ready @andf1n"
