"use strict";
// The Lead Check chat page. Loaded as a file (not inline) so the page can forbid inline scripts.
const APP = "lead_agent";
let USER = null;  // the signed-in email, from the server (/whoami)
const $ = id => document.getElementById(id);
const log = $("log"), msg = $("msg"), send = $("send");
let session = null, pending = [], busy = false;
const n = v => (v ?? 0).toLocaleString("en-US");
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

// Plain messages instead of raw server errors.
const PROBLEM = {
  401: "Your sign-in expired. Reload the page.",
  403: "That conversation belongs to someone else.",
  404: "This conversation has expired (cleared after 30 idle minutes). Start a new conversation and upload the file again.",
  413: "The file is too large. Upload a smaller export.",
};
async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!r.ok) { const e = new Error(PROBLEM[r.status] || "Something went wrong. Try again, or start a new conversation."); e.status = r.status; throw e; }
  return r.json();
}
const userPath = () => `/apps/${APP}/users/${encodeURIComponent(USER)}/sessions`;
async function whoami() {
  const me = await api("/whoami");
  USER = me.user;
  $("who").textContent = me.user === "local" ? "" : `Signed in as ${me.user} · `;
  $("devLink").hidden = !me.dev_ui;
}
async function newSession() {
  session = (await api(userPath(), {})).id;
  history.replaceState(null, "", "#" + session);
  $("sessionLbl").textContent = "Conversation · " + session.slice(0, 8);
}

// Bubbles for one agent turn: the scoring card (from the tool's numbers) + the model's text.
function renderTurn(events) {
  let card = "", text_out = "", error = "";
  for (const ev of events) for (const p of ev.content?.parts || []) {
    const fr = p.functionResponse;
    const cards = {check_leads: leadCheckCard};
    if (cards[fr?.name]) {
      if (fr.response.status === "ok") card = cards[fr.name](fr.response);
      else error = fr.response.message;
    }
    if (p.text && ev.author !== "user") text_out += p.text;
  }
  if (error) bubble("err", esc(error));
  if (card || text_out) bubble("a", card + (text_out ? `<div class="${card ? "note" : ""}">${md(text_out)}</div>` : ""));
  return !!card;
}
function userBubble(texts, files) {
  bubble("u", files.map(f => `<span class="file">📎 ${esc(f)}</span>`).join("") + (files.length && texts ? "<br>" : "") + esc(texts));
}

