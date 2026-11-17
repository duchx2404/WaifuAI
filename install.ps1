#Requires -Version 5.1
<#
  Bộ cài WaifuAI — chạy một lần là xong toàn bộ môi trường trên máy ở nhà:
    Python + thư viện, Ollama + mô hình chữ, ComfyUI + checkpoint SDXL,
    mở cổng tường lửa, Tailscale để điện thoại vào được khi ra ngoài,
    và tự chạy lại mỗi khi bật máy.

  Dùng:  bấm đúp cai-dat.bat
  Xem trước, không cài gì:  powershell -ExecutionPolicy Bypass -File install.ps1 -KiemTra
#>
[CmdletBinding()]
param(
  [string]$ThuMucComfy = "",
  [string]$CheckpointUrl = "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors",
  [string]$CheckpointTen = "",
  [string]$MoHinhChat = "gemma3:12b",
  [string]$MoHinhNong = "mistral-nemo:12b",
  [int]$Cong = 8600,
  [switch]$KiemTra,
  [switch]$BoQuaOllama,
  [switch]$BoQuaComfy,
  [switch]$BoQuaCheckpoint,
  [switch]$BoQuaTuongLua,
  [switch]$BoQuaTailscale,
  [switch]$BoQuaTuChay
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:Loi = @()
$script:BoQua = @()

# ---------------------------------------------------------------- tiện ích

function Tieu($n, $text) {
  Write-Host ""
  Write-Host ("  [{0}] {1}" -f $n, $text) -ForegroundColor Cyan
  Write-Host ("  " + ("-" * 66)) -ForegroundColor DarkGray
}
function Ok($t)   { Write-Host "      v  $t" -ForegroundColor Green }
function Tin($t)  { Write-Host "      -  $t" -ForegroundColor Gray }
function Canh($t) { Write-Host "      !  $t" -ForegroundColor Yellow; $script:BoQua += $t }
function Hong($t) { Write-Host "      x  $t" -ForegroundColor Red; $script:Loi += $t }

# Chỉ chạy khi KHÔNG ở chế độ xem trước. Một bước hỏng thì ghi lỗi rồi đi tiếp,
# không kéo sập cả bộ cài — để những thứ đã tải xong không phải làm lại.
function Lam($moTa, [scriptblock]$khoi) {
  if ($KiemTra) { Write-Host "      ~  (xem trước) $moTa" -ForegroundColor DarkGray; return $null }
  try { return & $khoi }
  catch { Hong "$moTa — $($_.Exception.Message)"; return $null }
}

function NapLaiPath {
  $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
  $u = [Environment]::GetEnvironmentVariable("Path", "User")
  $env:Path = ($m, $u | Where-Object { $_ }) -join ";"
}

# Ghi file văn bản KHÔNG kèm BOM (BOM làm hỏng .bat và làm json.loads của Python lỗi)
function GhiFile($duongDan, $noiDung) {
  [System.IO.File]::WriteAllText($duongDan, $noiDung, (New-Object System.Text.UTF8Encoding $false))
}

function CoLenh($ten) {
  $c = Get-Command $ten -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  return $null
}

function CaiWinget($id, $ten) {
  if (-not (CoLenh "winget")) { Hong "Máy chưa có winget (App Installer). Cài $ten thủ công rồi chạy lại."; return $false }
  Tin "Đang cài $ten qua winget (có thể mất vài phút)..."
  winget install --id $id --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
  # winget trả 0 = cài xong, -1978335189 = đã có bản mới nhất
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
    Hong "winget cài $ten thất bại (mã $LASTEXITCODE)"
    return $false
  }
  NapLaiPath
  return $true
}

# Tải file lớn bằng curl, hỗ trợ tải tiếp khi đứt mạng
function TaiFile($url, $dich, $tenHienThi) {
  $tam = "$dich.part"
  $tuyChon = @("-L", "--fail", "--retry", "3", "--retry-delay", "5", "--progress-bar", "-o", $tam, $url)
  if (Test-Path $tam) {
    Tin "Thấy file tải dở, tải tiếp..."
    $tuyChon = @("-C", "-") + $tuyChon
  }
  Write-Host "      Đang tải $tenHienThi ..." -ForegroundColor Gray
  & curl.exe @tuyChon
  if ($LASTEXITCODE -ne 0) { throw "Tải thất bại ($tenHienThi), mã $LASTEXITCODE. Chạy lại bộ cài để tải tiếp." }
  Move-Item -LiteralPath $tam -Destination $dich -Force
}

