@echo off
rem autoblog login helper - double-click. This window stays open until you press a key.
cd /d "%~dp0"
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY set "PY=python"

"%PY%" --version >nul 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] Python was not found. Run install.bat first, or sign out and sign in again.
    echo.
    pause
    exit /b 1
)
if not exist "config.yaml" (
    echo.
    echo [ERROR] config.yaml was not found in this folder:
    echo   %CD%
    echo Run this from the installed autoblog folder, and make config.yaml from config.example.yaml.
    echo.
    pause
    exit /b 1
)

echo.
echo ===== autoblog login =====
echo Log in once per platform. A browser window opens - log in there,
echo then come BACK to this window and press Enter.
echo.
set "ACC=acc1"
set /p ACC=Account name from config.yaml [acc1]:
echo.
echo   1) Naver
echo   2) Instagram
echo   3) Threads
echo   4) All three, one after another
set "SEL=4"
set /p SEL=Choose [4]:

if "%SEL%"=="1" call :login naver
if "%SEL%"=="2" call :login instagram
if "%SEL%"=="3" call :login threads
if "%SEL%"=="4" (
    call :login naver
    call :login instagram
    call :login threads
)

echo.
echo ===== Done. You can close this window. =====
pause
exit /b 0

:login
echo.
echo ----- %1 -----
"%PY%" main.py --login-only %ACC% --platform %1
if errorlevel 1 echo [!] %1 login ended with an error. Read the message above.
echo.
echo Checking %1 login status...
"%PY%" main.py --check-login %ACC% --platform %1
if errorlevel 1 (echo [!] %1 is NOT logged in yet. Run this again and try once more.) else (echo [OK] %1 is logged in.)
exit /b 0
