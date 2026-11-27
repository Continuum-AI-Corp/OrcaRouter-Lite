# Signs one Windows file for `tauri build` (bundle.windows.signCommand).
#
#   pwsh -NoProfile -File sign.ps1 -Setup          # once per job: fetch CodeSignTool (esigner mode)
#   pwsh -NoProfile -File sign.ps1 <file>          # what Tauri calls, once per file
#   pwsh -NoProfile -File sign.ps1 -Report         # after the build: what was signed
#
# ORCA_SIGN_MODE picks the signer:
#   esigner     release tags. SSL.com eSigner through CodeSignTool, with the
#               environment secrets ES_USERNAME, ES_PASSWORD, ES_CREDENTIAL_ID
#               and ES_TOTP_SECRET. Every call spends one signing from the
#               company's yearly eSigner allowance, shared with other products.
#   selfsigned  pull requests and manual runs. signtool with the throwaway
#               certificate whose thumbprint is in ORCA_SIGN_THUMBPRINT, so the
#               whole path (which files, verification, count) runs for free.
#
# ONLY .exe FILES ARE SIGNED. Tauri also asks for the NSIS plugin DLLs; those
# are only unpacked to a temp folder while the installer runs, SmartScreen
# never judges them, and signing them would spend five signings per release.
# What is signed: the app, the orca-engine sidecar, the uninstaller (Tauri
# names it *.tmp while makensis builds it) and the setup .exe.
#
# Each signed file is appended to $env:RUNNER_TEMP\orca-signed.txt so the
# workflow can print how many files went to the signer.
[CmdletBinding()]
param(
  [Parameter(Position = 0)] [string] $File,
  [switch] $Setup,
  [switch] $Report
)
$ErrorActionPreference = 'Stop'

# CodeSignTool, platform-independent build (runs on the runner's Java 17).
# Pinned by SHA-256: whatever runs here is handed all four eSigner secrets.
# Update by downloading the new release, reviewing it, and replacing BOTH
# values; never by dropping the hash check.
$CodeSignToolVersion = 'v1.3.2'
$CodeSignToolUrl = "https://github.com/SSLcom/CodeSignTool/releases/download/$CodeSignToolVersion/CodeSignTool-$CodeSignToolVersion.zip"
$CodeSignToolSha256 = ''   # TODO(release admin): fill in before the first signed tag, see RELEASING.md

# The O= of the signing certificate, compared against the leaf's subject.
$Publisher = if ($env:AUTHENTICODE_PUBLISHER) { $env:AUTHENTICODE_PUBLISHER } else { 'CONTINUUM AI PTE. LTD.' }
$TimestampUrl = 'http://timestamp.digicert.com'

$Temp = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { [IO.Path]::GetTempPath() }
$ToolDir = Join-Path $Temp 'codesigntool'
$Log = Join-Path $Temp 'orca-signed.txt'
$LastSign = Join-Path $Temp 'orca-esigner-last'

function Fail([string] $msg) { Write-Host "::error::sign.ps1: $msg"; exit 1 }

function Get-Mode {
  $m = $env:ORCA_SIGN_MODE
  if ($m -notin @('esigner', 'selfsigned')) { Fail "ORCA_SIGN_MODE must be esigner or selfsigned, got '$m'" }
  return $m
}

function Find-SignTool {
  $kits = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
  $tool = Get-ChildItem $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match '\\x64\\' } | Sort-Object FullName -Descending | Select-Object -First 1
  if (-not $tool) { Fail "signtool.exe not found under $kits" }
  return $tool.FullName
}

