# scripts/setup_env.ps1
# Интерактивный мастер настройки .env для Trading Bots
#
# Использование:
#   cd "D:\В ЗАМАРОЗКЕ\ИИ Claude Code\ПРОЕКТЫ В РАБОТЕ\TRADING\TRADING"
#   .\scripts\setup_env.ps1

$ProjectRoot = $PSScriptRoot | Split-Path -Parent
$EnvFile     = Join-Path $ProjectRoot ".env"
$EnvExample  = Join-Path $ProjectRoot ".env.example"
$KeysDir     = Join-Path $ProjectRoot "keys"

# ─── helpers ──────────────────────────────────────────────────────────

function Header($text) {
    Write-Host ""
    Write-Host "  ─────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host "   $text" -ForegroundColor Cyan
    Write-Host "  ─────────────────────────────────────" -ForegroundColor DarkGray
    Write-Host ""
}

function Ask($prompt, $default = "", $secret = $false) {
    $hint = if ($default) { " [Enter = $default]" } else { "" }
    Write-Host "  $prompt$hint" -ForegroundColor Yellow -NoNewline
    Write-Host " : " -NoNewline
    if ($secret) {
        $secure = Read-Host -AsSecureString
        $val = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
            [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
        )
    } else {
        $val = Read-Host
    }
    if ($val -eq "" -and $default -ne "") { return $default }
    return $val
}

function OK($text)   { Write-Host "  ✅ $text" -ForegroundColor Green }
function WARN($text) { Write-Host "  ⚠️  $text" -ForegroundColor Yellow }
function INFO($text) { Write-Host "  ℹ️  $text" -ForegroundColor Cyan }
function SKIP($text) { Write-Host "  ⏭️  $text" -ForegroundColor DarkGray }

# ─── banner ───────────────────────────────────────────────────────────

Clear-Host
Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║    Trading Bots — Мастер настройки   ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Этот скрипт создаст .env файл для запуска ботов." -ForegroundColor Gray
Write-Host "  Все данные сохраняются ТОЛЬКО локально." -ForegroundColor Gray
Write-Host ""
Write-Host "  Подсказки:" -ForegroundColor DarkGray
Write-Host "  • Нажми Enter чтобы принять значение по умолчанию [в скобках]" -ForegroundColor DarkGray
Write-Host "  • Можно пропустить необязательные разделы (введи n)" -ForegroundColor DarkGray
Write-Host ""

# ─── backup old .env ──────────────────────────────────────────────────

if (Test-Path $EnvFile) {
    $backup = "$EnvFile.bak_$(Get-Date -Format 'yyyyMMdd_HHmm')"
    Copy-Item $EnvFile $backup
    WARN "Найден существующий .env → резервная копия: $(Split-Path $backup -Leaf)"
    Write-Host ""
}

# ─── TELEGRAM ─────────────────────────────────────────────────────────

Header "Шаг 1 из 4 — Telegram Bot"
INFO "Получи токен у @BotFather: /newbot"
INFO "Свой Chat ID — у @userinfobot: /start"
Write-Host ""

$tgToken  = Ask "TELEGRAM_BOT_TOKEN"
$tgChatId = Ask "TELEGRAM_ALLOWED_CHAT_ID (твой user ID)"

if (-not $tgToken) {
    WARN "Токен не указан — Telegram уведомления работать не будут"
    $tgToken  = "YOUR_TELEGRAM_BOT_TOKEN"
    $tgChatId = "YOUR_CHAT_ID"
} else {
    OK "Telegram настроен"
}

# ─── BINANCE TESTNET ──────────────────────────────────────────────────

Header "Шаг 2 из 4 — Binance Testnet"
INFO "Регистрация: https://testnet.binancefuture.com"
INFO "API ключи: User Center → API Management"
Write-Host ""

$doBinance = Ask "Настроить Binance Testnet? (y/n)" "y"
if ($doBinance -eq "y") {
    $binKey    = Ask "BINANCE_API_KEY" -secret $true
    $binSecret = Ask "BINANCE_API_SECRET" -secret $true
    $binTest   = "true"
    if ($binKey) {
        OK "Binance Testnet настроен"
    } else {
        WARN "API ключ не указан — Crypto бот не запустится"
        $binKey    = "YOUR_BINANCE_API_KEY"
        $binSecret = "YOUR_BINANCE_API_SECRET"
    }
} else {
    SKIP "Binance пропущен"
    $binKey    = "YOUR_BINANCE_API_KEY"
    $binSecret = "YOUR_BINANCE_API_SECRET"
    $binTest   = "true"
}

# ─── KALSHI DEMO ──────────────────────────────────────────────────────

Header "Шаг 3 из 4 — Kalshi Demo (необязательно)"
INFO "Регистрация: https://kalshi.com → Settings → API"
INFO "Скачай .pem файл и положи его в папку keys/"
Write-Host ""

