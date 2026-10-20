[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SkillPath,
    [Parameter(Mandatory)][ValidatePattern('^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$')][string]$Version,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [ValidateSet('Wrapped', 'Flat')][string]$Layout = 'Wrapped',
    [string]$GitRevision
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Test-IgnoredSkillFile {
    param([Parameter(Mandatory)][string]$RelativePath)

    $normalized = $RelativePath.Replace('\', '/')
    $segments = $normalized.Split('/')
    if (@($segments | Where-Object { $_ -in @('.git', '.svn', '.hg', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'node_modules') }).Count -gt 0) {
        return $true
    }
    $leaf = $segments[-1]
    return $leaf -in @('.DS_Store', 'Thumbs.db') -or $leaf -match '(?i)\.(pyc|pyo|tmp)$'
}

function Invoke-Git {
    param([Parameter(Mandatory)][string]$WorkingDirectory, [Parameter(Mandatory)][string[]]$Arguments)

    $output = & git -C $WorkingDirectory -c core.quotePath=false @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE." }
    if ($null -ne $output) { $output }
}

$sourceRoot = [System.IO.Path]::GetFullPath($SkillPath).TrimEnd('\', '/')
if (-not (Test-Path -LiteralPath $sourceRoot -PathType Container)) { throw "Skill directory not found: $sourceRoot" }
$skillFile = Join-Path $sourceRoot 'SKILL.md'
if (-not (Test-Path -LiteralPath $skillFile -PathType Leaf)) { throw "SKILL.md must exist at the skill source root: $sourceRoot" }

$skillText = Get-Content -LiteralPath $skillFile -Raw
$frontmatter = [regex]::Match($skillText, '(?s)\A---\r?\n(.*?)\r?\n---(?:\r?\n|\z)')
if (-not $frontmatter.Success) { throw 'SKILL.md does not contain valid opening YAML frontmatter delimiters.' }
$nameMatch = [regex]::Match($frontmatter.Groups[1].Value, '(?m)^name:\s*([a-z0-9-]+)\s*$')
if (-not $nameMatch.Success) { throw 'SKILL.md frontmatter is missing a valid hyphen-case name.' }
$skillName = $nameMatch.Groups[1].Value
if ((Split-Path -Leaf $sourceRoot) -cne $skillName) { throw "Skill directory name must match frontmatter name '$skillName'." }

$outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) { New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null }
$destination = Join-Path $outputRoot "$skillName-v$Version.zip"
if (Test-Path -LiteralPath $destination) { throw "Release already exists and will not be overwritten: $destination" }
$temporary = Join-Path $outputRoot (".$skillName-v$Version-" + [guid]::NewGuid().ToString('N') + '.tmp')
$sourceTree = $null

try {
    if ($GitRevision) {
        # Pack the committed bytes of the skill's Git tree. Line-ending conversion is disabled so
        # the ZIP equals what the tag, the distribution, and installers serve.
        $repositoryRoot = [string](Invoke-Git -WorkingDirectory $sourceRoot -Arguments @('rev-parse', '--show-toplevel'))
        $prefix = [string](Invoke-Git -WorkingDirectory $sourceRoot -Arguments @('rev-parse', '--show-prefix'))
        $sourceTree = [string](Invoke-Git -WorkingDirectory $repositoryRoot -Arguments @('rev-parse', '--verify', "$GitRevision`:$prefix"))
        $archiveArguments = @('-c', 'core.autocrlf=false', 'archive', '--format=zip', '-o', $temporary)
        if ($Layout -eq 'Wrapped') { $archiveArguments += "--prefix=$skillName/" }
        Invoke-Git -WorkingDirectory $repositoryRoot -Arguments ($archiveArguments + $sourceTree) | Out-Null
    }
    else {
        $files = @(Get-ChildItem -LiteralPath $sourceRoot -Recurse -Force -File | Where-Object {
            $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\', '/')
            -not (Test-IgnoredSkillFile -RelativePath $relative)
        })
        if ($files.Count -eq 0) { throw "No release files found under: $sourceRoot" }

        $fileStream = [System.IO.File]::Open($temporary, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        try {
            $archive = [System.IO.Compression.ZipArchive]::new($fileStream, [System.IO.Compression.ZipArchiveMode]::Create, $true)
            try {
                foreach ($file in $files) {
                    $relative = $file.FullName.Substring($sourceRoot.Length).TrimStart('\', '/').Replace('\', '/')
                    $entryName = if ($Layout -eq 'Wrapped') { "$skillName/$relative" } else { $relative }
                    $entry = $archive.CreateEntry($entryName, [System.IO.Compression.CompressionLevel]::Optimal)
                    $entry.LastWriteTime = $file.LastWriteTime
                    $input = [System.IO.File]::OpenRead($file.FullName)
                    $output = $entry.Open()
                    try { $input.CopyTo($output) }
                    finally { $output.Dispose(); $input.Dispose() }
                }
            }
            finally { $archive.Dispose() }
        }
        finally { $fileStream.Dispose() }
    }

    $validator = Join-Path $PSScriptRoot 'Test-HomemadeSkillRelease.ps1'
    if ($GitRevision) { $validation = & $validator -ZipPath $temporary -SourcePath $sourceRoot -GitRevision $GitRevision }
    else { $validation = & $validator -ZipPath $temporary -SourcePath $sourceRoot }
    Move-Item -LiteralPath $temporary -Destination $destination

    [pscustomobject]@{
        skill = $skillName
        version = $Version
        zipPath = $destination
        fileCount = $validation.fileCount
        layout = $validation.layout
        sha256 = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash
        sourceTree = $sourceTree
    }
}
finally {
    if (Test-Path -LiteralPath $temporary -PathType Leaf) { Remove-Item -LiteralPath $temporary -Force }
}
