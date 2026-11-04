const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let state = { job: null, attempts: [], sel: 0, next: 0 };
let isPublicMock = false;
let selectedDemoId = "counter";
let trustedTbCache = "(host-owned — loaded per attempt from server events / static note)";

async function init() {
  const h = await (await fetch("/api/health")).json();
  isPublicMock = h.app_env === "public_mock";
  const m = $("#mode");
  m.textContent = h.mock_llm ? "MOCK LLM · counter demos" : `Vultr configured · NO LIVE EVIDENCE · ${h.model}`;
  m.className = "badge mock";
  if (!h.sandbox_image_ready && !h.local_sim) m.textContent += " · ⚠ sandbox image missing";
  if (h.local_sim) m.textContent += " · LOCAL SIM";
  const demos = await (await fetch("/api/demos")).json();
  for (const d of demos) {
    const b = document.createElement("button");
    b.textContent = d.title;
    b.onclick = () => { selectedDemoId = d.id; $("#req").value = d.prompt; };
    $("#demos").appendChild(b);
  }
  $("#req").value = demos[0].prompt;
  selectedDemoId = demos[0].id;
  if (isPublicMock) {
    $("#req").readOnly = true;
    $("#req").title = "Public MOCK: only select fixed demo IDs";
    $("#mode").textContent += " · FIXED DEMOS ONLY · NO LIVE INFERENCE";
    $("#run").textContent = "Run fixed MOCK demo";
    const btn = $("#probe");
    if (btn) btn.disabled = true;
  }
}

function addTimeline(cls, text, detail) {
  const li = document.createElement("li");
  if (cls) li.className = cls;
  li.innerHTML = text + (detail ? `<details><summary>diagnostic fed to model</summary><pre>${esc(detail)}</pre></details>` : "");
  $("#timeline").appendChild(li);
}

function setVerdict(cls, text) {
  const v = $("#verdict");
  v.className = "verdict " + cls;
  v.textContent = text;
}

$("#run").onclick = async () => {
  const req = $("#req").value.trim();
  if (!req && !isPublicMock) return;
  $("#run").disabled = true;
  $("#timeline").innerHTML = "";
  $("#attemptTabs").innerHTML = "";
  $("#probeOut").classList.add("hidden");
  state = { job: null, attempts: [], sel: 0, next: 0 };
  setVerdict("run", "Working…");
  const r = await fetch("/api/jobs", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(isPublicMock ? {demo_id: selectedDemoId} : {request: req, family: "counter"}) });
  if (!r.ok) { setVerdict("fail", (await r.json()).detail || "error"); $("#run").disabled = false; return; }
  state.job = (await r.json()).id;
  poll();
};

async function poll() {
  const r = await fetch(`/api/jobs/${state.job}?since=${state.next}`);
  const j = await r.json();
  state.next = j.next;
  for (const e of j.events) handle(e);
  if (j.status === "running") setTimeout(poll, 600);
  else {
    $("#run").disabled = false;
    setVerdict(j.status === "passed" ? "pass" : "fail",
      j.status === "passed"
        ? `✔ HOST PASS — attempt ${state.attempts.length} (oracle agreement)`
        : `✘ HOST FAIL after ${state.attempts.length} attempt(s)`);
  }
}

