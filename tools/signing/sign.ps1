<#
.SYNOPSIS
    Signs UIATools.exe and the CrowdStrike cert stub with your code-signing
    certificate, and exports the public .cer file for IT.

.DESCRIPTION
    Run this once you have a code-signing certificate installed in your
    personal certificate store (Cert:\CurrentUser\My).

    Uses PowerShell's built-in Set-AuthenticodeSignature - no Windows SDK
    (signtool) required. Applies an RFC 3161 timestamp so signatures stay
    valid after the certificate expires.

.EXAMPLE
    # Auto-picks the single code-signing cert in your store:
    .\tools\signing\sign.ps1

.EXAMPLE
    # Or pick a specific certificate by thumbprint:
    .\tools\signing\sign.ps1 -Thumbprint 1234ABCD...

.EXAMPLE
    # Sign additional/other files:
    .\tools\signing\sign.ps1 -Files dist\UIATools.exe, some\other.exe
#>
[CmdletBinding()]
param(
    # Thumbprint of the code-signing certificate to use. If omitted and
    # exactly one code-signing cert exists in Cert:\CurrentUser\My, it is used.
    [string]$Thumbprint,

    # Files to sign. Defaults to the main exe and the CrowdStrike stub.
    [string[]]$Files,

    # RFC 3161 timestamp server.
    [string]$TimestampServer = 'http://timestamp.digicert.com'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')

if (-not $Files) {
    $Files = @(
        (Join-Path $repoRoot 'dist\UIATools\UIATools.exe'),
        (Join-Path $PSScriptRoot 'UIATools-CertStub.exe')
    )
    # Fall back to a legacy one-file build if present instead of the one-dir layout.
    if (-not (Test-Path $Files[0]) -and (Test-Path (Join-Path $repoRoot 'dist\UIATools.exe'))) {
        $Files[0] = Join-Path $repoRoot 'dist\UIATools.exe'
    }
}

# --- Locate the certificate -------------------------------------------------
if ($Thumbprint) {
    $cert = Get-Item "Cert:\CurrentUser\My\$Thumbprint"
} else {
    $certs = @(Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert)
    if ($certs.Count -eq 0) {
        Write-Error ("No code-signing certificate found in Cert:\CurrentUser\My. " +
            "Install your certificate first, or pass -Thumbprint.")
    }
    if ($certs.Count -gt 1) {
        $certs | Format-Table Thumbprint, Subject, NotAfter -AutoSize | Out-String | Write-Host
        Write-Error "Multiple code-signing certificates found. Re-run with -Thumbprint <one of the above>."
    }
    $cert = $certs[0]
}
Write-Host "Signing with: $($cert.Subject)  (expires $($cert.NotAfter.ToShortDateString()))" -ForegroundColor Cyan

# --- Sign each file ----------------------------------------------------------
foreach ($file in $Files) {
    if (-not (Test-Path $file)) {
        Write-Warning "Skipping (not found): $file"
        if ($file -like '*UIATools-CertStub.exe') {
            Write-Warning "  Build it first: tools\signing\build-stub.bat"
        }
        if ($file -like '*UIATools.exe') {
            Write-Warning "  Build it first: build.bat"
        }
        continue
    }
    $result = Set-AuthenticodeSignature -FilePath $file -Certificate $cert `
        -HashAlgorithm SHA256 -TimestampServer $TimestampServer
    if ($result.Status -ne 'Valid') {
        Write-Error "Signing FAILED for $file : $($result.Status) - $($result.StatusMessage)"
    }
    Write-Host "Signed OK: $file" -ForegroundColor Green
}

# --- Export public certificate (.cer) for IT --------------------------------
$cerPath = Join-Path $repoRoot 'dist\UIATools.cer'
New-Item -ItemType Directory -Force -Path (Split-Path $cerPath) | Out-Null
Export-Certificate -Cert $cert -FilePath $cerPath | Out-Null
Write-Host "Exported public certificate: $cerPath" -ForegroundColor Green

Write-Host ""
Write-Host "Send IT either of these for the CrowdStrike certificate exclusion:" -ForegroundColor Yellow
Write-Host "  1. $cerPath  (the .cer file - contains no private key, safe to share)"
Write-Host "  2. tools\signing\UIATools-CertStub.exe  (small signed PE, <32MB)"
