@echo off
rem Запуск фронта MeetFlow на 8005 при входе в систему (задача планировщика «MeetFlow 8005»).
rem Сам проект лежит на общей папке; штатный скрипт запуска — meetflow\scripts\run_dev.ps1.
rem 06.11.2026: сервер после остановки не поднимался — задача запускала run_dev.ps1 один раз, а тот
rem сервер не перезапускает. Теперь здесь цикл: сервер вышел (упал или его остановили) — ждём 5 с и
rem поднимаем снова. Задача повторяется каждые 5 минут и второй экземпляр не запускает (IgnoreNew),
rem поэтому после падения самого этого файла сервер тоже вернётся. Если порт уже слушает другой
rem процесс (сервер, поднятый вручную), цикл не запускает второй, а ждёт минуту и проверяет снова.
:loop
netstat -ano | findstr /R /C:":8005 .*LISTENING" >nul
if not errorlevel 1 (
  ping -n 61 127.0.0.1 >nul
  goto loop
)
powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "\\SD2\GROUPS\Technical\AI Projects\MeetFlow\meetflow\scripts\run_dev.ps1" -Theme it_product -Port 8005 -Db data\meetflow.db -BindHost 0.0.0.0
ping -n 6 127.0.0.1 >nul
goto loop