function handle(e) {
  const t = `<span class="t">${e.t.toFixed(1)}s</span>`;
  if (e.kind === "llm") addTimeline("", t + esc(e.msg));
  else if (e.kind === "design") {
    state.attempts.push({ attempt: e.attempt, design: e, result: null, wave: null });
    if (e.inference_response_received && !e.mock) {
      $("#mode").textContent = `Vultr response received · ${e.model}`;
      $("#mode").className = "badge live";
    }
    addTimeline("", t + `Model ${e.mock ? "(mock)" : esc(e.model)} wrote <b>dut.v</b> · family <b>${esc(e.family || "counter")}</b>`);
    select(state.attempts.length - 1);
  } else if (e.kind === "sandbox") addTimeline("", t + "🧪 " + esc(e.msg));
  else if (e.kind === "preflight_reject") addTimeline("bad", t + "preflight rejected before any sandbox: " + esc(e.reason));
  else if (e.kind === "result") {
    const a = state.attempts.find((x) => x.attempt === e.attempt);
    if (a) { a.result = e.result; a.wave = e.wave; }
    const c = (e.result && e.result.containment) || {};
    const v = e.verdict || (e.result && e.result.verdict && e.result.verdict.verdict);
    addTimeline(e.ok ? "ok" : "bad", t + (e.ok ? "✔ HOST PASS" : `✘ HOST FAIL <b>${esc(e.reason || e.stage)}</b>`) +
      (c.local ? ' · UNCONTAINED LOCAL SIM' :
        c.container ? ` · <code>${esc(c.container)}</code> ${c.seconds}s cleanup ${c.destroyed ? "verified" : "NOT VERIFIED"}` : " · no sandbox spawned"));
    showSandbox(c);
    renderAttemptTabs();
    select(state.attempts.indexOf(a));
  } else if (e.kind === "heal") addTimeline("heal", t + "♻ " + esc(e.msg), e.log);
  else if (e.kind === "error") addTimeline("bad", t + esc(e.msg));
  else if (e.kind === "done") addTimeline("", t + "<b>" + esc(e.msg) + "</b>");
}

function showSandbox(c) {
  if (!c || !c.network) return;
  if (c.local) { $("#sandboxinfo").textContent = "UNCONTAINED LOCAL SIM: not a Docker isolation demonstration"; return; }
  $("#sandboxinfo").innerHTML = `Last sandbox: <code>--network ${c.network}</code> <code>--memory ${c.memory}</code>
  <code>--cpus ${c.cpus}</code> <code>--pids-limit ${c.pids_limit}</code> <code>--read-only</code>
  <code>--cap-drop ALL</code> · launcher <code>${esc(c.launcher || "docker")}</code>
  · wall ${c.wall_seconds}s · sim ${c.sim_seconds}s`;
}

function renderAttemptTabs() {
  const box = $("#attemptTabs");
  box.innerHTML = "";
  state.attempts.forEach((a, i) => {
    const b = document.createElement("button");
    const ok = a.result && a.result.ok;
    b.innerHTML = `Attempt ${a.attempt} <span class="${a.result ? (ok ? "p" : "f") : ""}">${a.result ? (ok ? "PASS" : "FAIL") : "…"}</span>`;
    if (i === state.sel) b.className = "sel";
    b.onclick = () => select(i);
    box.appendChild(b);
  });
}

function select(i) {
  state.sel = i;
  const a = state.attempts[i];
  if (!a) return;
  renderAttemptTabs();
  $("#panel-rtl").textContent = a.design.rtl || "";
  $("#panel-tb").textContent = a.design.testbench || trustedTbCache;
  $("#panel-notes").textContent = a.design.notes || "";
  const r = a.result;
  if (r) {
    const comp = r.compile || {}, sim = r.sim || {};
    const proto = (r.stdout || (sim.stdout || "")).split("\n").filter((l) => l.startsWith("VLTB1|")).join("\n");
    $("#panel-log").textContent =
      `$ iverilog -g2012 -Wall -s tb_top -o sim.vvp tb_counter.sv dut.v   (exit ${comp.rc ?? "?"})\n` +
      `${(comp.stdout || "") + (comp.stderr || "")}\n` +
      (r.sim || sim.rc != null ? `$ vvp -n sim.vvp +nonce=…   (exit ${sim.rc}${sim.timeout ? ", TIMEOUT" : ""})\n` : "") +
      (proto ? proto + "\n" : ((sim.stdout || "") + (sim.stderr || "")).slice(0, 8000)) +
      (r.stderr ? `\n${r.stderr}` : "");
    $("#panel-verdictj").textContent = JSON.stringify(r.verdict || { note: "pending" }, null, 2);
  } else {
    $("#panel-log").textContent = "running…";
    $("#panel-verdictj").textContent = "running…";
  }
  drawWave(a.wave);
  const link = $("#pnglink");
  if (a.wave && state.job) { link.href = `/api/jobs/${state.job}/wave.png?attempt=${a.attempt}`; link.classList.remove("hidden"); }
  else link.classList.add("hidden");
}

