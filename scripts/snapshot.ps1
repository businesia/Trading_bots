# scripts/snapshot.ps1
# Создаёт снапшот проекта в папку versions/
#
# Использование:
#   cd "D:\В ЗАМАРОЗКЕ\ИИ Claude Code\ПРОЕКТЫ В РАБОТЕ\TRADING\TRADING"
#   .\scripts\snapshot.ps1
#
# Или с явной версией:
#   .\scripts\snapshot.ps1 -Version "v0.4.0" -Note "добавили стратегию trend"

param(
    [string]$Version = "",
    [string]$Note = ""
)

$ProjectRoot = $PSScriptRoot | Split-Path -Parent
$VersionsDir = Join-Path $ProjectRoot "versions"

# Создаём папку versions если нет
if (-not (Test-Path $VersionsDir)) {
    New-Item -ItemType Directory -Path $VersionsDir | Out-Null
}

# Автоимя: дата + время
$Date = Get-Date -Format "yyyy-MM-dd_HH-mm"
if ($Version -eq "") {
    $ZipName = "snapshot_$Date.zip"
} else {
    $ZipName = "${Version}_${Date}.zip"
}

$ZipPath = Join-Path $VersionsDir $ZipName

# Что исключаем
$Exclude = @(
    "versions",
    ".git",
    "__pycache__",
    ".venv",
    "*.pyc",
    "*.db",
    "logs",
    "*.egg-info",
    ".DS_Store"
)

Write-Host "Создаём снапшот: $ZipName" -ForegroundColor Cyan

# Собираем файлы для архива
$Files = Get-ChildItem -Path $ProjectRoot -Recurse -File | Where-Object {
    $RelPath = $_.FullName.Substring($ProjectRoot.Length + 1)
    $Skip = $false
    foreach ($ex in $Exclude) {
        if ($RelPath -like "*$ex*") { $Skip = $true; break }
    }
    -not $Skip
}

# Создаём zip
Compress-Archive -Path $Files.FullName -DestinationPath $ZipPath -Force

$SizeMB = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host "✅ Готово: versions\$ZipName ($SizeMB MB)" -ForegroundColor Green
Write-Host "   Файлов в архиве: $($Files.Count)" -ForegroundColor Gray

# Сохраняем заметку если указана
if ($Note -ne "") {
    $NotePath = Join-Path $VersionsDir "${ZipName}.txt"
    "Версия: $ZipName`nДата: $Date`nЗаметка: $Note" | Out-File -FilePath $NotePath -Encoding UTF8
    Write-Host "   Заметка: $Note" -ForegroundColor Gray
}

# Показываем все снапшоты
Write-Host ""
Write-Host "Все снапшоты:" -ForegroundColor Yellow
Get-ChildItem -Path $VersionsDir -Filter "*.zip" |
    Sort-Object LastWriteTime |
    ForEach-Object {
        $MB = [math]::Round($_.Length / 1MB, 2)
        Write-Host "  $($_.Name)  [$MB MB]  $($_.LastWriteTime.ToString('yyyy-MM-dd HH:mm'))"
    }
