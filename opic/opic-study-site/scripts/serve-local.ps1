#Requires -Version 5.1
# public 폴더를 로컬에서 열기 (Node → Python → 안내)
# 사용: .\serve-local.ps1   (선택) 환경변수 PORT=3333
$ScriptDir = $PSScriptRoot
$Root = Split-Path $ScriptDir -Parent
$Public = Join-Path $Root "public"
$Port = if ($env:PORT) { [int]$env:PORT } else { 3333 }
$nodeServe = Join-Path $ScriptDir "serve.mjs"

$node = $null
foreach ($c in @("node", "nodejs")) {
  $cmd = Get-Command $c -ErrorAction SilentlyContinue
  if ($cmd) { $node = $cmd.Source; break }
}
# 일반 Windows Node 설치 경로
$common = @(
  "$env:ProgramFiles\nodejs\node.exe"
  "${env:ProgramFiles(x86)}\nodejs\node.exe"
  "$env:LocalAppData\Programs\node\node.exe"
)
if (-not $node) {
  foreach ($p in $common) { if (Test-Path -LiteralPath $p) { $node = $p; break } }
}

if ($node) {
  Write-Host "Node로 서버: http://127.0.0.1:$Port/"
  & $node $nodeServe
  return
}

$py = $null
if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" }
elseif (Get-Command python -ErrorAction SilentlyContinue) { $py = "python" }
if ($py) {
  Write-Host "Python으로 정적 서버 (Node 없음): http://127.0.0.1:$Port/"
  Write-Host "public 폴더: $Public"
  Set-Location $Public
  if ($py -eq "py") { & py -3 -m http.server $Port } else { & $py -m http.server $Port }
  return
}

Write-Host "Node도 Python도 PATH에 없습니다."
Write-Host "1) https://nodejs.org LTS 설치 후 터미널을 다시 열거나"
Write-Host "2) Microsoft Store에서 Python 설치"
Write-Host "그다음 이 스크립트를 다시 실행하세요."
Write-Host "수동: public 폴더에서  python -m http.server $Port"