function DungLuongTrong($duongDan) {
  $o = (Get-Item $duongDan).PSDrive.Name + ":"
  $d = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$o'"
  return [math]::Round($d.FreeSpace / 1GB, 1)
}

# ---------------------------------------------------------------- bắt đầu

Clear-Host
Write-Host ""
Write-Host "   WaifuAI - Bo cai tu dong" -ForegroundColor Magenta
Write-Host "   $Root" -ForegroundColor DarkGray
if ($KiemTra) { Write-Host "   CHE DO XEM TRUOC - khong cai, khong tai gi" -ForegroundColor Yellow }

if (-not $CheckpointTen) { $CheckpointTen = Split-Path -Leaf ($CheckpointUrl -split "\?")[0] }
if (-not $ThuMucComfy) { $ThuMucComfy = Join-Path (Split-Path -Parent $Root) "ComfyUI_windows_portable" }

# ---------------------------------------------------------------- 1. máy

Tieu 1 "Kiểm tra máy"

$gpu = Get-CimInstance Win32_VideoController | Where-Object { $_.Name -match "NVIDIA" } | Select-Object -First 1
if ($gpu) {
  $vram = $null
  try {
    $k = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}\0*" -ErrorAction SilentlyContinue |
         Where-Object { $_.'HardwareInformation.qwMemorySize' } | Select-Object -First 1
    if ($k) { $vram = [math]::Round($k.'HardwareInformation.qwMemorySize' / 1GB, 1) }
  } catch { }
  if ($vram) { Ok "GPU: $($gpu.Name) - $vram GB VRAM" } else { Ok "GPU: $($gpu.Name)" }
  if ($vram -and $vram -lt 10) { Canh "VRAM dưới 10 GB: nên dùng mô hình chữ nhỏ hơn (qwen3:8b) trong Cài đặt" }
} else {
  Canh "Không thấy GPU NVIDIA. Vẫn cài được nhưng vẽ ảnh sẽ rất chậm (chạy CPU)."
}

$quyenAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator)
if ($quyenAdmin) { Ok "Đang chạy với quyền Administrator" }
else { Canh "KHÔNG có quyền Administrator: bước tường lửa và cài phần mềm sẽ hỏng. Nên bấm đúp cai-dat.bat." }

$ram = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
Tin "RAM: $ram GB"
$trong = DungLuongTrong $Root
if ($trong -lt 35) { Canh "Ổ đĩa còn $trong GB. Bộ cài cần khoảng 30 GB." } else { Ok "Ổ đĩa còn trống $trong GB" }

# ---------------------------------------------------------------- 2. Python

Tieu 2 "Python và thư viện"

$py = CoLenh "py"
if (-not $py) { $py = CoLenh "python" }
$phienBan = ""
if ($py) { $phienBan = (& $py --version | Out-String).Trim() }
if ($phienBan -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 10) {
  Ok "Đã có $phienBan"
} else {
  Tin "Chưa có Python 3.10 trở lên"
  if (Lam "cài Python 3.12" { CaiWinget "Python.Python.3.12" "Python 3.12" }) { Ok "Đã cài Python 3.12" }
  $py = CoLenh "py"
  if (-not $py) { $py = CoLenh "python" }
}

$venv = Join-Path $Root ".venv"
$venvPy = Join-Path $venv "Scripts\python.exe"
if (Test-Path $venvPy) {
  Ok "Đã có môi trường .venv"
} else {
  Lam "tạo .venv" {
    & $py -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "Tạo .venv thất bại" }
  }
  if (-not $KiemTra) { Ok "Đã tạo .venv" }
}
Lam "cài fastapi / uvicorn / httpx" {
  & $venvPy -m pip install --quiet --upgrade pip
  & $venvPy -m pip install --quiet -r (Join-Path $Root "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install thất bại" }
  Ok "Đã cài thư viện Python"
}

