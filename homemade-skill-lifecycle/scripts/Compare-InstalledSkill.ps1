[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourcePath,
    [Parameter(Mandatory)][string]$InstalledPath,
    [string[]]$IgnoreRelativePath = @(),
    [string[]]$AllowedExtraFile = @('LICENSE', 'UPSTREAM_SOURCE.md', 'KNOWN_ISSUES.md')
)

$ErrorActionPreference = 'Stop'
$latin1 = [System.Text.Encoding]::GetEncoding(28591)

function Get-Sha256Hex {
    param([byte[]]$Bytes)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($Bytes))).Replace('-', '') }
    finally { $sha.Dispose() }
}

# Text files (no NUL byte) are compared with CRLF read as LF: the synchronized source is edited
# with CRLF, while Git and installers deliver LF. Binary files are compared byte for byte.
function Get-FileDigest {
    param([Parameter(Mandatory)][string]$Path)

    $bytes = [System.IO.File]::ReadAllBytes($Path)
    $raw = Get-Sha256Hex -Bytes $bytes
    $comparable = $raw
    if ([Array]::IndexOf($bytes, [byte]0) -lt 0) {
        $text = $latin1.GetString($bytes)
        if ($text.Contains("`r`n")) { $comparable = Get-Sha256Hex -Bytes $latin1.GetBytes($text.Replace("`r`n", "`n")) }
    }
    return [pscustomobject]@{ raw = $raw; comparable = $comparable }
}

function Get-ComparableFiles {
    param([Parameter(Mandatory)][string]$Root, [string[]]$Ignored)

    $result = @{}
    foreach ($file in @(Get-ChildItem -LiteralPath $Root -Recurse -Force -File)) {
        $relative = $file.FullName.Substring($Root.Length).TrimStart('\', '/').Replace('\', '/')
        $segments = $relative.Split('/')
        if (@($segments | Where-Object { $_ -in @('.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache') }).Count -gt 0) { continue }
        if ($segments[-1] -in @('.DS_Store', 'Thumbs.db') -or $segments[-1] -match '(?i)\.(pyc|pyo|tmp)$') { continue }
        if ($relative -in $Ignored) { continue }
        $result[$relative] = Get-FileDigest -Path $file.FullName
    }
    return $result
}

$sourceRoot = [System.IO.Path]::GetFullPath($SourcePath).TrimEnd('\', '/')
$installedRoot = [System.IO.Path]::GetFullPath($InstalledPath).TrimEnd('\', '/')
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { throw "Source skill directory not found: $sourceRoot" }
if (-not (Test-Path -LiteralPath $installedRoot -PathType Container)) { throw "Installed skill directory not found: $installedRoot" }

$normalizedIgnored = @($IgnoreRelativePath | ForEach-Object { $_.Replace('\', '/') })
$normalizedAllowed = @($AllowedExtraFile | ForEach-Object { $_.Replace('\', '/') })
$sourceFiles = Get-ComparableFiles -Root $sourceRoot -Ignored $normalizedIgnored
$installedFiles = Get-ComparableFiles -Root $installedRoot -Ignored $normalizedIgnored
$errors = New-Object System.Collections.Generic.List[string]
$allowedExtras = New-Object System.Collections.Generic.List[string]
$lineEndingOnly = 0

foreach ($relative in $sourceFiles.Keys) {
    if (-not $installedFiles.ContainsKey($relative)) { $errors.Add("Installed copy is missing: $relative") }
    elseif ($sourceFiles[$relative].comparable -ne $installedFiles[$relative].comparable) { $errors.Add("Installed content differs: $relative") }
    elseif ($sourceFiles[$relative].raw -ne $installedFiles[$relative].raw) { $lineEndingOnly++ }
}
foreach ($relative in $installedFiles.Keys) {
    if ($sourceFiles.ContainsKey($relative)) { continue }
    if ($relative -in $normalizedAllowed) { $allowedExtras.Add($relative) }
    else { $errors.Add("Installed copy contains an extra file: $relative") }
}

if ($errors.Count -gt 0) { throw ("Installed skill comparison failed:`n- " + (@($errors | Sort-Object) -join "`n- ")) }

[pscustomobject]@{
    matches = $true
    sourcePath = $sourceRoot
    installedPath = $installedRoot
    fileCount = $sourceFiles.Count
    lineEndingOnlyCount = $lineEndingOnly
    allowedExtraFiles = @($allowedExtras | Sort-Object)
}
