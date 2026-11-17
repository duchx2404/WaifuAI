@echo off
chcp 65001 >nul
rem Cai FaceDetailer (sua mat sau khi ve) cho ComfyUI de WaifuAI giu dung mat theo LoRA o anh nua nguoi / toan than.
rem  - Node: github.com/ltdrdata/ComfyUI-Impact-Pack (FaceDetailer) + ComfyUI-Impact-Subpack (UltralyticsDetectorProvider)
rem  - Mo hinh do mat: face_yolov8m.pt, khoang 52 MB, tu huggingface.co/Bingsu/adetailer
rem Dung:  cai_face_detailer.bat [thu muc ComfyUI portable]
rem Bat tu tat ComfyUI truoc khi cai thu vien; chay xong thi bat lai ComfyUI.

set "COMFY=%~1"
if "%COMFY%"=="" set "COMFY=E:\ComfyUI_windows_portable"
set "PY=%COMFY%\python_embeded\python.exe"
set "NODES=%COMFY%\ComfyUI\custom_nodes"
set "BBOX=%COMFY%\ComfyUI\models\ultralytics\bbox"

if not exist "%COMFY%\ComfyUI\main.py" goto :khongthay

echo [1/5] Node ComfyUI-Impact-Pack...
if exist "%NODES%\ComfyUI-Impact-Pack\__init__.py" goto :copack
git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Pack "%NODES%\ComfyUI-Impact-Pack"
if errorlevel 1 goto :loinode
:copack

echo [2/5] Node ComfyUI-Impact-Subpack...
if exist "%NODES%\ComfyUI-Impact-Subpack\__init__.py" goto :cosub
git clone --depth 1 https://github.com/ltdrdata/ComfyUI-Impact-Subpack "%NODES%\ComfyUI-Impact-Subpack"
if errorlevel 1 goto :loinode
:cosub

echo [3/5] Tat ComfyUI neu dang chay, de khong bi khoa file thu vien...
for /f "tokens=5" %%p in ('netstat -ano -p tcp ^| findstr ":8188" ^| findstr "LISTENING"') do taskkill /PID %%p /T /F >nul 2>&1
timeout /t 3 /nobreak >nul

echo [4/5] Thu vien Python - chi cai cai con thieu...
"%PY%" -m pip install --disable-pip-version-check -r "%NODES%\ComfyUI-Impact-Pack\requirements.txt"
if errorlevel 1 goto :loipip
rem ultralytics doi opencv-python, nhung ComfyUI da co opencv-python-headless -> cai --no-deps de khong ghi de OpenCV dang dung
"%PY%" -m pip install --disable-pip-version-check polars psutil py-cpuinfo pyyaml matplotlib requests
if errorlevel 1 goto :loipip
"%PY%" -m pip install --disable-pip-version-check --no-deps ultralytics ultralytics-thop
if errorlevel 1 goto :loipip
"%PY%" -c "import ultralytics, cv2; print('     ultralytics', ultralytics.__version__, '- OpenCV', cv2.__version__)"
if errorlevel 1 goto :loipip

echo [5/5] Mo hinh do mat face_yolov8m.pt...
if not exist "%BBOX%" mkdir "%BBOX%"
if exist "%BBOX%\face_yolov8m.pt" goto :comodel
curl.exe -L --fail --retry 5 -o "%BBOX%\face_yolov8m.pt.part" "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt"
if errorlevel 1 goto :loimodel
move /y "%BBOX%\face_yolov8m.pt.part" "%BBOX%\face_yolov8m.pt" >nul
:comodel

echo.
echo Xong. Bat lai ComfyUI de nap node moi.
goto :het

:khongthay
echo Khong thay ComfyUI o %COMFY%
goto :het
:loinode
echo Tai node that bai - kiem tra mang / git roi chay lai.
goto :het
:loipip
echo Cai thu vien Python loi - xem dong bao loi o tren.
goto :het
:loimodel
echo Tai mo hinh do mat that bai - chay lai de tai tiep.
goto :het

:het
echo.
pause
