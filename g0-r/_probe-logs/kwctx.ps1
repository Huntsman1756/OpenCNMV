param([Parameter(Mandatory=$true)][string]$File, [string[]]$Keywords = @("sustitu","revis","Observacion"))
$raw = [System.IO.File]::ReadAllText($File)
foreach($k in $Keywords){
  $pat = '(?is)' + [regex]::Escape($k) + '.{0,140}'
  $ms = [regex]::Matches($raw, $pat)
  Write-Output ("=== '" + $k + "' hits=" + $ms.Count)
  foreach($m in $ms){
    $txt = [System.Net.WebUtility]::HtmlDecode([regex]::Replace($m.Value,'(?s)<[^>]+>',' ')) -replace '\s+',' '
    Write-Output ("   " + $txt)
  }
}
