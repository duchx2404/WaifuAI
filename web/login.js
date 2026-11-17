(function () {
  const form = document.getElementById("form");
  const pw = document.getElementById("pw");
  const go = document.getElementById("go");
  const err = document.getElementById("err");

  // chỉ quay lại đường dẫn nội bộ
  const raw = new URLSearchParams(location.search).get("next") || "/chat";
  const next = raw.startsWith("/") && !raw.startsWith("//") && !raw.startsWith("/\\") ? raw : "/chat";

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    go.disabled = true;
    try {
      const res = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: pw.value }),
      });
      if (res.ok) { location.replace(next); return; }
      let msg = "Lỗi " + res.status;
      try { const d = await res.json(); if (typeof d.detail === "string") msg = d.detail; } catch (_) { /* bỏ qua */ }
      err.textContent = msg;
      pw.select();
    } catch (_) {
      err.textContent = "Không kết nối được máy chủ WaifuAI";
    } finally {
      go.disabled = false;
    }
  });
})();
