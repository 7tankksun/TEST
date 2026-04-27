#Requires -Version 5.1
# 로컬: DOCX -> JSON 빌드 + (선택) IT 뉴스 RSS, 브라우저용 서버 기동
# 사용:  .\local-run.ps1
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
& (Join-Path $ScriptDir "scripts\build-content.ps1")
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
  try { & node (Join-Path $ScriptDir "scripts\fetch-it-news.mjs") } catch { Write-Warning "IT 뉴스 RSS 갱신 실패(무시하고 계속): $_" }
} else { Write-Warning "node 가 없어 IT 뉴스는 건너뜁니다. 나중에 scripts\update-it-news.ps1 을 실행하세요." }
& (Join-Path $ScriptDir "scripts\serve-local.ps1")
