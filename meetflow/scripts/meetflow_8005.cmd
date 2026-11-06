@echo off
rem Запуск фронта MeetFlow на 8005 (задача планировщика «MeetFlow 8005»). Проект лежит на общей папке,
rem штатный скрипт запуска — meetflow\scripts\run_dev.ps1.
rem 06.11.2026, записка 57a2983: замок на одну обёртку, журнал в файл, код 3 (порт занят) — ждём дольше.
setlocal EnableExtensions EnableDelayedExpansion
set "LOCK=%LOCALAPPDATA%\MeetFlow\8005.lock"
set "LOGDIR=%LOCALAPPDATA%\MeetFlow\logs"
if not exist "%LOGDIR%" mkdir "%LOGDIR%"
set "LOG=%LOGDIR%\meetflow.log"

rem журнал не старше 7 дней: старый файл убираем при запуске
powershell -NoProfile -Command "if (Test-Path '%LOG%') { if (((Get-Date) - (Get-Item '%LOG%').LastWriteTime).TotalDays -gt 7) { Remove-Item '%LOG%' -Force } }" >nul 2>&1

:take_lock
mkdir "%LOCK%" 2>nul
if not errorlevel 1 goto have_lock
set "OLD="
if exist "%LOCK%\pid" set /p OLD=<"%LOCK%\pid"
if "%OLD%"=="" goto drop_stale
powershell -NoProfile -Command "if (Get-Process -Id %OLD% -ErrorAction SilentlyContinue) { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 goto drop_stale
echo [%date% %time%] обёртка уже работает (PID %OLD%) - выхожу >>"%LOG%"
exit /b 0

:drop_stale
echo [%date% %time%] старый замок (PID %OLD%) - снимаю >>"%LOG%"
rmdir /s /q "%LOCK%" 2>nul
goto take_lock

:have_lock
rem PID обёртки пишет сам PowerShell в файл: через for /f в файл попадал служебный текст cmd, и замок всегда
rem считался старым (найдено 06.11.2026 при проверке).
powershell -NoProfile -Command "$p=(Get-CimInstance Win32_Process -Filter ('ProcessId='+$PID)).ParentProcessId; Set-Content -Path '%LOCK%\pid' -Value $p -Encoding ascii" >nul 2>&1
set "MYID="
set /p MYID=<"%LOCK%\pid"
echo %date% %time%>"%LOCK%\time"
echo [%date% %time%] обёртка 8005 стартовала, PID %MYID% >>"%LOG%"

set "CODE3=0"
rem BOM у run_dev.ps1: PowerShell 5.1 читает .ps1 без BOM как ANSI и падает на кириллице (записка 9065fb3).
rem Проверяем первые три байта; нет BOM и есть не-ASCII — возвращаем BOM на месте, строка в журнал.
powershell -NoProfile -Command "$p='\SD2\GROUPS\Technical\AI Projects\MeetFlow\meetflow\scripts
un_dev.ps1'; if (Test-Path $p) { $b=[IO.File]::ReadAllBytes($p); $bom = $b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF; $non=$false; foreach ($x in $b) { if ($x -ge 0x80) { $non=$true; break } }; if (-not $bom -and $non) { [IO.File]::WriteAllBytes($p, ([byte[]](0xEF,0xBB,0xBF) + $b)); Write-Output 'вернул BOM run_dev.ps1' } }">>"%LOG%" 2>&1

:loop
echo [%date% %time%] запуск сервера >>"%LOG%"
powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "\\SD2\GROUPS\Technical\AI Projects\MeetFlow\meetflow\scripts\run_dev.ps1" -Theme it_product -Port 8005 -Db data\meetflow.db -BindHost 0.0.0.0 >>"%LOG%" 2>&1
set "RC=%ERRORLEVEL%"
if "%RC%"=="3" (
  set /a CODE3+=1
  echo [%date% %time%] порт 8005 занят (код 3, подряд !CODE3!) >>"%LOG%"
  if !CODE3! geq 3 (
    echo [%date% %time%] код 3 три раза подряд - жду 5 минут >>"%LOG%"
    set "CODE3=0"
    ping -n 301 127.0.0.1 >nul
  ) else (
    ping -n 61 127.0.0.1 >nul
  )
) else (
  set "CODE3=0"
  echo [%date% %time%] сервер вышел, код %RC% - перезапуск через 5 с >>"%LOG%"
  ping -n 6 127.0.0.1 >nul
)
goto loop
