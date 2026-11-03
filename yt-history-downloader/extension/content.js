(() => {
  "use strict";

  const ID_RE = /(?:[?&]v=|\/shorts\/)([\w-]{11})/;
  const LINK_SEL = 'a[href*="/watch?v="], a[href*="/shorts/"]';
  const BOX_SEL =
    "ytd-video-renderer, yt-lockup-view-model, ytm-video-with-context-renderer, ytd-rich-item-renderer";

  const QUALITIES = {
    video: [["best", "Best available"], ["1080", "1080p"], ["720", "720p"], ["480", "480p"], ["360", "360p"]],
    mp3: [["320", "320 kbps"], ["192", "192 kbps"], ["128", "128 kbps"]],
    m4a: [["best", "Best (original)"]],
  };

  const selected = new Map(); // videoId -> title
  let ui = null;
  let pollTimer = null;

  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v);
    }
    n.append(...kids);
    return n;
  }

  function send(msg) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(msg, (r) => {
        void chrome.runtime.lastError;
        resolve(r || { ok: false, error: "No response from extension" });
      });
    });
  }

  // ---------- Panel ----------
  function buildPanel() {
    const count = el("span", { class: "ythd-count", text: "0 selected" });
    const format = el("select", {},
      el("option", { value: "video", text: "Video (MP4)" }),
      el("option", { value: "mp3", text: "Audio (MP3)" }),
      el("option", { value: "m4a", text: "Audio (M4A)" }));
    const quality = el("select");
    const go = el("button", { class: "ythd-go", text: "Download", disabled: "" });
    const status = el("div", { class: "ythd-status" });

    const fillQuality = () => {
      quality.replaceChildren(
        ...QUALITIES[format.value].map(([v, t]) => el("option", { value: v, text: t }))
      );
    };
    format.addEventListener("change", fillQuality);
    fillQuality();

    const panel = el("div", { id: "ythd-panel" },
      el("div", { class: "ythd-title", text: "History downloader" }),
      el("div", { class: "ythd-row" },
        el("button", { text: "Select all", onclick: () => selectAll(true) }),
        el("button", { text: "Clear", onclick: () => selectAll(false) }),
        count),
      el("div", { class: "ythd-row" }, el("label", { text: "Format " }, format)),
      el("div", { class: "ythd-row" }, el("label", { text: "Quality " }, quality)),
      go,
      status);
    document.body.appendChild(panel);

    go.addEventListener("click", startDownload);
    ui = { panel, count, format, quality, go, status };
  }

  function setStatus(text, isError = false) {
    ui.status.textContent = text;
    ui.status.classList.toggle("ythd-error", isError);
  }

  function refreshCount() {
    ui.count.textContent = `${selected.size} selected`;
    if (selected.size) ui.go.removeAttribute("disabled");
    else ui.go.setAttribute("disabled", "");
  }

  // ---------- Checkboxes on video cards ----------
  function boxTitle(box) {
    const t = box.querySelector("#video-title, h3, [title]");
    return ((t && (t.getAttribute("title") || t.textContent)) || "video").trim().slice(0, 200);
  }

  function toggle(id, title, on) {
    if (on) selected.set(id, title);
    else selected.delete(id);
    refreshCount();
  }

  function selectAll(on) {
    document.querySelectorAll(".ythd-cb").forEach((cb) => {
      if (!cb.dataset.id) return;
      cb.checked = on;
      toggle(cb.dataset.id, boxTitle(cb.parentElement), on);
    });
    if (!on) selected.clear();
    refreshCount();
  }

  function scan() {
    document.querySelectorAll(LINK_SEL).forEach((a) => {
      const m = (a.getAttribute("href") || "").match(ID_RE);
      if (!m) return;
      const box = a.closest(BOX_SEL);
      if (!box) return;

      let cb = box._ythdCb;
      if (!cb) {
        cb = el("input", { type: "checkbox", class: "ythd-cb" });
        cb.addEventListener("click", (e) => e.stopPropagation());
        cb.addEventListener("change", () => toggle(cb.dataset.id, boxTitle(box), cb.checked));
        box.style.position = "relative";
        box.appendChild(cb);
        box._ythdCb = cb;
      }
      // YouTube recycles elements while scrolling, so keep the id in sync.
      if (cb.dataset.id !== m[1]) {
        cb.dataset.id = m[1];
        cb.checked = selected.has(m[1]);
      }
    });
  }

  // ---------- Download + progress ----------
  async function startDownload() {
    const payload = {
      format: ui.format.value,
      quality: ui.quality.value,
      items: [...selected].map(([id, title]) => ({ id, title })),
    };
    ui.go.setAttribute("disabled", "");
    const r = await send({ type: "download", payload });
    refreshCount();
    if (!r.ok) return setStatus(r.error, true);
    setStatus(`Queued ${r.data.queued} item(s)…`);
    startPolling();
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(poll, 1500);
    poll();
  }

  async function poll() {
    const r = await send({ type: "status" });
    if (!r.ok) {
      setStatus(r.error, true);
      clearInterval(pollTimer);
      pollTimer = null;
      return;
    }
    const jobs = r.data.jobs || {};
    let done = 0, active = 0, failed = 0;
    for (const [id, j] of Object.entries(jobs)) {
      if (j.status === "done") done++;
      else if (j.status === "error") failed++;
      else active++;
      const cb = document.querySelector(`.ythd-cb[data-id="${id}"]`);
      if (cb) {
        let badge = cb._badge;
        if (!badge) {
          badge = el("span", { class: "ythd-badge" });
          cb.after(badge);
          cb._badge = badge;
        }
        badge.textContent =
          j.status === "done" ? "✓ done" :
          j.status === "error" ? "✗ failed" :
          j.status === "queued" ? "… queued" : `⬇ ${Math.round(j.progress || 0)}%`;
        badge.title = j.error || "";
      }
    }
    setStatus(`${done} done · ${active} in progress · ${failed} failed\nSaved to: ${r.data.outDir}`, failed > 0 && active === 0);
    if (active === 0) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // ---------- SPA-aware lifecycle ----------
  function tick() {
    const onHistory = location.pathname === "/feed/history";
    if (onHistory && !ui) buildPanel();
    if (ui) ui.panel.style.display = onHistory ? "" : "none";
    if (onHistory) scan();
  }

  setInterval(tick, 800);
  tick();
})();
