@echo off
chcp 65001 >nul
echo ============================================
echo   ORESNA WhatsApp Bot - Arranque Local
echo   Version 1.2.0 - Estructura modular por carpetas
echo ============================================
echo.

set PYTHON=python
set PYTHONPATH=%~dp0venv_local;%PYTHONPATH%

:: Verificar que existe el .env
if not exist "%~dp0.env" (
    echo [ERROR] No se encontro el archivo .env
    echo Copia .env.example a .env y rellena las credenciales
    pause
    exit /b 1
)

echo [OK] Configuracion encontrada
echo.

:: Detectar si hay token de WhatsApp configurado
findstr /C:"WHATSAPP_TOKEN=tu_token" "%~dp0.env" >nul 2>&1
if not errorlevel 1 (
    echo [MODO] SIMULACION LOCAL (sin WhatsApp real)
    echo         El simulador visual estara disponible en el navegador
) else (
    findstr /C:"WHATSAPP_TOKEN=" "%~dp0.env" | findstr /V /C:"WHATSAPP_TOKEN=$" >nul 2>&1
    echo [MODO] Verificando configuracion de WhatsApp...
)

echo.
echo Endpoints disponibles:
echo   Health check:  http://localhost:8000
echo   API Docs:      http://localhost:8000/docs
echo   SIMULADOR:     http://localhost:8000/simulator  ^<-- Prueba el bot aqui!
echo   Ver leads:     http://localhost:8000/leads
echo.
echo IMPORTANTE: Para conectar WhatsApp real, abre OTRA ventana y ejecuta:
echo   ngrok http 8000
echo.
echo Presiona Ctrl+C para detener el bot
echo ============================================
echo.

:: Abrir el simulador en el navegador tras 3 segundos
start "" /B cmd /C "timeout /t 3 /nobreak >nul && start http://localhost:8000/simulator"

%PYTHON% -m uvicorn main:app --reload --port 8000

pause
