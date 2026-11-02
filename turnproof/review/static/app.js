/* TurnProof console: small progressive enhancements, no framework. */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = s => String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));

  // ---- verifier output -> trust summary (real PASS / FAIL / SKIP lines only) ---------------
  const GROUPS = [
    {key: "packet", label: "Packet integrity", re: /schema|required fields|possible_causes|packet hash/i},
    {key: "sig", label: "Digital signature", re: /signature/i},
    {key: "frames", label: "Frame integrity", re: /frame hash/i},
    {key: "log", label: "Event log integrity", re: /event-log/i},
  ];
  function parse(output) {
    return (output || "").split("\n").filter(l => /^(PASS|FAIL|SKIP)\b/.test(l)).map(l => {
      const st = l.slice(0, 4), rest = l.slice(4).trim(), i = rest.indexOf("  - ");
      return {status: st, name: i >= 0 ? rest.slice(0, i) : rest, detail: i >= 0 ? rest.slice(i + 4) : ""};
    });
  }
  function tile(label, cls, value) {
    return `<div class="t ${cls}"><div class="l">${esc(label)}</div><div class="v">${esc(value)}</div></div>`;
  }
  window.renderTrust = function (box, output, mode) {
    const checks = parse(output);
    const verified = /RESULT:\s*VERIFIED/.test(output || "");
    const skipped = checks.filter(c => c.status === "SKIP").length;
    let html = "";
    GROUPS.forEach(g => {
      const mine = checks.filter(c => g.re.test(c.name));
      let cls = "idle", v = "Not checked";
      if (mine.some(c => c.status === "FAIL")) { cls = "fail"; v = "Failed"; }
      else if (mine.length && mine.every(c => c.status === "PASS")) { cls = "pass"; v = "Passed"; }
      else if (mine.some(c => c.status === "SKIP")) { cls = "skip"; v = "Not checked (file missing)"; }
      html += tile(g.label, cls, v);
    });
    let oc, ov;
    if (mode === "tamper") { oc = verified ? "fail" : "pass"; ov = verified ? "Tampering NOT detected" : "Tampering detected"; }
    else if (!checks.length) { oc = "fail"; ov = "Verifier did not run"; }
    else if (verified && skipped) { oc = "partial"; ov = `Verified · ${skipped} check${skipped > 1 ? "s" : ""} not run`; }
    else if (verified) { oc = "pass"; ov = `Verified · all ${checks.length} checks passed`; }
    else { oc = "fail"; ov = "Tampered or invalid"; }
    html = tile(mode === "tamper" ? "Tamper test (one pixel changed on a copy)" : "Overall result", "overall " + oc, ov) + html;
    const list = checks.map(c => `<li><span class="st ${c.status}">${c.status}</span><span>${esc(c.name)}${c.detail ? ` <span class="muted">— ${esc(c.detail)}</span>` : ""}</span></li>`).join("");
    box.innerHTML = `<div class="trust">${html}</div>
      <details class="more"><summary>Each check (${checks.length})</summary><div class="more-body"><ul class="checks">${list || "<li>No check lines in the output.</li>"}</ul>
      <pre class="term ${oc === "pass" ? "ok" : (oc === "fail" ? "bad" : "")}">${esc(output)}</pre></div></details>`;
    box.hidden = false;
  };
  async function runCheck(btn, url, mode) {
    const box = document.getElementById(btn.dataset.target);
    if (!box) return;
    const label = btn.textContent;
    btn.disabled = true; btn.textContent = mode === "tamper" ? "Tampering a copy…" : "Verifying…";
    box.hidden = false; box.innerHTML = '<div class="muted small">Running the standalone verifier…</div>';
    try {
      const r = await fetch(url, {method: "POST"});
      const j = await r.json();
      window.renderTrust(box, (j.command ? "$ python " + j.command + "\n\n" : "") + (j.output || "") + "\nexit code " + j.exit_code, mode);
    } catch (e) { box.innerHTML = '<div class="banner bad">Request failed: ' + esc(e) + "</div>"; }
    btn.disabled = false; btn.textContent = label;
  }
  $$("[data-verify]").forEach(b => b.addEventListener("click", () => runCheck(b, `/api/packets/${b.dataset.verify}/verify`, "verify")));
  $$("[data-tamper]").forEach(b => b.addEventListener("click", () => runCheck(b, `/api/packets/${b.dataset.tamper}/tamper`, "tamper")));
  $$("[data-autoverify]").forEach(b => b.click());

  // ---- keyframe viewer ----------------------------------------------------------------------
  $$("[data-viewer]").forEach(v => {
    const img = $("img.main", v), title = $(".cap-title", v), meta = $(".cap-meta", v);
    $$(".thumb", v.closest("[data-viewer-scope]") || v).forEach(t => t.addEventListener("click", () => {
      $$(".thumb", v.closest("[data-viewer-scope]") || v).forEach(x => x.classList.remove("on"));
      t.classList.add("on");
      if (img) { img.src = t.dataset.img; img.alt = t.dataset.title || ""; }
      if (title) title.textContent = t.dataset.title || "";
      if (meta) meta.textContent = t.dataset.meta || "";
      const a = img && img.closest("a"); if (a) a.href = t.dataset.img;
      if (window.tpSeek && t.dataset.frame) window.tpSeek(parseFloat(t.dataset.frame), true);
    }));
  });

  // ---- tabs ---------------------------------------------------------------------------------
  $$("[data-tabs]").forEach(group => {
    const btns = $$("button[data-tab]", group);
    btns.forEach(b => b.addEventListener("click", () => {
      btns.forEach(x => { x.classList.toggle("on", x === b); const p = document.getElementById(x.dataset.tab); if (p) p.hidden = x !== b; });
    }));
  });

  // ---- upload drop zone ---------------------------------------------------------------------
  $$(".drop").forEach(d => {
    const input = $("input[type=file]", d), out = $(".file", d);
    const show = () => { if (out) out.textContent = input.files.length ? "Selected: " + input.files[0].name + " (" + Math.round(input.files[0].size / 1048576 * 10) / 10 + " MB)" : ""; };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach(ev => d.addEventListener(ev, e => { e.preventDefault(); d.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => d.addEventListener(ev, () => d.classList.remove("over")));
    d.addEventListener("drop", e => { e.preventDefault(); if (e.dataTransfer.files.length) { input.files = e.dataTransfer.files; show(); input.dispatchEvent(new Event("change")); } });
  });

  // ---- live summary of form values ----------------------------------------------------------
  $$("[data-summary-of]").forEach(box => {
    const form = document.getElementById(box.dataset.summaryOf);
    if (!form) return;
    const upd = () => $$("[data-sum]", box).forEach(cell => {
      const el = form.elements[cell.dataset.sum];
      if (!el) return;
      let v = el.type === "checkbox" ? (el.checked ? "On" : "Off") : (el.tagName === "SELECT" ? (el.options[el.selectedIndex] || {}).text : el.value);
      if (el.type === "file") v = el.files.length ? el.files[0].name : "";
      cell.textContent = v || cell.dataset.empty || "—";
      cell.classList.toggle("muted", !v);
    });
    form.addEventListener("input", upd); form.addEventListener("change", upd); upd();
  });

  // ---- table search / filter, clickable rows ----------------------------------------------------
  $$("[data-filter]").forEach(inp => {
    const table = document.querySelector(inp.dataset.filter);
    const sel = document.querySelector(inp.dataset.status || "_none_");
    const run = () => {
      const q = (inp.value || "").toLowerCase(), st = sel ? sel.value : "";
      $$("tbody tr[data-row]", table).forEach(tr => {
        const ok = (!q || tr.textContent.toLowerCase().includes(q)) && (!st || tr.dataset.status === st);
        tr.hidden = !ok;
        $$(`tr[data-parent="${tr.dataset.row}"]`, table).forEach(s => { s.hidden = !ok || s.dataset.collapsed === "1"; });
      });
    };
    inp.addEventListener("input", run); if (sel) sel.addEventListener("change", run);
  });
  $$("tr[data-href]").forEach(tr => tr.addEventListener("click", e => {
    if (e.target.closest("a, button, input, select, form")) return;
    window.location = tr.dataset.href;
  }));
  $$("[data-toggle-rows]").forEach(b => b.addEventListener("click", e => {
    e.preventDefault(); e.stopPropagation();
    $$(`tr[data-parent="${b.dataset.toggleRows}"]`).forEach(s => { const hide = !s.hidden; s.hidden = hide; s.dataset.collapsed = hide ? "1" : "0"; });
  }));

  // ---- confirm before actions that start paid analysis -------------------------------------------
  $$("form[data-confirm]").forEach(f => f.addEventListener("submit", e => { if (!window.confirm(f.dataset.confirm)) e.preventDefault(); }));

  // ---- tooltips (turnaround chart and anything with data-tip) -------------------------------------
  let tip = null;
  function showTip(el) {
    if (!tip) { tip = document.createElement("div"); tip.className = "tc-tip"; document.body.appendChild(tip); }
    const lines = (el.dataset.tip || "").split("\n");
    tip.innerHTML = "<b>" + esc(lines[0]) + "</b>" + lines.slice(1).map(l => "<div>" + esc(l) + "</div>").join("");
    tip.hidden = false;
    const r = el.getBoundingClientRect(), tr = tip.getBoundingClientRect();
    const x = Math.max(8, Math.min(r.left + r.width / 2 - tr.width / 2, window.innerWidth - tr.width - 8));
    let y = r.top - tr.height - 8; if (y < 8) y = r.bottom + 8;
    tip.style.left = (x + window.scrollX) + "px"; tip.style.top = (y + window.scrollY) + "px";
  }
  const hideTip = () => { if (tip) tip.hidden = true; };
  $$("[data-tip]").forEach(el => {
    el.addEventListener("mouseenter", () => showTip(el)); el.addEventListener("mouseleave", hideTip);
    el.addEventListener("focus", () => showTip(el)); el.addEventListener("blur", hideTip);
  });

  // ---- evidence viewer: large frame, previous / next, strip, linked to the turnaround chart ------
  const hmOf = t => { const s = String(t || "").slice(11, 19); return s.endsWith(":00") ? s.slice(0, 5) : s; };
  $$("[data-viewer2]").forEach(v => {
    const frames = JSON.parse($(".v-data", v).textContent || "[]");
    if (!frames.length) return;
    const img = $("img.main", v), open = $(".v-open", v), title = $(".cap-title", v), meta = $(".cap-meta", v);
    const pos = $(".v-pos", v), kind = $(".v-kind", v), ai = $(".v-ai", v), phase = $(".v-phase", v), src = $(".v-src", v);
    const strip = $$(".sf", v);
    const chart = document.getElementById(v.dataset.chart);
    const cursor = chart && $(".tc-cursor", chart);
    let cur = parseInt((($(".sf.on", v) || {}).dataset || {}).i || "0", 10);
    function show(i, scroll) {
      cur = (i + frames.length) % frames.length;
      const f = frames[cur];
      img.src = f.img; img.alt = f.title; if (open) open.href = f.img;
      title.textContent = f.title;
      meta.textContent = (f.t_utc ? hmOf(f.t_utc) + " UTC" : "no clock time") + " · " + f.t_s.toFixed(1) + " s into clip · frame " + f.frame_index;
      if (pos) pos.textContent = (cur + 1) + " / " + frames.length;
      if (kind) { kind.textContent = f.kind === "evidence" ? "Signed evidence frame" : "Context frame"; kind.classList.toggle("info", f.kind === "evidence"); }
      if (ai) ai.hidden = !f.ai;
      if (phase) phase.textContent = f.phase || "—";
      if (src) src.textContent = f.overlay ? "SAM 3.1 overlay · redacted frame" : "Redacted frame";
      const act = $("[data-active]", v);
      if (act) act.innerHTML = (f.active || []).map(a => '<span class="pill ' + (a.validated ? 'good' : 'probe') + '">' + a.label.replace(/</g, '&lt;') + '</span>').join('');
      strip.forEach((b, k) => b.classList.toggle("on", k === cur));
      if (scroll && strip[cur]) strip[cur].scrollIntoView({block: "nearest", inline: "nearest"});
      if (cursor) {
        cursor.hidden = f.x == null;
        if (f.x != null) cursor.style.left = "calc(var(--lbl) + (100% - var(--lbl)) * " + (f.x / 100) + ")";
      }
      if (chart) $$("[data-frame]", chart).forEach(b => b.classList.toggle("sel", b.dataset.frame === f.id));
      if (window.tpSeek) window.tpSeek(f.frame_index, true);
    }
    $(".v-nav.prev", v).addEventListener("click", () => show(cur - 1, true));
    $(".v-nav.next", v).addEventListener("click", () => show(cur + 1, true));
    strip.forEach(b => b.addEventListener("click", () => show(parseInt(b.dataset.i, 10), true)));
    v.addEventListener("keydown", e => {
      if (e.key === "ArrowLeft") { e.preventDefault(); show(cur - 1, true); }
      if (e.key === "ArrowRight") { e.preventDefault(); show(cur + 1, true); }
    });
    if (chart) $$("[data-frame]", chart).forEach(b => b.addEventListener("click", () => {
      const i = frames.findIndex(f => f.id === b.dataset.frame);
      if (i < 0) return;
      show(i, true);
      const r = v.getBoundingClientRect();
      if (r.top < 0 || r.bottom > window.innerHeight) v.scrollIntoView({behavior: "smooth", block: "start"});
    }));
    show(cur, false);
  });

  // ---- Airport & Cameras: switch the selected flight without reloading ---------------------------
  window.tpShowFlight = function (key, href) {
    const panels = $$("[data-flight-panel]");
    if (!panels.some(p => p.dataset.flightPanel === key)) return false;
    panels.forEach(p => { p.hidden = p.dataset.flightPanel !== key; });
    $$("a[data-flight]").forEach(a => a.classList.toggle("sel", a.dataset.flight === key));
    if (href) history.replaceState(null, "", href);
    return true;
  };
  $$("a[data-flight]").forEach(a => a.addEventListener("click", e => {
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    if (window.tpShowFlight(a.dataset.flight, a.href)) {
      e.preventDefault();
      if (window.innerWidth < 1100) { const p = $(`[data-flight-panel="${a.dataset.flight}"]`); if (p) p.scrollIntoView({behavior: "smooth"}); }
    }
  }));

  // ---- menus close on outside click / Escape ------------------------------------------------------
  document.addEventListener("click", e => $$("details[data-menu][open]").forEach(d => { if (!d.contains(e.target)) d.open = false; }));
  document.addEventListener("keydown", e => { if (e.key === "Escape") $$("details[data-menu][open]").forEach(d => { d.open = false; }); });
})();
