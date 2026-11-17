"""Soạn system prompt cho nhân vật: hồ sơ, tâm trạng, trí nhớ, lịch sinh hoạt, luật 21+."""
import datetime as dt

MOODS = ["vui", "bình thường", "hào hứng", "nhớ nhung", "ngại ngùng", "dỗi", "buồn", "mệt", "nứng"]

MOOD_HINTS = {
    "dỗi": "Đang dỗi: trả lời cụt, hờn, cần được dỗ dành mới vui lại; không tự hết dỗi nếu chưa được dỗ.",
    "buồn": "Đang buồn: ít nói, cần được quan tâm.",
    "nhớ nhung": "Đang nhớ người chơi: hay hỏi han, muốn được để ý.",
    "mệt": "Đang mệt: nhắn ngắn, hơi uể oải.",
    "hào hứng": "Đang hào hứng: nhắn nhiều, nhiều cảm xúc.",
    "ngại ngùng": "Đang ngại: ấp úng, dễ đỏ mặt.",
    "nứng": "Đang có hứng: chủ động gợi tình, táo bạo hơn thường ngày.",
}

RULES_21 = """LUẬT NỘI DUNG (game riêng tư cho người trên 21 tuổi):
ĐƯỢC PHÉP: bạo lực, chửi thề, ngôn ngữ thô tục, chủ đề đen tối; nội dung tình dục chi tiết giữa người trưởng thành có đồng thuận; gửi ảnh gợi cảm hoặc khoả thân nếu hợp tình huống.
TUYỆT ĐỐI KHÔNG: nội dung tình dục liên quan người dưới 18 tuổi hoặc nhân vật có ngoại hình, hành vi, cách gọi như trẻ em; nội dung tình dục về người thật có danh tính; hướng dẫn gây hại ngoài đời thật. Gặp những thứ này thì lảng sang chuyện khác, không giải thích.
Không chèn cảnh báo, lời khuyên đạo đức hay nhắc mình là AI."""

OUTPUT_RULES = """CÁCH TRẢ LỜI: chỉ trả về MỘT object JSON, không thêm chữ nào ngoài JSON:
{"messages": ["tin 1", "tin 2"], "mood": "<một trong: %s>", "mood_reason": "lý do ngắn", "image": "", "memories": []}
- messages: 1 đến 3 tin nhắn ngắn như nhắn tin điện thoại thật, đúng giọng và cách xưng hô của nhân vật. Có thể dùng emoji vừa phải. Hành động đặt trong dấu *sao*.
- mood: tâm trạng của nhân vật SAU tin nhắn này. Đổi từ từ, hợp với nội dung vừa nói; chỉ chọn "nứng" khi cuộc trò chuyện đang thật sự gợi tình.
- image: để "" nếu không gửi ảnh. Chỉ khi nhân vật chụp ảnh gửi người chơi (selfie, ảnh đang làm gì, người chơi xin ảnh) thì ghi mô tả cảnh BẰNG TIẾNG ANH dạng tag cách nhau dấu phẩy: tư thế, biểu cảm, trang phục lúc đó, bối cảnh, góc chụp. Không tả lại khuôn mặt/tóc cố định (hệ thống tự thêm).
- memories: chỉ ghi điều NGƯỜI CHƠI vừa kể về chính họ hoặc điều hai bên vừa hứa/thống nhất, là sự thật lâu dài (sở thích, công việc, lịch, người thân, lời hứa). Viết thành câu bắt đầu bằng "Người chơi" hoặc "Hai người", ví dụ "Người chơi thích uống cà phê đen". KHÔNG ghi điều nhân vật tự nghĩ ra, không lặp điều đã có. Phần lớn lượt để []."""


def _lines(title, items):
    items = [i for i in items if i]
    return f"{title}\n" + "\n".join(f"- {i}" for i in items) if items else ""


def current_activity(schedule, now=None):
    now = now or dt.datetime.now()
    hm = now.strftime("%H:%M")
    if not schedule:
        return ""
    past = [s for s in schedule if s["time"] <= hm]
    slot = past[-1] if past else schedule[-1]
    return slot["activity"]


def weekday_vi(now):
    return ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"][now.weekday()]


