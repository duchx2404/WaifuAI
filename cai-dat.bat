@echo off
chcp 65001 >nul
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% equ 0 goto run

echo Can quyen Administrator - dang mo lai cua so moi...
powershell -NoProfile -Command "$a='%*'; if($a.Trim()){Start-Process -FilePath '%~f0' -ArgumentList $a -Verb RunAs}else{Start-Process -FilePath '%~f0' -Verb RunAs}"
exit /b

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause
