# Managed by VWSHub HTTPS Installer — PUBLIC CA only; never import a private key.
[CmdletBinding()]
param(
    [string]$CertificatePath = (Join-Path $PSScriptRoot 'rootCA.crt'),
    [string]$ExpectedFingerprint,
    [string]$Url
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Normalize-Fingerprint([string]$Value) {
    $normalized = ($Value -replace '[:\s-]', '').ToUpperInvariant()
    if ($normalized -notmatch '^[0-9A-F]{64}$') {
        throw 'Expected a complete SHA-256 fingerprint (64 hexadecimal digits).'
    }
    return $normalized
}
function Get-Sha256($Certificate) {
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($algorithm.ComputeHash($Certificate.RawData))).Replace('-', '') }
    finally { $algorithm.Dispose() }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Open PowerShell as Administrator. No certificate was imported.'
}
$resolved = (Resolve-Path -LiteralPath $CertificatePath).Path
$item = Get-Item -LiteralPath $resolved
if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -or $item.Length -gt 1048576) {
    throw 'Use a regular, small local public certificate file.'
}
$pem = [IO.File]::ReadAllText($resolved)
if ($pem -match 'PRIVATE KEY|PKCS12|BEGIN TRUSTED CERTIFICATE') {
    throw 'Private keys and key containers are prohibited in this client package.'
}
$certificateBlocks = [regex]::Matches($pem, '(?s)-----BEGIN CERTIFICATE-----\s*([A-Za-z0-9+/=\r\n]+)\s*-----END CERTIFICATE-----')
if ($certificateBlocks.Count -ne 1) { throw 'Expected exactly one public PEM root certificate.' }
$der = [Convert]::FromBase64String(($certificateBlocks[0].Groups[1].Value -replace '\s', ''))
$certificate = New-Object Security.Cryptography.X509Certificates.X509Certificate2(,$der)
if ($certificate.HasPrivateKey) { throw 'A private key must never be imported.' }
if ($certificate.NotBefore -gt (Get-Date) -or $certificate.NotAfter -le (Get-Date)) {
    throw 'The CA certificate is not currently valid.'
}
if ($certificate.Subject -ne $certificate.Issuer) { throw 'The certificate must be a self-issued root CA.' }
$constraints = $certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.19' }
if (-not $constraints) { throw 'Missing Basic Constraints CA extension.' }
$basic = New-Object Security.Cryptography.X509Certificates.X509BasicConstraintsExtension
$basic.CopyFrom($constraints)
if (-not $basic.CertificateAuthority) { throw 'Basic Constraints must declare CA:TRUE.' }
$usageExtension = $certificate.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.15' }
if (-not $usageExtension) { throw 'Missing certificate-signing key usage.' }
$usage = New-Object Security.Cryptography.X509Certificates.X509KeyUsageExtension
$usage.CopyFrom($usageExtension)
if (-not ($usage.KeyUsages -band [Security.Cryptography.X509Certificates.X509KeyUsageFlags]::KeyCertSign)) {
    throw 'The certificate is not permitted to sign certificates.'
}
$chain = New-Object Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.RevocationMode = [Security.Cryptography.X509Certificates.X509RevocationMode]::NoCheck
$chain.ChainPolicy.VerificationFlags = [Security.Cryptography.X509Certificates.X509VerificationFlags]::AllowUnknownCertificateAuthority
try {
    if (-not $chain.Build($certificate)) { throw 'The root certificate chain/signature is invalid.' }
    if ($chain.ChainElements.Count -ne 1) { throw 'Expected a root CA, not an intermediate certificate.' }
} finally { $chain.Dispose() }
$actual = Get-Sha256 $certificate
Write-Host "Root CA SHA-256: $actual"
Write-Host 'Compare this fingerprint with the one shown by the installer on the server, through an independent trusted channel.'
if (-not $ExpectedFingerprint) {
    $ExpectedFingerprint = Read-Host 'Enter the SHA-256 fingerprint obtained from the server administrator'
}
if ((Normalize-Fingerprint $ExpectedFingerprint) -ne $actual) {
    throw 'Fingerprint mismatch. No certificate was imported.'
}
if ((Read-Host 'The CA can authorize HTTPS sites. Type TRUST to confirm the verified fingerprint') -cne 'TRUST') {
    throw 'Trust installation cancelled. No certificate was imported.'
}
# Add exactly the in-memory certificate whose DER/fingerprint was validated.
# Never re-read a mutable input file after the operator's trust confirmation.
$store = New-Object Security.Cryptography.X509Certificates.X509Store(
    [Security.Cryptography.X509Certificates.StoreName]::Root,
    [Security.Cryptography.X509Certificates.StoreLocation]::LocalMachine
)
try {
    $store.Open([Security.Cryptography.X509Certificates.OpenFlags]::ReadWrite)
    $existing = $store.Certificates.Find([Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint, $certificate.Thumbprint, $false)
    if ($existing.Count -gt 0) {
        foreach ($entry in $existing) {
            if ((Get-Sha256 $entry) -ne $actual) { throw 'Existing certificate differs. No certificate was replaced.' }
        }
        Write-Host 'The same CA is already trusted; no duplicate was created.'
    } else { $store.Add($certificate) }
    $installed = $store.Certificates.Find([Security.Cryptography.X509Certificates.X509FindType]::FindByThumbprint, $certificate.Thumbprint, $false)
    if ($installed.Count -eq 0) { throw 'Certificate installation could not be verified.' }
    foreach ($entry in $installed) {
        if ((Get-Sha256 $entry) -ne $actual) { throw 'Installed certificate fingerprint mismatch.' }
    }
} finally { $store.Close(); $store.Dispose() }
if (-not $Url) {
    $metadata = Join-Path $PSScriptRoot 'connection.json'
    if (Test-Path -LiteralPath $metadata) { $Url = (Get-Content -LiteralPath $metadata -Raw | ConvertFrom-Json).url }
}
if ($Url) {
    $destination = $null
    if (-not [Uri]::TryCreate($Url, [UriKind]::Absolute, [ref]$destination) -or $destination.Scheme -ne 'https' -or $destination.UserInfo) {
        throw 'CA installed; the supplied application URL is invalid. Obtain the HTTPS address from the administrator.'
    }
    Write-Host "WVW: $($destination.AbsoluteUri)"
} else { Write-Host 'CA installed. Obtain the WVW HTTPS address from the administrator.' }
Write-Host 'Windows system trust is configured for Chrome/Edge. No other root certificates were removed.'
