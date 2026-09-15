param([string]$Base = "https://www.cnmv.es", [string]$OutDir = "g0-r\R07-raw-retrieval\evidence")
$ErrorActionPreference = "Stop"
try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch {}
try { Add-Type -AssemblyName System.Net.Primitives -ErrorAction SilentlyContinue } catch {}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

function Get-Http($url){
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $true; $handler.MaxAutomaticRedirections = 20; $handler.UseCookies = $true
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    $resp = $client.GetAsync($url).GetAwaiter().GetResult()
    $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    $final = if ($resp.RequestMessage.RequestUri) { $resp.RequestMessage.RequestUri.AbsoluteUri } else { $url }
    $media = if ($resp.Content.Headers.ContentType) { $resp.Content.Headers.ContentType.MediaType } else { "" }
    $client.Dispose()
    return @{ status=[int]$resp.StatusCode; bytes=$bytes; media=$media; final=$final }
}

$issuers = @(
    @{ t="SAN"; nif="A39000013" },
    @{ t="BBVA"; nif="A48265169" },
    @{ t="IBE"; nif="A-48010615" }
)
$components = New-Object System.Collections.ArrayList

foreach($iss in $issuers){
    $t = $iss.t; $nif = $iss.nif
    Write-Output ("==== " + $t + " ====")
    $l = Get-Http "$Base/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif=$nif"
    $text = [System.Text.Encoding]::UTF8.GetString($l.bytes)
    # Per-row parse: registro oficial cell + ?e= tokens must come from the SAME <tr>.
    # (A page-global '>(\d{5})<' matches the AUDITA column links /AUDITA/<year>/<reg>.pdf,
    #  not the registro oficial cell, which contains whitespace.)
    $rowData = @{}
    foreach($row in [regex]::Matches($text,'(?is)<tr[^>]*>(.*?)</tr>')){
        $r = $row.Groups[1].Value
        $dateM = [regex]::Match($r,'(?i)31/12/(\d{4})')
        $rowToks = @([regex]::Matches($r,'ver\?e=([A-Za-z0-9%+/\-]+)') | ForEach-Object { $_.Groups[1].Value })
        $regM = [regex]::Match($r,'<td[^>]*>\s*(\d{4,6})\s*</td>')
        if($dateM.Success -and $rowToks.Count -ge 3 -and $regM.Success){
            $rowData["FY" + $dateM.Groups[1].Value] = @{ reg=$regM.Groups[1].Value; toks=$rowToks }
        }
    }
    Write-Output ("  rows mapped: " + $rowData.Keys.Count)
    foreach($tg in @("FY2025","FY2024")){
        if(-not $rowData.ContainsKey($tg)){ Write-Output ("  MISS row for " + $tg); continue }
        $ind = $rowData[$tg].toks[0]; $con = $rowData[$tg].toks[1]; $zip = $rowData[$tg].toks[2]
        $reg = $rowData[$tg].reg  # registro oficial from the same row
        Write-Output ("  " + $tg + "  registro=" + $reg)
        # --- ZIP/Xbri package (raw, preserve) ---
        $zipUrl = "$Base/webservices/verdocumento/ver?e=$zip"
        $zm = Get-Http $zipUrl
        $dest = Join-Path $OutDir ("esef-{0}-{1}-package.zip" -f $t, $tg)
        [System.IO.File]::WriteAllBytes($dest, $zm.bytes)
        $zsha = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
        [void]$components.Add([ordered]@{ role="ESEF_PACKAGE_ZIP_XBRL"; family="ESEF"; issuer=$t; year=$tg; registro=$reg; source_url=$zipUrl; media_type=$zm.media; byte_size=$zm.bytes.Length; sha256=$zsha; evidence_path=$dest })
        Write-Output ("    ZIP pkg bytes=" + $zm.bytes.Length + " sha=" + $zsha.Substring(0,12))
        # --- Consolidated iXBRL (real report) twice for R4 + schemaRef ---
        $conUrl = "$Base/webservices/verdocumento/ver?e=$con"
        $cm1 = Get-Http $conUrl
        $cm2 = Get-Http $conUrl
        $sha1 = (New-Object System.Security.Cryptography.SHA256Managed).ComputeHash($cm1.bytes)
        $sha1h = [System.BitConverter]::ToString($sha1).Replace("-","").ToLower()
        $sha2 = (New-Object System.Security.Cryptography.SHA256Managed).ComputeHash($cm2.bytes)
        $sha2h = [System.BitConverter]::ToString($sha2).Replace("-","").ToLower()
        $head = [System.Text.Encoding]::UTF8.GetString($cm1.bytes,0,[Math]::Min(200000,$cm1.bytes.Length))
        $sr = [regex]::Match($head,'schemaRef[^>]*xlink:href="([^"]+)"').Groups[1].Value
        [void]$components.Add([ordered]@{ role="IXBRL_CONSOLIDATED"; family="ESEF"; issuer=$t; year=$tg; registro=$reg; source_url=$conUrl; media_type=$cm1.media; byte_size=$cm1.bytes.Length; sha256_run1=$sha1h; sha256_run2=$sha2h; stable=($sha1h -eq $sha2h); schemaRef=$sr; evidence_path=$null })
        Write-Output ("    IXBRL con bytes=" + $cm1.bytes.Length + " sha_run1=" + $sha1h.Substring(0,12) + " stable=" + ($sha1h -eq $sha2h) + " schemaRef=" + $sr)
    }
}

$out = Join-Path (Split-Path $OutDir -Parent) "esef_components.json"
$components | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Output ("COMPONENTS: " + $out + "  count=" + $components.Count)
