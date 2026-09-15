param(
    [Parameter(Mandatory=$true)][string]$InFile,
    [string]$OutFile = ""
)
$ErrorActionPreference = "Stop"
$raw = [System.IO.File]::ReadAllText($InFile)
# Remove script/style blocks
$raw = [regex]::Replace($raw, '(?is)<script.*?</script>', ' ')
$raw = [regex]::Replace($raw, '(?is)<style.*?</style>', ' ')
# Replace block breaks with newline
$raw = [regex]::Replace($raw, '(?is)</(p|div|li|h1|h2|h3|h4|h5|tr|td|th|br)>', "`n")
$raw = [regex]::Replace($raw, '(?i)<br\s*/?>', "`n")
# Strip remaining tags
$raw = [regex]::Replace($raw, '(?s)<[^>]+>', ' ')
# Decode entities
$raw = [System.Net.WebUtility]::HtmlDecode($raw)
# Collapse whitespace per line
$lines = $raw -split "`n" | ForEach-Object { ($_ -replace '[ \t]+',' ').Trim() } | Where-Object { $_ -ne "" }
$text = $lines -join "`n"
if ($OutFile -eq "") { $OutFile = [System.IO.Path]::ChangeExtension($InFile, ".txt") }
[System.IO.File]::WriteAllText($OutFile, $text, [System.Text.Encoding]::UTF8)
Write-Output ("TEXT_FILE: " + $OutFile)
Write-Output ("TEXT_LEN: " + $text.Length)
