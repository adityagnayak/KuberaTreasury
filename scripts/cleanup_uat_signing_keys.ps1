param(
    [string]$TargetDirectory = ".\tmp\uat-keys",
    [switch]$Force
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedTarget = Resolve-Path -LiteralPath "." | ForEach-Object { Join-Path $_ $TargetDirectory }

if (-not (Test-Path -LiteralPath $resolvedTarget)) {
    Write-Host "No cleanup needed. Directory not found: $resolvedTarget"
    exit 0
}

$files = Get-ChildItem -LiteralPath $resolvedTarget -File -ErrorAction Stop
if ($files.Count -eq 0) {
    Write-Host "No cleanup needed. No files in: $resolvedTarget"
    exit 0
}

Write-Host "Found $($files.Count) file(s) in $resolvedTarget"
if (-not $Force) {
    Write-Host "Files:"
    $files | ForEach-Object { Write-Host "  - $($_.FullName)" }
    $confirm = Read-Host "Type DELETE to permanently remove these files"
    if ($confirm -ne "DELETE") {
        Write-Host "Cleanup cancelled."
        exit 1
    }
}

$files | Remove-Item -Force
Write-Host "Cleanup complete: removed temporary UAT signing key files from $resolvedTarget"