function Assert-Signed([string] $path, [string] $mode) {
  $sig = Get-AuthenticodeSignature -FilePath $path
  $name = Split-Path $path -Leaf
  if (-not $sig.SignerCertificate) { Fail "$name carries no signature after signing" }
  if (-not $sig.TimeStamperCertificate) { Fail "$name is signed but has no timestamp" }
  if ($mode -eq 'esigner') {
    if ($sig.Status -ne 'Valid') { Fail "$name signature status is $($sig.Status): $($sig.StatusMessage)" }
    # Subject is "CN=..., O=CONTINUUM AI PTE. LTD., L=..., C=SG": match the O= field exactly.
    $org = ($sig.SignerCertificate.Subject -split ',\s*(?=[A-Z]+=)' | Where-Object { $_ -like 'O=*' }) -replace '^O=', '' -replace '^"|"$', ''
    if ($org -ne $Publisher) { Fail "$name is signed by '$($sig.SignerCertificate.Subject)', not $Publisher" }
  }
  Write-Host "$name signed by $($sig.SignerCertificate.Subject), timestamped ($($sig.Status))"
}

function Invoke-Setup {
  if ((Get-Mode) -ne 'esigner') { Write-Host 'selfsigned mode: nothing to set up'; return }
  if (-not $CodeSignToolSha256) { Fail 'CodeSignTool is not pinned: set $CodeSignToolSha256 in desktop/src-tauri/windows/sign.ps1 (see RELEASING.md)' }
  foreach ($v in 'ES_USERNAME', 'ES_PASSWORD', 'ES_CREDENTIAL_ID', 'ES_TOTP_SECRET') {
    if (-not (Get-Item "env:$v" -ErrorAction SilentlyContinue).Value) {
      Fail "$v is not set. Add it as a secret of the desktop-release ENVIRONMENT (not a repository secret)."
    }
  }
  $zip = Join-Path $Temp 'codesigntool.zip'
  Invoke-WebRequest -Uri $CodeSignToolUrl -OutFile $zip -UseBasicParsing
  $got = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($got -ne $CodeSignToolSha256.ToLowerInvariant()) { Fail "CodeSignTool download hash $got does not match the pinned $CodeSignToolSha256" }
  Remove-Item -Recurse -Force $ToolDir -ErrorAction SilentlyContinue
  Expand-Archive $zip -DestinationPath $ToolDir
  Remove-Item $zip
  # The zip may wrap everything in one folder; find the jar wherever it is.
  $jar = Get-ChildItem $ToolDir -Recurse -Filter 'code_sign_tool-*.jar' | Select-Object -First 1
  if (-not $jar) { Fail 'code_sign_tool jar not found in the CodeSignTool download' }
  Write-Host "CodeSignTool $CodeSignToolVersion ready: $($jar.FullName)"
}

# Runs java with each argument passed as exactly one argument, whatever
# characters a credential holds (quotes and spaces included): .NET's
# ArgumentList does the quoting, unlike PowerShell's own native-argument
# passing. pwsh 7 (the runner's pwsh) has ArgumentList; Windows PowerShell 5.1
# does not and falls back to a plain call, fine for credentials without quotes.
function Invoke-Java([string] $java, [string] $cwd, [string[]] $javaArgs) {
  $psi = [Diagnostics.ProcessStartInfo]::new()
  if ($null -eq $psi.ArgumentList) {
    Push-Location $cwd
    try { return (& $java @javaArgs 2>&1 | Out-String) } finally { Pop-Location }
  }
  $psi.FileName = (Get-Command $java).Source
  $psi.WorkingDirectory = $cwd
  $psi.UseShellExecute = $false
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  foreach ($a in $javaArgs) { $psi.ArgumentList.Add($a) }
  $p = [Diagnostics.Process]::Start($psi)
  $stderr = $p.StandardError.ReadToEndAsync()
  $stdout = $p.StandardOutput.ReadToEnd()
  $p.WaitForExit()
  return $stdout + $stderr.Result + $(if ($p.ExitCode) { "`nCodeSignTool exited with Error code $($p.ExitCode)" } else { '' })
}

