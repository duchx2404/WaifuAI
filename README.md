# WaifuAI

App trò chuyện với nhân vật ảo chạy hoàn toàn trên máy của bạn: **Ollama** sinh thoại, **ComfyUI + SDXL** vẽ ảnh. Ý tưởng lấy từ IdolAI nhưng không cần Gemini API hay Telegram.

- **Chat** — `http://localhost:8600/chat`: nhắn tin, nhận ảnh, xin ảnh 📷, nhân vật tự nhắn trước.
- **Quản lý** — `http://localhost:8600/admin`: hồ sơ nhân vật, ảnh đại diện / LoRA, trí nhớ & tâm trạng, lịch sinh hoạt, cài đặt mô hình.

## Cài đặt — chạy một file là xong

Trên máy có GPU NVIDIA, bấm đúp **`cai-dat.bat`** rồi bấm Yes ở hộp xin quyền Administrator. Bộ cài tự làm hết:

| Bước | Làm gì |
|---|---|
| 1 | Kiểm tra GPU, RAM, dung lượng trống, quyền Administrator |
| 2 | Cài Python 3.12 nếu thiếu, tạo `.venv`, cài thư viện |
| 3 | Cài Ollama, tải `gemma3:12b` và `mistral-nemo:12b` — đã có mô hình cùng họ (vd. `gemma-4`) hay bản bỏ kiểm duyệt (`abliterated`, `uncensored`) thì dùng luôn, không tải |
| 4 | Tải ComfyUI bản portable + checkpoint SDXL — đã có `X:\ComfyUI_windows_portable` hay checkpoint (kể cả trong `extra_model_paths.yaml`) thì dùng luôn; checkpoint tải vào ổ còn trống nhiều nhất |
| 5 | Ghi `config.json` (mở cho máy khác trong mạng) và `chay.bat` |
| 6 | Mở cổng 8600 cho mạng nhà và dải Tailscale |
| 7 | Cài Tailscale, đăng nhập (mở trình duyệt một lần) |
| 8 | Tạo lối tắt trong Startup để tự chạy khi bật máy |

Tải về khoảng **24 GB**, cần khoảng **30 GB** trống. Mạng đứt giữa chừng thì chạy lại `cai-dat.bat`, nó tải tiếp chỗ dở chứ không tải lại từ đầu. Chạy lại nhiều lần cũng không sao — bước nào xong rồi thì bỏ qua.

Cài xong, bấm **`chay.bat`** để bật (nó mở luôn Ollama + ComfyUI + WaifuAI).

### Xem trước, không cài gì

```powershell
powershell -ExecutionPolicy Bypass -File install.ps1 -KiemTra
```

### Các tuỳ chọn

| Tham số | Ý nghĩa |
|---|---|
| `-ThuMucComfy "D:\ComfyUI"` | Chỗ cài ComfyUI (mặc định: cạnh thư mục WaifuAI) |
| `-CheckpointUrl "<link>"` | Checkpoint khác (mặc định LUSTIFY v2.0) |
| `-MoHinhChat "qwen3:8b"` | Mô hình chữ khác, hợp với GPU dưới 10 GB |
| `-Cong 9000` | Đổi cổng |
| `-BoQuaOllama` `-BoQuaComfy` `-BoQuaCheckpoint` | Đã có sẵn thì bỏ qua |
| `-BoQuaTuongLua` `-BoQuaTailscale` `-BoQuaTuChay` | Không đụng tường lửa / Tailscale / Startup |

**Về checkpoint:** mặc định tải **LUSTIFY v2.0** (SDXL tinh chỉnh ảnh tả thực, vẽ được cảnh nóng; bản sao trên Hugging Face, SHA256 khớp bản gốc trên Civitai, 6.5 GB). Hiểu cả câu văn lẫn tag; cảnh nóng mạnh có khi phải vẽ lại vài lần. Cài đặt ảnh mặc định theo khuyến nghị của tác giả: DPM++ 2M SDE Karras, CFG 5, 30 bước. Muốn bản khác thì chép file `.safetensors` vào `ComfyUI\models\checkpoints\` rồi chọn trong **Quản lý → Cài đặt**, hoặc truyền `-CheckpointUrl`.

## Giữ khuôn mặt nhân vật

**Cách 1 — PuLID (không cần huấn luyện):** chạy `tools\cai_pulid_sdxl.bat` một lần (cài node PuLID_ComfyUI + mô hình 0.79 GB), khởi động lại ComfyUI. Trong **Quản lý → Ảnh**, vẽ ảnh đại diện rồi bật *Giữ khuôn mặt theo ảnh đại diện*: mọi ảnh trong chat lấy mặt từ ảnh đó. Chỉ ảnh do app tự vẽ mới được làm mặt mẫu — ảnh đi kèm file nhập thì không.

**Cách 2 — LoRA từ 1 ảnh (giống nhất):** từ một ảnh AI vẽ của nhân vật, `tools\lora_1_anh` vẽ ra cả bộ ảnh nhiều góc rồi huấn luyện LoRA SDXL:

```powershell
# 1. Flux dev + PuLID-Flux vẽ ~32 ảnh (ComfyUI phải đang chạy; ~2,5 phút/ảnh trên RTX 3060)
.venv\Scripts\python.exe tools\lora_1_anh\ve_bo_anh.py --ten nu_chinh --anh "D:\...\face.png"
# 2. Chấm độ giống mặt, chọn ảnh vào dataset\, ghép bang_xem.jpg để xem lại
E:\ComfyUI_windows_portable\python_embeded\python.exe -I tools\lora_1_anh\cham_diem.py --ten nu_chinh
# 3. Huấn luyện LoRA SDXL trên LUSTIFY (tự tắt ComfyUI + Ollama), ra D:\AI\models\loras\wf_nu_chinh.safetensors
D:\AI\venv\kohya\Scripts\python.exe -I tools\lora_1_anh\huan_luyen.py --ten nu_chinh
```

Chọn LoRA `wf_…` cho nhân vật ở **Quản lý → Ảnh**; từ khoá kích hoạt được tự chèn.

**Sửa mặt (FaceDetailer, nên bật):** chạy `tools\cai_face_detailer.bat` một lần (Impact Pack + Impact Subpack + `face_yolov8m.pt`), bật lại ComfyUI. Mỗi ảnh được dò mặt rồi vẽ lại riêng vùng mặt ở độ phân giải cao qua LoRA — giữ đúng mặt cả ở ảnh nửa người / toàn thân (mặt nhỏ thì SDXL hay vẽ lệch). Bật / tắt và chỉnh độ vẽ lại ở **Quản lý → Cài đặt**; chưa cài thì app tự bỏ qua bước này. Chỉ dùng cho nhân vật hư cấu — không dùng ảnh chụp người thật.

## Dùng trên điện thoại

Điện thoại **không chạy AI** — nó chỉ mở trình duyệt, mọi thứ vẫn chạy trên máy GPU. Máy đó phải đang bật.

**Ở nhà, cùng WiFi:** mở `http://<IP máy GPU>:8600/chat`. Bộ cài in sẵn địa chỉ này ở cuối.

