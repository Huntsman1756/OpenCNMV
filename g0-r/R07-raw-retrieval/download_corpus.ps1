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
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $resp = $client.GetAsync($url).GetAwaiter().GetResult()
    $sw.Stop()
    $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    $final = if ($resp.RequestMessage.RequestUri) { $resp.RequestMessage.RequestUri.AbsoluteUri } else { $url }
    $media = if ($resp.Content.Headers.ContentType) { $resp.Content.Headers.ContentType.MediaType } else { "" }
    $status = [int]$resp.StatusCode
    $setCookies = @(); try { $setCookies += $resp.Headers.GetValues("Set-Cookie") } catch {}
    $client.Dispose()
    return @{ status=$status; bytes=$bytes; media=$media; final=$final; elapsed=$sw.ElapsedMilliseconds; cookies=($setCookies -join '; ') }
}

function Save-Artefact($url, $dest, $meta, $nreg, $role, $family){
    [System.IO.File]::WriteAllBytes($dest, $meta.bytes)
    $sha = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash
    return [ordered]@{
        role=$role; family=$family; source_registration_no=$nreg
        source_url=$url; final_url=$meta.final; retrieved_at=(Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
        http_status=$meta.status; media_type=$meta.media; byte_size=$meta.bytes.Length
        elapsed_ms=$meta.elapsed; set_cookie=($meta.cookies); sha256=$sha
        evidence_path=$dest
    }
}

function Get-Text($raw){ return ([System.Net.WebUtility]::HtmlDecode([regex]::Replace($raw,'(?s)<[^>]+>',' ')) -replace '\s+',' ') }

$issuers = @(
    @{ t="SAN"; nif="A39000013" },
    @{ t="BBVA"; nif="A48265169" },
    @{ t="IBE"; nif="A-48010615" }
)

$targetIpp = @("I semestre de 2026","II semestre de 2025","I semestre de 2025","II semestre de 2024","I semestre de 2024")
$targetEsef = @("31/12/2025","31/12/2024")

$manifest = New-Object System.Collections.ArrayList

foreach($iss in $issuers){
    $t = $iss.t; $nif = $iss.nif
    Write-Output ("==== " + $t + " (nif=" + $nif + ") ====")

    # ---- IPP ----
    $listUrl = "$Base/portal/consultas/ifi/listaifi?lang=es&nif=$nif"
    $list = Get-Http $listUrl
    $listText = [System.Text.Encoding]::UTF8.GetString($list.bytes)
    # map period label -> nreg by scanning rows
    $nregByPeriod = @{}
    foreach($row in [regex]::Matches($listText,'(?is)<tr[^>]*>(.*?)</tr>')){
        $r = $row.Groups[1].Value
        $nregM = [regex]::Match($r,'nreg=(\d+)')
        $labelM = [regex]::Match($r,'(?i)(I|II)\s+semestre\s+de\s+(\d{4})')
        if($nregM.Success -and $labelM.Success){
            $lbl = $labelM.Groups[1].Value + " semestre de " + $labelM.Groups[2].Value
            $nregByPeriod[$lbl] = $nregM.Groups[1].Value
        }
    }
    Write-Output ("  IPP rows mapped: " + $nregByPeriod.Count)

    foreach($per in $targetIpp){
        $nreg = $nregByPeriod[$per]
        if(-not $nreg){ Write-Output ("    MISS nreg for " + $per); continue }
        $detailUrl = "$Base/portal/aldia/detalleifialdia.aspx?nreg=$nreg"
        $det = Get-Http $detailUrl
        $detText = [System.Text.Encoding]::UTF8.GetString($det.bytes)
        $g = [regex]::Match($detText,'descargaxbrlipp\.ashx\?t=\{[0-9a-f-]{36}\}').Value
        $guid = [regex]::Match($g,'\{([0-9a-f-]{36})\}').Groups[1].Value
        if(-not $guid){ Write-Output ("    MISS GUID for nreg=$nreg"); continue }
        $dlUrl = "$Base/portal/consultas/wuc/descargaxbrlipp.ashx?t=%7b$guid%7d"
        $meta = Get-Http $dlUrl
        $dest = Join-Path $OutDir ("ipp-{0}-{1}.zip" -f $t, ($per -replace ' ','-'))
        $rec = Save-Artefact $dlUrl $dest $meta $nreg "IPP_XBRL" "IPP"
        [void]$manifest.Add($rec)
        Write-Output ("    IPP " + $per + " -> nreg=" + $nreg + " bytes=" + $rec.byte_size + " sha=" + $rec.sha256.Substring(0,12))
    }

    # ---- ESEF ----
    $lUrl = "$Base/Portal/Consultas/IFA/ListadoIFA?id=0&lang=es&nif=$nif"
    $l = Get-Http $lUrl
    $lText = [System.Text.Encoding]::UTF8.GetString($l.bytes)
    # map fecha estados financieros -> first ?e= token in the same row
    $tokByDate = @{}
    foreach($row in [regex]::Matches($lText,'(?is)<tr[^>]*>(.*?)</tr>')){
        $r = $row.Groups[1].Value
        $dateM = [regex]::Match($r,'(?i)(31/12/\d{4})')
        $tokM = [regex]::Match($r,'ver\?e=([A-Za-z0-9%+/\-]+)')
        if($dateM.Success -and $tokM.Success){
            $tokByDate[$dateM.Groups[1].Value] = $tokM.Groups[1].Value
        }
    }
    Write-Output ("  ESEF rows mapped: " + $tokByDate.Count)

    foreach($d in $targetEsef){
        $tok = $tokByDate[$d]
        if(-not $tok){ Write-Output ("    MISS token for " + $d); continue }
        $dlUrl = "$Base/webservices/verdocumento/ver?e=$tok"
        $meta = Get-Http $dlUrl
        $year = $d.Substring(6)
        $dest = Join-Path $OutDir ("esef-{0}-FY{1}.zip" -f $t, $year)
        $rec = Save-Artefact $dlUrl $dest $meta "registro-$t-FY$year" "ESEF_IXBRL" "ESEF"
        [void]$manifest.Add($rec)
        Write-Output ("    ESEF " + $d + " -> bytes=" + $rec.byte_size + " sha=" + $rec.sha256.Substring(0,12))
    }
}

$manifestPath = Join-Path (Split-Path $OutDir -Parent) "artifact_manifest.json"
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Write-Output ("MANIFEST: " + $manifestPath + "  artefacts=" + $manifest.Count)