function Invoke-ESigner([string] $path) {
  $jar = Get-ChildItem $ToolDir -Recurse -Filter 'code_sign_tool-*.jar' -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $jar) { Fail 'CodeSignTool is not set up; run sign.ps1 -Setup first' }
  $java = if ($env:JAVA_HOME_17_X64) { Join-Path $env:JAVA_HOME_17_X64 'bin\java.exe' } else { 'java' }
  $toolRoot = $jar.Directory.Parent.FullName  # CodeSignTool reads conf\ relative to its folder
  $out = Join-Path $Temp ("esigner-out-" + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory $out | Out-Null
  $name = Split-Path $path -Leaf
  for ($attempt = 1; $attempt -le 3; $attempt++) {
    # One TOTP code per 30 s: never present the same code twice, across
    # Tauri's separate calls too.
    if (Test-Path $LastSign) {
      $wait = 35 - ((Get-Date) - (Get-Item $LastSign).LastWriteTime).TotalSeconds
      if ($wait -gt 0) { Start-Sleep -Seconds ([math]::Ceiling($wait)) }
    }
    Set-Content -Path $LastSign -Value (Get-Date -Format o)
    Write-Host "eSigner: signing $name (attempt $attempt)"
    $text = Invoke-Java $java $toolRoot @(
      '-Xmx1024M', '-jar', $jar.FullName, 'sign',
      "-username=$env:ES_USERNAME", "-password=$env:ES_PASSWORD",
      "-credential_id=$env:ES_CREDENTIAL_ID", "-totp_secret=$env:ES_TOTP_SECRET",
      "-input_file_path=$path", "-output_dir_path=$out")
    Write-Host $text
    $signed = Join-Path $out $name
    if ($text -notmatch 'Error|Exception' -and (Test-Path $signed) -and (Get-Item $signed).Length -gt 0) {
      Copy-Item $signed $path -Force
      Remove-Item -Recurse -Force $out
      return
    }
  }
  Remove-Item -Recurse -Force $out -ErrorAction SilentlyContinue
  Fail "eSigner did not sign $name"
}

function Invoke-SelfSigned([string] $path) {
  $thumb = $env:ORCA_SIGN_THUMBPRINT
  if (-not $thumb) { Fail 'ORCA_SIGN_THUMBPRINT is not set for selfsigned mode' }
  $signtool = Find-SignTool
  & $signtool sign /fd sha256 /sha1 $thumb /d 'OrcaRouter Lite' /tr $TimestampUrl /td sha256 $path
  if ($LASTEXITCODE -ne 0) { Fail "signtool failed on $(Split-Path $path -Leaf)" }
}

function Invoke-Report {
  $lines = @(if (Test-Path $Log) { Get-Content $Log })
  Write-Host "Files sent to the signer: $($lines.Count)"
  $lines | ForEach-Object { Write-Host "  $_" }
  $esigner = @($lines | Where-Object { $_ -like 'esigner*' }).Count
  if ($esigner) { Write-Host "::notice::$esigner eSigner signings spent on this build" }
  if ($lines.Count -ne 4) { Write-Host "::warning::expected 4 signed files (app, engine, uninstaller, setup), got $($lines.Count)" }
}

if ($Setup) { Invoke-Setup; exit 0 }
if ($Report) { Invoke-Report; exit 0 }
if (-not $File) { Fail 'no file given' }
if (-not (Test-Path -LiteralPath $File)) { Fail "$File does not exist" }
$path = (Resolve-Path -LiteralPath $File).ProviderPath
if ([IO.Path]::GetExtension($path) -ieq '.dll') {
  Write-Host "skip (DLL, not signed): $(Split-Path $path -Leaf)"
  exit 0
}
$mode = Get-Mode
if ($mode -eq 'esigner') { Invoke-ESigner $path } else { Invoke-SelfSigned $path }
Assert-Signed $path $mode
Add-Content -Path $Log -Value "$mode $(Split-Path $path -Leaf)"
exit 0
