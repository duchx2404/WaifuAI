@echo off
chcp 65001 >nul
rem Cai PuLID SDXL cho ComfyUI de WaifuAI giu khuon mat theo anh dai dien.
rem  - Node: github.com/cubiq/PuLID_ComfyUI (ten node khac PuLID-Flux-Enhanced, cai chung duoc)
rem  - Mo hinh: ip-adapter_pulid_sdxl_fp16.safetensors (0.79 GB) tu huggingface.co/huchenlei/ipadapter_pulid
rem  - Thu vien Python (facexlib, insightface, ftfy, timm) da co san tu PuLID-Flux nen KHONG pip install gi.
rem Dung:  cai_pulid_sdxl.bat [thu muc ComfyUI portable] [thu muc model pulid]

set "COMFY=%~1"
if "%COMFY%"=="" set "COMFY=E:\ComfyUI_windows_portable"
set "PULID=%~2"
if "%PULID%"=="" set "PULID=D:\AI\models\pulid"
set "NODE=%COMFY%\ComfyUI\custom_nodes\PuLID_ComfyUI"
set "FILE=%PULID%\ip-adapter_pulid_sdxl_fp16.safetensors"
set "SHA=B258A5CD2C0C7D35F4D3E59909D7648498686AFAE4D0C74917E9C47D7704FBF5"

if not exist "%COMFY%\ComfyUI\main.py" (
  echo Khong thay ComfyUI o %COMFY%
  goto :het
)

echo [1/2] Node PuLID_ComfyUI...
if exist "%NODE%\__init__.py" (
  echo      Da co: %NODE%
) else (
  git clone --depth 1 https://github.com/cubiq/PuLID_ComfyUI "%NODE%"
  if errorlevel 1 ( echo      Tai node that bai & goto :het )
)

echo [2/2] Mo hinh PuLID SDXL (0.79 GB)...
if not exist "%PULID%" mkdir "%PULID%"
if exist "%FILE%" (
  echo      Da co: %FILE%
) else (
  curl.exe -L --fail --retry 5 -C - -o "%FILE%.part" "https://huggingface.co/huchenlei/ipadapter_pulid/resolve/main/ip-adapter_pulid_sdxl_fp16.safetensors"
  if errorlevel 1 ( echo      Tai mo hinh that bai - chay lai de tai tiep & goto :het )
  move /y "%FILE%.part" "%FILE%" >nul
)
for /f %%h in ('powershell -NoProfile -Command "(Get-FileHash -Algorithm SHA256 '%FILE%').Hash"') do set "GOT=%%h"
if /i "%GOT%"=="%SHA%" (
  echo      SHA256 khop.
) else (
  echo      SHA256 KHONG khop - xoa file va chay lai: %FILE%
  goto :het
)

echo.
echo Xong. Khoi dong lai ComfyUI, roi trong WaifuAI: Quan ly - Cai dat se hien "PuLID SDXL: da san sang".
:het
echo.
pause
