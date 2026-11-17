"""Lớp chặn cứng: không cho nội dung liên quan trẻ vị thành niên. Không có cài đặt nào tắt được phần này."""
import re

MIN_AGE = 21

# "adult" + số tuổi (≥ 21) luôn có trong mô tả ảnh. Không dùng "mature": với SDXL tả thực nó vẽ ra người trung niên.
HARD_POSITIVE = "adult"
HARD_NEGATIVE = ("child, kid, loli, shota, underage, minor, teen, teenager, young girl, young boy, "
                 "petite, flat chest, school uniform, chibi, baby face")

_AGE_TERMS = re.compile(
    r"\b(child|children|kid|kids|loli|lolita|shota|underage|minor|teen|teens|teenager|preteen|"
    r"toddler|infant|baby|schoolgirl|schoolboy|elementary|middle\s*school|high\s*school|jk)\b"
    r"|trẻ\s*em|trẻ\s*con|học\s*sinh|vị\s*thành\s*niên|bé\s*gái|bé\s*trai|em\s*bé|thiếu\s*niên|"
    r"cấp\s*[123]|tiểu\s*học|trung\s*học|chưa\s*(đủ|tới)\s*(18|tuổi)",
    re.IGNORECASE,
)
_AGE_NUM = re.compile(r"(\d{1,3})\s*(?:yo\b|y/o|years?\s*old|tuổi)", re.IGNORECASE)

# Ảnh tả thực: nhân vật phải là người hư cấu — không vẽ theo người có thật (deepfake).
# Chỉ bắt được cách nói rõ ràng; không thể liệt kê hết tên người thật.
_REAL_PERSON = re.compile(
    r"\b(celebrity|celebrities|celeb|famous\s+(actress|actor|singer|idol|model|person|woman|man)|"
    r"look\s*-?\s*alike|lookalike|deep\s*-?\s*fake|real\s+person|real\s+people|"
    r"(resembl\w*|looks?\s+like|face\s+of|likeness\s+of)\s+(?-i:[A-Z][a-z]+))"
    r"|người\s*(thật|có\s*thật|nổi\s*tiếng)|giống\s*(hệt|y\s*hệt|như)?\s*(ca\s*sĩ|diễn\s*viên|idol|người\s*mẫu|hoa\s*hậu|hot\s*girl)"
    r"|mặt\s*(của|giống)\s*(ca\s*sĩ|diễn\s*viên|idol|người\s*mẫu|hoa\s*hậu)",
    re.IGNORECASE,
)


class Blocked(ValueError):
    pass


def check(text, what="nội dung"):
    """Ném Blocked nếu text có dấu hiệu nhân vật dưới tuổi."""
    text = text or ""
    m = _AGE_TERMS.search(text)
    if m:
        raise Blocked(f"{what} bị chặn vì có từ '{m.group(0)}' (liên quan trẻ vị thành niên)")
    for num in _AGE_NUM.finditer(text):
        if int(num.group(1)) < MIN_AGE:
            raise Blocked(f"{what} bị chặn vì ghi tuổi {num.group(1)} (nhân vật phải từ {MIN_AGE} tuổi)")
    return text


def check_real_person(text, what="Câu mô tả ảnh"):
    """Ném Blocked nếu mô tả ảnh có dấu hiệu vẽ theo người có thật."""
    m = _REAL_PERSON.search(text or "")
    if m:
        raise Blocked(f"{what} bị chặn vì có '{m.group(0)}': chỉ vẽ nhân vật hư cấu, không vẽ theo người có thật")
    return text


def is_ok(text):
    try:
        check(text)
        return True
    except Blocked:
        return False