// Reopen a conversation from the URL (#session-id), e.g. after a reload or a page link.
async function restore() {
  const id = location.hash.slice(1);
  if (!id) return;
  try {
    const sess = await api(`${userPath()}/${encodeURIComponent(id)}`);
    session = id; $("sessionLbl").textContent = "Conversation · " + id.slice(0, 8);
    let turn = [], scored = false;
    const flush = () => { if (turn.length) scored = renderTurn(turn) || scored; turn = []; };
    for (const ev of sess.events || []) {
      if (ev.author === "user") {
        flush();
        const parts = ev.content?.parts || [];
        const files = parts.map(p => (p.text || "").match(/^\[Uploaded file: "(.+)" · /)?.[1]).filter(Boolean);
        const text = parts.filter(p => p.text && !/^\[(Upload(ed file|ed Artifact| refused)|Removed):/.test(p.text)).map(p => p.text).join(" ");
        userBubble(text, files);
      } else turn.push(ev);
    }
    flush();
    if (sess.events?.length) setFollowups(scored);
  } catch { history.replaceState(null, "", location.pathname); }
}

function addFiles(list) {
  for (const f of list) {
    if (!/\.(csv|xlsx)$/i.test(f.name)) continue;
    pending = pending.filter(p => p.name !== f.name).concat(f);
  }
  renderPending();
  if (!msg.value.trim() && pending.length) msg.value = "What's worth acting on in this file?";
}
function renderPending() {
  $("pending").innerHTML = pending.map((f, i) =>
    `<span class="pf">📄 ${esc(f.name)} <small>${(f.size/1e6).toFixed(1)} MB</small><button data-i="${i}" aria-label="Remove">×</button></span>`).join("");
}
$("pending").onclick = e => { if (e.target.dataset.i !== undefined) { pending.splice(+e.target.dataset.i, 1); renderPending(); } };
const b64 = f => new Promise((ok, bad) => { const r = new FileReader(); r.onload = () => ok(r.result.split(",")[1]); r.onerror = bad; r.readAsDataURL(f); });

function bubble(cls, html) {
  $("empty")?.remove();
  const d = document.createElement("div"); d.className = cls; d.innerHTML = html;
  log.appendChild(d); d.scrollIntoView({behavior: "smooth", block: "end"}); return d;
}

// The model's text as Markdown: no images, forms or embeds; links only to http(s), opened in a new tab.
const PURIFY = {FORBID_TAGS: ["img", "svg", "math", "style", "form", "input", "button", "iframe", "video", "audio", "source", "picture"],
                FORBID_ATTR: ["style", "srcset"], ALLOWED_URI_REGEXP: /^https?:\/\//i};
DOMPurify.addHook("afterSanitizeAttributes", el => { if (el.tagName === "A") { el.setAttribute("target", "_blank"); el.setAttribute("rel", "noopener noreferrer"); } });
const md = t => DOMPurify.sanitize(marked.parse(t), PURIFY);
// Page links from the file: http(s) only.
const safeUrl = u => /^https?:\/\//i.test(String(u)) ? u : "";
const pageLinks = urls => (urls || []).filter(safeUrl).map(u => `<a href="${esc(u)}" target="_blank" rel="noopener noreferrer" title="${esc(u)}">${esc(linkPath(u))} ↗</a>`).join("");

function linkPath(u) {
  try { const x = new URL(u); return (x.pathname === "/" ? x.hostname.replace(/^www\./, "") : x.pathname).replace(/\/$/, ""); } catch { return u; }
}
function leadRow(l, tag) {
  const links = pageLinks(l.pages);
  const more = l.more_pages ? `<span class="more">+${l.more_pages} more in the workbook</span>` : "";
  const seen = l.last_seen ? ` · last seen ${esc(l.last_seen)}` : "";
  return `<div class="lead"><div><div class="acct">${esc(l.account)}</div>${tag}</div>
    <div><b>${esc(l.name ? l.name + " · " : "")}${esc(l.title)}</b>
    <div class="why">${esc(l.persona)} · ${l.visits} visit${l.visits === 1 ? "" : "s"}${seen}</div>
    ${links || more ? `<div class="pg">${links}${more}</div>` : ""}</div></div>`;
}
const leadTag = l => `<span class="${l.tier === 1 ? "tagy" : "tagn"}">TIER ${l.tier}</span>`;

// The agreed lead check: top N per account by tier, account notes, what was left out.
function checkLead(l) {
  const links = pageLinks(l.pages);
  const more = l.more_pages ? `<span class="more">+${l.more_pages} more in the workbook</span>` : "";
  const flags = (l.flags || "").split(", ").filter(Boolean).map(f => `<span class="tagw">${esc(f)}</span>`).join(" ");
  const icp = l.icp ? `<span class="tagn">${esc(l.icp)}</span>` : "";
  return `<div><b>${esc(l.name ? l.name + " · " : "")}${esc(l.title)}</b> ${icp} ${flags}
    <div class="why">Why: ${esc(l.why)} · ${esc(l.country)}${l.last_seen ? " · last seen " + esc(l.last_seen) : ""}</div>
    ${links || more ? `<div class="pg">${links}${more}</div>` : ""}
    <div class="nx"><b>Next:</b> ${esc(l.next_step)}</div></div>`;
}
function checkAccount(a) {
  const tag = a.account_type === "new logo" ? `<span class="tagw">NEW LOGO</span>` : `<span class="tagy">YES</span>`;
  const extra = a.yes_total > a.leads.length ? `<div class="quiet">+${a.yes_total - a.leads.length} more from ${esc(a.account)} in the workbook</div>` : "";
  return `<div class="lead"><div><div class="acct">${esc(a.account)}</div>${tag}</div>
    <div>${a.leads.map(checkLead).join(`<div style="height:6px"></div>`)}${extra}</div></div>`;
}
function checkNote(n) {
  const links = pageLinks(n.pages);
  const what = [n.solution_page_visits ? `${n.solution_page_visits} solution-page visit${n.solution_page_visits > 1 ? "s" : ""}` : "",
                n.contact_us_visits ? `${n.contact_us_visits} Contact Us` : ""].filter(Boolean).join(" · ");
  return `<div class="lead"><div><div class="acct">${esc(n.account)}</div><span class="tagn">ACCOUNT NOTE</span></div>
    <div><b>${esc(what)}</b>, no person identified ${n.icp ? `<span class="tagn">${esc(n.icp)}</span>` : ""}<div class="why">${esc(n.countries)} · last seen ${esc(n.last_seen)}</div>
    ${links ? `<div class="pg">${links}</div>` : ""}<div class="nx"><b>Next:</b> ${esc(n.next_step)}</div></div></div>`;
}
function leadCheckCard(r) {
  const f = r.file, c = r.counts, N = r.account_notes;
  let h = `<div class="meta">${n(f.rows)} rows · ${n(f.people_identified)} people identified · ${n(f.company_only_rows)} company-only visits · visit window ${esc(f.visit_window)}</div>`;
  h += `<div class="sum">${c.yes ? `${c.yes} lead${c.yes > 1 ? "s" : ""} worth acting on` : "Nothing worth acting on in this file"}${c.account_notes ? ` · ${c.account_notes} account note${c.account_notes > 1 ? "s" : ""}` : ""}</div>`;
  h += `<div class="sec">Tier 1 · Whale &amp; priority existing accounts</div>`;
  for (const a of r.tier_1) h += checkAccount(a);
  for (const x of N.tier_1) h += checkNote(x);
  if (r.quiet_whales.length) h += `<div class="quiet">${r.quiet_whales.map(esc).join(" · ")}: nothing this week</div>`;
  h += `<div class="sec">Tier 2 · Target accounts &amp; new logos</div>`;
  for (const a of r.tier_2) h += checkAccount(a);
  if (!r.tier_2.length) h += `<div class="quiet">No Tier 2 leads this week</div>`;
  if (N.tier_2.length) {
    h += `<div class="subsec">Account notes · no person identified${N.tier_2_total > N.tier_2.length ? ` · top ${N.tier_2.length} of ${n(N.tier_2_total)}` : ""}</div>`;
    for (const x of N.tier_2) h += checkNote(x);
  }
  if (!c.yes) h += `<div class="quiet">A week with nothing worth acting on is a valid result.</div>`;
  const out = Object.entries(r.ruled_out_by_reason).map(([k, v]) => `${esc(k)} ${n(v)}`).join(" · ");
  const left = Object.entries(r.left_out_by_reason).map(([k, v]) => `${esc(k)} ${n(v)}`).join(" · ");
  h += `<div class="sec">Left out</div><div class="quiet">${n(c.no)} people without a strong role, strong interest or a Tier 1/2 account (${left || "none"}).</div>`;
  if (c.ruled_out) h += `<div class="quiet">${n(c.ruled_out)} ruled out: ${out}.</div>`;
  h += `<div class="left"><span>Top ${r.settings.top_n} per account · full list: ${esc(r.workbook_for_download)}</span><button class="dl" data-art="${esc(r.workbook_for_download)}">⬇ Full list (.xlsx)</button></div>`;
  return h;
}

function setFollowups(scored) {
  const f = scored
    ? ["Why isn't anyone from Initech here?", "Show the top 5 per account", "Which leads need a work email?"]
    : ["How do the four checks work?", "What gets ruled out?"];
  $("follow").innerHTML = f.map(q => `<button>${esc(q)}</button>`).join("");
}
$("follow").onclick = e => { if (e.target.tagName === "BUTTON") { msg.value = e.target.textContent; submit(); } };

async function submit() {
  const text = msg.value.trim();
  if (busy || (!text && !pending.length)) return;
  busy = true; send.disabled = true;
  const files = pending; pending = []; renderPending(); msg.value = "";
  userBubble(text, files.map(f => f.name));
  const wait = bubble("typing", files.length ? "Running the four checks<i></i><i></i><i></i>" : "Thinking<i></i><i></i><i></i>");
  try {
    if (!session) await newSession();
    const parts = [];
    if (text) parts.push({text});
    for (const f of files) parts.push({inlineData: {displayName: f.name, mimeType: f.name.endsWith(".csv") ? "text/csv" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", data: await b64(f)}});
    const events = await api("/run", {appName: APP, userId: USER, sessionId: session, newMessage: {role: "user", parts}});
    wait.remove();
    const scored = renderTurn(events);
    setFollowups(scored || !!document.querySelector(".a .dl"));
  } catch (e) {
    wait.remove(); bubble("err", esc(e.message));
    if (e.status === 404) { session = null; history.replaceState(null, "", location.pathname); }
  }
  busy = false; send.disabled = false; msg.focus();
}

send.onclick = submit;
msg.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } });
msg.addEventListener("input", () => { msg.style.height = "auto"; msg.style.height = msg.scrollHeight + "px"; });
$("clip").onclick = () => $("file").click();
$("drop").onclick = () => $("file").click();
$("file").onchange = e => { addFiles(e.target.files); e.target.value = ""; };
const drop = $("drop");
["dragover", "dragenter"].forEach(t => document.addEventListener(t, e => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach(t => document.addEventListener(t, e => { e.preventDefault(); if (t === "drop" || e.target === drop) drop.classList.remove("over"); }));
document.addEventListener("drop", e => addFiles(e.dataTransfer.files));
$("newChat").onclick = async e => { e.preventDefault(); session = null; history.replaceState(null, "", location.pathname); log.innerHTML = `<div class="empty" id="empty">New conversation. Drop a file to start.</div>`; $("follow").innerHTML = ""; $("sessionLbl").textContent = "New conversation"; };
whoami().then(restore).catch(e => bubble("err", esc(e.message)));
window.addEventListener("hashchange", () => location.reload());
