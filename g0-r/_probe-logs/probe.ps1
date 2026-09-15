param(
    [Parameter(Mandatory=$true)][string]$Url,
    [string]$Method = "GET",
    [string]$OutFile = "",
    [string]$CookieJar = "",
    [string]$UseCookies = "0",
    [string]$Referer = "",
    [string]$UserAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    [string]$Follow = "1",
    [string]$PostBody = "",
    [string]$ContentType = "application/x-www-form-urlencoded",
    [switch]$HeadOnly
)

$ErrorActionPreference = "Continue"
try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch {}
try { Add-Type -AssemblyName System.Net.Primitives -ErrorAction SilentlyContinue } catch {}
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.AllowAutoRedirect = ($Follow -eq "1")
$handler.MaxAutomaticRedirections = 20
$handler.UseCookies = ($UseCookies -eq "1")

if ($CookieJar -ne "" -and (Test-Path -LiteralPath $CookieJar)) {
    $handler.CookieContainer = New-Object System.Net.CookieContainer
    try { $handler.CookieContainer.SetCookies([Uri]$Url, (Get-Content -LiteralPath $CookieJar -Raw -ErrorAction SilentlyContinue).Trim()) } catch {}
}

$client = New-Object System.Net.Http.HttpClient($handler)

if ($UserAgent -ne "") { $client.DefaultRequestHeaders.UserAgent.ParseAdd($UserAgent) }
if ($Referer -ne "") { $client.DefaultRequestHeaders.Referrer = [Uri]$Referer }

$sw = [System.Diagnostics.Stopwatch]::StartNew()
$req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::new($Method), $Url)
if ($Method -eq "POST" -and $PostBody -ne "") {
    $req.Content = New-Object System.Net.Http.StringContent($PostBody, [System.Text.Encoding]::UTF8, $ContentType)
}

try {
    $resp = $client.SendAsync($req, [System.Net.Http.HttpCompletionOption]::ResponseContentRead).GetAwaiter().GetResult()
} catch {
    Write-Output ("PROBE_ERROR: " + $_.Exception.Message)
    exit 2
}
$sw.Stop()

$finalUri = if ($resp.RequestMessage -and $resp.RequestMessage.RequestUri) { $resp.RequestMessage.RequestUri.AbsoluteUri } else { $Url }
$status = [int]$resp.StatusCode
$reason = $resp.ReasonPhrase
$bytes = if ($resp.Content) { $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult() } else { [byte[]]@() }
$media = if ($resp.Content -and $resp.Content.Headers.ContentType) { $resp.Content.Headers.ContentType.MediaType } else { "" }

Write-Output ("STATUS: $status $reason")
Write-Output ("FINAL_URL: $finalUri")
Write-Output ("MEDIA_TYPE: $media")
Write-Output ("BYTE_SIZE: $($bytes.Length)")
Write-Output ("ELAPSED_MS: $($sw.ElapsedMilliseconds)")

# capture cookies set
$setCookies = @()
if ($resp.Headers) { try { $setCookies += $resp.Headers.GetValues("Set-Cookie") } catch {} }
if ($resp.Content -and $resp.Content.Headers) { try { $setCookies += $resp.Content.Headers.GetValues("Set-Cookie") } catch {} }
if ($setCookies.Count -gt 0) { Write-Output "SET_COOKIE:"; $setCookies | ForEach-Object { Write-Output ("  " + $_) } }
else { Write-Output "SET_COOKIE: (none)" }

Write-Output "RESPONSE_HEADERS:"
foreach ($h in $resp.Headers) { Write-Output ("  " + $h.Key + ": " + ($h.Value -join ", ")) }
if ($resp.Content -and $resp.Content.Headers) {
    foreach ($h in $resp.Content.Headers) { Write-Output ("  " + $h.Key + ": " + ($h.Value -join ", ")) }
}

if ($HeadOnly -eq $false -and $bytes.Length -gt 0) {
    $out = if ($OutFile -ne "") { $OutFile } else { "temp_resp_$(Get-Random).bin" }
    [System.IO.File]::WriteAllBytes($out, $bytes)
    $digest = (Get-FileHash -LiteralPath $out -Algorithm SHA256).Hash
    Write-Output ("BODY_FILE: $out")
    Write-Output ("BODY_SHA256: $digest")
}
