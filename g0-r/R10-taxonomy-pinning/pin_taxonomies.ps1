param([string]$Dir = "g0-r\R10-taxonomy-pinning")
$ErrorActionPreference = "Stop"
try { Add-Type -AssemblyName System.Net.Http -ErrorAction SilentlyContinue } catch {}
try { Add-Type -AssemblyName System.Net.Primitives -ErrorAction SilentlyContinue } catch {}
New-Item -ItemType Directory -Force -Path (Join-Path $Dir "evidence") | Out-Null

function Get-Http($url){
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $true; $handler.MaxAutomaticRedirections = 20
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.DefaultRequestHeaders.UserAgent.ParseAdd("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    $resp = $client.GetAsync($url).GetAwaiter().GetResult()
    $bytes = $resp.Content.ReadAsByteArrayAsync().GetAwaiter().GetResult()
    $media = if ($resp.Content.Headers.ContentType) { $resp.Content.Headers.ContentType.MediaType } else { "" }
    $status=[int]$resp.StatusCode
    $client.Dispose()
    return @{ status=$status; bytes=$bytes; media=$media }
}
function Sha256File($p){ return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash }

# --- packages to pin -------------------------------------------------------
$pkgs = @(
  @{ package="cnmv-ipp-2019-01-01"; source_url="https://www.cnmv.es/IPP/taxonomia/2019-01-01/ipp_2019-01-01.zip";
     file="cnmv-ipp_2019-01-01.zip"; taxonomy_version="2019-01-01"; filing_family="IPP";
     required_by="IPP corpus (15 IPP_XBRL artefacts): ipp_en (SAN/BBVA) + ipp_ge (IBE) entry points";
     must_contain=@("ipp_en_2019-01-01.xsd","ipp_ge_2019-01-01.xsd") },
  @{ package="esma-esef-2022"; source_url="https://www.esma.europa.eu/sites/default/files/2023-12/esef_taxonomy_2022_v1.1.zip";
     file="esef_taxonomy_2022_v1.1.zip"; taxonomy_version="2022-03-24"; filing_family="ESEF";
     required_by="ESEF FY2024 filings (SAN/BBVA/IBE) - esef_cor import https://www.esma.europa.eu/taxonomy/2022-03-24/esef_cor.xsd";
     must_contain=@("2022-03-24/esef_cor.xsd") },
  @{ package="esma-esef-2024"; source_url="https://www.esma.europa.eu/sites/default/files/2025-01/esef_taxonomy_2024.zip";
     file="esef_taxonomy_2024.zip"; taxonomy_version="2024-03-27"; filing_family="ESEF";
     required_by="ESEF FY2025 filings (SAN/BBVA/IBE) - esef_cor import https://www.esma.europa.eu/taxonomy/2024-03-27/esef_cor.xsd";
     must_contain=@("2024-03-27/esef_cor.xsd") }
)

# --- xbrl.org base schema files (imported by CNMV IPP + ESMA/issuer extensions) ---
$base = @(
  "http://www.xbrl.org/2003/xbrl-instance-2003-12-31.xsd",
  "http://www.xbrl.org/2003/xbrl-linkbase-2003-12-31.xsd",
  "http://www.xbrl.org/2005/xbrldt-2005.xsd",
  "http://www.xbrl.org/2006/xbrldi-2006.xsd",
  "https://www.xbrl.org/dtr/type/2020-01-21/types.xsd",
  "https://www.xbrl.org/dtr/type/2022-03-31/types.xsd",
  "http://www.xbrl.org/dtr/type/numeric-2009-12-16.xsd",
  "http://www.xbrl.org/dtr/type/nonNumeric-2009-12-16.xsd"
)

$rows = New-Object System.Collections.ArrayList
Add-Type -AssemblyName System.IO.Compression.FileSystem

# IPP package already preserved in R4 evidence -> reuse bytes, record pin
$ippRef = "g0-r\R04-artifact-url-stability\evidence\ipp_2019-01-01_run1.zip"
$ippDest = Join-Path $Dir ("evidence\" + $pkgs[0].file)
Copy-Item $ippRef $ippDest -Force
$ippSha = Sha256File $ippDest
$z=[System.IO.Compression.ZipFile]::OpenRead($ippDest)
$names=$z.Entries | ForEach-Object { $_.FullName }
$z.Dispose()
$ok = ($pkgs[0].must_contain | Where-Object { $n=$_; -not ($names | Where-Object { $_ -like "*$n" }) }).Count -eq 0
[void]$rows.Add([ordered]@{ package=$pkgs[0].package; source_url=$pkgs[0].source_url; retrieved_at="(preserved in R4, run1==run2 stable)";
  sha256=$ippSha; taxonomy_version=$pkgs[0].taxonomy_version; filing_family=$pkgs[0].filing_family;
  required_by=$pkgs[0].required_by; evidence_path=$ippDest; content_check=($ok) })
Write-Output ("PINNED " + $pkgs[0].package + " sha=" + $ippSha.Substring(0,12) + " contains_entry_points=" + $ok)

Start-Sleep -Seconds 20
foreach($p in $pkgs[1..2]){
    $r = Get-Http $p.source_url
    if($r.status -ne 200){ Write-Output ("FAIL " + $p.package + " http=" + $r.status); continue }
    $dest = Join-Path $Dir ("evidence\" + $p.file)
    [System.IO.File]::WriteAllBytes($dest, $r.bytes)
    $sha = Sha256File $dest
    $z=[System.IO.Compression.ZipFile]::OpenRead($dest)
    $names=$z.Entries | ForEach-Object { $_.FullName }
    $z.Dispose()
    $ok = ($p.must_contain | Where-Object { $n=$_; -not ($names | Where-Object { $_ -like "*$n" }) }).Count -eq 0
    [void]$rows.Add([ordered]@{ package=$p.package; source_url=$p.source_url; retrieved_at=(Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ");
      sha256=$sha; taxonomy_version=$p.taxonomy_version; filing_family=$p.filing_family;
      required_by=$p.required_by; evidence_path=$dest; content_check=($ok); media_type=$r.media; byte_size=$r.bytes.Length })
    Write-Output ("PINNED " + $p.package + " bytes=" + $r.bytes.Length + " sha=" + $sha.Substring(0,12) + " contains_expected_date=" + $ok)
    Start-Sleep -Seconds 20
}

foreach($u in $base){
    $fn = ($u -split '/')[-1]; $sub = ($u -replace '^https?://','') -replace '/','_'
    $dest = Join-Path $Dir ("evidence\xbrlorg_" + $sub)
    $r = Get-Http $u
    if($r.status -ne 200){ Write-Output ("FAIL " + $u + " http=" + $r.status); continue }
    [System.IO.File]::WriteAllBytes($dest, $r.bytes)
    $sha = Sha256File $dest
    $pkgName = "xbrl.org:" + ($u -replace '^https?://(www\.)?xbrl\.org/','')
    $ver = [regex]::Match($u,'(\d{4}(-\d{2}-\d{2})?)').Value
    [void]$rows.Add([ordered]@{ package=$pkgName; source_url=$u; retrieved_at=(Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ");
      sha256=$sha; taxonomy_version=$ver; filing_family="ALL";
      required_by="imported by CNMV IPP taxonomy and/or ESMA/issuer ESEF extensions"; evidence_path=$dest; media_type=$r.media; byte_size=$r.bytes.Length })
    Write-Output ("PINNED " + $fn + " bytes=" + $r.bytes.Length + " sha=" + $sha.Substring(0,12))
    Start-Sleep -Seconds 5
}

$rows | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Dir "taxonomy_manifest.json") -Encoding UTF8
Write-Output ("MANIFEST rows=" + $rows.Count)
