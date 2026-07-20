# scripts/start_manager.ps1
# Запускает Trading Bots Manager (http://localhost:7432)
#
# Использование:
#   cd "D:\В ЗАМАРОЗКЕ\ИИ Claude Code\ПРОЕКТЫ В РАБОТЕ\TRADING\TRADING"
#   .\scripts\start_manager.ps1

$ProjectRoot = $PSScriptRoot | Split-Path -Parent
$ManagerScript = Join-Path $ProjectRoot "manager\app.py"

# Проверяем что Python доступен
$Python = $null
foreach ($cmd in @("python", "python3", "py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python 3") {
            $Python = $cmd
            break
        }
    } catch {}
}

if (-not $Python) {
    Write-Host ""
    Write-Host "  ERROR: Python 3 не найден" -ForegroundColor Red
    Write-Host "  Убедись что Python 3.11+ установлен и добавлен в PATH" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

# Проверяем что файл существует
if (-not (Test-Path $ManagerScript)) {
    Write-Host ""
    Write-Host "  ERROR: Не найден manager\app.py" -ForegroundColor Red
    Write-Host "  Путь: $ManagerScript" -ForegroundColor Yellow
    Write-Host ""
    pause
    exit 1
}

Write-Host ""
Write-Host "  =========================" -ForegroundColor DarkGray
Write-Host "   Trading Bots Manager   " -ForegroundColor Cyan
Write-Host "  =========================" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Проект: $ProjectRoot" -ForegroundColor Gray
Write-Host "  Python: $Python" -ForegroundColor Gray
Write-Host ""

# Переходим в папку проекта и запускаем
Set-Location $ProjectRoot
& $Python $ManagerScript