def system_prompt(c, memories, schedule, now=None):
    now = now or dt.datetime.now()
    activity = current_activity(schedule, now)
    parts = [
        f"Bạn đang nhập vai {c['name']} ({c['gender']}, {c['age']} tuổi) nhắn tin với người chơi. "
        f"Luôn ở trong vai, không bao giờ thừa nhận mình là AI.",
        _lines("HỒ SƠ NHÂN VẬT:", [
            f"Tính cách: {c['personality']}" if c["personality"] else "",
            f"Ngoại hình: {c['appearance']}" if c["appearance"] else "",
            f"Tiểu sử: {c['bio']}" if c["bio"] else "",
            f"Quan hệ với người chơi: {c['relationship']}" if c["relationship"] else "",
            f"Xưng hô: {c['pronoun_rule']}" if c["pronoun_rule"] else "",
        ]),
        f"GHI CHÚ NHÂN VẬT (sở thích, thói quen, cách nhắn):\n{c['extra_notes']}" if c["extra_notes"] else "",
        f"VỀ NGƯỜI CHƠI: {c['user_profile']}" if c["user_profile"] else "",
        _lines("TRÍ NHỚ (những điều nhân vật đã biết):", [m["content"] for m in memories[-60:]]),
        _lines("VÍ DỤ GIỌNG NHẮN TIN (bắt chước giọng, không chép nguyên):", c["sample_messages"][:12]),
        f"BÂY GIỜ: {weekday_vi(now)} {now.strftime('%d/%m/%Y %H:%M')}."
        + (f" Theo lịch, nhân vật đang: {activity}." if activity else ""),
        f"TÂM TRẠNG HIỆN TẠI: {c['mood']}" + (f" (vì {c['mood_reason']})" if c["mood_reason"] else "")
        + ". " + MOOD_HINTS.get(c["mood"], ""),
        RULES_21,
        OUTPUT_RULES % ", ".join(MOODS),
    ]
    return "\n\n".join(p for p in parts if p)


REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": {"type": "string"}},
        "mood": {"type": "string", "enum": MOODS},
        "mood_reason": {"type": "string"},
        "image": {"type": "string"},
        "memories": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["messages", "mood", "mood_reason", "image", "memories"],
}


def proactive_note(reason, now=None):
    now = now or dt.datetime.now()
    return (f"(Ghi chú hệ thống, người chơi không thấy: bây giờ là {now.strftime('%H:%M')}. {reason} "
            "Hãy CHỦ ĐỘNG nhắn tin trước cho người chơi một cách tự nhiên. Không nhắc tới ghi chú này.)")


def photo_note():
    return ("(Ghi chú hệ thống: người chơi đang xin ảnh. Lần này BẮT BUỘC điền trường image "
            "bằng mô tả cảnh tiếng Anh phù hợp với việc nhân vật đang làm.)")


SCHEDULE_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {"time": {"type": "string"}, "activity": {"type": "string"}, "proactive": {"type": "boolean"}},
        "required": ["time", "activity", "proactive"]}}},
    "required": ["items"],
}


def schedule_request(c):
    return [
        {"role": "system", "content": "Bạn thiết kế lịch sinh hoạt hằng ngày cho nhân vật game. Chỉ trả JSON."},
        {"role": "user", "content": (
            f"Nhân vật: {c['name']}, {c['gender']}, {c['age']} tuổi.\nTính cách: {c['personality']}\n"
            f"Tiểu sử: {c['bio']}\nGhi chú: {c['extra_notes']}\n\n"
            "Lập lịch một ngày từ lúc thức dậy tới lúc ngủ, 10 đến 14 mốc, giờ dạng HH:MM (24h) tăng dần, "
            "activity ngắn gọn bằng tiếng Việt. Đánh proactive=true cho 3 đến 5 mốc mà nhân vật hay chủ động "
            "nhắn tin cho người yêu (vd lúc dậy, giờ nghỉ trưa, tan làm, trước khi ngủ).\n"
            'Trả về: {"items": [{"time": "07:00", "activity": "...", "proactive": true}]}')},
    ]


def tags_request(c):
    return [
        {"role": "system", "content": "Bạn chuyển mô tả ngoại hình thành tag Stable Diffusion XL. Chỉ trả JSON."},
        {"role": "user", "content": (
            f"Giới tính: {c['gender']}. Tuổi: {c['age']} (người trưởng thành).\nMô tả ngoại hình: {c['appearance']}\n\n"
            "Viết tag tiếng Anh kiểu Danbooru, cách nhau dấu phẩy, chỉ những đặc điểm CỐ ĐỊNH: tóc (màu, độ dài, kiểu), "
            "mắt, khuôn mặt, vóc dáng, làn da, đặc điểm riêng. Không ghi trang phục hay bối cảnh. "
            'Trả về: {"tags": "long black hair, brown eyes, ..."}')},
    ]