# ---------------------------------------------------------------- 3. Ollama

Tieu 3 "Ollama và mô hình chữ"

if ($BoQuaOllama) {
  Canh "Bỏ qua Ollama theo yêu cầu. Tự cài và tải mô hình chữ."
} elseif (CoLenh "ollama") {
  Ok "Đã có Ollama"
} else {
  if (Lam "cài Ollama" { CaiWinget "Ollama.Ollama" "Ollama" }) { Ok "Đã cài Ollama" }
}

function OllamaSong {
  try { Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -TimeoutSec 4 -UseBasicParsing | Out-Null; return $true }
  catch { return $false }
}

if (-not $BoQuaOllama) { Lam "chạy Ollama và tải mô hình" {
  if (-not (OllamaSong)) {
    Tin "Khởi động Ollama..."
    $exe = CoLenh "ollama"
    if ($exe) {
      Start-Process -FilePath $exe -ArgumentList "serve" -WindowStyle Hidden
      for ($i = 0; $i -lt 30; $i++) { if (OllamaSong) { break }; Start-Sleep -Seconds 2 }
    }
  }
  if (OllamaSong) {
    Ok "Ollama đang chạy"
    $daCo = (& ollama list | Out-String)
    foreach ($m in @($MoHinhChat, $MoHinhNong)) {
      if ($daCo -match [regex]::Escape($m)) {
        Ok "Đã có mô hình $m"
      } else {
        Write-Host "      Đang tải mô hình $m (vài GB, xem tiến độ bên dưới)..." -ForegroundColor Gray
        & ollama pull $m
        if ($LASTEXITCODE -ne 0) { Hong "Tải mô hình $m thất bại" } else { Ok "Đã tải $m" }
      }
    }
  } else {
    Hong "Không khởi động được Ollama. Mở app Ollama thủ công rồi chạy lại bộ cài."
  }
} }

# ---------------------------------------------------------------- 4. ComfyUI

Tieu 4 "ComfyUI và mô hình ảnh SDXL"

$comfyMain = Join-Path $ThuMucComfy "ComfyUI\main.py"
$comfyPy = Join-Path $ThuMucComfy "python_embeded\python.exe"

if ($BoQuaComfy) {
  Canh "Bỏ qua ComfyUI theo yêu cầu. Chưa có ComfyUI thì nhân vật không gửi được ảnh."
} elseif (Test-Path $comfyMain) {
  Ok "Đã có ComfyUI: $ThuMucComfy"
} else {
  Tin "Sẽ cài ComfyUI vào: $ThuMucComfy"
  Lam "tải và giải nén ComfyUI (khoảng 2 GB)" {
    $cha = Split-Path -Parent $ThuMucComfy
    if (-not (Test-Path $cha)) { New-Item -ItemType Directory -Path $cha -Force | Out-Null }
    $z7 = Join-Path $env:TEMP "7zr.exe"
    if (-not (Test-Path $z7)) { TaiFile "https://www.7-zip.org/a/7zr.exe" $z7 "7zr.exe (600 KB)" }
    $goi = Join-Path $cha "ComfyUI_portable.7z"
    if (-not (Test-Path $goi)) {
      TaiFile "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z" $goi "ComfyUI (2.0 GB)"
    }
    Write-Host "      Đang giải nén..." -ForegroundColor Gray
    & $z7 x $goi "-o$cha" -y | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Giải nén ComfyUI thất bại" }
    Remove-Item $goi -Force -ErrorAction SilentlyContinue
    if (Test-Path $comfyMain) { Ok "Đã cài ComfyUI" } else { throw "Giải nén xong nhưng không thấy $comfyMain" }
  }
}

