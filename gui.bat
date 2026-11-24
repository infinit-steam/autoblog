@echo off
rem autoblog GUI launcher (double-click)
rem Python is searched in its install folders first, because Explorer may not see PATH changes made right after install.
cd /d "%~dp0"
set "PYW="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
if not defined PYW for /d %%D in ("%ProgramFiles%\Python3*") do if exist "%%D\pythonw.exe" set "PYW=%%D\pythonw.exe"
if defined PYW (
    start "" "%PYW%" gui.py
    exit /b
)
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw gui.py
    exit /b
)
python gui.py
pause
