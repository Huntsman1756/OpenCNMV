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
    # extract all ?e= tokens in order (per row: Individual, Consolidada, ZIP/Xbri)
    $toks = @([regex]::Matches($text,'ver\?e=([A-Za-z0-9%+/\-]+)') | ForEach-Object { $_.Groups[1].Value })
    $regs = @([regex]::Matches($text,'(?i)>(\d{5})<') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
    Write-Output ("  tokens=" + $toks.Count + "  regs=" + ($regs -join ','))
    # target: FY2025 = tokens[0..2], FY2024 = tokens[3..5]
    $targets = @(
        @{ year="FY2025"; base=0 },
        @{ year="FY2024"; base=3 }
    )
    foreach($tg in $targets){
        $b = $tg.base
        $ind = $toks[$b]; $con = $toks[$b+1]; $zip = $toks[$b+2]
        $reg = $regs[$b/3]  # registro official for this row
        Write-Output ("  " + $tg.year + "  registro=" + $reg)
        # --- ZIP/Xbri package (raw, preserve) ---
        $zipUrl = "$Base/webservices/verdocumento/ver?e=$zip"
        $zm = Get-Http $zipUrl
        $dest = Join-Path $OutDir ("esef-{0}-{1}-package.zip" -f $t, $tg.year)
        [System.IO.File]::WriteAllBytes($dest, $zm.bytes)
        $zsha = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
        [void]$components.Add([ordered]@{ role="ESEF_PACKAGE_ZIP_XBRL"; family="ESEF"; issuer=$t; year=$tg.year; registro=$reg; source_url=$zipUrl; media_type=$zm.media; byte_size=$zm.bytes.Length; sha256=$zsha; evidence_path=$dest })
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
        [void]$components.Add([ordered]@{ role="IXBRL_CONSOLIDATED"; family="ESEF"; issuer=$t; year=$tg.year; registro=$reg; source_url=$conUrl; media_type=$cm1.media; byte_size=$cm1.bytes.Length; sha256_run1=$sha1h; sha256_run2=$sha2h; stable=($sha1h -eq $sha2h); schemaRef=$sr; evidence_path=$null })
        Write-Output ("    IXBRL con bytes=" + $cm1.bytes.Length + " sha_run1=" + $sha1h.Substring(0,12) + " stable=" + ($sha1h -eq $sha2h) + " schemaRef=" + $sr)
    }
}

$out = Join-Path (Split-Path $OutDir -Parent) "esef_components.json"
$components | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $out -Encoding UTF8
Write-Output ("COMPONENTS: " + $out + "  count=" + $components.Count)
