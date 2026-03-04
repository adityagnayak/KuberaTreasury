param(
    [string]$OutputDirectory = ".\tmp\uat-signing",
    [string]$KeyIdPrefix = "uat-pdf-signing"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$resolvedOutput = Resolve-Path -LiteralPath "." | ForEach-Object { Join-Path $_ $OutputDirectory }
New-Item -ItemType Directory -Path $resolvedOutput -Force | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$keyId = "$KeyIdPrefix-$timestamp"

$rsa = New-Object System.Security.Cryptography.RSACryptoServiceProvider(3072)
$rsa.PersistKeyInCsp = $false
try {
    $privateXml = $rsa.ToXmlString($true)
    $publicXml = $rsa.ToXmlString($false)

    $privateFile = Join-Path $resolvedOutput "audit_pdf_signing_private.xml"
    $publicFile = Join-Path $resolvedOutput "audit_pdf_signing_public.xml"

    [System.IO.File]::WriteAllText($privateFile, $privateXml, [System.Text.UTF8Encoding]::new($false))
    [System.IO.File]::WriteAllText($publicFile, $publicXml, [System.Text.UTF8Encoding]::new($false))

    $privateEscaped = $privateXml -replace "`r?`n", ""

    Write-Host "UAT signing keypair generated:"
    Write-Host "  Private: $privateFile"
    Write-Host "  Public : $publicFile"
    Write-Host ""
    Write-Host "Copy these into your .env (UAT only):"
    Write-Host "AUDIT_PDF_SIGNING_KEY_ID=$keyId"
    Write-Host "AUDIT_PDF_SIGNING_PRIVATE_KEY=$privateEscaped"
    Write-Host ""
    Write-Host "Format note: UAT fallback uses RSA XML key format for Windows PowerShell 5.1 compatibility."
    Write-Host "Important: Do NOT use these keys in production. Use KMS/HSM-managed keys in production."
}
finally {
    $rsa.Dispose()
}