$thuMucCkpt = Join-Path $ThuMucComfy "ComfyUI\models\checkpoints"
$fileCkpt = Join-Path $thuMucCkpt $CheckpointTen
if ($BoQuaComfy -or $BoQuaCheckpoint) {
  if ($BoQuaCheckpoint) { Canh "Bỏ qua tải checkpoint theo yêu cầu. Tự chép file .safetensors vào $thuMucCkpt" }
} elseif (Test-Path $fileCkpt) {
  Ok "Đã có checkpoint $CheckpointTen"
} else {
  $khac = @()
  if (Test-Path $thuMucCkpt) { $khac = @(Get-ChildItem $thuMucCkpt -Filter *.safetensors -ErrorAction SilentlyContinue) }
  if ($khac.Count -gt 0) {
    Ok "Đã có sẵn checkpoint: $($khac[0].Name) - không tải thêm"
  } else {
    Lam "tải checkpoint SDXL (khoảng 6.9 GB)" {
      if (-not (Test-Path $thuMucCkpt)) { New-Item -ItemType Directory -Path $thuMucCkpt -Force | Out-Null }
      TaiFile $CheckpointUrl $fileCkpt "$CheckpointTen (6.9 GB)"
      Ok "Đã tải $CheckpointTen"
    }
  }
}

# ---------------------------------------------------------------- 5. cấu hình

Tieu 5 "Cấu hình WaifuAI"

Lam "ghi config.json (host 0.0.0.0, cổng $Cong)" {
  $cfg = @{ host = "0.0.0.0"; port = $Cong } | ConvertTo-Json
  GhiFile (Join-Path $Root "config.json") $cfg
  Ok "config.json: mở cho máy khác trong mạng, cổng $Cong"
}

Lam "ghi chay.bat" {
  $bat = @"
@echo off
chcp 65001 >nul
title WaifuAI
cd /d "%~dp0"

echo [1/3] Ollama...
curl -s -o nul -m 3 http://127.0.0.1:11434/api/tags
if errorlevel 1 start "" /min ollama serve

echo [2/3] ComfyUI...
if exist "$comfyPy" (
  curl -s -o nul -m 3 http://127.0.0.1:8188/
  if errorlevel 1 start "ComfyUI" /min /d "$ThuMucComfy" "$comfyPy" -s ComfyUI\main.py --windows-standalone-build --disable-auto-launch
) else (
  echo      Chua cai ComfyUI - nhan vat se khong gui duoc anh
)

echo [3/3] WaifuAI...
call .venv\Scripts\activate.bat
python run.py
pause
"@
  GhiFile (Join-Path $Root "chay.bat") $bat
  Ok "Đã tạo chay.bat (bật Ollama + ComfyUI + WaifuAI)"
}

# ---------------------------------------------------------------- 6. tường lửa

Tieu 6 "Tường lửa"

if ($BoQuaTuongLua) { Canh "Bỏ qua tường lửa theo yêu cầu. Máy khác sẽ không vào được." }
else { Lam "mở cổng $Cong cho mạng nhà và Tailscale" {
  Get-NetFirewallRule -DisplayName "WaifuAI*" -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
  New-NetFirewallRule -DisplayName "WaifuAI (mang nha)" -Direction Inbound -Protocol TCP -LocalPort $Cong `
      -Action Allow -Profile Private | Out-Null
  New-NetFirewallRule -DisplayName "WaifuAI (Tailscale)" -Direction Inbound -Protocol TCP -LocalPort $Cong `
      -Action Allow -Profile Any -RemoteAddress 100.64.0.0/10 | Out-Null
  Ok "Mở cổng ${Cong}: chỉ mạng nhà (Private) và dải Tailscale 100.64.0.0/10"
  Tin "Không mở ra Internet - app chưa có mật khẩu"
} }

# ---------------------------------------------------------------- 7. Tailscale

Tieu 7 "Tailscale - để điện thoại vào được khi ra ngoài"

