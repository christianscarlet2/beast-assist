// Beast Assist live console. Every button calls this app's own /api, which runs in Azure.
const VIDEO = window.BEAST_VIDEO || "";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pretty = (o) => esc(typeof o === "string" ? o : JSON.stringify(o, null, 2));

const SCENARIOS = [
  ["tools", "What can the standup skill see?", "tools/list, filtered per skill", false],
  ["standup", "Open work on the BA board", "agile-mcp:list_tasks", false],
  ["search", "Semantic search the College", "college-mcp:search_lessons + pgvector", false],
  ["denied_write", "Standup skill tries to write", "OPA should refuse", true],
  ["cross_skill", "Tutor skill reaches for the board", "OPA should refuse", true],
  ["scope", "Read a project outside the scope", "the server should refuse", true],
  ["no_skill", "No skill header", "API Management should refuse", true],
  ["no_token", "No token", "API Management should refuse", true],
];

function renderScenarios() {
  const box = $("#scenarios");
  for (const [id, title, small, deny] of SCENARIOS) {
    const b = document.createElement("button");
    b.className = "scn" + (deny ? " deny" : "");
    b.dataset.id = id;
    b.innerHTML = `${esc(title)}<small>${esc(small)}</small>`;
    b.onclick = () => run(id, b);
    box.appendChild(b);
    if (id === "search") {
      const f = document.createElement("div");
      f.className = "scn-search";
      f.innerHTML = `<input id="q" maxlength="200" placeholder="override a FastAPI dependency in a test" aria-label="Search query">`;
      box.appendChild(f);
    }
  }
}

function hopsFor(r) {
  const gw = r.response.headers["x-beast-gateway"] || "";
  const served = r.response.headers["x-served-by"] || "";
  const body = r.response.body || {};
  const hops = [];
  hops.push({ cls: "", name: "demo app", d: "this page's backend, Azure Container Apps" });
  if (r.token) hops.push({ cls: "", name: "Entra ID token", d: r.token.cached ? "cached client-credentials token" : "new client-credentials token", ms: r.token.ms });
  else hops.push({ cls: "stop", name: "no token sent", d: "the scenario leaves the Authorization header out" });
  const gwStop = r.status === 401 || r.status === 400;
  hops.push({ cls: gwStop ? "stop" : "", name: "Azure API Management", d: (gw || "gateway") + (gwStop ? ` refused: HTTP ${r.status}` : " validate-jwt passed, skill header present") });
  if (!gwStop) {
    const text = JSON.stringify(body);
    const opaStop = /forbidden: skill|not in the skill|cannot run in|lacks Tools/.test(text);
    const scopeStop = /outside this server's scope/.test(text);
    hops.push({ cls: scopeStop ? "stop" : "", name: "MCP server", d: (served || "server") + (scopeStop ? " refused: project outside the scope" : " token verified again") });
    hops.push({ cls: opaStop ? "stop" : "", name: "OPA", d: opaStop ? "refused by policy" : "allowed: tool is in the skill's allowed_tools" });
    if (!opaStop && !scopeStop) hops.push({ cls: "", name: "backend", d: r.url.includes("/college/") ? "Scarlet College + pgvector on Azure Database for PostgreSQL" : "the Scarlet Beast agile board API" });
  }
  hops[hops.length - 1].ms = r.ms;
  return hops;
}

function renderContent(r) {
  const c = r.content;
  if (Array.isArray(c) && c.length && typeof c[0] === "object") {
    const cols = Object.keys(c[0]).filter((k) => !["body"].includes(k)).slice(0, 6);
    return `<table class="rows"><thead><tr>${cols.map((k) => `<th>${esc(k)}</th>`).join("")}</tr></thead><tbody>${c
      .map((row) => `<tr>${cols.map((k) => `<td>${esc(typeof row[k] === "number" ? Math.round(row[k] * 1000) / 1000 : row[k])}</td>`).join("")}</tr>`)
      .join("")}</tbody></table>`;
  }
  return `<pre>${pretty(c)}</pre>`;
}

