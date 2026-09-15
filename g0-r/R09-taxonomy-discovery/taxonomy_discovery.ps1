param([string]$Manifest = "g0-r\R07-raw-retrieval\artifact_manifest.json", [string]$OutDir = "g0-r\R09-taxonomy-discovery\evidence")
$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$m = Get-Content $Manifest -Raw | ConvertFrom-Json
$rows = New-Object System.Collections.ArrayList

foreach($a in $m){
    $path = $a.evidence_path
    if(-not (Test-Path $path)){ $path = Join-Path "g0-r\R07-raw-retrieval\evidence" ([System.IO.Path]::GetFileName($a.evidence_path)) }
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $head = [System.Text.Encoding]::UTF8.GetString($bytes,0,[Math]::Min(5000,$bytes.Length))
    $isZip = ($bytes.Length -ge 4 -and $bytes[0] -eq 0x50 -and $bytes[1] -eq 0x4b)

    $rec = [ordered]@{
        artifact=[System.IO.Path]::GetFileName($path); family=$a.family; issuer=($a.source_registration_no -replace '^[^A-Z]+' -replace '-.*$' -replace '[0-9].*$',''); 
    }
    # issuer derived from evidence path naming
    $rec.issuer = if($path -match '(SAN|BBVA|IBE)'){ $matches[1] } else { "" }
    $rec.source_registration_no = $a.source_registration_no
    $rec.role = $a.role

    if($a.family -eq "IPP"){
        $sr = [regex]::Match($head,'schemaRef[^>]*xlink:href="([^"]+)"').Groups[1].Value
        $ns = [regex]::Match($head,'xmlns:(ipp_en|ipp_ge)="([^"]+)"')
        $nsName = $ns.Groups[1].Value; $nsUri = $ns.Groups[2].Value
        $dim = [regex]::Match($head,'xmlns:ipp_en_dim="([^"]+)"').Groups[1].Value
        $rec.content_kind = "XBRL_XML"; $rec.is_zip = $isZip
        $rec.schemaRef = $sr; $rec.namespace = $nsUri; $rec.namespace_prefix = $nsName
        $rec.taxonomy_version = ($sr -replace '.*?(\d{4}-\d{2}-\d{2}).*','$1')
        $rec.model = if($nsName -eq 'ipp_en'){ 'ipp_en (entidades/credit model)' } elseif($nsName -eq 'ipp_ge'){ 'ipp_ge (general model)' } else { $nsName }
        $rec.taxonomy_ns = $nsUri; $rec.dim_ns = $dim
        $rec.entity_scheme = [regex]::Match($head,'identifier scheme="([^"]+)"').Groups[1].Value
        $rec.dependencies = "Arelle + CNMV IPP taxonomy package ($($rec.taxonomy_version))"
    } elseif($a.family -eq "ESEF"){
        $rec.is_zip = $isZip
        if($a.role -eq "ESEF_PACKAGE_ZIP_XBRL" -and $isZip){
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $z = [System.IO.Compression.ZipFile]::OpenRead($path)
            $xhtml = $z.Entries | Where-Object { $_.FullName -match '/reports/.*\.xhtml$' } | Select-Object -First 1
            $inner = ""
            if($xhtml){
                $reader = New-Object System.IO.StreamReader($xhtml.Open())
                $inner = $reader.ReadToEnd(); $reader.Close()
            }
            $z.Dispose()
            $hasIx = $inner.Contains("ix:"); $hasSr = $inner.Contains("schemaRef")
            $rec.content_kind = "ESEF_ZIP_PACKAGE"
            $rec.report_inside = if($xhtml){ $xhtml.FullName } else { "" }
            $rec.schemaRef = [regex]::Match($inner,'schemaRef[^>]*xlink:href="([^"]+)"').Groups[1].Value
            $rec.has_ix = $hasIx; $rec.has_schemaRef = $hasSr
            $rec.model = "ESEF (ESMA + issuer extension taxonomy)"
            $rec.dependencies = "Self-contained: iXBRL report + issuer extension taxonomy + META-INF inside the package"
            $rec.note = "schemaRef observed in the embedded report ($($rec.report_inside))."
        } else {
            $hasIx = $head.Contains("ix:"); $hasSr = $head.Contains("schemaRef")
            $rec.content_kind = if($hasIx -or $hasSr){ "INLINE_XBRL_XHTML" } else { "XHTML_COVER_ONLY" }
            $rec.schemaRef = [regex]::Match($head,'schemaRef[^>]*xlink:href="([^"]+)"').Groups[1].Value
            $rec.has_ix = $hasIx; $rec.has_schemaRef = $hasSr
            $rec.model = "ESEF (ESMA + issuer extension taxonomy)"
            $rec.dependencies = "Arelle + ESMA ESEF base taxonomy + issuer extension taxonomy (see ZIP/Xbri package)"
            if(-not $hasIx -and -not $hasSr){
                $rec.note = "The downloaded ?e= artefact is the cover page (no inline XBRL), served by the row's first component link. The iXBRL report (with schemaRef) and the ZIP/Xbri package are separate components in the same ListadoIFA row."
            }
        }
    }
    [void]$rows.Add($rec)
}

$rows | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $OutDir "taxonomy_matrix.json") -Encoding UTF8
# CSV
$csv = $rows | ConvertTo-Csv -NoTypeInformation
[System.IO.File]::WriteAllText((Join-Path $OutDir "taxonomy_matrix.csv"), ($csv -join "`r`n"), [System.Text.Encoding]::UTF8)
Write-Output ("matrix rows=" + $rows.Count)
$rows | ForEach-Object { Write-Output ("  " + $_.artifact + "  " + $_.family + "  model=" + $_.model + "  ver=" + $_.taxonomy_version + "  ns=" + $_.namespace_prefix) }
