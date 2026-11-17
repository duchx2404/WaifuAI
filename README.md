# WaifuAI

App trò chuyện với nhân vật ảo chạy hoàn toàn trên máy của bạn: **Ollama** sinh thoại, **ComfyUI + SDXL** vẽ ảnh. Ý tưởng lấy từ IdolAI nhưng không cần Gemini API hay Telegram.

- **Chat** — `http://localhost:8600/chat`: nhắn tin, nhận ảnh, xin ảnh 📷, nhân vật tự nhắn trước.
- **Quản lý** — `http://localhost:8600/admin`: hồ sơ nhân vật, ảnh đại diện / LoRA, trí nhớ & tâm trạng, lịch sinh hoạt, cài đặt mô hình.

## Cài trên máy có GPU (NVIDIA 12 GB)

1. **Ollama**
   ```powershell
   ollama pull gemma3:12b
   ollama pull mistral-nemo:12b
   ```
2. **ComfyUI** — tải bản *portable cho NVIDIA*, chép checkpoint SDXL (`.safetensors`) vào `ComfyUI\models\checkpoints\` (LoRA nhân vật vào `models\loras\`), chạy `run_nvidia_gpu.bat`.
3. **WaifuAI** — chép cả thư mục này sang, cài Python 3.10 trở lên, chạy `run.bat` (lần đầu tự tạo `.venv` và cài thư viện).
4. Mở **Quản lý → Cài đặt**: kiểm tra kết nối, chọn **Checkpoint**, bấm **Lưu cài đặt**.
5. **Nhân vật → + Tạo nhân vật**, hoặc **Nhập file** từ IdolAI (`HabitMate_HoSo_*.json` hoặc `HabitMate_MultiIdol_*.json`; token bot Telegram bị bỏ qua). Sang tab **Ảnh**: *Tạo tag từ mô tả ngoại hình* → **Lưu** → *Vẽ ảnh đại diện*. Tab **Lịch sinh hoạt**: *AI tạo lịch* → **Lưu**.

## Mở từ điện thoại / máy khác trong mạng LAN

Sửa `config.json` thành `"host": "0.0.0.0"`, mở cổng 8600 trên tường lửa Windows (chỉ mạng Private). WaifuAI **không có mật khẩu** — đừng mở ra Internet.

## Ghi chú

- **VRAM 12 GB:** bật *Nhả VRAM giữa chữ và ảnh* (mặc định bật) để mô hình chữ và SDXL không cùng nằm trong VRAM.
- **Cảnh nóng:** điều khoản Gemma cấm nội dung khiêu dâm, nên khi tin nhắn có nội dung tình dục app tự chuyển sang *Mô hình cảnh nóng* (mặc định `mistral-nemo:12b`) trong 6 lượt.
- **Lớp chặn cứng (không tắt được):** nhân vật phải từ 21 tuổi; mô tả ảnh có dấu hiệu trẻ vị thành niên thì không vẽ; luôn thêm `adult, mature, <tuổi> years old` và danh sách cấm vẽ trẻ em vào mọi ảnh.
- Dữ liệu nằm trong `data/` (`waifu.db` + `images/`). Sao lưu thư mục này là đủ.
