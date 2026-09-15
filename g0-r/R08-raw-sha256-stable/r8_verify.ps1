param([string]$Manifest = "g0-r\R07-raw-retrieval\artifact_manifest.json", [string]$Base = "https://www.cnmv.es", [string]$OutDir = "g0-r\R08-raw-sha256-stable\evidence")
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
    $client.Dispose()
    return @{ status=$status; bytes=$bytes }
}
function ShaOf($b){ return [System.BitConverter]::ToString((New-Object System.Security.Cryptography.SHA256Managed).ComputeHash($b)).Replace("-","").ToLower() }

$m = Get-Content $Manifest -Raw | ConvertFrom-Json
$results = New-Object System.Collections.ArrayList
$match=0; $mismatch=0; $errCount=0

foreach($a in $m){
    $url = $a.source_url
    try {
        $bytes = $null
        if($a.family -eq "IPP"){
            # IPP ?t={GUID} is ephemeral; re-resolve via nreg -> detail -> fresh GUID
            $nreg = $a.source_registration_no
            $det = Get-Bytes "$Base/portal/aldia/detalleifialdia.aspx?nreg=$nreg"
            $detText = [System.Text.Encoding]::UTF8.GetString($det.bytes)
            $g = [regex]::Match($detText,'descargaxbrlipp\.ashx\?t=\{[0-9a-f-]{36}\}').Value
            $guid = [regex]::Match($g,'\{([0-9a-f-]{36})\}').Groups[1].Value
            if(-not $guid){ throw "no GUID for nreg=$nreg" }
            $dl = Get-Bytes "$Base/portal/consultas/wuc/descargaxbrlipp.ashx?t=%7b$guid%7d"
            $bytes = $dl.bytes
            $url = "$Base/portal/consultas/wuc/descargaxbrlipp.ashx?t=%7b$guid%7d"
        } else {
            $dl = Get-Bytes $url
            $bytes = $dl.bytes
        }
        $sha = ShaOf $bytes
        $same = ($sha -eq $a.sha256)
        if($same){ $match++ } else { $mismatch++ }
        [void]$results.Add([ordered]@{ role=$a.role; family=$a.family; source_registration_no=$a.source_registration_no; source_url=$url; run1_sha256=$a.sha256; run2_sha256=$sha; byte_size=$bytes.Length; match=$same })
        Write-Output ("  " + $a.role + " " + $(if($same){"MATCH"}else{"MISMATCH"}) + " sha=" + $sha.Substring(0,12))
    } catch {
        $errCount++
        [void]$results.Add([ordered]@{ role=$a.role; family=$a.family; source_registration_no=$a.source_registration_no; error=$_.Exception.Message; match=$false })
        Write-Output ("  " + $a.role + " ERROR " + $_.Exception.Message)
    }
}
$results | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutDir "sha256_verify.json") -Encoding UTF8
Write-Output ("RESULT: match=$match mismatch=$mismatch error=$errCount total=" + $results.Count)