function drawWave(w) {
  const box = $("#wave");
  if (!w) { box.innerHTML = `<p class="muted">No waveform for this attempt.</p>`; return; }
  const sigs = w.signals.filter((s) => s.changes.length);
  const zoom = +$("#zoom").value;
  const end = Math.max(w.end, 1), labelW = 170, rowH = 26;
  const width = Math.max(900, 900 * zoom), plotW = width - labelW - 10;
  const x = (t) => labelW + (t / end) * plotW;
  let svg = `<svg width="${width}" height="${sigs.length * rowH + 30}" xmlns="http://www.w3.org/2000/svg">`;
  for (let k = 0; k <= 10; k++) {
    const t = Math.round((end * k) / 10), X = x(t);
    svg += `<line x1="${X}" y1="0" x2="${X}" y2="${sigs.length * rowH}" stroke="#1c2537"/>`;
    svg += `<text x="${X}" y="${sigs.length * rowH + 16}" text-anchor="middle" fill="#6b7896">${t}</text>`;
  }
  sigs.forEach((s, r) => {
    const y = r * rowH + 4, hi = y + 3, lo = y + rowH - 9;
    const name = s.name.replace(/^tb_top\./, "").replace(/^tb\./, "") + (s.width > 1 ? `[${s.width - 1}:0]` : "");
    svg += `<text x="4" y="${y + 13}">${esc(name)}</text>`;
    const ch = s.changes.concat([[end, s.changes[s.changes.length - 1][1]]]);
    for (let k = 0; k < ch.length - 1; k++) {
      const [ta, va] = ch[k], tb = ch[k + 1][0];
      const xa = x(ta), xb = x(tb);
      if (xb < xa) continue;
      const bad = /[xz]/i.test(va);
      if (s.width === 1) {
        const yy = va === "1" ? hi : va === "0" ? lo : (hi + lo) / 2;
        const col = bad ? "#ef4444" : "#4fd1c5";
        svg += `<path d="M${xa},${hi}V${lo}" stroke="${col}" stroke-opacity=".35"/><path d="M${xa},${yy}H${xb}" stroke="${col}" stroke-width="1.6"/>`;
      } else {
        const col = bad ? "#ef4444" : "#60a5fa";
        svg += `<path d="M${xa + 2},${hi}H${xb - 2}L${xb},${(hi + lo) / 2}L${xb - 2},${lo}H${xa + 2}L${xa},${(hi + lo) / 2}Z" fill="#132443" stroke="${col}"/>`;
        if (xb - xa > 22) {
          const n = /^[01]+$/.test(va) ? parseInt(va, 2).toString(16).toUpperCase() : va;
          svg += `<text x="${(xa + xb) / 2}" y="${(hi + lo) / 2 + 4}" text-anchor="middle">${esc(n)}</text>`;
        }
      }
    }
  });
  svg += `</svg>`;
  box.innerHTML = svg;
}

$("#zoom").oninput = () => { const a = state.attempts[state.sel]; if (a) drawWave(a.wave); };

document.querySelectorAll(".tabs button").forEach((b) => (b.onclick = () => {
  document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
  document.querySelectorAll(".panel").forEach((p) => p.classList.add("hidden"));
  $("#panel-" + b.dataset.tab).classList.remove("hidden");
}));

$("#probe").onclick = async () => {
  $("#probe").disabled = true;
  const out = $("#probeOut");
  out.classList.remove("hidden");
  out.innerHTML = `<p>Spawning sandbox and attacking it from inside…</p>`;
  try {
    const r = await (await fetch("/api/probe", { method: "POST" })).json();
    if (r.detail) { out.textContent = r.detail; $("#probe").disabled = false; return; }
    const rows = (r.probes || []).map((p) =>
      `<tr><td>${esc(p.probe)}</td><td class="${p.contained ? "ok" : "esc"}">${p.contained ? "CONTAINED" : "ESCAPED"}</td><td>${esc(p.detail)}</td></tr>`).join("");
    const all = (r.probes || []).length === 10 && (r.probes || []).every((p) => p.contained);
    out.innerHTML = `<div class="verdict ${all ? "pass" : "fail"}">${all ? "10/10 local containment probes contained (not a formal security proof)" : "Containment probe failure/inconclusive"}</div>
      <table class="probes"><tr><th>Attack</th><th>Result</th><th>Detail</th></tr>${rows}</table>`;
    showSandbox(r.containment || {});
  } catch (e) { out.textContent = "probe failed: " + e; }
  $("#probe").disabled = false;
};

init();
