@echo off
setlocal
cd /d "%~dp0"
title DSIP Automated Discovery Tool
chcp 65001 >nul 2>&1
mode con: cols=92 lines=42
color 0B

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $SplashMode='boot'; $p='%~f0'; $beg=':::'+'SPLASH'+':::'; $end=':::'+'ENDSPLASH'+':::'; $c=Get-Content -LiteralPath $p -Raw; $m=[regex]::Match($c,'(?s)'+[regex]::Escape($beg)+'(.*?)'+[regex]::Escape($end)); if($m.Success){ Invoke-Expression $m.Groups[1].Value } }"

echo.
echo    [*]  Locating Python runtime ...
python --version >nul 2>&1
if errorlevel 1 (
  color 0C
  echo.
  echo    [X]  Python was not found.
  echo         Install Python 3.12 or 3.13 from the Microsoft Store, then try again.
  echo         See docs\WINDOWS_11_NO_ADMIN_README.md
  echo.
  pause
  exit /b 1
)
echo    [OK] Python online.

echo    [*]  Loading PDF engine ^(pypdf^) ...
python -m pip install --disable-pip-version-check pypdf >nul 2>&1
if errorlevel 1 (
  color 0C
  echo.
  echo    [X]  Could not install pypdf. Check your network and try again.
  echo.
  pause
  exit /b 1
)
echo    [OK] PDF engine online.
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command "& { $SplashMode='open'; $p='%~f0'; $beg=':::'+'SPLASH'+':::'; $end=':::'+'ENDSPLASH'+':::'; $c=Get-Content -LiteralPath $p -Raw; $m=[regex]::Match($c,'(?s)'+[regex]::Escape($beg)+'(.*?)'+[regex]::Escape($end)); if($m.Success){ Invoke-Expression $m.Groups[1].Value } }"
if errorlevel 1 (
  echo    Opening DSIP GOV Portal Discovery Search Tool ...
)

python gui.py
if errorlevel 1 (
  color 0C
  echo.
  echo    [X]  The app exited with an error.
  echo.
  pause
)
exit /b 0

:::SPLASH:::
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

if ($SplashMode -eq 'open') {
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
    return
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
:::ENDSPLASH:::
