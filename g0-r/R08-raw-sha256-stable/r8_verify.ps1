param([string]$Manifest = "g0-r\R07-raw-retrieval\artifact_manifest.json", [string]$OutDir = "g0-r\R08-raw-sha256-stable\evidence")
$ErrorActionPreference = "Stop"
try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch {}
try { Add-Type -AssemblyName System.Net.Primitives -ErrorAction SilentlyContinue } catch {}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-Bytes($url){
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $true; $handler.MaxAutomaticRedirections = 20; $handler.UseCookies = $true
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    $resp = $client.GetAsync($url).GetAwaiter().GetResult()
    $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    $status = [int]$resp.StatusCode
    $final = if ($resp.RequestMessage.RequestUri) { $resp.RequestMessage.RequestUri.AbsoluteUri } else { $url }
    $client.Dispose()
    return @{ status=$status; bytes=$bytes; final=$final }
}

$m = Get-Content $Manifest -Raw | ConvertFrom-Json
$results = New-Object System.Collections.ArrayList
$matchCount = 0; $mismatchCount = 0; $errorCount = 0

foreach($a in $m){
    $url = $a.source_url
    try {
        $r = Get-Bytes $url
        $h = (New-Object System.Security.Cryptography.SHA256Managed).ComputeHash($r.bytes)
        $sha = [System.BitConverter]::ToString($h).Replace("-","").ToLower()
        $same = ($sha -eq $a.sha256)
        if($same){ $matchCount++ } else { $mismatchCount++ }
        $rec = [ordered]@{
            role=$a.role; family=$a.family; source_registration_no=$a.source_registration_no
            source_url=$url; final_url=$r.final; http_status=$r.status
            run1_sha256=$a.sha256; run2_sha256=$sha; byte_size=$r.bytes.Length
            match=$same
        }
        [void]$results.Add($rec)
        Write-Output ("  " + $a.role + "  " + ($(if($same){"MATCH"}else{"MISMATCH"})) + "  sha=" + $sha.Substring(0,12))
    } catch {
        $errorCount++
        [void]$results.Add([ordered]@{ role=$a.role; family=$a.family; source_registration_no=$a.source_registration_no; source_url=$url; error=$_.Exception.Message; match=$false })
        Write-Output ("  " + $a.role + "  ERROR " + $_.Exception.Message)
    }
}

$results | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutDir "sha256_verify.json") -Encoding UTF8
Write-Output ("RESULT: match=$matchCount mismatch=$mismatchCount error=$errorCount  total=" + $results.Count)
