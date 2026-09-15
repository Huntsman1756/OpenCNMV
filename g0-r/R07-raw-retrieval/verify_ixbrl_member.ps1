param([string]$Dir = "g0-r\R07-raw-retrieval")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.IO.Compression.FileSystem

# Proves that the iXBRL report inside each ESEF_PACKAGE_ZIP_XBRL is byte-identical
# to the standalone consolidated XHTML served directly by the CNMV ?e= link.
# If byte_equal = true for all six, IXBRL_CONSOLIDATED is modelled as
# "package member + direct CNMV view" (option B), not a separately persisted artefact.

$comps = Get-Content (Join-Path $Dir "esef_components.json") -Raw | ConvertFrom-Json
$results = New-Object System.Collections.ArrayList

foreach($pkg in ($comps | Where-Object { $_.role -eq "ESEF_PACKAGE_ZIP_XBRL" })){
    $con = $comps | Where-Object { $_.role -eq "IXBRL_CONSOLIDATED" -and $_.issuer -eq $pkg.issuer -and $_.year -eq $pkg.year } | Select-Object -First 1
    $z = [System.IO.Compression.ZipFile]::OpenRead($pkg.evidence_path)
    $xhtml = $z.Entries | Where-Object { $_.FullName -match '/reports/.*\.xhtml$' } | Select-Object -First 1
    $memberSha = ""
    if($xhtml){
        $ms = New-Object System.IO.MemoryStream
        $s = $xhtml.Open(); $s.CopyTo($ms); $s.Close()
        $memberSha = [System.BitConverter]::ToString((New-Object System.Security.Cryptography.SHA256Managed).ComputeHash($ms.ToArray())).Replace("-","")
        $ms.Dispose()
    }
    $z.Dispose()
    $directSha = $con.sha256_run1
    $equal = ($memberSha -ieq $directSha)
    [void]$results.Add([ordered]@{
        issuer=$pkg.issuer; year=$pkg.year; registro=$pkg.registro
        package=$pkg.evidence_path; package_sha256=$pkg.sha256
        package_member_path=($xhtml.FullName); member_sha256=$memberSha
        direct_ixbrl_sha256=$directSha; byte_equal=$equal
    })
    Write-Output ("  " + $pkg.issuer + " " + $pkg.year + "  member=" + $xhtml.FullName + "  byte_equal=" + $equal)
}

# write equality evidence + enrich esef_components.json IXBRL_CONSOLIDATED entries
$results | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Dir "ixbrl_member_equality.json") -Encoding UTF8
foreach($r in $results){
    $con = $comps | Where-Object { $_.role -eq "IXBRL_CONSOLIDATED" -and $_.issuer -eq $r.issuer -and $_.year -eq $r.year } | Select-Object -First 1
    $con | Add-Member -NotePropertyName package_member_path -NotePropertyValue $r.package_member_path -Force
    $con | Add-Member -NotePropertyName member_sha256 -NotePropertyValue $r.member_sha256 -Force
    $con | Add-Member -NotePropertyName byte_equal -NotePropertyValue $r.byte_equal -Force
}
$comps | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $Dir "esef_components.json") -Encoding UTF8
$allEq = ($results | Where-Object { -not $_.byte_equal }).Count -eq 0
Write-Output ("RESULT: " + $results.Count + " packages checked; all byte_equal=" + $allEq)