$tsIp = ""
if ($BoQuaTailscale) {
  Canh "Bỏ qua Tailscale theo yêu cầu. Ra ngoài sẽ không vào được."
} else {
  $ts = CoLenh "tailscale"
  if (-not $ts) {
    $thu = "C:\Program Files\Tailscale\tailscale.exe"
    if (Test-Path $thu) { $ts = $thu }
  }
  if (-not $ts) {
    if (Lam "cài Tailscale" { CaiWinget "Tailscale.Tailscale" "Tailscale" }) {
      $ts = CoLenh "tailscale"
      if (-not $ts -and (Test-Path "C:\Program Files\Tailscale\tailscale.exe")) { $ts = "C:\Program Files\Tailscale\tailscale.exe" }
    }
  } else { Ok "Đã có Tailscale" }

  if ($ts -and -not $KiemTra) {
    $tsIp = (& $ts ip -4 | Out-String).Trim()
    if (-not $tsIp) {
      Write-Host ""
      Write-Host "      >>> Trinh duyet se mo ra de dang nhap Tailscale." -ForegroundColor Yellow
      Write-Host "      >>> Dang nhap bang Google/Microsoft, roi quay lai cua so nay." -ForegroundColor Yellow
      Write-Host ""
      & $ts up
      Start-Sleep -Seconds 3
      $tsIp = (& $ts ip -4 | Out-String).Trim()
    }
    if ($tsIp) { Ok "Tailscale đã nối: $tsIp" } else { Canh "Chưa đăng nhập Tailscale. Mở app Tailscale đăng nhập rồi chạy lại." }
  }
}

# ---------------------------------------------------------------- 8. tự chạy

Tieu 8 "Tự chạy khi bật máy"

if ($BoQuaTuChay) {
  Canh "Bỏ qua tự chạy. Phải bấm chay.bat thủ công mỗi lần bật máy."
} else {
  Lam "tạo lối tắt trong Startup" {
    $startup = [Environment]::GetFolderPath("Startup")
    $lnk = Join-Path $startup "WaifuAI.lnk"
    $sh = New-Object -ComObject WScript.Shell
    $s = $sh.CreateShortcut($lnk)
    $s.TargetPath = Join-Path $Root "chay.bat"
    $s.WorkingDirectory = $Root
    $s.WindowStyle = 7
    $s.Description = "WaifuAI"
    $s.Save()
    Ok "Đã tạo: $lnk"
    Tin "Muốn tắt: xoá file lối tắt đó đi"
  }
}

# ---------------------------------------------------------------- tổng kết

$lanIp = ""
try {
  $lanIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notmatch "^(127\.|169\.254\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.)" -and $_.PrefixOrigin -ne "WellKnown" } |
    Select-Object -First 1).IPAddress
} catch { }

Write-Host ""
Write-Host ("  " + ("=" * 68)) -ForegroundColor Magenta
if ($KiemTra) {
  Write-Host "   XEM TRUOC XONG - chua cai gi ca" -ForegroundColor Yellow
} elseif ($script:Loi.Count -gt 0) {
  Write-Host "   CAI XONG NHUNG CO LOI" -ForegroundColor Red
  foreach ($e in $script:Loi) { Write-Host "     x $e" -ForegroundColor Red }
} else {
  Write-Host "   CAI XONG" -ForegroundColor Green
}
if ($script:BoQua.Count -gt 0) {
  Write-Host ""
  foreach ($w in $script:BoQua) { Write-Host "     ! $w" -ForegroundColor Yellow }
}
Write-Host ""
Write-Host "   Bam chay.bat de bat, roi mo:" -ForegroundColor White
Write-Host "     Tren may nay   :  http://localhost:$Cong/chat"
if ($lanIp) { Write-Host "     Dien thoai o nha:  http://${lanIp}:$Cong/chat" }
if ($tsIp)  { Write-Host "     Dien thoai ra ngoai: http://${tsIp}:$Cong/chat" -ForegroundColor Green }
Write-Host "     Quan ly        :  http://localhost:$Cong/admin"
Write-Host ""
if (-not $BoQuaTailscale -and $tsIp) {
  Write-Host "   De dien thoai vao duoc khi ra ngoai:" -ForegroundColor White
  Write-Host "     1. Cai app Tailscale tren dien thoai (App Store / CH Play)"
  Write-Host "     2. Dang nhap CUNG tai khoan vua dung o buoc 7"
  Write-Host "     3. Bat Tailscale tren dien thoai, mo http://${tsIp}:$Cong/chat"
  Write-Host "     4. Them vao man hinh chinh de dung nhu mot app"
  Write-Host ""
  Write-Host "   Luu y: may nay phai dang BAT thi dien thoai moi dung duoc." -ForegroundColor Yellow
}
Write-Host ("  " + ("=" * 68)) -ForegroundColor Magenta
Write-Host ""
