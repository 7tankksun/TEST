#Requires -Version 5.1
# OPIC 폴더의 .docx -> public/data/materials.json  (Node 없이 동일 결과)
# 사용:  .\build-content.ps1
$ErrorActionPreference = "Stop"
$ScriptDir = $PSScriptRoot
$Root = Split-Path $ScriptDir -Parent
$OpicDir = (Resolve-Path (Join-Path $Root "..")).Path
$OutDir = Join-Path $Root "public\data"
$OutFile = Join-Path $OutDir "materials.json"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Unescape-XmlText([string]$s) {
  if ([string]::IsNullOrEmpty($s)) { return "" }
  $s = $s.Replace("&amp;", "&").Replace("&lt;", "<").Replace("&gt;", ">")
  $s = $s.Replace([string]::Concat("&", "apos;"), "'")
  $s = $s.Replace([string]::Concat("&", "quot;"), '"')
  $s = [regex]::Replace($s, "&#x([0-9A-Fa-f]+);", {
      param($m)
      [System.Char]::ConvertFromUtf32([Convert]::ToInt32($m.Groups[1].Value, 16))
  })
  $s = [regex]::Replace($s, "&#([0-9]+);", { param($m) [char][int]$m.Groups[1].Value })
  return $s
}

function Get-DocxParagraphs([string]$DocxPath) {
  $zip = [System.IO.Compression.ZipFile]::OpenRead($DocxPath)
  try {
    $e = $zip.Entries | Where-Object { $_.FullName -eq "word/document.xml" }
    if (-not $e) { throw "word/document.xml 없음" }
    $sr = New-Object System.IO.StreamReader($e.Open(), [System.Text.Encoding]::UTF8)
    try { $xml = $sr.ReadToEnd() } finally { $sr.Close() }
  } finally { $zip.Dispose() }

  $out = [System.Collections.Generic.List[string]]::new()
  $parts = [regex]::Split($xml, "</w:p>", [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
  foreach ($part in $parts) {
    $texts = [System.Collections.Generic.List[string]]::new()
    $cm = [regex]::Matches($part, "<w:t[^>]*>([^<]*)</w:t>")
    foreach ($m in $cm) { $texts.Add((Unescape-XmlText $m.Groups[1].Value)) }
    $line = ($texts -join "").Replace("`r", "").Replace([char]0x00A0, [char]32).Trim()
    if ($line.Length -gt 0) { $out.Add($line) }
  }
  return ,$out.ToArray()
}

function Get-Slugify([string]$name) {
  $base = [System.IO.Path]::GetFileNameWithoutExtension($name).ToLower()
  $slug = $base -creplace "[^a-z0-9\uac00-\ud7af]+", "-"
  $slug = $slug.Trim("-")
  if ([string]::IsNullOrEmpty($slug)) { "doc" } else { $slug }
}

function Get-GuessTitle($paragraphs, [string]$filename) {
  if ($null -ne $paragraphs -and $paragraphs.Count -gt 0) {
    $p0 = $paragraphs[0]
    if ($p0.Length -gt 0 -and $p0.Length -lt 120) { return $p0 }
  }
  return [System.IO.Path]::GetFileNameWithoutExtension($filename)
}

function Build-QuestionCards([string]$fileId, [string[]]$paragraphs) {
  $rxStart = "^(?i)describe|talk about|can you|tell me|what |how |when |where |who "
  $all = [System.Collections.Generic.List[object]]::new()
  for ($i = 0; $i -lt $paragraphs.Count; $i++) {
    $t = $paragraphs[$i]
    if ($t.Length -lt 15) { continue }
    $okQ = $t -match "\?" -or $t -cmatch $rxStart
    if (-not $okQ) { continue }

    $after = [System.Collections.Generic.List[string]]::new()
    $maxJ = [Math]::Min($i + 8, $paragraphs.Count)
    for ($j = $i + 1; $j -lt $maxJ; $j++) {
      $p = $paragraphs[$j]
      if ($p.Length -lt 20) { continue }
      if ($p -cmatch "^\d+[\.\)]\s*|[Qq]\d" -and $p.Length -lt 200 -and $p -match "\?") { break }
      $after.Add($p)
      if ($after.Count -ge 2) { break }
    }
    if ($after.Count -eq 0) {
      if ($i + 1 -lt $paragraphs.Count -and $paragraphs[$i + 1].Length -gt 30) {
        $after.Add($paragraphs[$i + 1])
      }
    }
    if ($after.Count -gt 0) {
      $q = $t
      if ($q.Length -gt 400) { $q = $q.Substring(0, 400) + [char]0x2026 }
      $all.Add([pscustomobject]@{
        id         = [guid]::NewGuid().ToString()
        fileId     = $fileId
        q          = $q
        answerHints = @($after)
      })
    }
  }
  $seen = @{}
  $deduped = [System.Collections.Generic.List[object]]::new()
  foreach ($c in $all) {
    $k = if ($c.q.Length -ge 80) { $c.q.Substring(0, 80) } else { $c.q }
    if ($seen.ContainsKey($k)) { continue }
    $seen[$k] = $true
    $deduped.Add($c)
  }
  return ,$deduped.ToArray()
}

# --- main ---
# 한글 meta는 UTF-8로 저장한 site-meta.json에서만 읽습니다. (.ps1을 CP1252로 읽는 PS 5.1에서
# 스크립트 내부 한글 리터럴이 깨지는 문제를 피합니다.)
$metaPath = Join-Path $ScriptDir "site-meta.json"
if (-not (Test-Path -LiteralPath $metaPath)) { throw "없습니다: $metaPath" }
$metaFromFile = Get-Content -LiteralPath $metaPath -Encoding UTF8 -Raw | ConvertFrom-Json

$null = New-Item -ItemType Directory -Path $OutDir -Force
$docxList = Get-ChildItem -Path $OpicDir -Filter "*.docx" -File
if ($docxList.Count -eq 0) { Write-Warning "DOCX가 없습니다: $OpicDir" }

$files = [System.Collections.Generic.List[object]]::new()
$allCards = [System.Collections.Generic.List[object]]::new()
$ix = 0
foreach ($item in $docxList) {
  try { $paras = Get-DocxParagraphs $item.FullName } catch {
    Write-Warning "읽기 실패: $($item.Name) — $($_.Exception.Message)"
    continue
  }
  $id = (Get-Slugify $item.Name) + "-$ix"
  $ix++
  $title = Get-GuessTitle $paras $item.Name
  $files.Add([pscustomobject]@{ id = $id; sourceFile = $item.Name; title = $title; paragraphs = $paras })
  foreach ($c in (Build-QuestionCards $id $paras)) { $allCards.Add($c) }
}

$payload = [pscustomobject]@{
  meta = [pscustomobject]@{
    levelGoal   = [int]$metaFromFile.levelGoal
    blurb       = [string]$metaFromFile.blurb
    tips        = @($metaFromFile.tips)
    generatedAt = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ss.fffZ")
  }
  files         = $files
  questionCards = $allCards
}

$json = $payload | ConvertTo-Json -Depth 30
[System.IO.File]::WriteAllText($OutFile, $json, [System.Text.UTF8Encoding]::new($false))

Write-Host "Wrote: $OutFile"
Write-Host "Files: $($files.Count), question cards: $($allCards.Count)"
