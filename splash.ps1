param(
    [ValidateSet('boot', 'open')]
    [string]$Mode = 'boot'
)

$ErrorActionPreference = 'Stop'
try { $Host.UI.RawUI.WindowTitle = 'DSIP Automated Discovery Tool' } catch {}

function Write-C([string]$Text, [string]$Color = 'Cyan') {
    Write-Host $Text -ForegroundColor $Color
}

function Show-Spin([string]$Label, [int]$Ms = 650) {
    $frames = @('|', '/', '-', '\')
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $i = 0
    while ($sw.ElapsedMilliseconds -lt $Ms) {
        Write-Host -NoNewline ("`r    [{0}]  {1}   " -f $frames[$i % 4], $Label) -ForegroundColor Yellow
        Start-Sleep -Milliseconds 70
        $i++
    }
    Write-Host ("`r    [OK]  {0}          " -f $Label) -ForegroundColor Green
}

function Show-Bar([int]$Ms = 900) {
    $width = 28
    $delay = [Math]::Max(15, [int]($Ms / $width))
    for ($n = 0; $n -le $width; $n++) {
        $pct = [int](100 * $n / $width)
        $bar = ('#' * $n) + ('-' * ($width - $n))
        Write-Host -NoNewline ("`r    [" + $bar + "] " + $pct + "%  ") -ForegroundColor Cyan
        Start-Sleep -Milliseconds $delay
    }
    Write-Host ""
}

function Show-Type([string]$Text, [string]$Color = 'Yellow', [int]$Ms = 22) {
    foreach ($ch in $Text.ToCharArray()) {
        Write-Host -NoNewline $ch -ForegroundColor $Color
        Start-Sleep -Milliseconds $Ms
    }
    Write-Host ""
}

if ($Mode -eq 'open') {
    Write-Host ""
    Write-C "    +--------------------------------------------------------------+" 'DarkCyan'
    Write-C "    |              UPLINK  -  DSIP TOPICS APP  -  LOCAL            |" 'DarkCyan'
    Write-C "    +--------------------------------------------------------------+" 'DarkCyan'
    Write-Host ""
    Write-Host -NoNewline "    " -ForegroundColor Yellow
    Show-Type "Opening DSIP GOV Portal Discovery Search Tool ..." 'Yellow' 28
    Write-Host ""
    Show-Bar 850
    Write-C "    [OK]  Link established. Launching Discovery GUI ..." 'Green'
    Write-Host ""
    exit 0
}

Clear-Host
Write-Host ""
Write-C "                  *  .    *          .       *     ." 'DarkCyan'
Write-C "             .        *    ^    *         .          " 'DarkGray'
Write-C "                     / \                             " 'Cyan'
Write-C "                    / | \           .     *          " 'Cyan'
Write-C "               ----[--+--]----                      " 'Yellow'
Write-C "                    \ | /      *                     " 'Cyan'
Write-C "               .     \ /            .                " 'Cyan'
Write-C "                  *   V   *                          " 'Yellow'
Write-Host ""
Write-C "       ____  ____ ___ ____                           " 'Cyan'
Write-C "      |  _ \/ ___|_ _|  _ \                          " 'Cyan'
Write-C "      | | | \___ \| || |_) |                         " 'Cyan'
Write-C "      | |_| |___) | ||  __/                          " 'Cyan'
Write-C "      |____/|____/___|_|                             " 'Cyan'
Write-Host ""
Write-C "           A U T O M A T E D                         " 'Yellow'
Write-C "           D I S C O V E R Y   T O O L               " 'White'
Write-Host ""
Write-C "    +--------------------------------------------------------------+" 'DarkCyan'
Write-C "    |  DoD SBIR / STTR     local open-topics     no cloud / login  |" 'DarkGray'
Write-C "    |  Discovery scan      ->  snapshot  ->  extractive briefing   |" 'DarkGray'
Write-C "    +--------------------------------------------------------------+" 'DarkCyan'
Write-Host ""
Show-Spin "Awakening Discovery core ..." 720
Show-Spin "Calibrating topic sensors ..." 640
Show-Spin "Locking local catalog link ..." 640
Write-Host ""
Write-C "    > SYS     python + pypdf" 'DarkGray'
Write-C "    > MODE    local appliance  (nothing typed is sent as searchText)" 'DarkGray'
Write-C "    > SCOPE   DAF  Army  Navy  OSD  DARPA  + other DoW components" 'DarkGray'
Write-Host ""