async function run(id, btn) {
  document.querySelectorAll(".scn").forEach((b) => b.classList.toggle("on", b === btn));
  const t = $("#trace");
  t.innerHTML = `<div class="empty">Calling through Azure…</div>`;
  const t0 = performance.now();
  try {
    const res = await fetch("/api/run", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scenario: id, query: ($("#q") || {}).value || "" }) });
    const r = await res.json();
    if (!res.ok) throw new Error(r.detail || res.status);
    const total = Math.round(performance.now() - t0);
    const deny = r.is_error;
    t.innerHTML = `
      <div class="verdict"><span class="tag ${deny ? "deny" : ""}">${deny ? "refused" : "allowed"}</span>${esc(r.title)}</div>
      <p class="expect">Expected: ${esc(r.expect)}</p>
      <ol class="hops">${hopsFor(r).map((h) => `<li class="${h.cls}"><span class="dot"></span><span><b>${esc(h.name)}</b> <span class="d">${esc(h.d)}</span></span><span class="ms">${h.ms != null ? h.ms + " ms" : ""}</span></li>`).join("")}</ol>
      <h3>Result</h3>${renderContent(r)}
      <details><summary>Request sent to ${esc(r.url)}</summary><pre>${pretty(r.request)}</pre></details>
      <details><summary>Response: HTTP ${r.status}, headers and body</summary><pre>${pretty(r.response)}</pre></details>
      ${r.claims ? `<details><summary>Token claims (from Entra ID)</summary><pre>${pretty(r.claims)}</pre></details>` : ""}
      <p class="fine">Round trip from your browser: ${total} ms.</p>`;
  } catch (e) {
    t.innerHTML = `<div class="empty">The call failed: ${esc(e.message)}</div>`;
  }
}

async function ask(ev) {
  ev?.preventDefault();
  const out = $("#agent-out"), btn = $("#ask button");
  btn.disabled = true;
  out.innerHTML = `<div class="empty">The coordinator is resolving a skill and calling Bedrock. This takes 10 to 40 seconds…</div>`;
  try {
    const res = await fetch("/api/agent", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: $("#ask-q").value, skill: $("#ask-skill").value }) });
    const r = await res.json();
    if (!res.ok) throw new Error(r.detail || res.status);
    const calls = r.steps.filter((s) => s.kind === "tool_call");
    const br = r.bedrock.filter((b) => b.request_id);
    out.innerHTML = `
      <div class="answer">${esc(r.answer)}</div>
      <p class="fine">Skill: <b>${esc(r.skill || "none")}</b> · model <code>${esc(r.model)}</code> on Amazon Bedrock · ${r.bedrock.length} model call(s) · ${calls.length} tool call(s) · ${Math.round(r.ms / 100) / 10} s · ${r.left_today} agent runs left today</p>
      ${calls.map((s) => `<div class="step">called <code>${esc(s.tool)}</code> ${esc(JSON.stringify(s.args))}</div>`).join("")}
      <details><summary>Every step (tool calls and results)</summary><pre>${pretty(r.steps)}</pre></details>
      <details><summary>Bedrock evidence (request ids from AWS)</summary><pre>${pretty(br.length ? br : r.bedrock)}</pre></details>`;
  } catch (e) {
    out.innerHTML = `<div class="empty">${esc(e.message)}</div>`;
  } finally {
    btn.disabled = false;
  }
}

function dl(el, rows) {
  el.innerHTML = rows.filter(([, v]) => v).map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
}

