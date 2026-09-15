param([string]$Manifest = "g0-r\R07-raw-retrieval\artifact_manifest.json")
$ErrorActionPreference = "Stop"
$m = Get-Content $Manifest -Raw | ConvertFrom-Json
$comps = Get-Content "g0-r\R07-raw-retrieval\esef_components.json" -Raw | ConvertFrom-Json
$pkgs  = Get-Content "g0-r\R07-raw-retrieval\esef_packages.json" -Raw | ConvertFrom-Json
$out = New-Object System.Collections.ArrayList

foreach($a in $m){
    if($a.family -eq "ESEF" -and $a.role -eq "ESEF_IXBRL"){
        $a.role = "ESEF_COVER"
        $a | Add-Member -NotePropertyName note -NotePropertyValue "reclassified from ESEF_IXBRL (was the Portada/cover, not iXBRL)" -Force
    }
    [void]$out.Add($a)
}
# add the 6 ZIP/Xbri packages
foreach($p in $pkgs){
    $comp = $comps | Where-Object { $_.role -eq "ESEF_PACKAGE_ZIP_XBRL" -and $_.issuer -eq $p.issuer -and $_.year -eq $p.year } | Select-Object -First 1
    [void]$out.Add([ordered]@{
        role="ESEF_PACKAGE_ZIP_XBRL"; family="ESEF"; issuer=$p.issuer; year=$p.year
        source_registration_no=$p.registro; source_url=($comp.source_url); final_url=""
        retrieved_at=(Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ"); http_status=200
        media_type="application/zip"; byte_size=$p.byte_size; set_cookie=""
        sha256=$p.sha256; iXBRL_title=$p.iXBRL_title; iXBRL_schemaRef=$p.iXBRL_schemaRef
        evidence_path=$p.evidence_path
    })
}
$out | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $Manifest -Encoding UTF8
Write-Output ("updated manifest artefacts=" + $out.Count + "  (IPP=" + ($out|Where-Object{$_.family -eq 'IPP'}).Count + " ESEF_COVER=" + ($out|Where-Object{$_.role -eq 'ESEF_COVER'}).Count + " ESEF_PACKAGE=" + ($out|Where-Object{$_.role -eq 'ESEF_PACKAGE_ZIP_XBRL'}).Count + ")")
