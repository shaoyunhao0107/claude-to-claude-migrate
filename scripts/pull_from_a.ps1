param(
    [Parameter(Mandatory=$true)][string]$SshAlias,
    [Parameter(Mandatory=$true)][string]$SourceProfile,
    [Parameter(Mandatory=$true)][string]$SourceConfigDir,
    [Parameter(Mandatory=$true)][string]$OutDir,
    [string]$RemotePython = 'python',
    [string]$ProjectsFile
)
# Windows A and B, configured OpenSSH alias, authenticated known host, Python on A.
$ErrorActionPreference = 'Stop'
if ($SshAlias -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]*$') {
    throw 'Use an SSH config alias containing only letters, digits, dot, underscore or hyphen.'
}
$target = [System.IO.Path]::GetFullPath($OutDir)
if (Test-Path -LiteralPath $target) { throw 'OutDir must be a new directory.' }
$remoteRel = 'claude-migrate-' + [guid]::NewGuid().ToString('N')
function Quote-PS([string]$Value) { return "'" + $Value.Replace("'", "''") + "'" }
function Invoke-Remote([string]$Code) {
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($Code))
    & ssh -o BatchMode=yes -o StrictHostKeyChecking=yes $SshAlias "powershell.exe -NoProfile -NonInteractive -EncodedCommand $encoded"
    if ($LASTEXITCODE -ne 0) { throw 'Remote command failed; retain staging and inspect locally.' }
}
New-Item -ItemType Directory -Path $target | Out-Null
$remoteRoot = Quote-PS $remoteRel
Invoke-Remote "`$ErrorActionPreference='Stop'; New-Item -ItemType Directory -Path (Join-Path `$env:USERPROFILE $remoteRoot) | Out-Null"
$scriptFile = Join-Path $PSScriptRoot 'migrate.py'
& scp -o BatchMode=yes -o StrictHostKeyChecking=yes $scriptFile "${SshAlias}:${remoteRel}/migrate.py"
if ($LASTEXITCODE -ne 0) { throw 'Script upload failed.' }
$profileArg = Quote-PS $SourceProfile
$configArg = Quote-PS $SourceConfigDir
$pythonArg = Quote-PS $RemotePython
$projectArgs = ''
if ($ProjectsFile) {
    & scp -o BatchMode=yes -o StrictHostKeyChecking=yes $ProjectsFile "${SshAlias}:${remoteRel}/projects.json"
    if ($LASTEXITCODE -ne 0) { throw 'Project selection upload failed.' }
    $projectArgs = " --projects (Join-Path `$r 'projects.json')"
}
$remoteCode = "`$ErrorActionPreference='Stop'; `$r=Join-Path `$env:USERPROFILE $remoteRoot; & $pythonArg (Join-Path `$r 'migrate.py') export --profile $profileArg --config-dir $configArg --out (Join-Path `$r 'export')$projectArgs; if (`$LASTEXITCODE -ne 0) { exit 1 }"
Invoke-Remote $remoteCode
& scp -o BatchMode=yes -o StrictHostKeyChecking=yes "${SshAlias}:${remoteRel}/export/claude-transfer.zip" $target
if ($LASTEXITCODE -ne 0) { throw 'Bundle download failed.' }
& scp -o BatchMode=yes -o StrictHostKeyChecking=yes "${SshAlias}:${remoteRel}/export/claude-transfer.zip.sha256" $target
if ($LASTEXITCODE -ne 0) { throw 'Checksum download failed.' }
$bundle = Join-Path $target 'claude-transfer.zip'
$expected = (Get-Content -Raw -LiteralPath ($bundle + '.sha256')).Trim()
$actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $bundle).Hash.ToLowerInvariant()
if ($expected -notmatch '^[a-f0-9]{64}$' -or $actual -ne $expected) { throw 'Transport SHA-256 mismatch.' }
[pscustomobject]@{ Bundle=$bundle; Sha256=$actual; RemoteStaging=$remoteRel; Applied=$false } | ConvertTo-Json
