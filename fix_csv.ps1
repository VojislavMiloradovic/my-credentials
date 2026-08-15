# Simple CSV fix for LinkedIn
$csvPath = 'data/Certifications.csv'
$content = Get-Content $csvPath -Raw
$lines = $content -split "`n"
$header = $lines[0]
$delimiter = if ($header -like "*`t*") { "`t" } else { "," }

if ($header -notmatch 'retired') {
    $lines[0] = $header + $delimiter + 'retired'
}

$modified = 0
for ($i = 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match 'ae6b4ab2f3e25673ea0b882f5443d748f91855994ac4f6204d2b824e14bc51f4') {
        if ($lines[$i] -notmatch 'retired') {
            $lines[$i] = $lines[$i] + $delimiter + 'true'
            $modified++
        }
    }
}

if ($modified -gt 0) {
    $lines -join "`n" | Set-Content $csvPath -Encoding utf8
    Write-Host "Updated $modified item(s) in Certifications.csv"
} else {
    Write-Host "No matching item found"
}