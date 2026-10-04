@echo off
setlocal
cd /d "%~dp0"
echo === 1/2 Building VibePause.exe (PyInstaller) ===
py -m pip install -U pyinstaller pystray pillow winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections || goto :error
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
py -m PyInstaller --noconfirm --clean VibePause.spec || goto :error
if not exist "dist\VibePause\VibePause.exe" goto :error

echo === 2/2 Building VibePause_Setup.exe (Inno Setup) ===
set "ISCC="
for %%P in ("%LocalAppData%\Programs\Inno Setup 6" "%LocalAppData%\Programs\Inno Setup 7" "%ProgramFiles(x86)%\Inno Setup 6" "%ProgramFiles%\Inno Setup 6" "%ProgramFiles(x86)%\Inno Setup 7" "%ProgramFiles%\Inno Setup 7") do (
  if exist "%%~P\ISCC.exe" set "ISCC=%%~P\ISCC.exe"
)
if not defined ISCC (
  echo Inno Setup is not installed. Install it: winget install JRSoftware.InnoSetup
  echo The EXE folder is ready in dist\VibePause but there is no installer yet.
  exit /b 2
)
"%ISCC%" "installer\VibePause.iss" || goto :error
echo.
echo DONE: installer_output\VibePause_Setup.exe
exit /b 0
:error
echo BUILD FAILED.
exit /b 1
