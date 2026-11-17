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
| 3 | Cài Ollama, tải `gemma3:12b` và `mistral-nemo:12b` |
| 4 | Tải ComfyUI bản portable + checkpoint SDXL, giải nén |
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
| `-CheckpointUrl "<link>"` | Checkpoint khác (mặc định SDXL base của Stability) |
| `-MoHinhChat "qwen3:8b"` | Mô hình chữ khác, hợp với GPU dưới 10 GB |
| `-Cong 9000` | Đổi cổng |
| `-BoQuaOllama` `-BoQuaComfy` `-BoQuaCheckpoint` | Đã có sẵn thì bỏ qua |
| `-BoQuaTuongLua` `-BoQuaTailscale` `-BoQuaTuChay` | Không đụng tường lửa / Tailscale / Startup |

**Về checkpoint:** mặc định tải SDXL base của Stability vì link ổn định và không cần đăng nhập. Bản này vẽ ảnh "sạch" và không mạnh ở phong cách nhân vật. Muốn dùng bản tinh chỉnh của cộng đồng thì chép file `.safetensors` vào `ComfyUI\models\checkpoints\` rồi chọn trong **Quản lý → Cài đặt**, hoặc truyền `-CheckpointUrl`.

## Dùng trên điện thoại

Điện thoại **không chạy AI** — nó chỉ mở trình duyệt, mọi thứ vẫn chạy trên máy GPU. Máy đó phải đang bật.

**Ở nhà, cùng WiFi:** mở `http://<IP máy GPU>:8600/chat`. Bộ cài in sẵn địa chỉ này ở cuối.

**Ra ngoài:** bộ cài đã dựng sẵn Tailscale.
1. Cài app **Tailscale** trên điện thoại (App Store / CH Play).
2. Đăng nhập **cùng tài khoản** đã dùng ở bước 7 của bộ cài.
3. Bật Tailscale, mở `http://<IP Tailscale của máy GPU>:8600/chat`.
4. Menu trình duyệt → **Thêm vào màn hình chính** để dùng như một app.

Cách này không mở cổng nào ra Internet: chỉ thiết bị trong tài khoản Tailscale của bạn mới vào được.

## Ghi chú

- **VRAM 12 GB:** bật *Nhả VRAM giữa chữ và ảnh* (mặc định bật) để mô hình chữ và SDXL không cùng nằm trong VRAM.
- **Cảnh nóng:** điều khoản Gemma cấm nội dung khiêu dâm, nên khi tin nhắn có nội dung tình dục app tự chuyển sang *Mô hình cảnh nóng* (mặc định `mistral-nemo:12b`) trong 6 lượt.
- **Lớp chặn cứng (không tắt được):** nhân vật phải từ 21 tuổi; mô tả ảnh có dấu hiệu trẻ vị thành niên thì không vẽ; luôn thêm `adult, mature, <tuổi> years old` và danh sách cấm vẽ trẻ em vào mọi ảnh.
- **Chưa có mật khẩu:** app tin mọi người vào được địa chỉ của nó. Chỉ dùng trong mạng nhà và qua Tailscale, đừng mở cổng ra Internet.
- Dữ liệu nằm trong `data/` (`waifu.db` + `images/`). Sao lưu thư mục này là đủ.
