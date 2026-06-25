@echo off
cd /d "%~dp0"

py --version >nul 2>&1
if errorlevel 1 (
    echo Python не найден. Установите Python 3.10+ с python.org
    pause
    exit /b
)

if not exist ".deps_installed" (
    echo Устанавливаем зависимости...
    py -m pip install -r requirements.txt
    echo. > .deps_installed
)

py main.py
if errorlevel 1 (
    echo.
    echo ОШИБКА ЗАПУСКА - см. текст выше
    pause
)
