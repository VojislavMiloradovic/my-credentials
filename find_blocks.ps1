$content = Get-Content 'C:\Users\Toughbook\OneDrive\Documents\GitHub\my-credentials\update_credly_badges.py' -Raw

# Find positions
$idx1 = $content.IndexOf('# 3. Anomaly & Loss Guard Assertion - Content-Aware')
$idx2 = $content.IndexOf('# 4. Retired URL / Identity detection')
$idx3 = $content.IndexOf('# Generate and save baseline fingerprints for L1_normalized (credentials)')
$idx4 = $content.IndexOf('# 5. Build Markdown Archives')

Write-Host "idx1: $idx1"
Write-Host "idx2: $idx2"
Write-Host "idx3: $idx3"
Write-Host "idx4: $idx4"

if ($idx1 -ge 0 -and $idx2 -ge 0) {
    $guardBlock = $content.Substring($idx1, $idx2 - $idx1)
    $guardBlock | Set-Content 'C:\temp\guard_block.txt' -Encoding UTF8
    Write-Host 'Guard block saved'
}

if ($idx3 -ge 0 -and $idx4 -ge 0) {
    $baseBlock = $content.Substring($idx3, $idx4 - $idx3)
    $baseBlock | Set-Content 'C:\temp\base_block.txt' -Encoding UTF8
    Write-Host 'Baseline block saved'
}