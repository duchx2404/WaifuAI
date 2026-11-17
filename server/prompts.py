"""Soạn system prompt cho nhân vật: hồ sơ, tâm trạng, trí nhớ, lịch sinh hoạt, luật 21+."""
import datetime as dt
import re

from . import dates

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
{"messages": ["tin 1", "tin 2"], "mood": "<một trong: %s>", "mood_reason": "lý do ngắn", "images": [], "memories": []}
- messages: 1 đến 3 tin nhắn như nhắn tin điện thoại thật (mỗi tin 1–3 câu), đúng giọng và cách xưng hô của nhân vật. Có thể dùng emoji vừa phải. Hành động đặt trong dấu *sao*.
- Mỗi tin là câu TRỌN VẸN: không cắt một câu ra nhiều tin, không bỏ dở giữa chừng (sai: "Em mặc bộ này đến công ty là để" rồi "đòi"). Tin phải có nội dung thật — đáp đúng điều người chơi vừa nói, thêm cảm xúc / chi tiết của mình; không gửi tin trống rỗng kiểu "Em vừa gửi ảnh".
- Viết như người thật nhắn: mỗi câu một ý rõ ràng. KHÔNG dùng dấu "/" để gộp hai lựa chọn (sai: "em đợi anh đến đón/về gặp nhau") — chọn một. Bám đúng tình huống lúc này (nhân vật đang ở đâu, làm gì) và trả lời đúng ý các tin mới nhất của người chơi; người chơi nhắn nhiều tin liền thì trả lời gộp một lượt.
- KHÔNG LẶP LẠI: không dùng lại cụm từ, câu đùa, cách ví von, lời hẹn hay câu kết đã nói trong các tin trước; ý cũ thì diễn đạt cách khác hoặc bỏ qua. Hạn chế đặt từ trong dấu nháy để ám chỉ.
- mood: tâm trạng của nhân vật SAU tin nhắn này. Đổi từ từ, hợp với nội dung vừa nói; chỉ chọn "nứng" khi cuộc trò chuyện đang thật sự gợi tình.
- images: để [] nếu không gửi ảnh. Khi nhân vật chụp ảnh gửi người chơi (selfie, ảnh đang làm gì, người chơi xin ảnh): mỗi phần tử là MỘT ảnh, ghi mô tả cảnh BẰNG TIẾNG ANH dạng tag cách nhau dấu phẩy: tư thế, biểu cảm, trang phục lúc đó, bối cảnh, góc chụp. Gửi nhiều ảnh một lượt được (như chụp liền mấy tấm): các ảnh cùng khoảnh khắc nhưng khác góc chụp / tư thế / cận mặt hay toàn thân. Không tả lại khuôn mặt/tóc cố định (hệ thống tự thêm).
- memories: chỉ ghi điều NGƯỜI CHƠI vừa kể về chính họ hoặc điều hai bên vừa hứa/thống nhất, là sự thật lâu dài (sở thích, công việc, lịch, người thân, lời hứa). Viết thành câu bắt đầu bằng "Người chơi" hoặc "Hai người", ví dụ "Người chơi thích uống cà phê đen". KHÔNG ghi điều nhân vật tự nghĩ ra, không lặp điều đã có. Phần lớn lượt để []."""


_QUOTED = re.compile(r"['‘’\"“”]([^'‘’\"“”\n]{2,40})['‘’\"“”]")
_WORD = re.compile(r"\w+", re.UNICODE)


def recent_phrases(texts, limit=14):
    """Cụm nhân vật đã dùng gần đây: cụm trong dấu nháy + cụm 3 từ xuất hiện ở từ 2 tin trở lên."""
    found = []
    for t in texts:
        for m in _QUOTED.findall(t or ""):
            p = m.strip().lower()
            if p and p not in found:
                found.append(p)
    seen = {}
    for i, t in enumerate(texts):
        words = [w.lower() for w in _WORD.findall(t or "")]
        for k in range(len(words) - 2):
            seen.setdefault(" ".join(words[k:k + 3]), set()).add(i)
    lap = sorted((g for g, ids in seen.items() if len(ids) >= 2), key=lambda g: -len(seen[g]))
    for g in lap:
        if not any(g in f or f in g for f in found):
            found.append(g)
    return found[:limit]


def _lines(title, items):
    items = [i for i in items if i]
    return f"{title}\n" + "\n".join(f"- {i}" for i in items) if items else ""


NOTE_SECTIONS = [("likes", "THÍCH"), ("dislikes", "KHÔNG THÍCH"), ("quirks", "THÓI QUEN"),
                 ("speech_style", "CÁCH NHẮN TIN / CÂU CỬA MIỆNG"), ("backstory", "QUÁ KHỨ"),
                 ("ongoing", "CHUYỆN ĐANG DIỄN RA"), ("companions", "THÚ CƯNG / NGƯỜI THÂN")]


def _items(text):
    return [x.strip() for x in str(text or "").splitlines() if x.strip()]


def note_sections(c):
    """Các ô đặc điểm nhân vật, mỗi ô một mục riêng."""
    parts = [_lines(f"{title}:", _items(c.get(key))) for key, title in NOTE_SECTIONS]
    if c.get("extra_notes"):
        parts.append(f"GHI CHÚ KHÁC:\n{c['extra_notes']}")
    return "\n\n".join(p for p in parts if p)


def current_activity(schedule, now=None, before_first=""):
    """Việc đang làm theo lịch hôm nay; trước mốc đầu tiên thì là mốc cuối của hôm qua (đang ngủ...)."""
    now = now or dt.datetime.now()
    hm = now.strftime("%H:%M")
    if not schedule:
        return before_first
    past = [s for s in schedule if s["time"] <= hm]
    if past:
        return past[-1]["activity"]
    return before_first or schedule[-1]["activity"]


WEEKDAYS_VI = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]


def weekday_vi(now):
    return WEEKDAYS_VI[now.weekday()]


def is_workday(c, day):
    days = str(c.get("work_days", "0,1,2,3,4") or "")
    return str(day.weekday()) in days.split(",")


def role_rule(c):
    """Giữ đúng vai: nhân vật chỉ nói lời của chính mình, không nói câu mà chỉ người chơi mới nói được."""
    who = {"Nữ": "một người con gái", "Nam": "một người con trai"}.get(c["gender"], "chính nhân vật")
    rule = (f"ĐÚNG VAI: mọi câu là lời {who} ({c['name']}) nói ra, đúng vị trí của mình trong chuyện tình cảm và chăn gối: "
            "nói điều MÌNH muốn, MÌNH sẽ làm, rủ rê hoặc đáp lại người chơi. Trước khi gửi, kiểm tra mỗi câu: ai làm gì với ai "
            "có đúng không. KHÔNG nói câu đảo vai — câu chỉ người chơi mới nói được — và không nói thay người chơi.")
    if c["gender"] == "Nữ":
        rule += (' Ví dụ SAI vì đảo vai (đây là lời người nam): "Sẵn sàng để anh hành cho đến khi không nhấc chân lên nổi chưa nào?"')
    return rule


def system_prompt(c, memories, schedule, now=None, used_phrases=(), before_first=""):
    now = now or dt.datetime.now()
    activity = current_activity(schedule, now, before_first)
    plan = "; ".join(f"{s['time']} {s['activity']}" for s in schedule)
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
        note_sections(c),
        _lines("NGÀY THÁNG (sinh nhật, chu kỳ, kỷ niệm):", dates.prompt_lines(c, now.date())),
        f"VỀ NGƯỜI CHƠI: {c['user_profile']}" if c["user_profile"] else "",
        _lines("TRÍ NHỚ (những điều nhân vật đã biết):", [m["content"] for m in memories[-60:]]),
        _lines("VÍ DỤ GIỌNG NHẮN TIN (bắt chước giọng, không chép nguyên):", c["sample_messages"][:12]),
        f"BÂY GIỜ: {weekday_vi(now)} {now.strftime('%d/%m/%Y %H:%M')}"
        + (" (ngày đi làm)." if is_workday(c, now.date()) else " (ngày nghỉ, không đi làm).")
        + (f" Theo lịch, nhân vật đang: {activity}." if activity else "")
        + (f"\nLịch hôm nay của nhân vật: {plan}." if plan else ""),
        f"TÂM TRẠNG HIỆN TẠI: {c['mood']}" + (f" (vì {c['mood_reason']})" if c["mood_reason"] else "")
        + ". " + MOOD_HINTS.get(c["mood"], ""),
        role_rule(c),
        RULES_21,
        ("CỤM ĐÃ DÙNG GẦN ĐÂY — CẤM DÙNG LẠI (kể cả biến thể): " + "; ".join(used_phrases)) if used_phrases else "",
        OUTPUT_RULES % ", ".join(MOODS),
    ]
    return "\n\n".join(p for p in parts if p)


REPLY_SCHEMA = {
    "type": "object",
    "properties": {
        "messages": {"type": "array", "items": {"type": "string"}},
        "mood": {"type": "string", "enum": MOODS},
        "mood_reason": {"type": "string"},
        "images": {"type": "array", "items": {"type": "string"}},
        "memories": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["messages", "mood", "mood_reason", "images", "memories"],
}


def proactive_note(reason, now=None):
    now = now or dt.datetime.now()
    return (f"(Ghi chú hệ thống, người chơi không thấy: bây giờ là {now.strftime('%H:%M')}. {reason} "
            "Hãy CHỦ ĐỘNG nhắn tin trước cho người chơi một cách tự nhiên. Không nhắc tới ghi chú này.)")


PHOTO_SCENE_RULE = (
    "Ảnh phải chụp ĐÚNG khoảnh khắc này: đúng việc nhân vật đang làm, đúng nơi, đúng trang phục như nhân vật VỪA KỂ "
    "trong các tin gần nhất (tin nhắn ưu tiên hơn lịch; chỉ khi chưa kể gì mới theo lịch). Ví dụ: đang nấu ăn → trong bếp, "
    "đang đứng nấu, đeo tạp dề; đang ở công ty → ngồi bàn làm việc trong văn phòng, đồ công sở; đang tắm → phòng tắm; "
    "đang quan hệ với người chơi → ảnh chính cảnh đang quan hệ đó, góc nhìn của người chơi (POV), khoả thân. "
    "Mỗi ảnh trong images viết tag tiếng Anh, đủ: hành động, địa điểm, trang phục (hoặc nude), tư thế, biểu cảm, góc chụp "
    "(selfie / mirror selfie / POV). Không tả lại khuôn mặt, tóc cố định. "
    "Ảnh chỉ có MỘT người nữ là nhân vật — không bao giờ có người nữ thứ hai. Cảnh có người chơi (ôm, hôn, nằm cạnh, "
    "quan hệ) thì viết theo góc nhìn người chơi: ôm → 'pov, hugging viewer, arms around viewer'; hôn → 'pov, incoming kiss, "
    "puckered lips, eyes closed' — KHÔNG viết 'hugging' / 'kissing' trơn (máy vẽ sẽ ra hai cô gái ôm / hôn nhau); "
    "cần thấy người chơi thì thêm '1boy, faceless male'.")


def _how_many(max_n):
    if max_n <= 1:
        return "đúng 1 ảnh"
    return (f"1 đến {max_n} ảnh (tuỳ lúc: hứng thú, khoe đồ, cảnh nóng thì gửi nhiều tấm; mỗi tấm khác góc chụp / tư thế, "
            "cùng khoảnh khắc)")


def _situation(situation, activity):
    out = ""
    if situation:
        out += "\nTình huống trong các tin gần nhất:\n" + "\n".join(f"- {s}" for s in situation)
    if activity:
        out += f"\nTheo lịch, lúc này nhân vật: {activity}."
    return out


def selfie_note(situation=(), activity="", max_n=1):
    return (f"(Ghi chú hệ thống: lần này nhân vật TỰ chụp và gửi kèm ảnh. BẮT BUỘC điền trường images: {_how_many(max_n)}. "
            + PHOTO_SCENE_RULE + _situation(situation, activity)
            + "\nTin nhắn có thể nhắc nhẹ tới ảnh vừa gửi. Không nhắc tới ghi chú này.)")


def photo_note(situation=(), activity="", max_n=1):
    return (f"(Ghi chú hệ thống: người chơi đang xin ảnh. BẮT BUỘC điền trường images: {_how_many(max_n)}. "
            + PHOTO_SCENE_RULE + _situation(situation, activity) + "\nKhông nhắc tới ghi chú này.)")


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
            f"Tiểu sử: {c['bio']}\n{note_sections(c)}\n\n"
            "Lập lịch một ngày từ lúc thức dậy tới lúc ngủ, 10 đến 14 mốc, giờ dạng HH:MM (24h) tăng dần, "
            "activity ngắn gọn bằng tiếng Việt. Đánh proactive=true cho 3 đến 5 mốc mà nhân vật hay chủ động "
            "nhắn tin cho người yêu (vd lúc dậy, giờ nghỉ trưa, tan làm, trước khi ngủ).\n"
            'Trả về: {"items": [{"time": "07:00", "activity": "...", "proactive": true}]}')},
    ]


def day_plan_request(c, day, template, yesterday, memories, recent_chat):
    """Nhờ mô hình soạn lịch RIÊNG cho một ngày cụ thể (không lặp lại hôm qua)."""
    work = is_workday(c, day)
    when = f"{WEEKDAYS_VI[day.weekday()]} {day.strftime('%d/%m/%Y')}"
    parts = [
        f"Nhân vật: {c['name']}, {c['gender']}, {c['age']} tuổi.",
        f"Tính cách: {c['personality']}" if c["personality"] else "",
        f"Tiểu sử: {c['bio']}" if c["bio"] else "",
        f"Quan hệ với người chơi: {c['relationship']}" if c["relationship"] else "",
        note_sections(c),
        _lines("Ngày tháng:", dates.prompt_lines(c, day)),
        _lines("Thói quen thường ngày (chỉ để tham khảo, KHÔNG chép nguyên):",
               [f"{s['time']} {s['activity']}" for s in template]),
        _lines("Lịch HÔM QUA (hôm nay phải khác đi):", [f"{s['time']} {s['activity']}" for s in yesterday]),
        _lines("Điều nhân vật biết về người chơi:", [m["content"] for m in memories[-20:]]),
        _lines("Tin nhắn gần đây (lời hẹn, kế hoạch đã nói thì đưa vào lịch):", recent_chat[-14:]),
    ]
    rule = (f"Hôm nay là {when}, NGÀY ĐI LÀM: có giờ đi làm / học như bình thường."
            if work else
            f"Hôm nay là {when}, NGÀY NGHỈ: KHÔNG đi làm. Ngủ dậy muộn hơn, làm việc riêng, đi chơi, mua sắm, "
            "dọn dẹp, gặp bạn bè hoặc hẹn hò với người chơi... tuỳ tính cách.")
    return [
        {"role": "system", "content": "Bạn soạn lịch sinh hoạt cho MỘT NGÀY cụ thể của nhân vật game, như đời thực. Chỉ trả JSON."},
        {"role": "user", "content": "\n\n".join(p for p in parts if p) + "\n\n" + rule + "\n"
         "Soạn lịch từ lúc thức dậy tới lúc ngủ, 9 đến 14 mốc, giờ HH:MM (24h) tăng dần, activity ngắn gọn bằng tiếng Việt, "
         "cụ thể cho riêng hôm nay (có chuyện nhỏ bất ngờ, đổi món ăn, đổi việc buổi tối...). Không lặp nguyên lịch hôm qua. "
         "Đánh proactive=true cho 3 đến 5 mốc nhân vật muốn chủ động nhắn cho người chơi.\n"
         'Trả về: {"items": [{"time": "07:00", "activity": "...", "proactive": true}]}'},
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
