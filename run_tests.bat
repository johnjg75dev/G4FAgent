@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHONPATH=%cd%;%PYTHONPATH%"

:menu
echo.
echo ======================================
echo G4FAgent Test Runner
echo ======================================
echo 1. Run offline-only tests
echo 2. Run online-only tests
echo 3. Run both offline and online tests
echo 4. Exit
set /p TEST_CHOICE=Select an option [1-4]: 

if "%TEST_CHOICE%"=="1" goto run_offline
if "%TEST_CHOICE%"=="2" goto run_online
if "%TEST_CHOICE%"=="3" goto run_both
if "%TEST_CHOICE%"=="4" goto done

echo Invalid option.
goto menu

:run_offline
echo.
echo Running offline tests...
python -m unittest discover -s tests -p "test_offline_*.py" -v
set "RC=%ERRORLEVEL%"
goto result

:run_online
echo.
echo Running online tests...
set "G4F_ONLINE_TESTS=1"
python -m unittest discover -s tests -p "test_online_*.py" -v
set "RC=%ERRORLEVEL%"
goto result

:run_both
echo.
echo Running offline tests...
set "RC=0"
python -m unittest discover -s tests -p "test_offline_*.py" -v
if errorlevel 1 set "RC=1"

echo.
echo Running online tests...
set "G4F_ONLINE_TESTS=1"
python -m unittest discover -s tests -p "test_online_*.py" -v
if errorlevel 1 set "RC=1"
goto result

:result
echo.
if "%RC%"=="0" (
    echo Test run completed successfully.
) else (
    echo Test run completed with failures.
)
echo Exit code: %RC%
exit /b %RC%

:done
exit /b 0
