"""Ngày sinh, chu kỳ kinh nguyệt và ngày kỷ niệm của nhân vật (chỉ tính toán, không đụng DB)."""
import datetime as dt
import re

CYCLE_RANGE = (20, 45)
PERIOD_RANGE = (2, 10)
PMS_DAYS = 3  # mấy ngày trước kỳ thì nhân vật dễ cáu, nhạy cảm


def parse_date(s):
    """'2003-04-24' hoặc '24/04/2003' → date; sai → None."""
    s = str(s or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        y, mo, d = map(int, m.groups())
    else:
        m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s)
        if not m:
            return None
        d, mo, y = map(int, m.groups())
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def iso(s):
    d = parse_date(s)
    return d.isoformat() if d else ""


def dmy(d, year=True):
    return d.strftime("%d/%m/%Y" if year else "%d/%m")


def _on_year(d, year):
    """Ngày d trong năm `year` (29/02 → 28/02 nếu năm không nhuận)."""
    try:
        return d.replace(year=year)
    except ValueError:
        return d.replace(year=year, day=28)


def age_on(birthday, today):
    b = parse_date(birthday)
    if not b:
        return None
    return today.year - b.year - ((today.month, today.day) < (b.month, b.day))


def next_yearly(d, today):
    """Lần tới (kể cả hôm nay) của một ngày lặp lại hằng năm → (ngày, còn mấy ngày, tròn mấy năm)."""
    nxt = _on_year(d, today.year)
    if nxt < today:
        nxt = _on_year(d, today.year + 1)
    return nxt, (nxt - today).days, nxt.year - d.year


def cycle_info(period_start, cycle_length, period_length, today):
    """Trạng thái chu kỳ hôm nay. None nếu chưa nhập ngày đến kỳ."""
    start = parse_date(period_start)
    if not start:
        return None
    cyc = min(max(int(cycle_length or 28), CYCLE_RANGE[0]), CYCLE_RANGE[1])
    plen = min(max(int(period_length or 5), PERIOD_RANGE[0]), PERIOD_RANGE[1])
    if today < start:
        cur, nxt = None, start
    else:
        k = (today - start).days // cyc
        cur = start + dt.timedelta(days=k * cyc)
        nxt = cur + dt.timedelta(days=cyc)
    day = (today - cur).days + 1 if cur else 0
    on_period = bool(cur) and day <= plen
    days_to = (nxt - today).days
    state = "period" if on_period else "pms" if days_to <= PMS_DAYS else "normal"
    return {"state": state, "day": day if on_period else 0, "length": plen, "cycle": cyc,
            "current_start": cur, "next_start": nxt, "days_to_next": days_to,
            "after_next": nxt + dt.timedelta(days=cyc)}


def anniversaries(items, today, within=14):
    """Ngày kỷ niệm sắp tới trong `within` ngày (kể cả hôm nay), gần nhất trước."""
    out = []
    for it in items or []:
        d = parse_date(it.get("date"))
        title = str(it.get("title") or "").strip()
        if not d or not title:
            continue
        if it.get("yearly", True):
            when, left, years = next_yearly(d, today)
        else:
            when, left, years = d, (d - today).days, 0
            if left < 0:
                continue
        if left <= within:
            out.append({"title": title, "date": when, "days": left, "years": years, "origin": d})
    return sorted(out, key=lambda x: x["days"])


def today_events(c, today):
    """Sự kiện đúng hôm nay (sinh nhật, kỷ niệm) để nhân vật chủ động nhắn."""
    ev = []
    b = parse_date(c.get("birthday"))
    if b and next_yearly(b, today)[1] == 0:
        ev.append(f"sinh nhật lần thứ {age_on(b.isoformat(), today)} của chính nhân vật")
    for a in anniversaries(c.get("anniversaries"), today, within=0):
        ev.append(a["title"] + (f" (tròn {a['years']} năm)" if a["years"] > 0 else ""))
    return ev


def prompt_lines(c, today):
    """Các dòng về ngày tháng đưa vào system prompt."""
    lines = []
    b = parse_date(c.get("birthday"))
    if b:
        _, left, _ = next_yearly(b, today)
        if left == 0:
            lines.append(f"HÔM NAY LÀ SINH NHẬT nhân vật (tròn {age_on(b.isoformat(), today)} tuổi) — nhân vật mong được người chơi nhớ và chúc.")
        else:
            lines.append(f"Ngày sinh nhân vật: {dmy(b)} (còn {left} ngày tới sinh nhật).")
    cy = cycle_info(c.get("period_start"), c.get("cycle_length"), c.get("period_length"), today)
    if cy:
        if cy["state"] == "period":
            lines.append(f"Nhân vật ĐANG ĐẾN KỲ KINH NGUYỆT (ngày {cy['day']}/{cy['length']}): người mệt, có thể đau bụng, "
                         "thèm đồ ngọt, dễ nhạy cảm, muốn được chiều; không muốn quan hệ — người chơi gạ thì từ chối khéo, chỉ ôm ấp.")
        elif cy["state"] == "pms":
            lines.append(f"Nhân vật sắp đến kỳ (còn {cy['days_to_next']} ngày): dễ cáu, dễ tủi thân, hay dỗi hơn thường ngày.")
        lines.append(f"Kỳ kinh tới dự kiến: {dmy(cy['next_start'], False)} (còn {cy['days_to_next']} ngày)."
                     if cy["state"] != "period" else
                     f"Kỳ này bắt đầu {dmy(cy['current_start'], False)}, kỳ sau dự kiến {dmy(cy['next_start'], False)}.")
    for a in anniversaries(c.get("anniversaries"), today):
        nam = f", tròn {a['years']} năm" if a["years"] > 0 else ""
        if a["days"] == 0:
            lines.append(f"HÔM NAY là ngày kỷ niệm: {a['title']}{nam} — nhân vật nhớ và nhắc tới.")
        else:
            lines.append(f"Sắp tới: {a['title']} ngày {dmy(a['date'], False)} (còn {a['days']} ngày{nam}).")
    others = [f"{str(it.get('title')).strip()} {dmy(parse_date(it.get('date')))}" for it in c.get("anniversaries") or []
              if parse_date(it.get("date")) and str(it.get("title") or "").strip()]
    if others:
        lines.append("Các ngày kỷ niệm của hai người: " + "; ".join(others) + ".")
    return lines


def clean_anniversaries(items):
    """Chuẩn hoá danh sách từ giao diện / file nhập: [{date: ISO, title, yearly}]."""
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        d = iso(it.get("date"))
        title = str(it.get("title") or "").strip()[:120]
        if d and title:
            out.append({"date": d, "title": title, "yearly": bool(it.get("yearly", True))})
    return sorted(out, key=lambda x: x["date"][5:])
