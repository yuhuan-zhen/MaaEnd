@echo off
rem Double-click entry: push this branch to homesrv:~/maaend and run the deploy there.
rem Pure ASCII on purpose: cmd.exe parses .bat/.cmd as the OEM code page (GBK on zh-CN),
rem so non-ASCII text here would be executed as commands.
rem
rem   deploy.cmd            real deploy (asks for Enter first)
rem   deploy.cmd --dry-run  read-only precheck on the remote host
rem
setlocal
set "BASH=C:\Program Files\Git\bin\bash.exe"
if not exist "%BASH%" set "BASH=bash"
echo == maaend web layer -^> homesrv:~/maaend ==
echo    source : %~dp0..\..\..
echo    dry run: deploy.cmd --dry-run
echo.
if "%~1"=="" pause
"%BASH%" "%~dp0deploy.sh" --remote homesrv --yes %*
set "RC=%ERRORLEVEL%"
set "MODE=deployed"
echo %* | "%SystemRoot%\System32\findstr.exe" /C:"--dry-run" >nul
if not errorlevel 1 set "MODE=dry run - nothing changed"
echo.
if "%RC%"=="0" (echo [OK] %MODE%) else (echo [FAIL] exit code %RC% - see output above)
if "%~1"=="" pause
exit /b %RC%