$doKalshi = Ask "Настроить Kalshi Demo? (y/n)" "n"
if ($doKalshi -eq "y") {
    $kalshiKey = Ask "KALSHI_API_KEY"
    $kalshiEnv = "demo"

    # Check for PEM file
    New-Item -ItemType Directory -Path $KeysDir -Force | Out-Null
    $pemFiles = Get-ChildItem -Path $KeysDir -Filter "*.pem" 2>$null
    if ($pemFiles) {
        $pemName = $pemFiles[0].Name
        # Rename to standard name if needed
        if ($pemName -ne "kalshi_private.pem") {
            Rename-Item -Path (Join-Path $KeysDir $pemName) -NewName "kalshi_private.pem"
            OK "PEM файл переименован → kalshi_private.pem"
        } else {
            OK "PEM файл найден: keys/kalshi_private.pem"
        }
    } else {
        WARN "PEM файл не найден в keys/"
        WARN "Скопируй скачанный .pem в: $KeysDir"
        WARN "И переименуй в: kalshi_private.pem"
    }

    if ($kalshiKey) { OK "Kalshi Demo настроен" }
} else {
    SKIP "Kalshi пропущен (можно добавить позже)"
    $kalshiKey = "YOUR_KALSHI_API_KEY"
    $kalshiEnv = "demo"
}

# ─── TRADING MODE ─────────────────────────────────────────────────────

Header "Шаг 4 из 4 — Режим торговли"
Write-Host ""
Write-Host "  Сейчас установим БЕЗОПАСНЫЙ paper trading режим:" -ForegroundColor Gray
Write-Host "  • LIVE_TRADING=false  → ордера не отправляются на биржу" -ForegroundColor Green
Write-Host "  • DRY_RUN=true        → только логи, никаких реальных действий" -ForegroundColor Green
Write-Host ""
Write-Host "  ⛔ Не меняй эти флаги без 30 дней успешного paper trading!" -ForegroundColor Red
Write-Host ""
$_ = Read-Host "  Нажми Enter чтобы подтвердить"

$liveTrade = "false"
$dryRun    = "true"
$logLevel  = Ask "LOG_LEVEL" "INFO"

OK "Режим: paper trading (безопасный)"

# ─── Write .env ───────────────────────────────────────────────────────

$envContent = @"
# ============================================
# TRADING BOTS — Конфиг (создан setup_env.ps1)
# Дата: $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# НИКОГДА не коммить этот файл в git!
# ============================================

# === KALSHI BOT ===
KALSHI_API_KEY=$kalshiKey
KALSHI_PRIVATE_KEY_PATH=./keys/kalshi_private.pem
KALSHI_ENV=$kalshiEnv

# === CRYPTO FUTURES BOT ===
BINANCE_API_KEY=$binKey
BINANCE_API_SECRET=$binSecret
BINANCE_TESTNET=$binTest

# Bybit (резервная биржа, опционально)
BYBIT_API_KEY=YOUR_BYBIT_API_KEY
BYBIT_API_SECRET=YOUR_BYBIT_API_SECRET
BYBIT_TESTNET=true

# === РЕЖИМ ТОРГОВЛИ ===
# ⛔ НЕ МЕНЯТЬ без 30 дней paper trading!
LIVE_TRADING=$liveTrade
DRY_RUN=$dryRun

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN=$tgToken
TELEGRAM_ALLOWED_CHAT_ID=$tgChatId

# === БАЗА ДАННЫХ ===
DATABASE_URL=sqlite+aiosqlite:///./trading.db

# === МОНИТОРИНГ ===
LOG_LEVEL=$logLevel
"@

$envContent | Out-File -FilePath $EnvFile -Encoding UTF8 -NoNewline
OK ".env файл создан"

# ─── create keys dir ──────────────────────────────────────────────────

New-Item -ItemType Directory -Path $KeysDir -Force | Out-Null
OK "Папка keys/ готова"

# Protect keys dir from accidental writes
$gitignoreKeys = Join-Path $KeysDir ".gitignore"
"*" | Out-File -FilePath $gitignoreKeys -Encoding UTF8
"!.gitignore" | Out-File -FilePath $gitignoreKeys -Encoding UTF8 -Append

# ─── Docker check ─────────────────────────────────────────────────────

Header "Проверка Docker"

try {
    $dockerVer = docker --version 2>&1
    if ($dockerVer -match "Docker version") {
        OK "Docker найден: $dockerVer"
    } else {
        throw "не найден"
    }
} catch {
    WARN "Docker не найден!"
    INFO "Установи Docker Desktop: https://www.docker.com/products/docker-desktop"
}

# ─── Summary ──────────────────────────────────────────────────────────

Write-Host ""
Write-Host "  ╔══════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║           Всё готово! 🎉              ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
Write-Host "  Следующие шаги:" -ForegroundColor Cyan
Write-Host ""
Write-Host "  1. Убедись что Docker Desktop запущен" -ForegroundColor White
Write-Host ""
Write-Host "  2. Запусти Crypto бота:" -ForegroundColor White
Write-Host "     docker compose up crypto-bot --build" -ForegroundColor Yellow
Write-Host ""
Write-Host "  3. Проверь статус:" -ForegroundColor White
Write-Host "     curl http://localhost:8080/health" -ForegroundColor Yellow
Write-Host ""
Write-Host "  4. Напиши боту в Telegram: /status" -ForegroundColor White
Write-Host ""
Write-Host "  5. Читай логи:" -ForegroundColor White
Write-Host "     docker compose logs -f crypto-bot" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Полный гайд: SETUP.md" -ForegroundColor DarkGray
Write-Host ""
