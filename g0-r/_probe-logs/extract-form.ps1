param([Parameter(Mandatory=$true)][string]$InFile)
$raw = [System.IO.File]::ReadAllText($InFile)
# Isolate main content region
$m = [regex]::Match($raw, '(?is)<h1 id="ctl00_H1">.*?</h1>(.*?)(<div class="col-', 'Singleline')
$content = if ($m.Success) { $m.Groups[1].Value } else { $raw }
# Links
Write-Output "== LINKS (href + text) =="
foreach ($mm in [regex]::Matches($content, '(?is)<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>')) {
    $text = [System.Net.WebUtility]::HtmlDecode([regex]::Replace($mm.Groups[2].Value, '(?s)<[^>]+>',' ')).Trim() -replace '\s+',' '
    Write-Output ("  " + $mm.Groups[1].Value + "  ::  " + $text)
}
# Form controls
Write-Output "== FORM CONTROLS =="
foreach ($mm in [regex]::Matches($content, '(?is)<(input|select|option|textarea|button)[^>]*>')) {
    $t = $mm.Value
    $name = [regex]::Match($t, 'name="([^"]*)"').Groups[1].Value
    $id = [regex]::Match($t, 'id="([^"]*)"').Groups[1].Value
    $val = [regex]::Match($t, 'value="([^"]*)"').Groups[1].Value
    if ($name -ne "" -or $val -ne "") { Write-Output ("  [" + $mm.Groups[1].Value + "] name=" + $name + " id=" + $id + " value=" + $val) }
}
Write-Output "== FORMS =="
foreach ($mm in [regex]::Matches($content, '(?is)<form[^>]*>')) { Write-Output ("  " + $mm.Value) }
