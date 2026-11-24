@echo off
rem Tai LoRA chi tiet da cho SDXL vao D:\AI\models\loras (ComfyUI doc thu muc nay qua extra_model_paths.yaml)
rem  1) Ultra-Realistic Face skin v1 (epoch 10, ~457 MB) - lo chan long / ket cau da mat, tu khoa: ufs9
rem     https://huggingface.co/faisalKSA/Ultra-Realistic-Face-skin-v1
rem  2) DetailTweakerXL (~228 MB) - tang chi tiet chung
rem     https://huggingface.co/Maxixa/civit-xl
setlocal
set "DIR=D:\AI\models\loras"
if not exist "%DIR%" mkdir "%DIR%"

call :tai "https://huggingface.co/faisalKSA/Ultra-Realistic-Face-skin-v1/resolve/main/Ultra-Realistic_Face_skin_epoch_10.safetensors" "%DIR%\ultra_realistic_face_skin_e10.safetensors"
call :tai "https://huggingface.co/Maxixa/civit-xl/resolve/main/lora/DetailTweakerXL.safetensors" "%DIR%\DetailTweakerXL.safetensors"

echo.
echo Xong. Khong can khoi dong lai ComfyUI (danh sach LoRA tu cap nhat).
pause
exit /b 0

:tai
if exist "%~2" (
  echo Da co: %~2 - bo qua
  exit /b 0
)
echo Dang tai: %~nx2
curl.exe -L --fail --retry 3 -o "%~2.part" "%~1"
if errorlevel 1 (
  echo LOI khi tai %~nx2
  if exist "%~2.part" del "%~2.part"
  exit /b 1
)
move /y "%~2.part" "%~2" >nul
echo OK: %~2
exit /b 0
