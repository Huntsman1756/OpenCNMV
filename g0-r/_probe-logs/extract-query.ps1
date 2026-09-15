param([Parameter(Mandatory=$true)][string]$InFile)
$raw = [System.IO.File]::ReadAllText($InFile)
# take region after the main content marker
$idx = $raw.IndexOf("#maincontent")
if ($idx -ge 0) { $content = $raw.Substring($idx) } else { $content = $raw }
$formM = [regex]::Match($content, '(?is)<form[^>]*>')
if ($formM.Success) { Write-Output ("FORM: " + $formM.Value) }
Write-Output "== CONTROLS (non-hidden) =="
foreach ($mm in [regex]::Matches($content, '(?i)<(input|select|textarea|button|a)[^>]*>')) {
    $t = $mm.Value
    if ($t -match '(?i)type="hidden"') { continue }
    $name = [regex]::Match($t, 'name="([^"]*)"').Groups[1].Value
    if ($name -eq "") { continue }
    $txt = [regex]::Match($t, '(?i)value="([^"]*)"').Groups[1].Value
    if ($txt -eq "") { $txt = [regex]::Match($t, '(?i)title="([^"]*)"').Groups[1].Value }
    Write-Output ("  " + $mm.Groups[1].Value.ToUpper() + " :: name=" + $name + " :: " + $txt)
}
Write-Output "== OPTION TEXTS =="
foreach ($mm in [regex]::Matches($content, '(?is)<option[^>]*>([^<]*)</option>')) {
    $t = [System.Net.WebUtility]::HtmlDecode($mm.Groups[1].Value).Trim()
    if ($t -ne "") { Write-Output ("  " + $t) }
}
