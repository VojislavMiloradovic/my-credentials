# PowerShell script to mark retired items

# 1. Mark MS Learn dead item as retired
Write-Host "Processing microsoft-learn.json..."
$json = Get-Content data/microsoft-learn.json -Raw | ConvertFrom-Json

# Find the item with sourceId "learn.viva-glint-360-feedback"
$found = $false
# The data appears to be an object with nested arrays, need to traverse
# Based on the structure, it's in the top-level array/object

# Let's check if it's an array or object
if ($json -is [Array]) {
    foreach ($item in $json) {
        if ($item.sourceId -eq 'learn.viva-glint-360-feedback') {
            $item | Add-Member -MemberType NoteProperty -Name "retired" -Value $true -Force
            $found = $true
            Write-Host "  Marked retired: $($item.sourceId)"
        }
    }
} else {
    # It's an object, need to find the right property
    # The output shows it's in a complex nested structure
    # Let's use a recursive approach
    function Set-Retired {
        param($obj)
        if ($null -eq $obj) { return }
        if ($obj -is [Array]) {
            foreach ($item in $obj) { Set-Retired $item }
        } elseif ($obj -is [PSCustomObject]) {
            if ($obj.sourceId -eq 'learn.viva-glint-360-feedback') {
                $obj | Add-Member -MemberType NoteProperty -Name "retired" -Value $true -Force
                $script:found = $true
                Write-Host "  Marked retired: $($obj.sourceId)"
            }
            $obj.PSObject.Properties | ForEach-Object { Set-Retired $_.Value }
        }
    }
    $script:found = $false
    Set-Retired $json
}

if ($found -or $script:found) {
    $json | ConvertTo-Json -Depth 10 | Set-Content data/microsoft-learn.json -Encoding utf8
    Write-Host "  Updated microsoft-learn.json"
} else {
    Write-Host "  No matching item found in microsoft-learn.json"
}

# 2. Mark LinkedIn dead item as retired
Write-Host "`nProcessing Certifications.csv..."
$csvPath = 'data/Certifications.csv'
$content = Get-Content $csvPath -Raw
$lines = $content -split "`n"
$header = $lines[0]
$delimiter = if ($header -like "*`t*") { "`t" } else { "," }
$headerCols = $header -split $delimiter

# Add retired column if not present
if ($headerCols -notcontains 'retired') {
    $header += $delimiter + 'retired'
    $lines[0] = $header
}

$modified = 0
for ($i = 1; $i -lt $lines.Count; $i++) {
    $line = $lines[$i]
    if ($line -match 'ae6b4ab2f3e25673ea0b882f5443d748f91855994ac4f6204d2b824e14bc51f4') {
        if ($line -notmatch 'retired') {
            $lines[$i] = $line + $delimiter + 'true'
            $modified++
            Write-Host "  Marked retired: $line"
        }
    }
}

if ($modified -gt 0) {
    $lines -join "`n" | Set-Content $csvPath -Encoding utf8
    Write-Host "  Updated $modified item(s) in Certifications.csv"
} else {
    Write-Host "  No matching item found in Certifications.csv"
}

Write-Host "`nDone!"