async function where() {
  const [w, h] = await Promise.all([
    fetch("/api/where").then((r) => r.json()).catch(() => ({})),
    fetch("/api/health").then((r) => r.json()).catch(() => ({})),
  ]);
  dl($("#where-host"), [
    ["Served by", w.container_app && `Azure Container Apps · app <code>${esc(w.container_app)}</code>`],
    ["Region", esc(w.region)],
    ["Replica", w.replica && `<code>${esc(w.replica)}</code>`],
    ["Revision", w.revision && `<code>${esc(w.revision)}</code>`],
    ["Outbound IP", w.outbound_ip && `${esc(w.outbound_ip)} · ${esc(w.outbound_network)}${w.outbound_location ? " · " + esc(w.outbound_location) : ""}`],
    ["DNS", w.dns_cname && w.dns_cname.length ? `${location.hostname} → <code>${esc(w.dns_cname.join(", "))}</code>` : ""],
    ["Gateway", w.gateway && `<code>${esc(w.gateway)}</code>`],
    ["Identity", w.token_issuer && `<code>${esc(w.token_issuer)}</code>`],
    ["Model", w.model && `<code>${esc(w.model)}</code> at <code>${esc(w.bedrock)}</code>`],
  ]);
  const names = { "agile-mcp": "agile-mcp", "college-mcp": "college-mcp", registry: "Skills Registry", opa: "OPA", entra: "Entra ID" };
  dl($("#where-hops"), Object.entries(h).map(([k, v]) => [names[k] || k,
    `${v.ok ? "✅" : "❌"} ${v.ok ? "healthy" : esc(v.error || "HTTP " + v.status)}${v.ms != null ? ` · ${v.ms} ms` : ""}${v.served_by ? `<br><code>${esc(v.served_by)}</code>` : ""}`]));
  const azOk = w.container_app && h["agile-mcp"]?.ok && h["college-mcp"]?.ok;
  const pills = [
    [azOk, "az", `Azure Container Apps · ${w.region || ""}`],
    [h.entra?.ok, "az", "Microsoft Entra ID"],
    [!!w.gateway, "az", "Azure API Management"],
    [h.registry?.ok, "az", "Azure Database for PostgreSQL"],
    [!!w.model, "aws", "Amazon Bedrock"],
  ];
  $("#pills").innerHTML = pills.map(([ok, c, t]) => `<span class="pill ${c} ${ok ? "ok" : "bad"}">${esc(t)}</span>`).join("");
}

function film() {
  const v = $("#film");
  if (!VIDEO) { $("#video").style.display = "none"; return; }
  v.poster = VIDEO.replace(/\.mp4$/, ".jpg");
  v.innerHTML = `<source src="${VIDEO}" type="video/mp4"><track kind="captions" srclang="en" label="English" src="/static/captions.vtt" default>`;
  v.load();
}

function ago(t, now) {
  if (!t) return "never";
  const s = Math.max(0, Math.round(now - t));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
}

async function status() {
  let d;
  try { d = await fetch("/api/status").then((r) => r.json()); } catch { return; }
  const now = d.now;
  for (const cloud of ["azure", "aws"]) {
    $(`#lights-${cloud}`).innerHTML = d.services.filter((s) => s.cloud === cloud).map((s) => {
      const state = s.ok == null ? "wait" : s.ok ? "ok" : "bad";
      const label = s.ok == null ? "first check running" : s.ok ? "operational" : "failing";
      const hist = (s.history || []).map((h) => `<i class="${h ? "" : "f"}"></i>`).join("");
      const uptime = s.checks ? `${Math.round((100 * (s.checks - s.fails)) / s.checks)}% of ${s.checks} checks` : "";
      return `<div class="light" title="${esc(s.what)}">
        <div class="light-top"><span class="lamp ${state}" aria-label="${label}"></span><span class="light-name">${esc(s.name)}</span></div>
        <div class="light-what">${esc(s.what)}</div>
        <div class="light-last">${esc(s.ok == null ? "checking…" : s.detail)}</div>
        <div class="light-meta">${s.checked_at ? `checked ${ago(s.checked_at, now)} · ${s.ms} ms · ` : ""}${label}${s.ok === false ? ` · last healthy ${ago(s.last_ok, now)}` : ""}${uptime ? ` · ${uptime}` : ""}</div>
        <div class="spark" aria-hidden="true">${hist}</div>
      </div>`;
    }).join("");
  }
  const el = $("#status-all");
  const bad = d.services.filter((s) => s.ok === false).length;
  el.className = "status-all " + (d.all_ok ? "ok" : bad ? "bad" : "");
  el.textContent = d.all_ok ? `● All ${d.services.length} services operational` : bad ? `● ${bad} of ${d.services.length} failing` : "checking…";
}

renderScenarios();
status();
setInterval(status, 15000);
$("#ask").addEventListener("submit", ask);
document.querySelectorAll(".examples button").forEach((b) => b.addEventListener("click", () => {
  $("#ask-q").value = b.dataset.q; $("#ask-skill").value = b.dataset.s || ""; ask();
}));
film();
where();
