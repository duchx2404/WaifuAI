/* Thành phần giao diện dùng chung (tự vẽ, không dùng alert/confirm/select/date mặc định của trình duyệt). */
(function () {
  const UI = {};

  UI.esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  UI.h = (tag, attrs = {}, ...kids) => {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(kid));
    return el;
  };

  UI.api = async (method, url, body) => {
    const opt = { method, headers: {} };
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    let res;
    try { res = await fetch(url, opt); } catch (e) { throw new Error("Không kết nối được máy chủ WaifuAI"); }
    let data = null;
    try { data = await res.json(); } catch (e) { /* không có JSON */ }
    if (!res.ok) throw new Error((data && (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))) || `Lỗi ${res.status}`);
    return data;
  };

  // ---------- thông báo ----------
  let toastBox;
  UI.toast = (msg, kind = "") => {
    if (!toastBox) { toastBox = UI.h("div", { class: "toasts" }); document.body.append(toastBox); }
    const t = UI.h("div", { class: "toast " + kind }, msg);
    toastBox.append(t);
    setTimeout(() => t.remove(), kind === "bad" ? 5200 : 2800);
  };

  // ---------- hộp thoại ----------
  UI.modal = (build) => new Promise((resolve) => {
    const back = UI.h("div", { class: "modal-back" });
    const box = UI.h("div", { class: "modal", role: "dialog", "aria-modal": "true" });
    back.append(box);
    const close = (val) => { back.remove(); document.removeEventListener("keydown", onKey); resolve(val); };
    const onKey = (e) => { if (e.key === "Escape") close(null); };
    back.addEventListener("mousedown", (e) => { if (e.target === back) close(null); });
    document.addEventListener("keydown", onKey);
    build(box, close);
    document.body.append(back);
    const f = box.querySelector("[autofocus], .input, .textarea, .btn.primary");
    if (f) setTimeout(() => f.focus(), 30);
  });

  UI.confirm = ({ title, message = "", ok = "Đồng ý", cancel = "Huỷ", danger = false }) =>
    UI.modal((box, close) => {
      box.append(
        UI.h("h3", {}, title),
        message ? UI.h("p", {}, message) : "",
        UI.h("div", { class: "actions" },
          UI.h("button", { class: "btn", onclick: () => close(false) }, cancel),
          UI.h("button", { class: "btn primary" + (danger ? " danger-fill" : ""), onclick: () => close(true) }, ok)),
      );
    }).then((v) => v === true);

  // ---------- xem ảnh lớn ----------
  UI.lightbox = (src) => {
    const lb = UI.h("div", { class: "lightbox" }, UI.h("img", { src, alt: "" }));
    const close = () => { lb.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    lb.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.append(lb);
  };

  // ---------- hộp chọn tự vẽ ----------
  // UI.select(host, {options:[{value,label}], value, placeholder, onChange})
  let openSelect = null;
  document.addEventListener("mousedown", (e) => {
    if (openSelect && !openSelect.root.contains(e.target) && !openSelect.list.contains(e.target)) openSelect.close();
  });
  window.addEventListener("resize", () => openSelect && openSelect.close());
  document.addEventListener("scroll", (e) => { if (openSelect && !openSelect.list.contains(e.target)) openSelect.close(); }, true);

  UI.select = (host, cfg) => {
    const st = { options: cfg.options || [], value: cfg.value ?? "", active: -1 };
    const btn = UI.h("button", { type: "button", class: "cselect-btn", "aria-haspopup": "listbox" });
    const root = UI.h("div", { class: "cselect" }, btn);
    const list = UI.h("div", { class: "cselect-list", role: "listbox" });
    host.replaceChildren(root);

    const label = () => {
      const o = st.options.find((o) => String(o.value) === String(st.value));
      btn.textContent = o ? o.label : (cfg.placeholder || "Chọn...");
      btn.classList.toggle("placeholder", !o);
    };
    const render = () => {
      list.replaceChildren();
      if (!st.options.length) list.append(UI.h("div", { class: "cselect-empty" }, cfg.empty || "Không có lựa chọn"));
      st.options.forEach((o, i) => {
        const el = UI.h("div", {
          class: "cselect-opt" + (String(o.value) === String(st.value) ? " selected" : "") + (i === st.active ? " active" : ""),
          role: "option",
          onmousedown: (e) => { e.preventDefault(); pick(o.value); },
        }, o.label);
        list.append(el);
      });
    };
    const place = () => {
      const r = btn.getBoundingClientRect();
      const below = window.innerHeight - r.bottom;
      list.style.minWidth = r.width + "px";
      list.style.maxWidth = Math.max(r.width, Math.min(420, window.innerWidth - 16)) + "px";
      list.style.left = Math.min(r.left, window.innerWidth - Math.max(r.width, 160) - 8) + "px";
      if (below < 220 && r.top > below) { list.style.top = ""; list.style.bottom = (window.innerHeight - r.top + 4) + "px"; list.style.maxHeight = Math.min(280, r.top - 12) + "px"; }
      else { list.style.bottom = ""; list.style.top = (r.bottom + 4) + "px"; list.style.maxHeight = Math.min(280, below - 12) + "px"; }
    };
    const open = () => {
      if (openSelect) openSelect.close();
      st.active = st.options.findIndex((o) => String(o.value) === String(st.value));
      render(); document.body.append(list); place();
      root.classList.add("open"); openSelect = api;
      reveal(list.querySelector(".selected"));
    };
    // cuộn trong danh sách, không dùng scrollIntoView (nó cuộn cả trang làm hộp chọn tự đóng)
    const reveal = (el) => {
      if (!el) return;
      if (el.offsetTop < list.scrollTop) list.scrollTop = el.offsetTop - 5;
      else if (el.offsetTop + el.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = el.offsetTop + el.offsetHeight - list.clientHeight + 5;
    };
    const close = () => { list.remove(); root.classList.remove("open"); if (openSelect === api) openSelect = null; };
    const pick = (v) => { const changed = String(v) !== String(st.value); st.value = v; label(); close(); btn.focus(); if (changed && cfg.onChange) cfg.onChange(v); };

    btn.addEventListener("click", () => (root.classList.contains("open") ? close() : open()));
    btn.addEventListener("keydown", (e) => {
      const isOpen = root.classList.contains("open");
      if (["ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        if (!isOpen) return open();
        const n = st.options.length; if (!n) return;
        st.active = (st.active + (e.key === "ArrowDown" ? 1 : -1) + n) % n; render();
        reveal(list.querySelector(".active"));
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (isOpen && st.active >= 0) pick(st.options[st.active].value); else if (!isOpen) open();
      } else if (e.key === "Escape" && isOpen) { e.preventDefault(); close(); }
    });

    const api = {
      root, list, close,
      get value() { return st.value; },
      set value(v) { st.value = v ?? ""; label(); },
      setOptions(opts, keep = true) { st.options = opts; if (!keep) st.value = ""; label(); if (root.classList.contains("open")) render(); },
    };
    label();
    return api;
  };

  // ---------- menu chuột phải (tự vẽ, không dùng menu của trình duyệt) ----------
  let openMenu = null;
  UI.menu = (x, y, items) => {
    if (openMenu) openMenu();
    const box = UI.h("div", { class: "ctxmenu", role: "menu" });
    const close = () => { box.remove(); document.removeEventListener("mousedown", onOut, true);
      document.removeEventListener("keydown", onKey, true); window.removeEventListener("resize", close);
      if (openMenu === close) openMenu = null; };
    const onOut = (e) => { if (!box.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } };
    for (const it of items) {
      if (!it) continue;
      box.append(UI.h("button", {
        class: "ctxitem" + (it.danger ? " danger" : ""), type: "button", role: "menuitem",
        onclick: () => { close(); it.onClick(); },
      }, it.icon ? UI.h("span", { class: "ic" }, it.icon) : "", it.label));
    }
    document.body.append(box);
    const r = box.getBoundingClientRect();
    box.style.left = Math.max(8, Math.min(x, window.innerWidth - r.width - 8)) + "px";
    box.style.top = Math.max(8, Math.min(y, window.innerHeight - r.height - 8)) + "px";
    document.addEventListener("mousedown", onOut, true);
    document.addEventListener("keydown", onKey, true);
    window.addEventListener("resize", close);
    openMenu = close;
    return close;
  };

  // Nhấn giữ trên điện thoại = chuột phải. onFire(x, y) chạy khi giữ đủ lâu.
  UI.longPress = (el, onFire, ms = 450) => {
    let timer = null, sx = 0, sy = 0;
    const huy = () => { if (timer) { clearTimeout(timer); timer = null; } };
    el.addEventListener("touchstart", (e) => {
      const t = e.touches[0]; sx = t.clientX; sy = t.clientY;
      timer = setTimeout(() => {
        timer = null;
        el.dataset.lp = "1";              // chặn cú chạm này biến thành click mở chat
        setTimeout(() => { delete el.dataset.lp; }, 800);
        onFire(sx, sy);
      }, ms);
    }, { passive: true });
    el.addEventListener("touchmove", (e) => {
      const t = e.touches[0];
      if (Math.abs(t.clientX - sx) > 10 || Math.abs(t.clientY - sy) > 10) huy();
    }, { passive: true });
    el.addEventListener("touchend", huy);
    el.addEventListener("touchcancel", huy);
  };

  // ---------- công tắc ----------
  UI.switch = (checked, text, onChange) => {
    const input = UI.h("input", { type: "checkbox" });
    input.checked = !!checked;
    if (onChange) input.addEventListener("change", () => onChange(input.checked));
    const el = UI.h("label", { class: "switch" }, input, UI.h("span", { class: "track" }), text ? UI.h("span", {}, text) : "");
    el.input = input;
    return el;
  };

  // ---------- ô giờ HH:MM (gõ số, tự chèn dấu :) ----------
  UI.timeInput = (value = "", attrs = {}) => {
    const el = UI.h("input", { class: "input time-input", inputmode: "numeric", maxlength: "5", placeholder: "HH:MM", autocomplete: "off", ...attrs });
    el.value = value;
    el.addEventListener("input", () => {
      let d = el.value.replace(/\D/g, "").slice(0, 4);
      if (d.length >= 3) d = d.slice(0, 2) + ":" + d.slice(2);
      el.value = d;
    });
    el.addEventListener("blur", () => {
      const m = el.value.match(/^(\d{1,2}):?(\d{2})?$/);
      if (!m) return;
      const hh = Math.min(23, +m[1]), mm = Math.min(59, +(m[2] || 0));
      el.value = String(hh).padStart(2, "0") + ":" + String(mm).padStart(2, "0");
    });
    return el;
  };

  UI.busy = (btn, on, text) => {
    if (on) { btn.dataset.label = btn.innerHTML; btn.disabled = true; btn.innerHTML = `<span class="spin"></span>${text ? UI.esc(text) : ""}`; }
    else { btn.disabled = false; if (btn.dataset.label != null) btn.innerHTML = btn.dataset.label; }
  };

  UI.initial = (name) => (String(name || "?").trim().split(/\s+/).pop() || "?").charAt(0).toUpperCase();

  UI.avatar = (c, size = 44) => {
    const st = `width:${size}px;height:${size}px;font-size:${Math.round(size * 0.4)}px`;
    if (c && c.avatar_path) return UI.h("img", { class: "avatar", src: "/images/" + encodeURIComponent(c.avatar_path), alt: "", style: st });
    return UI.h("span", { class: "avatar", style: st }, UI.initial(c && c.name));
  };

  UI.MOOD_EMOJI = { "vui": "😊", "bình thường": "🙂", "hào hứng": "🤩", "nhớ nhung": "🥺", "ngại ngùng": "😳", "dỗi": "😤", "buồn": "😢", "mệt": "😪", "nứng": "🥵" };

  UI.store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* bỏ qua */ } },
  };

  window.UI = UI;
})();
