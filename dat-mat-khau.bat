@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Dat / doi mat khau dang nhap WaifuAI. Them --ngau-nhien de tu sinh, --xoa de bo mat khau.
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe tools\dat_mat_khau.py %*
) else (
  python tools\dat_mat_khau.py %*
)
echo.
pause
