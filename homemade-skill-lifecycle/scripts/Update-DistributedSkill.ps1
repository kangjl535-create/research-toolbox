[CmdletBinding(DefaultParameterSetName = 'Sync')]
param(
    [Parameter(Mandatory)][string]$DistributionPath,
    [Parameter(Mandatory)][string]$Branch,
    [Parameter(Mandatory, ParameterSetName = 'Sync')]
    [Parameter(Mandatory, ParameterSetName = 'Verify')]
    [string]$UpstreamPath,
    [Parameter(Mandatory, ParameterSetName = 'Sync')]
    [Parameter(Mandatory, ParameterSetName = 'Verify')]
    [string]$Tag,
    [Parameter(Mandatory, ParameterSetName = 'Sync')][ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$ReleaseDate,
    [Parameter(ParameterSetName = 'Sync')][string]$Timestamp,
    [Parameter(Mandatory, ParameterSetName = 'Verify')][switch]$Verify,
    [Parameter(Mandatory, ParameterSetName = 'Package')][switch]$Package,
    [Parameter(Mandatory, ParameterSetName = 'Package')][string]$OutputDirectory,
    [string[]]$DistributionFile = @('LICENSE', 'UPSTREAM_SOURCE.md', 'KNOWN_ISSUES.md')
)

# Adopts an upstream skill release into a curated distribution checkout (references/distribution-repository.md).
# Sync writes the work tree from the tag's commit, -Verify checks the committed files against the upstream
# blob IDs, and -Package builds the distribution ZIP and SHA256SUMS.txt line from the committed tree.

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Invoke-Git {
    param([Parameter(Mandatory)][string]$WorkingDirectory, [Parameter(Mandatory)][string[]]$Arguments)

    $output = & git -C $WorkingDirectory -c core.quotePath=false @Arguments
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE." }
    if ($null -ne $output) { $output }
}

function Get-GitLocation {
    param([Parameter(Mandatory)][string]$Path)

    $root = [string](Invoke-Git -WorkingDirectory $Path -Arguments @('rev-parse', '--show-toplevel'))
    $prefix = [string](Invoke-Git -WorkingDirectory $Path -Arguments @('rev-parse', '--show-prefix'))
    return [pscustomobject]@{ root = $root; prefix = $prefix; path = $prefix.TrimEnd('/') }
}

function Get-GitTreeFiles {
    param([Parameter(Mandatory)][string]$RepositoryRoot, [Parameter(Mandatory)][string]$TreeIsh)

    $files = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
    foreach ($line in @(Invoke-Git -WorkingDirectory $RepositoryRoot -Arguments @('ls-tree', '-r', $TreeIsh))) {
        $match = [regex]::Match($line, '^(\d{6}) (\w+) ([0-9a-f]{40,64})\t(.+)$')
        if (-not $match.Success) { throw "Unexpected git ls-tree output: $line" }
        $relative = $match.Groups[4].Value
        if ($match.Groups[2].Value -ne 'blob' -or $match.Groups[1].Value -eq '120000') { throw "Git tree entry is not a regular file: $relative" }
        if ([System.IO.Path]::IsPathRooted($relative) -or $relative -match '(^|/)\.\.(/|$)') { throw "Unsafe path in Git tree: $relative" }
        $files[$relative] = $match.Groups[3].Value
    }
    return $files
}

function Get-GitBlobId {
    param([byte[]]$Bytes, [int]$IdLength = 40)

    $header = [System.Text.Encoding]::ASCII.GetBytes("blob $($Bytes.Length)`0")
    $algorithm = if ($IdLength -eq 64) { [System.Security.Cryptography.SHA256]::Create() } else { [System.Security.Cryptography.SHA1]::Create() }
    try {
        $algorithm.TransformBlock($header, 0, $header.Length, $null, 0) | Out-Null
        $algorithm.TransformFinalBlock($Bytes, 0, $Bytes.Length) | Out-Null
        return ([BitConverter]::ToString($algorithm.Hash)).Replace('-', '').ToLowerInvariant()
    }
    finally { $algorithm.Dispose() }
}

function Read-EntryBytes {
    param([Parameter(Mandatory)]$Entry)

    $stream = $Entry.Open()
    try {
        $memory = New-Object System.IO.MemoryStream
        $stream.CopyTo($memory)
        return ,$memory.ToArray()
    }
    finally { $stream.Dispose() }
}

function Read-SourceField {
    param([Parameter(Mandatory)][string]$Text, [Parameter(Mandatory)][string]$Pattern, [Parameter(Mandatory)][string]$Name)

    $found = [regex]::Matches($Text, $Pattern)
    if ($found.Count -ne 1) { throw "UPSTREAM_SOURCE.md must contain the field '$Name' exactly once; found $($found.Count)." }
    return $found[0].Groups['v'].Value
}

# A partial clone downloads blobs during checkout; a network error can stop a branch switch halfway.
function Assert-CleanBranch {
    param([Parameter(Mandatory)][string]$RepositoryRoot, [Parameter(Mandatory)][string]$ExpectedBranch)

    $current = [string](Invoke-Git -WorkingDirectory $RepositoryRoot -Arguments @('branch', '--show-current'))
    if ($current -cne $ExpectedBranch) { throw "Distribution checkout is on branch '$current', expected '$ExpectedBranch'." }
    $status = @(Invoke-Git -WorkingDirectory $RepositoryRoot -Arguments @('status', '--porcelain'))
    if ($status.Count -gt 0) {
        throw ("Distribution work tree is not clean (an interrupted checkout can leave files deleted or modified); rerun the checkout or clone again:`n" + ($status -join "`n"))
    }
}

$distributionRoot = [System.IO.Path]::GetFullPath($DistributionPath).TrimEnd('\', '/')
if (-not (Test-Path -LiteralPath $distributionRoot -PathType Container)) { throw "Distributed skill directory not found: $distributionRoot" }
$skillName = Split-Path -Leaf $distributionRoot
$sourceRecordPath = Join-Path $distributionRoot 'UPSTREAM_SOURCE.md'
if (-not (Test-Path -LiteralPath $sourceRecordPath -PathType Leaf)) { throw "UPSTREAM_SOURCE.md not found; adding a skill to the distribution is a curation decision: $distributionRoot" }
$distribution = Get-GitLocation -Path $distributionRoot
Assert-CleanBranch -RepositoryRoot $distribution.root -ExpectedBranch $Branch
$additions = @($DistributionFile | ForEach-Object { $_.Replace('\', '/') })

$recordBytes = [System.IO.File]::ReadAllBytes($sourceRecordPath)
$recordHasBom = $recordBytes.Length -ge 3 -and $recordBytes[0] -eq 0xEF -and $recordBytes[1] -eq 0xBB -and $recordBytes[2] -eq 0xBF
$recordEncoding = New-Object System.Text.UTF8Encoding $recordHasBom
$recordText = if ($recordHasBom) { $recordEncoding.GetString($recordBytes, 3, $recordBytes.Length - 3) } else { $recordEncoding.GetString($recordBytes) }
$versionPattern = '(?m)^- Distribution name: [^\r\n]*distribution version: `(?<v>[^`]+)`'

if ($Package) {
    $version = Read-SourceField -Text $recordText -Pattern $versionPattern -Name 'distribution version'
    $outputRoot = [System.IO.Path]::GetFullPath($OutputDirectory)
    if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) { New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null }
    $zipName = "$skillName-$version.zip"
    $destination = Join-Path $outputRoot $zipName
    if (Test-Path -LiteralPath $destination) { throw "Distribution ZIP already exists and will not be overwritten: $destination" }
    $checksumPath = Join-Path $outputRoot 'SHA256SUMS.txt'
    $checksumText = ''
    if (Test-Path -LiteralPath $checksumPath -PathType Leaf) {
        $checksumText = [System.IO.File]::ReadAllText($checksumPath)
        if ($checksumText -match "(?m) \*$([regex]::Escape($zipName))\r?$") { throw "SHA256SUMS.txt already lists $zipName." }
    }

    $staging = Join-Path $outputRoot ('.' + $skillName + '-' + [guid]::NewGuid().ToString('N'))
    try {
        $built = & (Join-Path $PSScriptRoot 'Build-HomemadeSkillRelease.ps1') -SkillPath $distributionRoot -Version $version -OutputDirectory $staging -GitRevision HEAD
        Move-Item -LiteralPath $built.zipPath -Destination $destination
    }
    finally { if (Test-Path -LiteralPath $staging) { Remove-Item -LiteralPath $staging -Recurse -Force } }

    # sha256sum binary-mode format, as in the existing research-toolbox Releases.
    $sha256 = $built.sha256.ToLowerInvariant()
    [System.IO.File]::WriteAllText($checksumPath, $checksumText + "$sha256 *$zipName`n", (New-Object System.Text.UTF8Encoding $false))
    return [pscustomobject]@{
        skill = $skillName
        version = $version
        zipPath = $destination
        sha256 = $sha256
        checksumFile = $checksumPath
        fileCount = $built.fileCount
        commit = [string](Invoke-Git -WorkingDirectory $distribution.root -Arguments @('rev-parse', 'HEAD'))
        skillTree = $built.sourceTree
    }
}

$upstreamRoot = [System.IO.Path]::GetFullPath($UpstreamPath).TrimEnd('\', '/')
if (-not (Test-Path -LiteralPath $upstreamRoot -PathType Container)) { throw "Upstream skill directory not found: $upstreamRoot" }
if ((Split-Path -Leaf $upstreamRoot) -cne $skillName) {
    throw "Upstream skill '$(Split-Path -Leaf $upstreamRoot)' differs from distributed skill '$skillName'; a rename is a removal plus an addition."
}
$tagMatch = [regex]::Match($Tag, '^' + [regex]::Escape($skillName) + '-v(?<version>\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)$')
if (-not $tagMatch.Success) { throw "Tag '$Tag' is not of the form '$skillName-vX.Y.Z'." }
$version = $tagMatch.Groups['version'].Value
$upstream = Get-GitLocation -Path $upstreamRoot
$commit = [string](Invoke-Git -WorkingDirectory $upstream.root -Arguments @('rev-parse', '--verify', "$Tag^{commit}"))
$tree = [string](Invoke-Git -WorkingDirectory $upstream.root -Arguments @('rev-parse', '--verify', "$commit`:$($upstream.prefix)"))
$upstreamFiles = Get-GitTreeFiles -RepositoryRoot $upstream.root -TreeIsh $tree
if (-not $upstreamFiles.ContainsKey('SKILL.md')) { throw "The upstream skill tree of $Tag has no SKILL.md." }
foreach ($relative in $upstreamFiles.Keys) {
    if ($relative -in $additions) { throw "The upstream skill contains '$relative', which the distribution adds itself." }
}
$committedBefore = Get-GitTreeFiles -RepositoryRoot $distribution.root -TreeIsh "HEAD`:$($distribution.prefix)"

if ($Verify) {
    $errors = New-Object System.Collections.Generic.List[string]
    foreach ($relative in $upstreamFiles.Keys) {
        if (-not $committedBefore.ContainsKey($relative)) { $errors.Add("Committed distribution is missing: $relative") }
        elseif ($committedBefore[$relative] -ne $upstreamFiles[$relative]) { $errors.Add("Committed distribution differs from upstream: $relative") }
    }
    foreach ($relative in $committedBefore.Keys) {
        if (-not $upstreamFiles.ContainsKey($relative) -and $relative -notin $additions) { $errors.Add("Committed distribution has a file not in upstream: $relative") }
    }
    $recordedCommit = Read-SourceField -Text $recordText -Pattern '(?m)^- Fixed commit: `(?<v>[0-9a-f]+)`' -Name 'Fixed commit'
    $recordedTree = Read-SourceField -Text $recordText -Pattern '(?m)^- Skill directory Git tree: `(?<v>[0-9a-f]+)`' -Name 'Skill directory Git tree'
    if ($recordedCommit -ne $commit) { $errors.Add("UPSTREAM_SOURCE.md records commit $recordedCommit; $Tag is $commit.") }
    if ($recordedTree -ne $tree) { $errors.Add("UPSTREAM_SOURCE.md records skill tree $recordedTree; $Tag has $tree.") }
    if ($errors.Count -gt 0) { throw ("Distribution verification failed:`n- " + (@($errors | Sort-Object) -join "`n- ")) }

    return [pscustomobject]@{
        verified = $true
        skill = $skillName
        version = $version
        branch = $Branch
        commit = [string](Invoke-Git -WorkingDirectory $distribution.root -Arguments @('rev-parse', 'HEAD'))
        skillTree = [string](Invoke-Git -WorkingDirectory $distribution.root -Arguments @('rev-parse', "HEAD`:$($distribution.prefix)"))
        upstreamCommit = $commit
        upstreamTree = $tree
        fileCount = $upstreamFiles.Count
    }
}

# Check every UPSTREAM_SOURCE.md field before anything is written.
$repositoryUrl = (Read-SourceField -Text $recordText -Pattern '(?m)^- Maintained source repository: (?<v>https://\S+)' -Name 'Maintained source repository').TrimEnd('/')
if ($repositoryUrl.EndsWith('.git')) { $repositoryUrl = $repositoryUrl.Substring(0, $repositoryUrl.Length - 4) }
$stamp = if ($Timestamp) { $Timestamp } else { [DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'", [System.Globalization.CultureInfo]::InvariantCulture) }
$fields = @(
    @{ name = 'Selected reference'; pattern = '(?m)^- Selected reference: tag `(?<v>[^`]+)`'; value = $Tag },
    @{ name = 'Fixed commit'; pattern = '(?m)^- Fixed commit: `(?<v>[0-9a-f]+)`'; value = $commit },
    @{ name = 'Skill directory Git tree'; pattern = '(?m)^- Skill directory Git tree: `(?<v>[0-9a-f]+)`'; value = $tree },
    @{ name = 'Source'; pattern = '(?m)^- Source: (?<v>https://\S+)'; value = "$repositoryUrl/tree/$commit/$($upstream.path)" },
    @{ name = 'Source-query timestamp'; pattern = '(?m)^- Source-query timestamp: `(?<v>[^`]+)`'; value = $stamp },
    @{ name = 'Acquisition timestamp'; pattern = '(?m)^- Acquisition timestamp: `(?<v>[^`]+)`'; value = $stamp },
    @{ name = 'Upstream declared skill version'; pattern = '(?m)^- Upstream declared skill version: `(?<v>[^`]+)`'; value = $version },
    @{ name = 'distribution version'; pattern = $versionPattern; value = $version },
    @{ name = 'Latest stable upstream release'; pattern = '(?m)^Latest stable upstream release: \[(?<v>[^\]]+)\]'; value = "$skillName v$version" },
    @{ name = 'Latest stable upstream release link'; pattern = '(?m)^Latest stable upstream release: \[[^\]]+\]\((?<v>[^)]+)\)'; value = "$repositoryUrl/releases/tag/$Tag" },
    @{ name = 'Latest stable upstream release date'; pattern = '(?m)^Latest stable upstream release: \[[^\]]+\]\([^)]+\) \((?<v>[^)]+)\)'; value = $ReleaseDate },
    @{ name = 'upstream file count'; pattern = 'All (?<v>\d+) upstream skill files'; value = [string]$upstreamFiles.Count }
)
foreach ($field in $fields) { Read-SourceField -Text $recordText -Pattern $field.pattern -Name $field.name | Out-Null }

# Export the committed bytes with line-ending conversion disabled and check them before writing.
$exported = New-Object 'System.Collections.Generic.Dictionary[string,object]' ([System.StringComparer]::Ordinal)
$exportZip = Join-Path ([System.IO.Path]::GetTempPath()) ('distributed-skill-' + [guid]::NewGuid().ToString('N') + '.zip')
try {
    Invoke-Git -WorkingDirectory $upstream.root -Arguments @('-c', 'core.autocrlf=false', 'archive', '--format=zip', '-o', $exportZip, $tree) | Out-Null
    $archive = [System.IO.Compression.ZipFile]::OpenRead($exportZip)
    try {
        foreach ($entry in $archive.Entries) {
            if ([string]::IsNullOrEmpty($entry.Name)) { continue }
            $relative = $entry.FullName.Replace('\', '/')
            if (-not $upstreamFiles.ContainsKey($relative)) { throw "Exported file is not in the upstream tree: $relative" }
            $exported[$relative] = Read-EntryBytes -Entry $entry
        }
    }
    finally { $archive.Dispose() }
}
finally { if (Test-Path -LiteralPath $exportZip -PathType Leaf) { Remove-Item -LiteralPath $exportZip -Force } }
foreach ($relative in $upstreamFiles.Keys) {
    if (-not $exported.ContainsKey($relative)) { throw "Export is missing upstream file: $relative" }
    if ((Get-GitBlobId -Bytes $exported[$relative] -IdLength $upstreamFiles[$relative].Length) -ne $upstreamFiles[$relative]) { throw "Exported bytes differ from the upstream blob: $relative" }
}

# Mirror: remove runtime files deleted upstream, keep distribution additions, write every upstream file.
$removed = New-Object System.Collections.Generic.List[string]
foreach ($file in @(Get-ChildItem -LiteralPath $distributionRoot -Recurse -Force -File)) {
    $relative = $file.FullName.Substring($distributionRoot.Length).TrimStart('\', '/').Replace('\', '/')
    if ($exported.ContainsKey($relative) -or $relative -in $additions) { continue }
    Remove-Item -LiteralPath $file.FullName -Force
    $removed.Add($relative)
}
foreach ($directory in @(Get-ChildItem -LiteralPath $distributionRoot -Recurse -Force -Directory | Sort-Object { $_.FullName.Length } -Descending)) {
    if (@(Get-ChildItem -LiteralPath $directory.FullName -Force).Count -eq 0) { Remove-Item -LiteralPath $directory.FullName -Force }
}
foreach ($relative in $exported.Keys) {
    $target = [System.IO.Path]::Combine($distributionRoot, $relative.Replace('/', [System.IO.Path]::DirectorySeparatorChar))
    $parent = Split-Path -Parent $target
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    [System.IO.File]::WriteAllBytes($target, [byte[]]$exported[$relative])
}

$errors = New-Object System.Collections.Generic.List[string]
foreach ($file in @(Get-ChildItem -LiteralPath $distributionRoot -Recurse -Force -File)) {
    $relative = $file.FullName.Substring($distributionRoot.Length).TrimStart('\', '/').Replace('\', '/')
    if ($relative -in $additions) { continue }
    if (-not $upstreamFiles.ContainsKey($relative)) { $errors.Add("Distributed copy has a file not in upstream: $relative"); continue }
    $blobId = Get-GitBlobId -Bytes ([System.IO.File]::ReadAllBytes($file.FullName)) -IdLength $upstreamFiles[$relative].Length
    if ($blobId -ne $upstreamFiles[$relative]) { $errors.Add("Distributed file does not match the upstream blob: $relative") }
}
if ($errors.Count -gt 0) { throw ("Distribution update failed verification:`n- " + (@($errors | Sort-Object) -join "`n- ")) }

foreach ($field in $fields) {
    $group = [regex]::Match($recordText, $field.pattern).Groups['v']
    $recordText = $recordText.Substring(0, $group.Index) + $field.value + $recordText.Substring($group.Index + $group.Length)
}
$recordOutput = $recordEncoding.GetBytes($recordText)
if ($recordHasBom) { $recordOutput = [byte[]](@(0xEF, 0xBB, 0xBF) + $recordOutput) }
[System.IO.File]::WriteAllBytes($sourceRecordPath, $recordOutput)

[pscustomobject]@{
    skill = $skillName
    version = $version
    tag = $Tag
    upstreamCommit = $commit
    upstreamTree = $tree
    fileCount = $upstreamFiles.Count
    added = @($upstreamFiles.Keys | Where-Object { -not $committedBefore.ContainsKey($_) } | Sort-Object)
    changed = @($upstreamFiles.Keys | Where-Object { $committedBefore.ContainsKey($_) -and $committedBefore[$_] -ne $upstreamFiles[$_] } | Sort-Object)
    removed = @($removed | Sort-Object)
    timestamp = $stamp
    reviewByHand = 'Free text in UPSTREAM_SOURCE.md (file lists, test counts) and the distribution README entry.'
}
