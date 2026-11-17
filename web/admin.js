/* Giao diện Quản lý */
(function () {
  const { h, api, toast } = UI;
  const $ = (id) => document.getElementById(id);

  // Đặc điểm nhân vật: mỗi mục một ô, mỗi ý một dòng (khớp NOTE_FIELDS trong server/db.py)
  const NOTE_FIELDS = [
    ["likes", "Thích", "Ăn gà rán"], ["dislikes", "Không thích", "Mùi thuốc lá"],
    ["quirks", "Thói quen", "Hay xoắn tóc khi tập trung", true], ["speech_style", "Cách nhắn tin / câu cửa miệng", "Hứ, ghét anh thế!", true],
    ["backstory", "Quá khứ", "Từng là hoa khôi khoa", true], ["ongoing", "Chuyện đang diễn ra", "Đang ôn thi chứng chỉ"],
    ["companions", "Thú cưng / người thân", "Mèo trắng tên Pun"]];

  const CHAR_KEYS = ["name", "gender", "age", "personality", "appearance", "appearance_tags", "bio", "extra_notes",
    ...NOTE_FIELDS.map((f) => f[0]), "birthday", "period_start", "cycle_length", "period_length", "anniversaries", "work_days", "photo_rate", "photos_max", "face_ref_ok", "user_profile", "relationship", "pronoun_rule", "sample_messages", "model_chat", "explicit_enabled", "lora_name",
    "lora_strength", "seed", "face_lock", "mood", "mood_reason", "proactive_enabled", "silence_minutes"];

  const st = {
    view: "chars", chars: [], cur: null, draft: null, dirty: false, sub: "profile",
    memories: [], schedule: [], schedDirty: false,
    status: { ollama: false, comfy: false, models: [], image_options: {}, moods: [], min_age: 21, hard_negative: "" },
    settings: null, setDraft: null, setDirty: false,
  };

  // ---------- trạng thái máy chủ AI ----------
  async function loadStatus() {
    try { st.status = await api("GET", "/api/status"); } catch (e) { st.status.ollama = st.status.comfy = false; }
    const s = st.status;
    $("statusPills").replaceChildren(
      h("span", {}, h("i", { class: "dot " + (s.ollama ? "ok" : "bad") }), "Ollama"),
      h("span", {}, h("i", { class: "dot " + (s.comfy ? "ok" : "bad") }), "ComfyUI"),
      s.image_queue ? h("span", {}, `Đang chờ vẽ: ${s.image_queue}`) : "");
    return s;
  }

  // ---------- chuyển màn chính ----------
  document.querySelectorAll("#mainTabs .tab").forEach((b) => b.addEventListener("click", async () => {
    if (b.dataset.view === st.view) return;
    if (!(await leaveOk())) return;
    st.view = b.dataset.view;
    document.querySelectorAll("#mainTabs .tab").forEach((x) => x.classList.toggle("active", x === b));
    $("view-chars").classList.toggle("hidden", st.view !== "chars");
    $("view-settings").classList.toggle("hidden", st.view !== "settings");
    $("view-logs").classList.toggle("hidden", st.view !== "logs");
    if (st.view === "settings") openSettings();
    if (st.view === "logs") openLogs(); else stopLogs();
  }));

  // ---------- Log: xem từng lượt nhân vật làm gì (gieo ảnh, vẽ ảnh, soạn lịch, lỗi) ----------
  const LOG_KINDS = [
    ["", "Tất cả"], ["photo,image", "Ảnh"], ["reply", "Trả lời"], ["proactive,nudge", "Chủ động nhắn"], ["plan", "Lịch"], ["error", "Lỗi"]];
  const KIND_LABEL = { photo: "gieo ảnh", image: "vẽ ảnh", reply: "trả lời", proactive: "chủ động", nudge: "giục", plan: "lịch", error: "lỗi" };
  const lg = { cid: 0, kind: "", rows: [], timer: null, open: new Set() };

  async function openLogs() {
    if (!st.chars.length) { try { await loadChars(); } catch (e) { /* bỏ qua */ } }
    if (!lg.cid && st.cur) lg.cid = st.cur.id;
    renderLogs();
    await refreshLogs();
    stopLogs();
    lg.timer = setInterval(() => { if (!document.hidden) refreshLogs(); }, 4000);
  }
  function stopLogs() { if (lg.timer) { clearInterval(lg.timer); lg.timer = null; } }

  async function refreshLogs() {
    try { lg.rows = await api("GET", `/api/logs?character_id=${lg.cid || 0}&limit=400`); }
    catch (e) { toast(e.message, "bad"); return; }
    drawLogRows();
  }

  function renderLogs() {
    const view = $("view-logs");
    const charHost = h("div", { class: "log-char" });
    UI.select(charHost, {
      options: [{ value: 0, label: "Mọi nhân vật" }].concat(st.chars.map((c) => ({ value: c.id, label: c.name }))),
      value: lg.cid, onChange: (v) => { lg.cid = +v || 0; refreshLogs(); },
    });
    const chips = h("div", { class: "row day-chips" }, LOG_KINDS.map(([k, label]) => h("button", {
      class: "day-chip" + (lg.kind === k ? " on" : ""), type: "button",
      onclick: () => { lg.kind = k; renderLogs(); drawLogRows(); },
    }, label)));
    view.replaceChildren(
      h("div", { class: "log-bar" }, charHost, chips,
        h("button", { class: "btn sm ghost", onclick: refreshLogs }, "Tải lại")),
      h("div", { class: "log-summary", id: "logSummary" }),
      h("div", { class: "log-list", id: "logList" }));
  }

  function drawLogRows() {
    const list = $("logList"), sum = $("logSummary");
    if (!list) return;
    const kinds = lg.kind ? lg.kind.split(",") : null;
    const rows = lg.rows.filter((r) => !kinds || kinds.includes(r.kind));
    const name = (id) => (st.chars.find((c) => c.id === id) || {}).name || "";
    // tổng kết gieo ảnh trong phần đang xem
    const rolls = lg.rows.filter((r) => r.kind === "photo" && r.data && typeof r.data.hit === "boolean");
    const hits = rolls.filter((r) => r.data.hit).length;
    sum.textContent = rolls.length
      ? `Gieo ảnh ${rolls.length} lần · trúng ${hits} (${Math.round((hits / rolls.length) * 100)}%) · tỷ lệ đặt ${rolls[0].data.rate}%`
      : "Chưa có lần gieo ảnh nào trong nhật ký.";
    const t = new Date(), p2 = (n) => String(n).padStart(2, "0");
    const today = `${t.getFullYear()}-${p2(t.getMonth() + 1)}-${p2(t.getDate())}`;  // giờ máy, khớp giờ ghi log
    list.replaceChildren(...(rows.length ? rows.map((r) => {
      const hot = r.kind === "error" ? " bad" : r.kind === "photo" && r.data && r.data.hit ? " good" : "";
      const when = r.ts.slice(0, 10) === today ? r.ts.slice(11) : r.ts.slice(8, 10) + "/" + r.ts.slice(5, 7) + " " + r.ts.slice(11, 16);
      const row = h("div", { class: "log-row" + hot },
        h("span", { class: "log-ts" }, when),
        h("span", { class: "log-kind k-" + r.kind }, KIND_LABEL[r.kind] || r.kind),
        h("span", { class: "log-text" }, (lg.cid ? "" : name(r.character_id) ? name(r.character_id) + " · " : "") + r.text));
      if (r.data) {
        const pre = h("pre", { class: "log-data" }, JSON.stringify(r.data, null, 2));
        const det = h("details", { class: "log-more", open: lg.open.has(r.id) }, h("summary", {}, "chi tiết"), pre);
        det.addEventListener("toggle", () => { det.open ? lg.open.add(r.id) : lg.open.delete(r.id); });  // giữ mở khi tự tải lại
        row.append(det);
      }
      return row;
    }) : [h("div", { class: "note" }, "Chưa có nhật ký. Mỗi lượt trả lời, gieo ảnh, vẽ ảnh, soạn lịch sẽ hiện ở đây.")]));
  }

  async function leaveOk() {
    const dirty = (st.view === "chars" && (st.dirty || st.schedDirty || st.todayDirty)) || (st.view === "settings" && st.setDirty);
    if (!dirty) return true;
    const ok = await UI.confirm({ title: "Bỏ thay đổi chưa lưu?", message: "Những gì bạn vừa sửa sẽ mất.", ok: "Bỏ thay đổi" });
    if (ok) { st.dirty = st.schedDirty = st.todayDirty = st.setDirty = false; }
    return ok;
  }
  window.addEventListener("beforeunload", (e) => { if (st.dirty || st.schedDirty || st.setDirty) { e.preventDefault(); e.returnValue = ""; } });

  // ---------- danh sách nhân vật ----------
  async function loadChars() {
    st.chars = await api("GET", "/api/characters");
    renderCharList();
  }

  function renderCharList() {
    const list = $("charList");
    list.replaceChildren();
    if (!st.chars.length) { list.append(h("div", { class: "muted", style: "padding:8px 4px;font-size:13px" }, "Chưa có nhân vật.")); return; }
    for (const c of st.chars) {
      list.append(h("button", { class: "c-item" + (st.cur && st.cur.id === c.id ? " active" : ""), onclick: () => selectChar(c.id) },
        UI.avatar(c, 40),
        h("div", {}, h("div", { class: "nm" }, c.name), h("div", { class: "sub" }, `${UI.MOOD_EMOJI[c.mood] || ""} ${c.mood} · ${c.age} tuổi`))));
    }
  }

  async function selectChar(id, force = false) {
    if (!force && st.cur && st.cur.id === id) return;
    if (!force && !(await leaveOk())) return;
    try {
      const [c, mem, sch, today] = await Promise.all([
        api("GET", `/api/characters/${id}`), api("GET", `/api/characters/${id}/memories`), api("GET", `/api/characters/${id}/schedule`),
        api("GET", `/api/characters/${id}/today`)]);
      st.cur = c; st.draft = pick(c); st.memories = mem; st.schedule = sch.map((x) => ({ ...x }));
      st.today = { ...today, items: today.items.map((x) => ({ ...x })) };
      st.dirty = st.schedDirty = st.todayDirty = false;
      renderCharList(); renderEditor();
      if (c.avatar_status === "pending") watchAvatar(id);
    } catch (e) { toast(e.message, "bad"); }
  }

  const pick = (c) => Object.fromEntries(CHAR_KEYS.map((k) => [k, Array.isArray(c[k]) ? [...c[k]] : c[k]]));

  function markDirty() { st.dirty = true; updateSavebar(); }

  // ---------- tạo / nhập ----------
  $("newCharBtn").addEventListener("click", async () => {
    if (!(await leaveOk())) return;
    const data = await UI.modal((box, close) => {
      const name = h("input", { class: "input", placeholder: "Ví dụ: Thu Phương", autofocus: true });
      const ageIn = h("input", { class: "input", inputmode: "numeric", value: "23" });
      const gHost = h("div");
      const g = UI.select(gHost, { options: [{ value: "Nữ", label: "Nữ" }, { value: "Nam", label: "Nam" }, { value: "Khác", label: "Khác" }], value: "Nữ" });
      const err = h("div", { class: "hint", style: "color:var(--bad);min-height:18px" });
      const submit = () => {
        const age = parseInt(ageIn.value, 10);
        if (!name.value.trim()) { err.textContent = "Nhập tên nhân vật"; return; }
        if (!(age >= st.status.min_age)) { err.textContent = `Tuổi phải từ ${st.status.min_age} trở lên`; return; }
        close({ name: name.value.trim(), gender: g.value, age });
      };
      name.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
      box.append(h("h3", {}, "Tạo nhân vật"),
        h("div", { class: "grid", style: "margin:14px 0 6px" },
          h("div", { class: "field span2" }, h("label", {}, "Tên"), name),
          h("div", { class: "field" }, h("label", {}, "Giới tính"), gHost),
          h("div", { class: "field" }, h("label", {}, `Tuổi (từ ${st.status.min_age})`), ageIn)),
        err,
        h("div", { class: "actions" }, h("button", { class: "btn", onclick: () => close(null) }, "Huỷ"), h("button", { class: "btn primary", onclick: submit }, "Tạo")));
    });
    if (!data) return;
    try {
      const c = await api("POST", "/api/characters", data);
      await loadChars();
      st.sub = "profile";
      await selectChar(c.id, true);
      toast("Đã tạo nhân vật. Điền hồ sơ rồi bấm Lưu.", "ok");
    } catch (e) { toast(e.message, "bad"); }
  });

  $("importBtn").addEventListener("click", async () => { if (await leaveOk()) $("importFile").click(); });
  $("importFile").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    const btn = $("importBtn");
    UI.busy(btn, true, "Đang nhập");
    try {
      const data = JSON.parse(await file.text());
      const res = await api("POST", "/api/import", data);
      await loadChars();
      toast(`Đã nhập ${res.created.length} nhân vật`, "ok");
      if (res.created.length) await selectChar(res.created[0], true);
    } catch (err) {
      toast(err instanceof SyntaxError ? "File không phải JSON hợp lệ" : err.message, "bad");
    } finally { UI.busy(btn, false); }
  });

  // ---------- vùng sửa ----------
  const SUBS = [["profile", "Hồ sơ"], ["dates", "Ngày tháng"], ["image", "Ảnh"], ["memory", "Trí nhớ & tâm trạng"], ["schedule", "Lịch sinh hoạt"]];

  function renderEditor() {
    const ed = $("editor");
    const c = st.cur, d = st.draft;
    ed.replaceChildren(
      h("div", { class: "ed-head" }, UI.avatar(c, 56),
        h("div", { style: "min-width:0;flex:1" },
          h("h2", {}, d.name || "(chưa có tên)"),
          h("div", { class: "meta" },
            h("span", { class: "chip" }, `${UI.MOOD_EMOJI[d.mood] || ""} ${d.mood}`),
            c.activity ? h("span", { class: "muted", style: "font-size:13px" }, "Đang: " + c.activity) : ""))),
      h("nav", { class: "subtabs" }, SUBS.map(([k, label]) => h("button", {
        class: "subtab" + (st.sub === k ? " active" : ""),
        onclick: () => { st.sub = k; renderEditor(); },
      }, label))),
      h("div", { class: "ed-body", id: "edBody" }),
      h("div", { class: "savebar", id: "savebar" }));
    const body = $("edBody");
    ({ profile: subProfile, dates: subDates, image: subImage, memory: subMemory, schedule: subSchedule })[st.sub](body);
    updateSavebar();
  }

  function updateSavebar() {
    const bar = $("savebar");
    if (!bar) return;
    const dirty = st.dirty || st.schedDirty || st.todayDirty;
    const save = h("button", { class: "btn primary", onclick: () => saveChar(save) }, "Lưu thay đổi");
    save.disabled = !dirty;
    const undo = h("button", { class: "btn ghost", onclick: () => selectChar(st.cur.id, true) }, "Hoàn tác");
    undo.disabled = !dirty;
    bar.replaceChildren(dirty ? h("span", { class: "dirty" }, "● Có thay đổi chưa lưu") : h("span", { class: "muted", style: "font-size:13px" }, "Đã lưu"),
      h("span", { class: "spacer" }), undo, save);
  }

  async function saveChar(btn) {
    const born = D.parse(st.draft.birthday);
    const age = born ? D.age(born, D.today()) : parseInt(st.draft.age, 10);
    if (!(age >= st.status.min_age)) {
      toast(born ? `Theo ngày sinh nhân vật mới ${age} tuổi — phải từ ${st.status.min_age} trở lên` : `Tuổi phải từ ${st.status.min_age} trở lên`, "bad");
      return false;
    }
    if (btn) UI.busy(btn, true, "Đang lưu");
    try {
      if (st.dirty) {
        const payload = { ...st.draft, age, silence_minutes: parseInt(st.draft.silence_minutes, 10) || 0,
          seed: parseInt(st.draft.seed, 10) || 0, lora_strength: parseFloat(st.draft.lora_strength) || 0,
          cycle_length: parseInt(st.draft.cycle_length, 10) || 28, period_length: parseInt(st.draft.period_length, 10) || 5,
          photo_rate: Math.min(100, Math.max(0, parseInt(st.draft.photo_rate, 10) || 0)),
          photos_max: Math.min(5, Math.max(1, parseInt(st.draft.photos_max, 10) || 1)) };
        // trường trang chưa tải được (trang mở từ bản cũ) thì không gửi, để không ghi đè giá trị thật bằng 0 / rỗng
        for (const k of Object.keys(payload)) if (st.cur[k] === undefined && st.draft[k] === undefined) delete payload[k];
        st.cur = { ...st.cur, ...(await api("PUT", `/api/characters/${st.cur.id}`, payload)) };
      }
      if (st.schedDirty) {
        st.schedule = await api("PUT", `/api/characters/${st.cur.id}/schedule`, { items: st.schedule });
      }
      if (st.todayDirty) {
        const t = await api("PUT", `/api/characters/${st.cur.id}/today`, { items: st.today.items });
        st.today = { ...t, items: t.items.map((x) => ({ ...x })) };
      } else if (st.dirty) {  // đổi ngày đi làm → nhãn "ngày nghỉ / đi làm" của hôm nay
        const t = await api("GET", `/api/characters/${st.cur.id}/today`);
        st.today = { ...t, items: t.items.map((x) => ({ ...x })) };
      }
      st.draft = pick(st.cur); st.dirty = st.schedDirty = st.todayDirty = false;
      toast("Đã lưu", "ok");
      await loadChars();
      renderEditor();
      return true;
    } catch (e) { toast(e.message, "bad"); if (btn) UI.busy(btn, false); return false; }
  }

  // ---- ô nhập gắn với bản nháp ----
  function fText(key, label, o = {}) {
    const el = o.textarea
      ? h("textarea", { class: "textarea" + (o.mono ? " mono" : ""), rows: o.rows || 3, placeholder: o.placeholder || "" })
      : h("input", { class: "input" + (o.mono ? " mono" : ""), placeholder: o.placeholder || "", inputmode: o.numeric ? "numeric" : null });
    const v = st.draft[key];
    el.value = Array.isArray(v) ? v.join("\n") : (v ?? "");
    el.addEventListener("input", () => {
      st.draft[key] = o.lines ? el.value.split("\n").map((s) => s.trim()).filter(Boolean) : el.value;
      if (key === "name") { const t = document.querySelector(".ed-head h2"); if (t) t.textContent = el.value || "(chưa có tên)"; }
      markDirty();
    });
    return h("div", { class: "field" + (o.span2 ? " span2" : "") }, h("label", {}, label), el, o.hint ? h("div", { class: "hint" }, o.hint) : "");
  }

  function fSelect(key, label, options, o = {}) {
    const host = h("div");
    UI.select(host, { options, value: st.draft[key], placeholder: o.placeholder, onChange: (v) => { st.draft[key] = v; markDirty(); if (o.rerender) renderEditor(); } });
    return h("div", { class: "field" + (o.span2 ? " span2" : "") }, h("label", {}, label), host, o.hint ? h("div", { class: "hint" }, o.hint) : "");
  }

  function fSwitch(key, label, hint) {
    const sw = UI.switch(st.draft[key], label, (v) => { st.draft[key] = v; markDirty(); });
    return h("div", { class: "field span2" }, sw, hint ? h("div", { class: "hint" }, hint) : "");
  }

  function modelOptions(value, emptyLabel) {
    const opts = [{ value: "", label: emptyLabel }].concat(st.status.models.map((m) => ({ value: m, label: m })));
    if (value && !st.status.models.includes(value)) opts.push({ value, label: `${value} (không thấy trên Ollama)` });
    return opts;
  }

  // ---- tab Hồ sơ ----
  function subProfile(body) {
    const s = st.settings || {};
    body.append(
      h("div", { class: "grid" },
        fText("name", "Tên"),
        fSelect("gender", "Giới tính", [{ value: "Nữ", label: "Nữ" }, { value: "Nam", label: "Nam" }, { value: "Khác", label: "Khác" }]),
        D.parse(st.draft.birthday)
          ? h("div", { class: "field" }, h("label", {}, "Tuổi"),
              h("input", { class: "input", value: String(D.age(D.parse(st.draft.birthday), D.today())), disabled: true }),
              h("div", { class: "hint" }, "Tính từ ngày sinh (tab Ngày tháng), tự tăng mỗi năm"))
          : fText("age", `Tuổi (từ ${st.status.min_age})`, { numeric: true, hint: "Hoặc nhập ngày sinh ở tab Ngày tháng để tuổi tự tính" }),
        fText("relationship", "Quan hệ với người chơi", { placeholder: "Người yêu, vợ sắp cưới, bạn cùng phòng..." }),
        fText("personality", "Tính cách", { textarea: true, span2: true, placeholder: "Dịu dàng, hay dỗi, thích được dỗ..." }),
        fText("appearance", "Ngoại hình", { textarea: true, span2: true, hint: "Viết tiếng Việt, dùng cho lời thoại. Tag để vẽ ảnh nằm ở tab Ảnh." }),
        fText("bio", "Tiểu sử", { textarea: true, span2: true }),
        h("div", { class: "section-title span2" }, "Đặc điểm nhân vật"),
        ...NOTE_FIELDS.map(([key, label, ex, wide]) => {
          const n = String(st.draft[key] || "").split("\n").filter((s) => s.trim()).length;
          return fText(key, label, { textarea: true, rows: Math.min(Math.max(n + 1, 3), 9), span2: !!wide, placeholder: ex, hint: "Mỗi ý một dòng" });
        }),
        fText("extra_notes", "Ghi chú khác", { textarea: true, rows: 3, span2: true, hint: "Những gì không thuộc các ô trên" }),
        fText("user_profile", "Về người chơi", { textarea: true, span2: true, placeholder: "Nhân vật biết gì về bạn" }),
        fText("pronoun_rule", "Cách xưng hô", { span2: true, placeholder: 'Xưng "em", gọi người chơi là "anh"' }),
        fText("sample_messages", "Tin nhắn mẫu", { textarea: true, rows: 5, span2: true, lines: true, hint: "Mỗi dòng một tin. Nhân vật sẽ bắt chước giọng nhắn." })),
      h("div", { class: "section-title" }, "Mô hình chữ"),
      h("div", { class: "grid" },
        fSelect("model_chat", "Mô hình trò chuyện", modelOptions(st.draft.model_chat, `Theo Cài đặt chung${s.model_chat ? " (" + s.model_chat + ")" : ""}`)),
        h("div"),
        fSwitch("explicit_enabled", "Chuyển sang mô hình cảnh nóng khi cần",
          `Khi tin nhắn có nội dung tình dục, dùng ${s.model_explicit || "mô hình cảnh nóng trong Cài đặt"} trong 6 lượt kế tiếp.`)),
      h("div", { class: "section-title" }, "Khác"),
      h("div", { class: "row" },
        h("button", { class: "btn", onclick: exportChar }, "Xuất file"),
        h("button", { class: "btn danger", onclick: clearChat }, "Xoá lịch sử chat"),
        h("button", { class: "btn danger", onclick: deleteChar }, "Xoá nhân vật")));
  }

  async function exportChar() {
    try {
      const data = await api("GET", `/api/characters/${st.cur.id}/export`);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = h("a", { href: URL.createObjectURL(blob), download: `WaifuAI_${st.cur.name.replace(/[^\p{L}\p{N}]+/gu, "_")}.json` });
      document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    } catch (e) { toast(e.message, "bad"); }
  }

  async function clearChat() {
    if (!(await UI.confirm({ title: `Xoá lịch sử chat với ${st.cur.name}?`, message: "Toàn bộ tin nhắn và ảnh trong khung chat sẽ mất. Hồ sơ, trí nhớ và lịch vẫn giữ nguyên.", ok: "Xoá lịch sử", danger: true }))) return;
    try { await api("DELETE", `/api/characters/${st.cur.id}/messages`); toast("Đã xoá lịch sử chat", "ok"); } catch (e) { toast(e.message, "bad"); }
  }

  async function deleteChar() {
    if (!(await UI.confirm({ title: `Xoá nhân vật ${st.cur.name}?`, message: "Hồ sơ, trí nhớ, lịch và toàn bộ tin nhắn sẽ bị xoá vĩnh viễn.", ok: "Xoá nhân vật", danger: true }))) return;
    try {
      await api("DELETE", `/api/characters/${st.cur.id}`);
      st.cur = null; st.dirty = st.schedDirty = false;
      await loadChars();
      $("editor").replaceChildren(h("div", { class: "empty-state" }, "Đã xoá. Chọn nhân vật khác bên trái."));
      toast("Đã xoá nhân vật", "ok");
    } catch (e) { toast(e.message, "bad"); }
  }

  // ---- tab Ảnh ----
  function subImage(body) {
    const c = st.cur;
    const big = h("div", { class: "avatar-big" + (c.avatar_status === "pending" ? " pending" : "") });
    if (c.avatar_path) {
      const src = "/images/" + encodeURIComponent(c.avatar_path) + "?t=" + Date.now();
      const img = h("img", { src, alt: "Ảnh đại diện" });
      img.addEventListener("click", () => UI.lightbox(src));
      big.append(img);
    } else big.append(h("span", { class: "big-initial" }, UI.initial(c.name)));

    const tagsField = fText("appearance_tags", "Tag ngoại hình để vẽ (tiếng Anh)", {
      textarea: true, rows: 4, mono: true, span2: true,
      hint: "Chỉ đặc điểm cố định: tóc, mắt, khuôn mặt, vóc dáng. Ghép vào mọi ảnh để nhân vật giữ đúng mặt." });
    const tagBtn = h("button", { class: "btn sm" }, "Tạo tag từ mô tả ngoại hình");
    tagBtn.addEventListener("click", async () => {
      UI.busy(tagBtn, true, "Đang tạo");
      try {
        const r = await api("POST", `/api/characters/${c.id}/appearance-tags`, { appearance: st.draft.appearance, gender: st.draft.gender, age: st.draft.age });
        st.draft.appearance_tags = r.tags; tagsField.querySelector("textarea").value = r.tags; markDirty();
        toast("Đã tạo tag, kiểm tra rồi bấm Lưu", "ok");
      } catch (e) { toast(e.message, "bad"); }
      UI.busy(tagBtn, false);
    });
    tagsField.append(h("div", { class: "row" }, tagBtn));

    const loras = st.status.image_options.loras || [];
    const loraOpts = [{ value: "", label: "Không dùng LoRA" }].concat(loras.map((l) => ({ value: l, label: l })));
    if (st.draft.lora_name && !loras.includes(st.draft.lora_name)) loraOpts.push({ value: st.draft.lora_name, label: st.draft.lora_name + " (không thấy)" });

    const genBtn = h("button", { class: "btn primary" }, c.avatar_path ? "Vẽ lại ảnh đại diện" : "Vẽ ảnh đại diện");
    const newFaceBtn = h("button", { class: "btn" }, "Vẽ khuôn mặt khác");
    const gen = async (newSeed) => {
      if ((st.dirty || st.schedDirty) && !(await saveChar())) return;
      try {
        st.cur = await api("POST", `/api/characters/${st.cur.id}/avatar`, { new_seed: newSeed });
        st.draft.seed = st.cur.seed;
        renderEditor(); watchAvatar(st.cur.id); loadStatus();
      } catch (e) { toast(e.message, "bad"); }
    };
    genBtn.addEventListener("click", () => gen(false));
    newFaceBtn.addEventListener("click", () => gen(true));
    if (c.avatar_status === "pending") { genBtn.disabled = newFaceBtn.disabled = true; }

    let statusLine = "";
    if (c.avatar_status === "pending") statusLine = h("div", { class: "note" }, "Đang vẽ... Nếu ComfyUI đang bận vẽ ảnh chat, ảnh đại diện sẽ đợi tới lượt.");
    else if (c.avatar_status === "error" || c.avatar_status === "blocked") statusLine = h("div", { class: "note", style: "color:var(--bad)" }, c.avatar_error || "Vẽ lỗi");
    if (!st.status.comfy) statusLine = h("div", { class: "note", style: "color:var(--bad)" }, "Chưa kết nối được ComfyUI. Kiểm tra địa chỉ trong Cài đặt.");

    body.append(h("div", { class: "img-wrap" }, big,
      h("div", {},
        h("div", { class: "grid" },
          tagsField,
          fText("seed", "Seed (giữ nguyên = cùng khuôn mặt)", { numeric: true, mono: true }),
          fText("photo_rate", "Tỷ lệ tự gửi ảnh (%)", { numeric: true, hint: "Mỗi lần trả lời / chủ động nhắn có bấy nhiêu % kèm ảnh. 100 = lượt nào cũng gửi, 0 = chỉ gửi khi bạn xin." }),
          h("div"),
          fText("photos_max", "Số ảnh tối đa mỗi lần nhắn", { numeric: true, hint: "1 đến 5. Nhân vật tự chọn gửi 1 hay vài tấm (khác góc / tư thế) tuỳ lúc. Mỗi ảnh ~30 giây GPU." }),
          fSelect("lora_name", "LoRA nhân vật", loraOpts, { hint: "LoRA luyện riêng cho nhân vật giúp giữ mặt tốt nhất. LoRA tên wf_… tự chèn từ khoá kích hoạt." }),
          fText("lora_strength", "Độ mạnh LoRA", { numeric: true, hint: "0.6 đến 1.0" }),
          fSwitch("face_lock", "Giữ khuôn mặt (PuLID)", faceHint(c)),
          faceRefBlock(c)),
        h("div", { class: "row", style: "margin-top:18px" }, genBtn, newFaceBtn),
        statusLine ? h("div", { style: "margin-top:12px" }, statusLine) : "",
        h("div", { class: "note lock", style: "margin-top:18px" },
          h("b", {}, "Luôn được thêm, không tắt được: "), `"adult, ${Math.max(parseInt(st.draft.age, 10) || 0, st.status.min_age)} years old" vào mô tả, và vào phần cấm vẽ: `,
          h("span", { class: "mono", style: "font-family:ui-monospace,Consolas,monospace;font-size:12px" }, st.status.hard_negative)))));
  }

  function faceHint(c) {
    if (!st.status.image_options.pulid) return "ComfyUI chưa có PuLID SDXL (chạy tools\\cai_pulid_sdxl.bat rồi khởi động lại ComfyUI). Chưa có thì ảnh vẫn vẽ bình thường, chỉ không khoá mặt.";
    if (c.face_ref && st.draft.face_ref_ok) return "Mọi ảnh trong chat khoá theo khuôn mặt trong Ảnh mặt mẫu bên dưới.";
    if (c.face_ref) return "Đã có Ảnh mặt mẫu nhưng chưa tích xác nhận bên dưới — chưa dùng.";
    if (c.avatar_source === "gen") return "Mọi ảnh trong chat giữ khuôn mặt của ảnh đại diện (app tự vẽ).";
    return "Tải Ảnh mặt mẫu bên dưới (ảnh AI của nhân vật), hoặc bấm Vẽ lại ảnh đại diện để app tự vẽ mặt mẫu.";
  }

  // Ảnh mặt mẫu PuLID tải lên — chỉ dùng khi người dùng xác nhận ảnh do AI tạo / nhân vật hư cấu
  function faceRefBlock(c) {
    const box = h("div", { class: "field span2 face-ref" });
    const file = h("input", { type: "file", accept: "image/png,image/jpeg,image/webp", hidden: true });
    const up = h("button", { class: "btn sm", type: "button", onclick: () => file.click() }, c.face_ref ? "Đổi ảnh mặt mẫu" : "Tải ảnh mặt mẫu");
    file.addEventListener("change", () => {
      const f = file.files[0]; if (!f) return;
      const rd = new FileReader();
      rd.onload = async () => {
        UI.busy(up, true, "Đang tải");
        try {
          const nc = await api("POST", `/api/characters/${c.id}/face-ref`, { image: rd.result });
          st.cur = { ...st.cur, face_ref: nc.face_ref, face_ref_ok: false }; st.draft.face_ref_ok = false;
          toast("Đã tải ảnh mặt mẫu — tích xác nhận rồi bấm Lưu", "ok"); renderEditor();
        } catch (e) { toast(e.message, "bad"); UI.busy(up, false); }
      };
      rd.readAsDataURL(f);
    });
    const del = c.face_ref ? h("button", { class: "btn sm ghost danger", type: "button", onclick: async () => {
      try { const nc = await api("DELETE", `/api/characters/${c.id}/face-ref`); st.cur = { ...st.cur, face_ref: "", face_ref_ok: false }; st.draft.face_ref_ok = false; renderEditor(); }
      catch (e) { toast(e.message, "bad"); }
    } }, "Xoá") : "";
    box.append(h("label", {}, "Ảnh mặt mẫu (PuLID)"),
      h("div", { class: "row nowrap", style: "align-items:flex-start;gap:14px" },
        c.face_ref ? h("img", { class: "face-ref-img", src: "/images/" + encodeURIComponent(c.face_ref), alt: "Ảnh mặt mẫu" }) : h("div", { class: "face-ref-img empty" }, "Chưa có"),
        h("div", { style: "display:flex;flex-direction:column;gap:8px;min-width:0" },
          h("div", { class: "row" }, up, del, file),
          c.face_ref ? UI.switch(st.draft.face_ref_ok, "Tôi xác nhận ảnh này do AI tạo, là nhân vật hư cấu — không phải ảnh / khuôn mặt người thật",
            (v) => { st.draft.face_ref_ok = v; markDirty(); }) : "",
          h("div", { class: "hint" }, "Ảnh rõ mặt, nhìn thẳng. PuLID khoá mọi ảnh chat theo khuôn mặt này (giống hơn LoRA). Không dùng ảnh người thật."))));
    return box;
  }

  let avatarTimer = null;
  function watchAvatar(id) {
    clearTimeout(avatarTimer);
    avatarTimer = setTimeout(async () => {
      if (!st.cur || st.cur.id !== id) return;
      try {
        const c = await api("GET", `/api/characters/${id}`);
        if (!st.cur || st.cur.id !== id) return;
        if (c.avatar_status === "pending") return watchAvatar(id);
        st.cur = { ...st.cur, avatar_path: c.avatar_path, avatar_status: c.avatar_status, avatar_error: c.avatar_error };
        if (c.avatar_status === "done") toast("Đã vẽ xong ảnh đại diện", "ok");
        renderEditor(); loadChars(); loadStatus();
      } catch (e) { watchAvatar(id); }
    }, 3000);
  }

  // ---- tab Trí nhớ & tâm trạng ----
  function subMemory(body) {
    const moods = (st.status.moods.length ? st.status.moods : [st.draft.mood]).map((m) => ({ value: m, label: `${UI.MOOD_EMOJI[m] || ""} ${m}` }));
    body.append(
      h("div", { class: "section-title" }, "Tâm trạng hiện tại"),
      h("div", { class: "grid" },
        fSelect("mood", "Tâm trạng", moods),
        fText("mood_reason", "Lý do", { placeholder: "Vì sao nhân vật đang như vậy" })),
      h("p", { class: "hint muted", style: "font-size:13px" }, "Tâm trạng tự đổi sau mỗi tin nhắn; chỉnh ở đây để đặt lại bằng tay."),
      h("div", { class: "section-title" }, `Trí nhớ (${st.memories.length})`));

    const addIn = h("input", { class: "input", placeholder: "Thêm một điều nhân vật cần nhớ về bạn..." });
    const addBtn = h("button", { class: "btn primary" }, "Thêm");
    const add = async () => {
      const content = addIn.value.trim();
      if (!content) return;
      try { st.memories.push(await api("POST", `/api/characters/${st.cur.id}/memories`, { content })); addIn.value = ""; renderEditor(); }
      catch (e) { toast(e.message, "bad"); }
    };
    addBtn.addEventListener("click", add);
    addIn.addEventListener("keydown", (e) => { if (e.key === "Enter") add(); });
    body.append(h("div", { class: "mem-add" }, addIn, addBtn));

    const list = h("div", { class: "mem-list" });
    if (!st.memories.length) list.append(h("div", { class: "note" }, "Chưa có trí nhớ. Nhân vật sẽ tự ghi lại khi bạn kể chuyện về mình."));
    const SRC = { auto: "tự ghi", manual: "bạn ghi", import: "nhập" };
    [...st.memories].reverse().forEach((m) => {
      const row = h("div", { class: "mem" });
      const view = () => {
        row.replaceChildren(
          h("div", { class: "txt" }, m.content),
          h("span", { class: "src" }, SRC[m.source] || m.source),
          h("div", { class: "acts" },
            h("button", { class: "btn sm ghost", onclick: edit }, "Sửa"),
            h("button", { class: "btn sm ghost danger", onclick: del }, "Xoá")));
      };
      const edit = () => {
        const ta = h("textarea", { class: "textarea" }); ta.value = m.content;
        row.replaceChildren(ta, h("div", { class: "acts" },
          h("button", { class: "btn sm primary", onclick: async () => {
            try { Object.assign(m, await api("PUT", `/api/memories/${m.id}`, { content: ta.value })); view(); } catch (e) { toast(e.message, "bad"); }
          } }, "Lưu"),
          h("button", { class: "btn sm ghost", onclick: view }, "Huỷ")));
        ta.focus();
      };
      const del = async () => {
        try { await api("DELETE", `/api/memories/${m.id}`); st.memories = st.memories.filter((x) => x.id !== m.id); renderEditor(); }
        catch (e) { toast(e.message, "bad"); }
      };
      view();
      list.append(row);
    });
    body.append(list);
  }

  // ---- tab Ngày tháng: ngày sinh, chu kỳ, kỷ niệm (công thức khớp server/dates.py) ----
  const D = {
    parse(s) { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ""); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; },
    today() { const t = new Date(); return new Date(t.getFullYear(), t.getMonth(), t.getDate()); },
    days(a, b) { return Math.round((b - a) / 86400000); },
    add(d, n) { return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n); },
    dmy(d, year = true) { const p = (n) => String(n).padStart(2, "0"); return `${p(d.getDate())}/${p(d.getMonth() + 1)}` + (year ? `/${d.getFullYear()}` : ""); },
    onYear(d, y) { const x = new Date(y, d.getMonth(), d.getDate()); return x.getMonth() === d.getMonth() ? x : new Date(y, 1, 28); },
    nextYearly(d, t) {
      let n = D.onYear(d, t.getFullYear());
      if (n < t) n = D.onYear(d, t.getFullYear() + 1);
      return { date: n, days: D.days(t, n), years: n.getFullYear() - d.getFullYear() };
    },
    age(b, t) { return t.getFullYear() - b.getFullYear() - ((t.getMonth() < b.getMonth() || (t.getMonth() === b.getMonth() && t.getDate() < b.getDate())) ? 1 : 0); },
    cycle(startIso, cyc, plen, t) {
      const s = D.parse(startIso); if (!s) return null;
      cyc = Math.min(Math.max(parseInt(cyc, 10) || 28, 20), 45); plen = Math.min(Math.max(parseInt(plen, 10) || 5, 2), 10);
      let cur = null, next = s;
      if (t >= s) { const k = Math.floor(D.days(s, t) / cyc); cur = D.add(s, k * cyc); next = D.add(cur, cyc); }
      const day = cur ? D.days(cur, t) + 1 : 0;
      return { on: !!cur && day <= plen, day, plen, cyc, next, toNext: D.days(t, next), after: D.add(next, cyc) };
    },
  };

  function subDates(body) {
    const d = st.draft, t = D.today(), min = st.status.min_age;

    // ngày sinh
    const bHint = h("div", { class: "hint" });
    const showBirth = () => {
      const b = D.parse(d.birthday);
      if (!b) { bHint.textContent = "Có ngày sinh thì tuổi tự tính và tự tăng; đúng ngày sinh nhật nhân vật sẽ chủ động nhắn."; bHint.classList.remove("bad-text"); return; }
      const a = D.age(b, t), n = D.nextYearly(b, t);
      bHint.textContent = `${a} tuổi · ` + (n.days === 0 ? "hôm nay là sinh nhật 🎂" : `còn ${n.days} ngày tới sinh nhật`) + (a < min ? ` — phải từ ${min} tuổi trở lên` : "");
      bHint.classList.toggle("bad-text", a < min);
    };
    const bIn = UI.dateInput(d.birthday, (iso) => { d.birthday = iso; markDirty(); showBirth(); });
    showBirth();

    // chu kỳ
    const cInfo = h("div", { class: "cycle-info" });
    const showCycle = () => {
      const cy = D.cycle(d.period_start, d.cycle_length, d.period_length, t);
      if (!cy) { cInfo.replaceChildren(h("div", { class: "hint" }, "Nhập ngày bắt đầu kỳ gần nhất để tính các kỳ sau.")); return; }
      const rows = [];
      if (cy.on) rows.push(["Đang đến kỳ", `ngày ${cy.day}/${cy.plen}`, true]);
      else if (cy.toNext <= 3) rows.push(["Sắp đến kỳ", `còn ${cy.toNext} ngày — dễ cáu, hay dỗi`, true]);
      rows.push(["Kỳ tiếp theo", `${D.dmy(cy.next)} (còn ${cy.toNext} ngày)`, false]);
      rows.push(["Kỳ sau nữa", `${D.dmy(cy.after)} (còn ${D.days(t, cy.after)} ngày)`, false]);
      cInfo.replaceChildren(...rows.map(([k, v, hot]) => h("div", { class: "ci-row" + (hot ? " hot" : "") }, h("span", {}, k), h("b", {}, v))));
    };
    const pIn = UI.dateInput(d.period_start, (iso) => { d.period_start = iso; markDirty(); showCycle(); });
    const num = (key, def) => {
      const el = h("input", { class: "input num-input", inputmode: "numeric", maxlength: "2" });
      el.value = d[key] || def;
      el.addEventListener("input", () => { el.value = el.value.replace(/\D/g, ""); d[key] = parseInt(el.value, 10) || def; markDirty(); showCycle(); });
      return el;
    };
    const clearP = h("button", { class: "btn icon ghost danger", "aria-label": "Xoá ngày đến kỳ", onclick: () => pIn.setIso("") }, "✕");
    showCycle();

    body.append(
      h("div", { class: "section-title" }, "Ngày sinh & chu kỳ"),
      h("div", { class: "grid" },
        h("div", { class: "field" }, h("label", {}, "Ngày sinh"), bIn, bHint),
        h("div"),
        h("div", { class: "field" }, h("label", {}, "Ngày bắt đầu kỳ gần nhất"), h("div", { class: "row nowrap" }, pIn, clearP)),
        h("div", { class: "field" }, h("label", {}, "Chu kỳ"),
          h("div", { class: "row nowrap" }, num("cycle_length", 28), h("span", { class: "muted" }, "ngày · mỗi kỳ"), num("period_length", 5), h("span", { class: "muted" }, "ngày"))),
        h("div", { class: "field span2" }, cInfo)),
      h("p", { class: "hint muted", style: "font-size:13px" },
        "Nhân vật biết mình đang/sắp đến kỳ: mệt, dễ cáu, không muốn quan hệ trong những ngày đó. Để trống ngày đến kỳ thì bỏ qua."));

    // ngày kỷ niệm
    body.append(h("div", { class: "section-title" }, "Ngày kỷ niệm"));
    const list = h("div", { class: "sched" });
    const setList = (arr) => { d.anniversaries = arr; markDirty(); };
    const draw = () => {
      list.replaceChildren();
      const items = d.anniversaries || [];
      if (!items.length) list.append(h("div", { class: "note" }, "Chưa có ngày kỷ niệm. Ví dụ: Ngày yêu nhau, Lần đầu hẹn hò, Sinh nhật anh, Ngày cưới."));
      items.forEach((it, i) => {
        const left = h("span", { class: "a-left muted" });
        const showLeft = () => {
          const cur = d.anniversaries[i], x = D.parse(cur.date);
          if (!x) { left.textContent = ""; return; }
          if (cur.yearly !== false) {
            const n = D.nextYearly(x, t);
            left.textContent = (n.days === 0 ? "hôm nay" : `còn ${n.days} ngày`) + (n.years > 0 ? ` · tròn ${n.years} năm` : "");
          } else {
            const k = D.days(t, x);
            left.textContent = k === 0 ? "hôm nay" : k > 0 ? `còn ${k} ngày` : "đã qua";
          }
        };
        const upd = (patch) => { setList(d.anniversaries.map((x, j) => (j === i ? { ...x, ...patch } : x))); showLeft(); };
        const di = UI.dateInput(it.date, (iso) => upd({ date: iso }));
        const ti = h("input", { class: "input", placeholder: "Ngày yêu nhau" }); ti.value = it.title || "";
        ti.addEventListener("input", () => upd({ title: ti.value }));
        const sw = UI.switch(it.yearly !== false, "Hằng năm", (v) => upd({ yearly: v }));
        const del = h("button", { class: "btn icon ghost danger", "aria-label": "Xoá ngày kỷ niệm", onclick: () => { setList(d.anniversaries.filter((_, j) => j !== i)); draw(); } }, "✕");
        showLeft();
        list.append(h("div", { class: "a-row" }, di, ti, h("div", { class: "a-meta" }, sw, left), del));
      });
    };
    draw();
    const add = h("button", { class: "btn", onclick: () => { setList([...(d.anniversaries || []), { date: "", title: "", yearly: true }]); draw(); } }, "+ Thêm ngày kỷ niệm");
    body.append(list, h("div", { class: "row", style: "margin-top:10px" }, add),
      h("p", { class: "hint muted", style: "font-size:13px" },
        "Nhân vật nhớ các ngày này, nhắc khi sắp tới, và đúng ngày (sau 8 giờ sáng) sẽ chủ động nhắn. Dòng thiếu ngày hoặc tên sẽ không được lưu."));
  }

  // ---- tab Lịch sinh hoạt ----
  // Bảng sửa các mốc giờ, dùng cho cả lịch hôm nay lẫn lịch mẫu. getList() trả mảng đang sửa (sửa tại chỗ).
  function scheduleRows(getList, onDirty, { highlightNow = false, empty = "" } = {}) {
    const rows = h("div", { class: "sched" });
    const draw = () => {
      const list = getList();
      rows.replaceChildren();
      const nowHm = new Date().toTimeString().slice(0, 5);
      const curIdx = highlightNow ? list.reduce((acc, x, i) => (x.time && x.time <= nowHm ? i : acc), -1) : -2;
      if (!list.length) rows.append(h("div", { class: "note" }, empty));
      list.forEach((it, i) => {
        const t = UI.timeInput(it.time);
        t.addEventListener("input", () => { it.time = t.value; onDirty(); });
        t.addEventListener("blur", () => { it.time = t.value; });
        const a = h("input", { class: "input", placeholder: "Đang làm gì" }); a.value = it.activity;
        a.addEventListener("input", () => { it.activity = a.value; onDirty(); });
        const sw = UI.switch(it.proactive, "Chủ động nhắn", (v) => { it.proactive = v; onDirty(); });
        const del = h("button", { class: "btn icon ghost danger", "aria-label": "Xoá mốc", onclick: () => { list.splice(i, 1); onDirty(); draw(); } }, "✕");
        rows.append(h("div", { class: "s-row" + (i === curIdx ? " now" : "") + (it.fired ? " fired" : "") }, t, a, sw, del));
      });
    };
    draw();
    rows.draw = draw;
    rows.add = () => { getList().push({ time: "", activity: "", proactive: false }); onDirty(); draw(); rows.lastChild.querySelector(".time-input").focus(); };
    rows.sort = () => { getList().sort((x, y) => (x.time || "99").localeCompare(y.time || "99")); onDirty(); draw(); };
    return rows;
  }

  function subSchedule(body) {
    const s = st.settings || {}, d = st.draft, td = st.today || { items: [] };
    const DAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"];

    // ngày đi làm
    const workSet = () => new Set(String(d.work_days ?? "0,1,2,3,4").split(",").filter((x) => x !== ""));
    const dayChips = h("div", { class: "row day-chips" });
    const drawDays = () => {
      const ws = workSet();
      dayChips.replaceChildren(...DAYS.map((lb, i) => h("button", {
        class: "day-chip" + (ws.has(String(i)) ? " on" : ""), type: "button",
        onclick: () => { const x = workSet(); x.has(String(i)) ? x.delete(String(i)) : x.add(String(i)); d.work_days = [...x].sort().join(","); markDirty(); drawDays(); },
      }, lb)));
    };
    drawDays();

    body.append(
      h("div", { class: "grid" },
        fSwitch("proactive_enabled", "Cho nhân vật chủ động nhắn tin",
          `Nhắn ở các mốc có bật "Chủ động nhắn" và khi bạn im lặng lâu. Không nhắn trong giờ yên lặng ${s.quiet_start || "--"} – ${s.quiet_end || "--"} (đổi trong Cài đặt).`),
        fText("silence_minutes", "Nhắn khi bạn im lặng quá (phút)", { numeric: true, hint: "0 = tắt. Mỗi đợt im lặng chỉ nhắn một lần." }),
        h("div", { class: "field span2" }, h("label", {}, "Ngày đi làm"), dayChips,
          h("div", { class: "hint" }, "Ngày không chọn là ngày nghỉ: AI soạn lịch nghỉ ngơi, đi chơi, hẹn hò thay vì đi làm."))));

    // lịch hôm nay (AI soạn)
    const dirtyToday = () => { st.todayDirty = true; updateSavebar(); };
    const today = scheduleRows(() => td.items, dirtyToday, {
      highlightNow: true,
      empty: td.planning ? "AI đang soạn lịch hôm nay..." : "Chưa có lịch hôm nay — AI sẽ tự soạn trong ít phút (cần Ollama đang chạy), hoặc bấm \"AI soạn lại hôm nay\".",
    });
    const dd = td.date ? td.date.split("-").reverse().slice(0, 2).join("/") : "";
    const regen = h("button", { class: "btn" }, "AI soạn lại hôm nay");
    regen.addEventListener("click", async () => {
      if (td.items.length && !(await UI.confirm({ title: "Soạn lại lịch hôm nay?", message: "Lịch hôm nay sẽ được AI soạn mới và lưu ngay.", ok: "Soạn lại" }))) return;
      UI.busy(regen, true, "Đang soạn");
      try { st.today = await api("POST", `/api/characters/${st.cur.id}/today/generate`); st.todayDirty = false; renderEditor(); toast("Đã soạn lịch hôm nay", "ok"); }
      catch (e) { toast(e.message, "bad"); UI.busy(regen, false); }
    });
    const testBtn = h("button", { class: "btn ghost" }, "Thử chủ động nhắn ngay");
    testBtn.addEventListener("click", async () => {
      UI.busy(testBtn, true, "Đang soạn");
      try { await api("POST", `/api/characters/${st.cur.id}/proactive-test`); toast("Nhân vật vừa nhắn, mở Chat để xem", "ok"); }
      catch (e) { toast(e.message, "bad"); }
      UI.busy(testBtn, false);
    });
    body.append(
      h("div", { class: "section-title" }, `Lịch hôm nay · ${td.weekday || ""} ${dd}`,
        td.date ? h("span", { class: "chip day-kind" + (td.workday ? "" : " off") }, td.workday ? "ngày đi làm" : "ngày nghỉ") : ""),
      h("p", { class: "hint muted", style: "font-size:13px;margin-top:-6px" },
        "Mỗi ngày AI soạn một lịch mới (lúc 0 giờ hoặc khi bật máy) dựa trên thói quen bên dưới, lịch hôm qua, chuyện vừa nói trong chat, sinh nhật, kỷ niệm, chu kỳ. Sửa tay được, bấm Lưu."),
      today,
      h("div", { class: "row", style: "margin-top:14px" },
        h("button", { class: "btn", onclick: today.add }, "+ Thêm mốc"), regen, testBtn));

    // lịch mẫu / thói quen
    const dirtySched = () => { st.schedDirty = true; updateSavebar(); };
    const tpl = scheduleRows(() => st.schedule, dirtySched, { empty: "Chưa có thói quen nào. Có thể để trống — AI vẫn soạn lịch từ hồ sơ nhân vật." });
    const aiBtn = h("button", { class: "btn ghost" }, "AI tạo thói quen");
    aiBtn.addEventListener("click", async () => {
      if (st.schedule.length && !(await UI.confirm({ title: "Thay thói quen hiện tại?", message: "AI sẽ tạo danh sách thói quen mới từ hồ sơ nhân vật. Bạn vẫn xem lại được trước khi bấm Lưu.", ok: "Tạo mới" }))) return;
      UI.busy(aiBtn, true, "Đang tạo");
      try { const r = await api("POST", `/api/characters/${st.cur.id}/schedule/generate`); st.schedule = r.items; dirtySched(); tpl.draw(); toast("Đã tạo, xem lại rồi bấm Lưu", "ok"); }
      catch (e) { toast(e.message, "bad"); }
      UI.busy(aiBtn, false);
    });
    body.append(
      h("div", { class: "section-title" }, "Thói quen thường ngày (lịch mẫu)"),
      h("p", { class: "hint muted", style: "font-size:13px;margin-top:-6px" },
        "Không phải lịch cố định: AI chỉ tham khảo để lịch mỗi ngày giữ đúng tính cách, rồi tự thay đổi cho hợp từng ngày."),
      tpl,
      h("div", { class: "row", style: "margin-top:14px" },
        h("button", { class: "btn", onclick: tpl.add }, "+ Thêm mốc"),
        h("button", { class: "btn ghost", onclick: tpl.sort }, "Sắp theo giờ"), aiBtn));
  }

  // ---------- Cài đặt ----------
  async function openSettings() {
    const view = $("view-settings");
    view.replaceChildren(h("div", { class: "empty-state" }, "Đang tải..."));
    try { [st.settings] = await Promise.all([api("GET", "/api/settings"), loadStatus()]); }
    catch (e) { toast(e.message, "bad"); return; }
    st.setDraft = { ...st.settings }; st.setDirty = false;
    renderSettings();
  }

  function renderSettings() {
    const view = $("view-settings");
    const d = st.setDraft, s = st.status, io = s.image_options || {};
    const dirty = () => { st.setDirty = true; bar(); };
    const text = (key, label, o = {}) => {
      const el = o.time ? UI.timeInput(d[key]) : h("input", { class: "input" + (o.mono ? " mono" : ""), inputmode: o.numeric ? "decimal" : null, placeholder: o.placeholder || "" });
      if (!o.time) el.value = d[key] ?? "";
      el.addEventListener("input", () => { d[key] = el.value; dirty(); });
      el.addEventListener("blur", () => { d[key] = el.value; });
      return h("div", { class: "field" + (o.span2 ? " span2" : "") }, h("label", {}, label), el, o.hint ? h("div", { class: "hint" }, o.hint) : "");
    };
    const area = (key, label, hint) => {
      const el = h("textarea", { class: "textarea mono", rows: 3 }); el.value = d[key] ?? "";
      el.addEventListener("input", () => { d[key] = el.value; dirty(); });
      return h("div", { class: "field span2" }, h("label", {}, label), el, hint ? h("div", { class: "hint" }, hint) : "");
    };
    const sel = (key, label, list, o = {}) => {
      const host = h("div");
      const opts = (o.empty ? [{ value: "", label: o.empty }] : []).concat(list.map((x) => ({ value: x, label: x })));
      if (d[key] && !list.includes(d[key])) opts.push({ value: d[key], label: `${d[key]} (không thấy)` });
      UI.select(host, { options: opts, value: d[key], placeholder: o.placeholder || "Chọn...", empty: o.emptyList, onChange: (v) => { d[key] = v; dirty(); } });
      return h("div", { class: "field" + (o.span2 ? " span2" : "") }, h("label", {}, label), host, o.hint ? h("div", { class: "hint" }, o.hint) : "");
    };
    const sw = (key, label, hint) => h("div", { class: "field span2" }, UI.switch(d[key], label, (v) => { d[key] = v; dirty(); }), hint ? h("div", { class: "hint" }, hint) : "");

    const testBtn = h("button", { class: "btn" }, "Kiểm tra kết nối");
    testBtn.addEventListener("click", async () => {
      if (st.setDirty && !(await saveSettings())) return;
      UI.busy(testBtn, true, "Đang kiểm tra");
      await loadStatus();
      UI.busy(testBtn, false);
      renderSettings();
      toast(`Ollama: ${st.status.ollama ? "được" : "không kết nối"} · ComfyUI: ${st.status.comfy ? "được" : "không kết nối"}`, st.status.ollama && st.status.comfy ? "ok" : "bad");
    });
    const conn = (ok, name, extra) => h("span", { class: "row", style: "gap:6px;font-size:13px" }, h("i", { class: "dot " + (ok ? "ok" : "bad") }), `${name}: ${ok ? extra : "chưa kết nối"}`);

    const saveBar = h("div", { class: "savebar", style: "border-radius:14px;border:1px solid var(--line)" });
    const bar = () => {
      const save = h("button", { class: "btn primary" }, "Lưu cài đặt");
      save.disabled = !st.setDirty;
      save.addEventListener("click", async () => { UI.busy(save, true, "Đang lưu"); if (await saveSettings()) renderSettings(); else UI.busy(save, false); });
      saveBar.replaceChildren(st.setDirty ? h("span", { class: "dirty" }, "● Có thay đổi chưa lưu") : h("span", { class: "muted", style: "font-size:13px" }, "Đã lưu"), h("span", { class: "spacer" }), save);
    };
    bar();

    view.replaceChildren(
      h("div", { class: "card" }, h("h3", {}, "Kết nối"),
        h("p", { class: "muted" }, "Địa chỉ Ollama và ComfyUI trên máy có GPU. Nếu WaifuAI chạy cùng máy thì để 127.0.0.1."),
        h("div", { class: "grid" },
          text("ollama_url", "Ollama", { mono: true, placeholder: "http://127.0.0.1:11434" }),
          text("comfy_url", "ComfyUI", { mono: true, placeholder: "http://127.0.0.1:8188" })),
        h("div", { class: "row", style: "margin-top:14px;gap:16px" }, testBtn,
          conn(s.ollama, "Ollama", `${s.models.length} mô hình`), conn(s.comfy, "ComfyUI", `${(io.checkpoints || []).length} checkpoint`))),

      h("div", { class: "card" }, h("h3", {}, "Mô hình chữ"),
        h("p", { class: "muted" }, "Mô hình cảnh nóng: nếu mô hình trò chuyện đã là bản bỏ kiểm duyệt (abliterated, uncensored) thì chọn chính nó, không cần mô hình riêng."),
        h("div", { class: "grid" },
          sel("model_chat", "Mô hình trò chuyện mặc định", s.models, { emptyList: "Ollama chưa có mô hình nào" }),
          sel("model_explicit", "Mô hình cảnh nóng", s.models, { empty: "Không dùng (luôn dùng mô hình trên)", emptyList: "Ollama chưa có mô hình nào" }),
          text("temperature", "Độ sáng tạo (temperature)", { numeric: true, hint: "0.7 đến 1.1" }),
          text("context_messages", "Số tin nhắn gần nhất đưa vào ngữ cảnh", { numeric: true }),
          text("keep_alive", "Giữ mô hình trong VRAM", { mono: true, hint: "Ví dụ 10m, 1h. Khi bật nhả VRAM bên dưới, mô hình vẫn bị nhả trước mỗi lần vẽ." }),
          text("reply_delay_seconds", "Chờ trước khi trả lời (giây)", { numeric: true, hint: "Tính từ tin nhắn cuối của bạn; nhắn thêm thì đếm lại. Nhân vật trả lời gộp mọi tin trong lúc chờ. 0 = trả lời ngay." }),
          sw("disable_thinking", "Tắt chế độ suy nghĩ (Qwen3...)", "Trả lời nhanh hơn với mô hình có chế độ suy nghĩ."),
          sw("vram_swap", "Nhả VRAM giữa chữ và ảnh", "Nên bật với GPU 12 GB: nhả mô hình chữ trước khi vẽ, nhả mô hình ảnh sau khi vẽ. Chậm hơn vài giây mỗi lượt nhưng không tràn VRAM."))),

      h("div", { class: "card" }, h("h3", {}, "Mô hình ảnh (SDXL qua ComfyUI)"),
        h("p", { class: "muted" }, "Danh sách checkpoint, sampler lấy trực tiếp từ ComfyUI."),
        h("div", { class: "grid" },
          sw("image_enabled", "Cho nhân vật gửi ảnh trong chat"),
          sel("checkpoint", "Checkpoint", io.checkpoints || [], { span2: true, placeholder: "Chọn checkpoint SDXL", emptyList: "Không lấy được danh sách (kiểm tra kết nối ComfyUI)" }),
          sel("sampler", "Sampler", io.samplers || [d.sampler]),
          sel("scheduler", "Scheduler", io.schedulers || [d.scheduler]),
          text("steps", "Số bước", { numeric: true, hint: "SDXL: 25 đến 35" }),
          text("cfg", "CFG", { numeric: true, hint: "SDXL: 5 đến 7" }),
          text("width", "Rộng", { numeric: true }),
          text("height", "Cao", { numeric: true, hint: "Dọc 832×1216 hợp ảnh selfie" }),
          area("quality_prefix", "Tag chất lượng (đặt đầu mô tả)"),
          area("negative_extra", "Cấm vẽ thêm (negative)"),
          text("pulid_weight", "Độ mạnh giữ khuôn mặt (PuLID)", { numeric: true, hint: `0.6 đến 1.0. ${io.pulid ? "PuLID SDXL: đã sẵn sàng" : "PuLID SDXL: chưa cài"}` }),
          text("face_detail_denoise", "Độ vẽ lại vùng mặt", { numeric: true, hint: "0.3 đến 0.5. Cao hơn = mặt giống LoRA hơn nhưng dễ lệch tông với thân." }),
          sw("face_detail", "Sửa mặt sau khi vẽ (FaceDetailer)",
            (io.face_detail ? "FaceDetailer: đã sẵn sàng. " : "FaceDetailer: chưa cài — chạy tools\\cai_face_detailer.bat rồi bật lại ComfyUI. ")
            + "Dò khuôn mặt rồi vẽ lại riêng vùng mặt ở độ phân giải cao qua LoRA, giữ mặt đúng ở ảnh nửa người / toàn thân. Thêm ~10–15 giây mỗi ảnh.")),
        h("div", { class: "note lock", style: "margin-top:14px" }, h("b", {}, "Luôn cấm vẽ, không tắt được: "), s.hard_negative)),

      h("div", { class: "card" }, h("h3", {}, "Chủ động nhắn"),
        h("div", { class: "grid" },
          sw("proactive_enabled", "Bật chủ động nhắn cho mọi nhân vật", "Tắt ở đây thì không nhân vật nào tự nhắn, kể cả khi bật riêng."),
          text("quiet_start", "Giờ yên lặng từ", { time: true }),
          text("quiet_end", "đến", { time: true }))),
      saveBar);
  }

  async function saveSettings() {
    try {
      st.settings = await api("PUT", "/api/settings", st.setDraft);
      st.setDraft = { ...st.settings }; st.setDirty = false;
      toast("Đã lưu cài đặt", "ok");
      return true;
    } catch (e) { toast(e.message, "bad"); return false; }
  }

  // ---------- chạy ----------
  (async () => {
    await loadStatus();
    try { st.settings = await api("GET", "/api/settings"); } catch (e) { /* hiện lỗi khi mở Cài đặt */ }
    try { await loadChars(); } catch (e) { toast(e.message, "bad"); }
    if (st.chars.length) selectChar(st.chars[0].id);
  })();
  setInterval(() => { if (!document.hidden) loadStatus(); }, 15000);
})();