**Ra ngoài:** bộ cài đã dựng sẵn Tailscale.
1. Cài app **Tailscale** trên điện thoại (App Store / CH Play).
2. Đăng nhập **cùng tài khoản** đã dùng ở bước 7 của bộ cài.
3. Bật Tailscale, mở `http://<IP Tailscale của máy GPU>:8600/chat`.
4. Menu trình duyệt → **Thêm vào màn hình chính** để dùng như một app.

Cách này không mở cổng nào ra Internet: chỉ thiết bị trong tài khoản Tailscale của bạn mới vào được.

**Ra ngoài, chỉ cần trình duyệt (không cài app trên điện thoại) — Tailscale Funnel:**
1. Đặt mật khẩu trước: bấm đúp `dat-mat-khau.bat` (thêm `--ngau-nhien` để tự sinh). Chưa có mật khẩu thì WaifuAI từ chối mọi truy cập qua Funnel.
2. Trên máy GPU (đã đăng nhập Tailscale): `tailscale funnel --bg 8600`. Lần đầu nó đưa một link để bật Funnel cho tài khoản — bấm *Enable*.
3. Mở `https://<tên-máy>.<tên-mạng>.ts.net/chat` ở bất cứ đâu, đăng nhập một lần (nhớ 30 ngày).

Funnel đưa app ra Internet công khai, nên mật khẩu là bắt buộc; sai 5 lần thì khoá 15 phút. Tắt: `tailscale funnel --https=443 off`. **Cloudflare WARP (1.1.1.1) đang bật sẽ chặn Tailscale** — tắt WARP thì Tailscale mới đăng nhập/kết nối được.

## Ghi chú

- **VRAM 12 GB:** bật *Nhả VRAM giữa chữ và ảnh* (mặc định bật) để mô hình chữ và SDXL không cùng nằm trong VRAM.
- **Cảnh nóng:** điều khoản Gemma cấm nội dung khiêu dâm, nên khi tin nhắn có nội dung tình dục app tự chuyển sang *Mô hình cảnh nóng* (mặc định `mistral-nemo:12b`) trong 6 lượt.
- **Lớp chặn cứng (không tắt được):** nhân vật phải từ 21 tuổi; mô tả ảnh có dấu hiệu trẻ vị thành niên thì không vẽ; luôn thêm `adult, <tuổi> years old` và danh sách cấm vẽ trẻ em vào mọi ảnh (không dùng `mature` vì SDXL tả thực sẽ vẽ người trung niên; nhân vật 21–29 tuổi còn được cấm vẽ già: `middle-aged, wrinkles...`).
- **Không vẽ người có thật:** mô tả ảnh có dấu hiệu vẽ theo người thật (`celebrity`, `lookalike`, `looks like <Tên>`, "giống ca sĩ/diễn viên"...) thì không vẽ. Lớp này chỉ bắt cách nói rõ ràng — đừng gắn LoRA khuôn mặt người thật cho nhân vật.
- **Mật khẩu:** đặt / đổi bằng `dat-mat-khau.bat` (lưu dạng băm trong `data/auth.json`; đổi mật khẩu thì mọi thiết bị phải đăng nhập lại; `--xoa` để bỏ). Chưa đặt mật khẩu thì chỉ chính máy chủ vào được. Đăng xuất: mở `/logout`. Đừng mở cổng router ra Internet — dùng Tailscale / Funnel.
- Dữ liệu nằm trong `data/` (`waifu.db` + `images/`). Sao lưu thư mục này là đủ.
