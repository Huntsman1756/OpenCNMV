param([string]$OutDir = "g0-r\R07-raw-retrieval\evidence")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem
$known = @{
  "SAN-FY2025"="20875"; "SAN-FY2024"="20509"
  "BBVA-FY2025"="20854"; "BBVA-FY2024"="20448"
  "IBE-FY2025"="20934"; "IBE-FY2024"="20515"
}
$rows = New-Object System.Collections.ArrayList
foreach($k in $known.Keys){
    $iss = $k.Split("-")[0]; $year = $k.Split("-")[1]
    $zipPath = Join-Path $OutDir ("esef-{0}-{1}-package.zip" -f $iss, $year)
    if(-not (Test-Path $zipPath)){ Write-Output ("MISS " + $zipPath); continue }
    $z = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    $xhtml = $z.Entries | Where-Object { $_.FullName -match '/reports/.*\.xhtml$' } | Select-Object -First 1
    $sr = ""; $title = ""
    if($xhtml){
        $reader = New-Object System.IO.StreamReader($xhtml.Open())
        $head = $reader.ReadToEnd()
        $reader.Close()
        $sr = [regex]::Match($head,'schemaRef[^>]*xlink:href="([^"]+)"').Groups[1].Value
        $title = [regex]::Match($head,'(?is)<title>([^<]*)</title>').Groups[1].Value
    }
    $z.Dispose()
    $h = (Get-FileHash -LiteralPath $zipPath -Algorithm SHA256).Hash
    [void]$rows.Add([ordered]@{
        role="ESEF_PACKAGE_ZIP_XBRL"; family="ESEF"; issuer=$iss; year=$year
        registro=$known[$k]; source_url=("(from ListadoIFA ?e=; see esef_components.json)")
        media_type="application/zip"; byte_size=(Get-Item $zipPath).Length; sha256=$h
        iXBRL_title=$title; iXBRL_schemaRef=$sr; evidence_path=$zipPath
    })
    Write-Output ("$k  registro=" + $known[$k] + "  title=" + $title + "  schemaRef=" + $sr)
}
$rows | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path (Split-Path $OutDir -Parent) "esef_packages.json") -Encoding UTF8
Write-Output ("written esef_packages.json count=" + $rows.Count)
