param(
    [Parameter(Mandatory=$true)][string]$Url,
    [Parameter(Mandatory=$true)][string]$PostData,
    [string]$OutFile = "",
    [string]$Referer = ""
)
$ErrorActionPreference = "Continue"
try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch {}
try { Add-Type -AssemblyName System.Net.Primitives -ErrorAction SilentlyContinue } catch {}

# --- STEP 1: GET page, capture cookies + viewstate ---
$handler = New-Object System.Net.Http.HttpClientHandler
$handler.AllowAutoRedirect = $true
$handler.MaxAutomaticRedirections = 20
$handler.UseCookies = $true
$handler.CookieContainer = New-Object System.Net.CookieContainer
$client = New-Object System.Net.Http.HttpClient($handler)
$client.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")

$getResp = $client.GetAsync($Url).GetAwaiter().GetResult()
$getBody = $getResp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
Write-Output ("STEP1_GET_STATUS: " + [int]$getResp.StatusCode)
Write-Output ("STEP1_FINAL_URL: " + $getResp.RequestMessage.RequestUri.AbsoluteUri)

# Extract form tokens
$vs = [regex]::Match($getBody, 'id="__VIEWSTATE"[^>]*value="([^"]*)"').Groups[1].Value
$vsg = [regex]::Match($getBody, 'id="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"').Groups[1].Value
$ev = [regex]::Match($getBody, 'id="__EVENTVALIDATION"[^>]*value="([^"]*)"').Groups[1].Value
Write-Output ("TOKEN_VIEWSTATE_LEN: " + $vs.Length)
Write-Output ("TOKEN_VIEWSTATEGENERATOR: " + $vsg)
Write-Output ("TOKEN_EVENTVALIDATION_LEN: " + $ev.Length)

# Build form body: viewstate + posted data
$pairs = [System.Net.WebUtility]::UrlEncode($vs)
if ($vsg -ne "") { $pairs += "&__VIEWSTATEGENERATOR=" + [System.Net.WebUtility]::UrlEncode($vsg) }
if ($ev -ne "") { $pairs += "&__EVENTVALIDATION=" + [System.Net.WebUtility]::UrlEncode($ev) }
$pairs += "&" + $PostData
Write-Output ("POST_BODY_PREVIEW: " + $pairs.Substring(0, [Math]::Min(200, $pairs.Length)))

# --- STEP 2: POST with cookies ---
$content = New-Object System.Net.Http.StringContent($pairs, [System.Text.Encoding]::UTF8, "application/x-www-form-urlencoded")
$postReq = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Post, $Url)
$postReq.Content = $content
if ($Referer -ne "") { $postReq.Headers.Referrer = [Uri]$Referer }
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$postResp = $client.SendAsync($postReq).GetAwaiter().GetResult()
$sw.Stop()
$postBody = $postResp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
Write-Output ("STEP2_POST_STATUS: " + [int]$postResp.StatusCode)
Write-Output ("STEP2_FINAL_URL: " + $postResp.RequestMessage.RequestUri.AbsoluteUri)
Write-Output ("STEP2_ELAPSED_MS: " + $sw.ElapsedMilliseconds)

if ($OutFile -ne "") {
    [System.IO.File]::WriteAllText($OutFile, $postBody, [System.Text.Encoding]::UTF8)
    Write-Output ("STEP2_BODY_SHA256: " + (Get-FileHash -LiteralPath $OutFile -Algorithm SHA256).Hash)
    Write-Output ("STEP2_BODY_BYTES: " + [System.Text.Encoding]::UTF8.GetByteCount($postBody))
}
Write-Output ("STEP2_BODY_LEN: " + $postBody.Length)
