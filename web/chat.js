/* Giao diện Chat */
(function () {
  const { h, api, toast, esc } = UI;
  const $ = (id) => document.getElementById(id);
  const app = $("app"), rosterEl = $("roster"), msgsEl = $("messages"), input = $("input");

  const st = {
    chars: [],
    active: null,       // id nhân vật đang mở
    rev: 0,
    msgs: new Map(),    // id -> tin nhắn
    busy: false,
    sending: false,
    hasOlder: true,
    seen: UI.store.get("waifu_seen", {}),
  };

  // ---------- định dạng ----------
  const pad = (n) => String(n).padStart(2, "0");
  const parseTs = (s) => new Date(String(s).replace(" ", "T"));
  const hm = (s) => { const d = parseTs(s); return isNaN(d) ? "" : pad(d.getHours()) + ":" + pad(d.getMinutes()); };
  const dayLabel = (s) => {
    const d = parseTs(s), t = new Date(); if (isNaN(d)) return "";
    const y = new Date(t); y.setDate(t.getDate() - 1);
    if (d.toDateString() === t.toDateString()) return "Hôm nay";
    if (d.toDateString() === y.toDateString()) return "Hôm qua";
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
  };
  const shortTime = (s) => (dayLabel(s) === "Hôm nay" ? hm(s) : dayLabel(s).replace(/\/\d{4}$/, ""));
  const richText = (t) => esc(t).replace(/\*([^*\n]+)\*/g, "<em>$1</em>");

  // ---------- danh sách nhân vật ----------
  async function loadRoster() {
    try { st.chars = await api("GET", "/api/characters"); } catch (e) { return; }
    renderRoster();
  }

  function renderRoster() {
    rosterEl.replaceChildren();
    if (!st.chars.length) {
      rosterEl.append(h("div", { class: "empty-state" },
        h("p", {}, "Chưa có nhân vật nào."),
        h("a", { class: "btn primary", href: "/admin" }, "Tạo nhân vật")));
      return;
    }
    // Ghim lên đầu; trong mỗi nhóm xếp theo thời gian tin cuối
    // (tin nhập từ IdolAI có id mới nhưng ngày cũ nên không xếp theo id)
    const key = (c) => (c.last_message ? c.last_message.created_at : "");
    const theoTin = (a, b) => key(b).localeCompare(key(a)) || b.id - a.id;
    const ghim = st.chars.filter((c) => c.pinned).sort(theoTin);
    const thuong = st.chars.filter((c) => !c.pinned).sort(theoTin);
    const sorted = ghim.concat(thuong);
    for (const c of sorted) {
      if (ghim.length && thuong.length && c === thuong[0]) rosterEl.append(h("div", { class: "r-sep" }));
      const last = c.last_message;
      const unread = last && last.role === "assistant" && last.id > (st.seen[c.id] || 0) && c.id !== st.active;
      let preview = c.busy ? "đang nhập..." : last ? (last.role === "user" ? "Bạn: " : "") + (last.content || (last.image_path ? "📷 Ảnh" : "")) : "Chưa có tin nhắn";
      const row = h("button", {
        class: "r-item" + (c.id === st.active ? " active" : "") + (unread ? " unread" : "") + (c.pinned ? " pinned" : ""),
        onclick: () => { if (row.dataset.lp) { delete row.dataset.lp; return; } openChat(c.id); },
        oncontextmenu: (e) => { e.preventDefault(); menuGhim(c, e.clientX, e.clientY); },
      },
        h("span", { class: "r-av" }, UI.avatar(c, 48), h("span", { class: "r-mood" }, UI.MOOD_EMOJI[c.mood] || "")),
        h("span", { class: "r-body" },
          h("span", { class: "r-top" },
            c.pinned ? h("span", { class: "r-pin", "aria-label": "đã ghim" }, "📌") : "",
            h("span", { class: "r-name" }, c.name),
            last ? h("span", { class: "r-time" }, shortTime(last.created_at)) : ""),
          h("span", { class: "r-last" }, preview)),
        unread ? h("span", { class: "r-badge" }) : "");
      UI.longPress(row, (x, y) => menuGhim(c, x, y));
      rosterEl.append(row);
    }
  }

  function menuGhim(c, x, y) {
    UI.menu(x, y, [{
      icon: "📌",
      label: c.pinned ? "Bỏ ghim" : "Ghim lên đầu",
      onClick: async () => {
        try {
          const moi = await api("POST", `/api/characters/${c.id}/pin`, { pinned: !c.pinned });
          c.pinned = moi.pinned;
          renderRoster();
          toast(moi.pinned ? `Đã ghim ${c.name}` : `Đã bỏ ghim ${c.name}`, "ok");
        } catch (e) { toast(e.message, "bad"); }
      },
    }]);
  }

  // ---------- mở cuộc trò chuyện ----------
  const narrow = () => matchMedia("(max-width: 760px)").matches;

  async function openChat(id) {
    // Điện thoại: mở hội thoại = một bước trong lịch sử, để vuốt lùi / nút Back về danh sách (như Messenger)
    if (narrow() && !(history.state && history.state.thread)) history.pushState({ thread: id }, "");
    else if (narrow()) history.replaceState({ thread: id }, "");
    st.active = id; st.rev = 0; st.msgs.clear(); st.hasOlder = true; st.busy = false;
    UI.store.set("waifu_last_chat", id);
    app.classList.add("show-thread");
    $("threadEmpty").classList.add("hidden");
    ["threadHead", "messages", "composer"].forEach((x) => $(x).classList.remove("hidden"));
    msgsEl.replaceChildren();
    renderHead();
    renderRoster();
    await poll(true);
    if (matchMedia("(min-width: 761px)").matches) input.focus();
  }

  function renderHead(extra) {
    const c = st.chars.find((x) => x.id === st.active);
    if (!c) return;
    $("headAvatar").replaceChildren(UI.avatar(c, 42));
    $("headName").textContent = c.name;
    const mood = extra?.mood ?? c.mood, act = extra?.activity ?? c.activity;
    $("headStatus").replaceChildren(
      h("span", { class: "chip" }, (UI.MOOD_EMOJI[mood] || "") + " " + mood),
      act ? h("span", { class: "act" }, act) : "");
  }

  // ---------- tải tin nhắn ----------
  async function poll(first = false) {
    const id = st.active;
    if (!id) return;
    let data;
    try { data = await api("GET", `/api/characters/${id}/messages?rev=${first ? 0 : st.rev}`); }
    catch (e) { return; }
    if (id !== st.active) return;
    const nearBottom = msgsEl.scrollHeight - msgsEl.scrollTop - msgsEl.clientHeight < 120;
    let changed = first;
    for (const m of data.messages) {
      const old = st.msgs.get(m.id);
      if (!old || old.rev !== m.rev) { st.msgs.set(m.id, m); changed = true; }
    }
    if (first && data.messages.length < 80) st.hasOlder = false;
    st.rev = data.rev;
    if (st.busy !== data.busy) { st.busy = data.busy; changed = true; }
    $("nudgeBtn").disabled = st.busy;
    renderHead(data);
    if (changed) { renderMessages(); if (first || nearBottom) scrollBottom(); }
    markSeen();
  }

  function markSeen() {
    const ids = [...st.msgs.keys()];
    if (!ids.length) return;
    const max = Math.max(...ids);
    if ((st.seen[st.active] || 0) < max) { st.seen[st.active] = max; UI.store.set("waifu_seen", st.seen); }
  }

  async function loadOlder(btn) {
    const ids = [...st.msgs.keys()];
    if (!ids.length) return;
    UI.busy(btn, true);
    try {
      const data = await api("GET", `/api/characters/${st.active}/messages/before?before=${Math.min(...ids)}`);
      if (data.messages.length < 50) st.hasOlder = false;
      const prevH = msgsEl.scrollHeight;
      data.messages.forEach((m) => st.msgs.set(m.id, m));
      renderMessages();
      msgsEl.scrollTop = msgsEl.scrollHeight - prevH;
    } catch (e) { toast(e.message, "bad"); UI.busy(btn, false); }
  }

  function scrollBottom() { msgsEl.scrollTop = msgsEl.scrollHeight; }

  function renderMessages() {
    const list = [...st.msgs.values()].sort((a, b) => a.id - b.id);
    const frag = document.createDocumentFragment();
    if (st.hasOlder && list.length) {
      const b = h("button", { class: "btn sm load-older" }, "Xem tin cũ hơn");
      b.addEventListener("click", () => loadOlder(b));
      frag.append(b);
    }
    if (!list.length) frag.append(h("div", { class: "empty-state" }, "Hãy gửi lời chào đầu tiên 💌"));
    let lastDay = "", prev = null;
    list.forEach((m, i) => {
      const day = dayLabel(m.created_at);
      if (day !== lastDay) { frag.append(h("div", { class: "day-sep" }, day)); lastDay = day; prev = null; }
      const side = m.role === "user" ? "me" : m.role === "system" ? "system" : "her";
      const next = list[i + 1];
      const lastOfGroup = !next || next.role !== m.role || dayLabel(next.created_at) !== day;
      const el = h("div", { class: `msg ${side}` + (prev && prev.role !== m.role ? " gap" : "") });
      if (m.content) el.append(h("div", { class: "bubble", html: richText(m.content) }));
      el.append(...photoNodes(m));
      if (lastOfGroup && side !== "system") el.append(h("div", { class: "time" }, hm(m.created_at)));
      frag.append(el);
      prev = m;
    });
    if (st.busy) frag.append(h("div", { class: "typing", "aria-label": "đang nhập" }, h("i"), h("i"), h("i")));
    msgsEl.replaceChildren(frag);
  }

  function photoNodes(m) {
    if (m.image_status === "done" && m.image_path) {
      const src = "/images/" + encodeURIComponent(m.image_path);
      const img = h("img", { src, alt: "Ảnh", loading: "lazy" });
      img.addEventListener("click", () => UI.lightbox(src));
      return [h("div", { class: "photo" }, img)];
    }
    if (m.image_status === "pending") return [h("div", { class: "photo pending" }, h("span", {}, "📷 Đang chụp ảnh..."))];
    if (m.image_status === "error") {
      const b = h("button", { class: "btn sm" }, "Thử lại");
      b.addEventListener("click", async () => {
        UI.busy(b, true);
        try { await api("POST", `/api/messages/${m.id}/retry-image`); poll(); }
        catch (e) { toast(e.message, "bad"); UI.busy(b, false); }
      });
      return [h("div", { class: "photo-fail" }, "Ảnh gửi lỗi.", b)];
    }
    if (m.image_status === "blocked") return [h("div", { class: "photo-fail" }, "🚫 Ảnh này bị chặn bởi bộ lọc tuổi.")];
    return [];
  }

  // ---------- gửi tin ----------
  async function send(wantPhoto = false) {
    const text = input.value.trim();
    if (!st.active || st.sending || (!text && !wantPhoto)) return;
    st.sending = true;  // nhắn liền nhiều tin cũng được: nhân vật đợi bạn ngừng nhắn rồi trả lời gộp
    const cid = st.active;
    input.value = ""; autoGrow();
    $("sendBtn").disabled = true; $("photoBtn").disabled = true;
    const kick = setTimeout(() => poll(), 350);
    if (matchMedia("(max-width: 760px)").matches) input.focus();  // giữ bàn phím như Messenger
    try {
      await api("POST", `/api/characters/${cid}/messages`, { text, want_photo: wantPhoto });
    } catch (e) {
      toast(e.message, "bad");
      if (!input.value) input.value = text;
    } finally {
      clearTimeout(kick);
      st.sending = false;
      $("sendBtn").disabled = false; $("photoBtn").disabled = false;
      if (cid === st.active) await poll();
      loadRoster();
    }
  }

  function autoGrow() { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight + 2, 160) + "px"; }

  $("composer").addEventListener("submit", (e) => { e.preventDefault(); send(); });
  $("photoBtn").addEventListener("click", () => send(true));
  input.addEventListener("input", autoGrow);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing && matchMedia("(min-width: 761px)").matches) { e.preventDefault(); send(); }
  });
  // Giục nhắn: trả lời ngay tin đang chờ, hoặc nhân vật chủ động nhắn trước
  const nudgeBtn = $("nudgeBtn");
  nudgeBtn.addEventListener("click", async () => {
    if (!st.active || st.busy) return;
    const cid = st.active;
    nudgeBtn.disabled = true;
    try {
      await api("POST", `/api/characters/${cid}/nudge`);
      if (cid === st.active) { await poll(); scrollBottom(); }
    } catch (e) { toast(e.message, "bad"); }
    finally { setTimeout(() => { nudgeBtn.disabled = false; }, 1500); }
  });

  function closeChat() {
    if (!app.classList.contains("show-thread")) return;
    input.blur();
    app.classList.remove("show-thread");
    st.active = null;
    renderRoster();
  }
  // nút ← và vuốt lùi đều đi qua lịch sử, để cử chỉ vuốt của Safari cũng chỉ đóng hội thoại
  const goBack = () => { if (history.state && history.state.thread) history.back(); else closeChat(); };
  $("backBtn").addEventListener("click", goBack);
  window.addEventListener("popstate", closeChat);

  // Vuốt từ mép trái sang phải để về danh sách (cho chế độ "Thêm vào màn hình chính", nơi Safari không có cử chỉ lùi)
  (() => {
    const thread = $("thread");
    let sx = 0, sy = 0, dx = 0, tracking = false;
    const standalone = () => navigator.standalone === true || matchMedia("(display-mode: standalone)").matches;
    thread.addEventListener("touchstart", (e) => {
      const t = e.touches[0];
      tracking = narrow() && standalone() && e.touches.length === 1 && t.clientX < 28;
      sx = t.clientX; sy = t.clientY; dx = 0;
    }, { passive: true });
    thread.addEventListener("touchmove", (e) => {
      if (!tracking) return;
      const t = e.touches[0];
      dx = t.clientX - sx;
      if (Math.abs(t.clientY - sy) > 60) { tracking = false; thread.style.transform = ""; return; }
      if (dx > 0) thread.style.transform = `translateX(${Math.min(dx, innerWidth)}px)`;
    }, { passive: true });
    thread.addEventListener("touchend", () => {
      if (!tracking) return;
      tracking = false;
      const done = dx > Math.min(110, innerWidth * 0.3);
      thread.style.transition = "transform .18s ease-out";
      thread.style.transform = done ? `translateX(${innerWidth}px)` : "";
      setTimeout(() => {
        thread.style.transition = ""; thread.style.transform = "";
        if (done) goBack();
      }, 180);
    });
  })();

  // Bàn phím iOS: cho khung app cao đúng phần nhìn thấy, không để trang bị đẩy lên dưới thanh trạng thái
  if (window.visualViewport) {
    const vv = window.visualViewport;
    const fit = () => {
      document.documentElement.style.setProperty("--vvh", vv.height + "px");
      if (narrow() && (window.scrollY || vv.offsetTop)) window.scrollTo(0, 0);
    };
    vv.addEventListener("resize", () => { fit(); if (document.activeElement === input) scrollBottom(); });
    vv.addEventListener("scroll", fit);
    fit();
  }

  // ---------- chạy ----------
  (async () => {
    if (history.state && history.state.thread) history.replaceState(null, "");  // tải lại trang khi đang mở hội thoại
    await loadRoster();
    const last = UI.store.get("waifu_last_chat", null);
    const wide = matchMedia("(min-width: 761px)").matches;
    if (wide && st.chars.some((c) => c.id === last)) openChat(last);
    else if (wide && st.chars.length) openChat(st.chars[0].id);
  })();
  setInterval(() => { if (!document.hidden) poll(); }, 2500);
  setInterval(() => { if (!document.hidden) loadRoster(); }, 8000);
})();
