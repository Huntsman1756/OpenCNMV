param(
    [Parameter(Mandatory=$true)][string]$Base,
    [Parameter(Mandatory=$true)][string]$Denominacion,
    [string]$OutFile = "g0-r\_probe-logs\cj-result.html"
)
$dir = Split-Path $OutFile -Parent
$jar = Join-Path $dir "cj-cookies.txt"
$page = Join-Path $dir "cj-page.html"
$bodyFile = Join-Path $dir "cj-body.txt"
Remove-Item -LiteralPath $jar, $page, $bodyFile, $OutFile -ErrorAction SilentlyContinue

# Step 1: GET the page, save cookies + page
curl.exe -s -L -c $jar -A "Mozilla/5.0" -o $page $Base | Out-Null
$raw = [System.IO.File]::ReadAllText($page)
$vs  = [regex]::Match($raw, 'id="__VIEWSTATE"[^>]*value="([^"]*)"').Groups[1].Value
$vsg = [regex]::Match($raw, 'id="__VIEWSTATEGENERATOR"[^>]*value="([^"]*)"').Groups[1].Value
$ev  = [regex]::Match($raw, 'id="__EVENTVALIDATION"[^>]*value="([^"]*)"').Groups[1].Value
Write-Output ("vsLen=$($vs.Length) vsg=$vsg evLen=$($ev.Length)")

function Enc($s) { return [System.Net.WebUtility]::UrlEncode($s) }
$body = "__VIEWSTATE=$(Enc $vs)&__VIEWSTATEGENERATOR=$(Enc $vsg)&__EVENTVALIDATION=$(Enc $ev)&ctl00`$ContentPrincipal`$wNombreEntidad`$txtDenominacion=$(Enc $Denominacion)&ctl00`$ContentPrincipal`$btnOk=$(Enc 'Buscar')"
[System.IO.File]::WriteAllText($bodyFile, $body, [System.Text.Encoding]::UTF8)

curl.exe -s -L -b $jar -c $jar -A "Mozilla/5.0" -e $Base --data-binary "@$bodyFile" -o $OutFile $Base | Out-Null
Write-Output ("curlExit=$LASTEXITCODE")
$res = [System.IO.File]::ReadAllText($OutFile)
Write-Output ("resultLen=$($res.Length)")
Write-Output ("containsDenom=$($res.Contains($Denominacion))")
Write-Output ("tables=$(([regex]::Matches($res,'(?i)<table')).Count)")
