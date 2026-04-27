#Requires -Version 5.1
# IT 뉴스 RSS -> public/data/it-news.json
# 작업 스케줄러: 매일 1회 이 스크립트만 실행해도 됩니다.
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Mjs = Join-Path $ScriptDir "fetch-it-news.mjs"
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
  throw "node 가 PATH 에 없습니다. Node.js 18+ 설치 후 다시 시도하세요."
}
& node $Mjs
Write-Host "Done."
