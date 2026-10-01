"use strict";

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const CAT = { outage: "단수", water_accident: "상수도 사고", flood: "풍수해" };
const SRC = { google: "구글", naver: "네이버" };

const state = {
  settings: null,      // 서버 저장값(마스킹)
  draft: null,         // 환경설정 편집본
  live: [],            // 실시간 재난문자
  scheduled: [],       // 예약 조회 뉴스
  status: null,
  dMode: "live",
  rangeItems: null,
  dBasins: null,
  nBasins: null,
  newsKeywords: [],    // [{text, on, temp}]
  newsResult: null,
  fresh: new Set(),
  unseen: 0,
  tab: "dashboard",
};

// ------------------------------------------------------------------ 유틸
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pad = (n) => String(n).padStart(2, "0");
const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
const nowKst = () => new Date(Date.now() + (9 * 60 + new Date().getTimezoneOffset()) * 60000);
const todayKst = () => ymd(nowKst());
function fmtTime(iso, withDate = true) {
  if (!iso) return "-";
  const m = iso.match(/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/);
  if (!m) return iso;
  return withDate ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : `${m[4]}:${m[5]}`;
}
function highlight(text, words) {
  let html = esc(text);
  const list = [...new Set(words.filter(Boolean))].sort((a, b) => b.length - a.length).map(esc);
  if (!list.length) return html;
  const re = new RegExp(`(${list.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return html.replace(re, "<mark>$1</mark>");
}
const catTags = (cats) => (cats || []).map((c) => `<span class="tag ${c}">${CAT[c] || c}</span>`).join(" ");
function regionTags(regions, max = 4) {
  const byBasin = {};
  for (const r of regions || []) (byBasin[r.basin] ||= []).push(r.region);
  const parts = Object.entries(byBasin).map(([b, rs]) => `<span class="tag region" title="${esc(rs.join(", "))}">${esc(b)} · ${esc(rs.slice(0, 2).join(", "))}${rs.length > 2 ? ` 외 ${rs.length - 2}` : ""}</span>`);
  return parts.slice(0, max).join(" ");
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function toast(title, body, { alert = false, onClick } = {}) {
  const el = document.createElement("div");
  el.className = `toast${alert ? " alert" : ""}`;
  el.innerHTML = `<strong>${esc(title)}</strong>${esc(body).slice(0, 200)}`;
  el.onclick = () => { el.remove(); onClick && onClick(); };
  $("#toasts").prepend(el);
  setTimeout(() => el.remove(), alert ? 15000 : 5000);
  while ($("#toasts").children.length > 5) $("#toasts").lastChild.remove();
}

let audioCtx;
function beep() {
  try {
    audioCtx ||= new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = 880; g.gain.value = 0.06;
    o.connect(g).connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + 0.25);
  } catch (_) { /* 오디오 미지원 */ }
}
function notify(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    try { new Notification(title, { body, tag: title + body.slice(0, 20) }); } catch (_) { /* 무시 */ }
  }
}
document.addEventListener("click", () => {
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
}, { once: true });

// ------------------------------------------------------------------ 탭
function showTab(name) {
  state.tab = name;
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "disaster") { state.unseen = 0; updateUnseen(); }
}
$$(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
function updateUnseen() {
  const p = $("#newCount");
  p.hidden = state.unseen === 0;
  p.textContent = state.unseen;
}

// ------------------------------------------------------------------ 공통 상태
const basins = () => state.settings?.basins || [];
const enabledIds = () => new Set(basins().filter((b) => b.enabled).map((b) => b.id));

function renderHeader() {
  const s = state.settings;
  $("#demoBadge").hidden = !s?.demo;
  const on = basins().filter((b) => b.enabled).map((b) => b.name);
  $("#targetSummary").textContent = on.length ? `타겟: ${on.join(", ")}` : "타겟 유역 없음(전국)";
}
setInterval(() => {
  const d = nowKst();
  $("#clock").textContent = `${ymd(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())} KST`;
}, 1000);

// ------------------------------------------------------------------ 대시보드
function targetedToday() {
  const today = todayKst();
  const ids = enabledIds();
  return state.live.filter((m) => (m.createdAt || "").startsWith(today) &&
    (!ids.size || m.regions.some((r) => ids.has(r.basinId))));
}

function renderDashboard() {
  const s = state.settings;
  const notice = $("#setupNotice");
  const missing = [];
  if (s && !s.safetydata.serviceKeySet) missing.push("재난문자 포털 인증키");
  if (s && !s.naver.clientIdSet) missing.push("네이버 검색 API 키");
  notice.hidden = !missing.length;
  notice.innerHTML = missing.length ? `${esc(missing.join(", "))}가 설정되지 않았습니다. <a data-goto="settings">환경설정</a>에서 입력하세요. (구글 뉴스는 키 없이 조회됩니다)` : "";

  const today = targetedToday();
  const water = today.filter((m) => m.relevant);
  const outage = water.filter((m) => m.categories.includes("outage")).length +
    state.scheduled.filter((n) => n.categories.includes("outage")).length;
  $("#kpiDisaster").textContent = today.length;
  $("#kpiDisasterWater").textContent = water.length;
  $("#kpiOutage").textContent = outage;
  $("#kpiNews").textContent = s?.news.scheduleEnabled ? state.scheduled.length : "꺼짐";

  // 유역별 집계
  const rows = basins().filter((b) => b.enabled);
  const allItems = [...water, ...state.scheduled.filter((n) => n.categories.length)];
  const tbody = $("#basinTable tbody");
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="muted">환경설정에서 타겟 유역을 선택하세요.</td></tr>`;
  } else {
    tbody.innerHTML = rows.map((b) => {
      const mine = allItems.filter((it) => it.regions.some((r) => r.basinId === b.id));
      const c = (k) => mine.filter((it) => it.categories.includes(k)).length;
      return `<tr><td>${esc(b.name)}</td><td>${c("outage")}</td><td>${c("water_accident")}</td><td>${c("flood")}</td><td><strong>${mine.length}</strong></td></tr>`;
    }).join("");
  }

  // 피드
  const feed = [
    ...water.map((m) => ({ kind: "문자", time: m.createdAt, cats: m.categories, regions: m.regions, text: m.message, sub: m.region, step: m.step })),
    ...state.scheduled.filter((n) => n.categories.length).map((n) => ({ kind: "뉴스", time: n.publishedAt, cats: n.categories, regions: n.regions, text: n.title, sub: n.press, link: n.link })),
  ].sort((a, b) => (b.time || "").localeCompare(a.time || "")).slice(0, 50);
  $("#feed").innerHTML = feed.length ? feed.map((f) => `
    <li>
      <div class="meta"><span class="tag src">${f.kind}</span><span class="mono">${fmtTime(f.time)}</span>${f.step ? `<span class="tag step-${esc(f.step)}">${esc(f.step)}</span>` : ""}${catTags(f.cats)} ${regionTags(f.regions, 2)}</div>
      <div>${f.link ? `<a href="${esc(f.link)}" target="_blank" rel="noopener">${esc(f.text)}</a>` : esc(f.text)}</div>
      <div class="desc">${esc(f.sub)}</div>
    </li>`).join("") : `<li class="empty">감지된 항목이 없습니다.</li>`;

  renderStatus();
}

function renderStatus() {
  const st = state.status;
  if (!st) return;
  const d = st.disaster, n = st.news;
  const dState = !d.keySet ? "인증키 미설정" : !d.enabled ? "중지됨" : d.error ? "오류" : "정상";
  $("#statusList").innerHTML = `
    <dt>재난문자</dt><dd>${dState} · ${d.intervalSec}초 주기 · 보관 ${d.liveCount}건</dd>
    <dt>마지막 조회</dt><dd class="mono">${fmtTime(d.lastSuccess)} (다음 ${fmtTime(d.nextPoll, false)})</dd>
    ${d.error ? `<dt>오류</dt><dd class="err">${esc(d.error)}</dd>` : ""}
    <dt>예약 뉴스</dt><dd>${n.enabled ? `${n.intervalMin}분 주기 · ${n.count}건 · 마지막 ${fmtTime(n.lastRun)}` : "꺼짐"}</dd>
    ${n.error ? `<dt>뉴스 경고</dt><dd class="err">${esc(n.error)}</dd>` : ""}`;
}

document.addEventListener("click", (e) => {
  const g = e.target.closest("[data-goto]");
  if (g) showTab(g.dataset.goto);
});
$("#btnRefreshAll").onclick = async () => {
  await api("/api/live/refresh", { method: "POST", body: JSON.stringify({ target: "all" }) });
  toast("갱신 요청", "재난문자·예약 뉴스를 다시 조회합니다.");
};

// ------------------------------------------------------------------ 재난문자 탭
function basinChecks(container, selected, onChange) {
  container.innerHTML = basins().map((b) => `<label class="check"><input type="checkbox" value="${esc(b.id)}" ${selected.has(b.id) ? "checked" : ""}> ${esc(b.name)}</label>`).join("") || `<span class="muted small">유역 없음</span>`;
  $$("input", container).forEach((i) => (i.onchange = () => {
    i.checked ? selected.add(i.value) : selected.delete(i.value);
    onChange();
  }));
}

function renderDisaster() {
  const src = state.dMode === "live" ? state.live : (state.rangeItems || []);
  const sel = state.dBasins;
  const waterOnly = $("#dWaterOnly").checked;
  const unmatched = $("#dUnmatched").checked;
  const q = $("#dText").value.trim();
  const items = src.filter((m) =>
    (unmatched || !sel.size || m.regions.some((r) => sel.has(r.basinId))) &&
    (!waterOnly || m.relevant) &&
    (!q || m.message.includes(q) || m.region.includes(q)));
  const kw = state.settings?.keywords || [];
  if (state.dMode === "live") {
    const st = state.status?.disaster;
    $("#dInfo").textContent = `실시간 · 최근 ${3}일 보관분 ${src.length}건 중 ${items.length}건 표시` + (st?.lastSuccess ? ` · 마지막 조회 ${fmtTime(st.lastSuccess)}` : "") + (st?.error ? ` · 오류: ${st.error}` : "");
  }
  $("#dList").innerHTML = items.length ? items.slice(0, 500).map((m) => {
    const cls = ["msg", m.relevant ? "relevant" : "", m.categories[0] ? `cat-${m.categories[0]}` : "", state.fresh.has(m.sn) ? "fresh" : ""].join(" ");
    return `<article class="${cls}">
      <div class="meta">
        <span class="mono">${fmtTime(m.createdAt)}</span>
        ${m.step ? `<span class="tag step-${esc(m.step)}">${esc(m.step)}</span>` : ""}
        ${m.disasterType ? `<span class="tag src">${esc(m.disasterType)}</span>` : ""}
        ${catTags(m.categories)}
        ${m.keywordHits.map((k) => `<span class="tag kw">#${esc(k)}</span>`).join(" ")}
        ${regionTags(m.regions)}
        <span class="muted">SN ${esc(m.sn)}</span>
      </div>
      <div class="body">${highlight(m.message, [...kw, ...m.keywordHits])}</div>
      <div class="rgn">수신지역: ${esc(m.region)}</div>
    </article>`;
  }).join("") : `<div class="empty">${state.dMode === "range" && !state.rangeItems ? "기간을 선택하고 조회하세요." : "조건에 맞는 재난문자가 없습니다."}</div>`;
}

$$("#dMode button").forEach((b) => (b.onclick = () => {
  state.dMode = b.dataset.mode;
  $$("#dMode button").forEach((x) => x.classList.toggle("active", x === b));
  $("#dRange").hidden = state.dMode !== "range";
  if (state.dMode === "range") $("#dInfo").textContent = state.rangeItems ? $("#dInfo").textContent : "";
  renderDisaster();
}));
["#dWaterOnly", "#dUnmatched"].forEach((s) => ($(s).onchange = renderDisaster));
$("#dText").oninput = renderDisaster;
$("#btnLiveRefresh").onclick = async () => {
  await api("/api/live/refresh", { method: "POST", body: JSON.stringify({ target: "disaster" }) });
  toast("재난문자", "즉시 조회를 요청했습니다.");
};
$("#btnDSearch").onclick = async () => {
  const params = new URLSearchParams({ from: $("#dFrom").value, to: $("#dTo").value, basins: "", includeUnmatched: "1" });
  if ($("#dRgn").value.trim()) params.set("rgnNm", $("#dRgn").value.trim());
  const btn = $("#btnDSearch");
  btn.disabled = true; $("#dInfo").textContent = "조회 중…";
  try {
    const res = await api(`/api/disaster?${params}`);
    state.rangeItems = res.items;
    $("#dInfo").textContent = `${res.start} ~ ${res.end} · 수신 ${res.fetched}건`;
  } catch (e) {
    state.rangeItems = [];
    $("#dInfo").innerHTML = `<span class="error-box">${esc(e.message)}</span>`;
  } finally { btn.disabled = false; renderDisaster(); }
};

// ------------------------------------------------------------------ 뉴스 탭
function renderNewsKeywords() {
  $("#nKeywords").innerHTML = state.newsKeywords.map((k, i) => `
    <span class="chip toggle ${k.on ? "" : "off"}" data-i="${i}" title="클릭하여 선택/해제">${k.on ? "✓ " : ""}${esc(k.text)}${k.temp ? `<button type="button" data-del="${i}" aria-label="삭제">×</button>` : ""}</span>`).join("");
}
$("#nKeywords").onclick = (e) => {
  const del = e.target.closest("[data-del]");
  if (del) { state.newsKeywords.splice(+del.dataset.del, 1); return renderNewsKeywords(); }
  const chip = e.target.closest("[data-i]");
  if (chip) { const k = state.newsKeywords[+chip.dataset.i]; k.on = !k.on; renderNewsKeywords(); }
};
$("#nKeywordAdd").onkeydown = (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();
  for (const t of e.target.value.split(",").map((x) => x.trim()).filter(Boolean)) {
    const ex = state.newsKeywords.find((k) => k.text === t);
    if (ex) ex.on = true; else state.newsKeywords.push({ text: t, on: true, temp: true });
  }
  e.target.value = "";
  renderNewsKeywords();
};
$$("#nQuick button").forEach((b) => (b.onclick = () => {
  const today = new Date(todayKst() + "T00:00");
  $("#nFrom").value = ymd(addDays(today, -Number(b.dataset.days)));
  $("#nTo").value = ymd(today);
}));

function newsFiltered() {
  const items = state.newsResult?.items || [];
  return $("#nWaterOnly").checked ? items.filter((n) => n.categories.length) : items;
}
function renderNews() {
  const res = state.newsResult;
  const items = newsFiltered();
  $("#btnNewsCsv").disabled = !items.length;
  if (!res) return;
  $("#nInfo").textContent = `${res.start} ~ ${res.end} · 키워드 ${res.keywords.join(", ")} · 요청 ${res.requestCount}회 · 수집 ${res.rawCount}건 → 표시 ${items.length}건`;
  $("#nErrors").innerHTML = res.errors.map((e) => `<div class="error-box">${esc(e)}</div>`).join("");
  const kws = res.keywords;
  $("#newsTable tbody").innerHTML = items.length ? items.map((n) => `
    <tr>
      <td class="mono">${fmtTime(n.publishedAt)}</td>
      <td class="title-cell"><a href="${esc(n.link)}" target="_blank" rel="noopener">${highlight(n.title, kws)}</a>
        ${n.description ? `<div class="desc">${highlight(n.description, kws)}</div>` : ""}</td>
      <td>${catTags(n.categories) || `<span class="muted small">-</span>`}</td>
      <td>${regionTags(n.regions, 3) || `<span class="muted small">지역 미확인</span>`}</td>
      <td><div>${esc(n.press)}</div>${n.sources.map((s) => `<span class="tag src">${SRC[s] || s}</span>`).join(" ")}</td>
    </tr>`).join("") : `<tr><td colspan="5" class="empty">검색 결과가 없습니다.</td></tr>`;
}
$("#nWaterOnly").onchange = renderNews;

$("#newsForm").onsubmit = async (e) => {
  e.preventDefault();
  const keywords = state.newsKeywords.filter((k) => k.on).map((k) => k.text);
  if (!keywords.length) return toast("뉴스 조회", "키워드를 1개 이상 선택하세요.", { alert: true });
  const sources = $$("input[name=src]:checked").map((i) => i.value);
  if (!sources.length) return toast("뉴스 조회", "구글 또는 네이버를 선택하세요.", { alert: true });
  const params = new URLSearchParams({
    keywords: keywords.join(","), from: $("#nFrom").value, to: $("#nTo").value,
    sources: sources.join(","), basins: [...state.nBasins].join(","),
    regionInQuery: $("#nRegionQuery").checked ? "1" : "0",
    includeUnmatched: $("#nUnmatched").checked ? "1" : "0",
  });
  const btn = $("#btnNews");
  btn.disabled = true; btn.textContent = "조회 중…";
  $("#nInfo").textContent = "구글·네이버 뉴스를 조회하고 있습니다…";
  try {
    state.newsResult = await api(`/api/news?${params}`);
    renderNews();
  } catch (err) {
    $("#nErrors").innerHTML = `<div class="error-box">${esc(err.message)}</div>`;
    $("#nInfo").textContent = "";
  } finally { btn.disabled = false; btn.textContent = "조회"; }
};

$("#btnNewsCsv").onclick = () => {
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const rows = [["일시", "제목", "언론사", "분류", "유역", "지자체", "출처", "검색어", "링크"]];
  for (const n of newsFiltered()) {
    rows.push([n.publishedAt, n.title, n.press, n.categories.map((c) => CAT[c]).join("/"),
      [...new Set(n.regions.map((r) => r.basin))].join("/"), n.regions.map((r) => r.region).join("/"),
      n.sources.map((s) => SRC[s]).join("/"), n.queries.join("/"), n.link]);
  }
  const blob = new Blob(["﻿" + rows.map((r) => r.map(cell).join(",")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `뉴스모니터링_${state.newsResult.start}_${state.newsResult.end}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
};

// ------------------------------------------------------------------ 환경설정 탭
function fillSettings() {
  const s = state.draft;
  const sd = s.safetydata, nv = s.naver, ns = s.news;
  $("#sKey").value = ""; $("#nvId").value = ""; $("#nvSecret").value = "";
  $("#sKey").placeholder = sd.serviceKeySet ? "설정됨 (변경 시에만 입력)" : "미설정";
  $("#sKeyState").textContent = sd.serviceKeySet ? `저장된 키: ${sd.serviceKeyHint}` : "저장된 키 없음";
  $("#nvId").placeholder = nv.clientIdSet ? "설정됨 (변경 시에만 입력)" : "미설정";
  $("#nvIdState").textContent = nv.clientIdSet ? `저장됨: ${nv.clientIdHint}` : "";
  $("#nvSecret").placeholder = nv.clientSecretSet ? "설정됨 (변경 시에만 입력)" : "미설정";
  $("#nvSecretState").textContent = nv.clientSecretSet ? `저장됨: ${nv.clientSecretHint}` : "";
  $("#sUrl").value = sd.apiUrl; $("#sRows").value = sd.numOfRows; $("#sPages").value = sd.maxPages;
  $("#sRgn").value = sd.rgnNm; $("#sSsl").checked = sd.verifySsl; $("#sPoll").checked = sd.pollEnabled;
  $("#sInterval").value = sd.pollIntervalSec; $("#sWaterOnly").checked = s.alerts.waterOnly;
  $("#nsEnabled").checked = ns.scheduleEnabled; $("#nsInterval").value = ns.scheduleIntervalMin;
  $("#nsLookback").value = ns.scheduleLookbackHours; $("#nsNaverPages").value = ns.naverMaxPages;
  $("#nsGoogle").checked = ns.sources.includes("google"); $("#nsNaver").checked = ns.sources.includes("naver");
  $("#nsRegionQuery").checked = ns.regionInQuery;
  renderKeywordEditor();
  renderBasinEditor();
  $("#saveState").textContent = "";
}

function dirty() { $("#saveState").textContent = "저장되지 않은 변경사항이 있습니다."; }
$("#settingsForm").addEventListener("input", dirty);

function renderKeywordEditor() {
  $("#kwChips").innerHTML = state.draft.keywords.map((k, i) => `<span class="chip">${esc(k)}<button type="button" data-kw="${i}" aria-label="${esc(k)} 삭제">×</button></span>`).join("") || `<span class="muted small">키워드 없음</span>`;
}
$("#kwChips").onclick = (e) => {
  const b = e.target.closest("[data-kw]");
  if (!b) return;
  state.draft.keywords.splice(+b.dataset.kw, 1);
  renderKeywordEditor(); dirty();
};
function addKeywords() {
  const input = $("#kwAdd");
  for (const t of input.value.split(",").map((x) => x.trim()).filter(Boolean)) {
    if (!state.draft.keywords.includes(t)) state.draft.keywords.push(t);
  }
  input.value = "";
  renderKeywordEditor(); dirty();
}
$("#btnKwAdd").onclick = addKeywords;
$("#kwAdd").onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); addKeywords(); } };

function renderBasinEditor() {
  $("#basinEditor").innerHTML = state.draft.basins.map((b, i) => `
    <div class="basin ${b.enabled ? "on" : ""}" data-b="${i}">
      <div class="basin-head">
        <input type="checkbox" data-act="toggle" ${b.enabled ? "checked" : ""} title="타겟 사용">
        <input type="text" data-act="name" value="${esc(b.name)}" class="grow">
        <span class="muted small">${b.regions.length}곳</span>
        <button type="button" class="btn small danger" data-act="remove">유역 삭제</button>
      </div>
      <div class="chips">${b.regions.map((r, j) => `<span class="chip">${esc(r)}<button type="button" data-act="rm-region" data-r="${j}" aria-label="${esc(r)} 삭제">×</button></span>`).join("") || `<span class="muted small">지자체 없음</span>`}</div>
      <div class="row gap">
        <input type="text" data-act="region-input" class="grow" placeholder="지자체 추가 (예: 정읍시, 완주군) — 쉼표로 여러 개">
        <button type="button" class="btn small" data-act="add-region">추가</button>
      </div>
    </div>`).join("") || `<div class="empty">등록된 유역이 없습니다.</div>`;
}
function addRegions(i, box) {
  const input = $("[data-act=region-input]", box);
  const b = state.draft.basins[i];
  for (const t of input.value.split(/[,\n]/).map((x) => x.trim()).filter(Boolean)) {
    if (!b.regions.includes(t)) b.regions.push(t);
  }
  renderBasinEditor(); dirty();
  $(`[data-b="${i}"] [data-act=region-input]`).focus();
}
$("#basinEditor").addEventListener("click", (e) => {
  const box = e.target.closest("[data-b]");
  if (!box) return;
  const i = +box.dataset.b, act = e.target.dataset.act, b = state.draft.basins[i];
  if (act === "remove") {
    if (confirm(`'${b.name}' 유역을 삭제할까요?`)) { state.draft.basins.splice(i, 1); renderBasinEditor(); dirty(); }
  } else if (act === "rm-region") {
    b.regions.splice(+e.target.dataset.r, 1); renderBasinEditor(); dirty();
  } else if (act === "add-region") {
    addRegions(i, box);
  }
});
$("#basinEditor").addEventListener("change", (e) => {
  const box = e.target.closest("[data-b]");
  if (!box) return;
  const b = state.draft.basins[+box.dataset.b];
  if (e.target.dataset.act === "toggle") { b.enabled = e.target.checked; box.classList.toggle("on", b.enabled); }
  if (e.target.dataset.act === "name") b.name = e.target.value.trim() || b.name;
});
$("#basinEditor").addEventListener("keydown", (e) => {
  if (e.target.dataset.act === "region-input" && e.key === "Enter") {
    e.preventDefault();
    const box = e.target.closest("[data-b]");
    addRegions(+box.dataset.b, box);
  }
});
$("#btnBasinAdd").onclick = () => {
  const name = $("#basinNew").value.trim();
  if (!name) return $("#basinNew").focus();
  state.draft.basins.push({ id: "", name, enabled: true, regions: [] });
  $("#basinNew").value = "";
  renderBasinEditor(); dirty();
};

$("#btnKeyToggle").onclick = () => {
  const i = $("#sKey");
  i.type = i.type === "password" ? "text" : "password";
  $("#btnKeyToggle").textContent = i.type === "password" ? "표시" : "숨김";
};
$("#btnKeyTest").onclick = async () => {
  const out = $("#keyTestResult");
  out.textContent = "연결 확인 중…";
  try {
    const r = await api("/api/disaster/test", { method: "POST", body: JSON.stringify({ serviceKey: $("#sKey").value.trim() }) });
    out.innerHTML = r.ok
      ? `<span style="color:var(--ok)">✔ ${esc(r.message)}</span>${(r.sample || []).map((m) => `<div class="desc">${fmtTime(m.createdAt)} ${esc(m.region)} — ${esc(m.message.slice(0, 60))}</div>`).join("")}`
      : `<div class="error-box">✖ ${esc(r.message)}</div>`;
  } catch (e) { out.innerHTML = `<div class="error-box">${esc(e.message)}</div>`; }
};
$$("[data-clear]").forEach((b) => (b.onclick = async () => {
  if (!confirm("저장된 인증키를 삭제할까요?")) return;
  await saveSettings({ clearSecrets: b.dataset.clear.split(",") });
}));
$("#btnReset").onclick = () => { state.draft = structuredClone(state.settings); fillSettings(); };

function collectSettings() {
  const num = (s) => Number($(s).value);
  const payload = {
    safetydata: {
      apiUrl: $("#sUrl").value.trim(), numOfRows: num("#sRows"), maxPages: num("#sPages"),
      rgnNm: $("#sRgn").value.trim(), verifySsl: $("#sSsl").checked, pollEnabled: $("#sPoll").checked,
      pollIntervalSec: num("#sInterval"),
    },
    naver: {},
    news: {
      scheduleEnabled: $("#nsEnabled").checked, scheduleIntervalMin: num("#nsInterval"),
      scheduleLookbackHours: num("#nsLookback"), naverMaxPages: num("#nsNaverPages"),
      sources: [$("#nsGoogle").checked && "google", $("#nsNaver").checked && "naver"].filter(Boolean),
      regionInQuery: $("#nsRegionQuery").checked,
    },
    alerts: { waterOnly: $("#sWaterOnly").checked },
    keywords: state.draft.keywords,
    basins: state.draft.basins,
  };
  if ($("#sKey").value.trim()) payload.safetydata.serviceKey = $("#sKey").value.trim();
  if ($("#nvId").value.trim()) payload.naver.clientId = $("#nvId").value.trim();
  if ($("#nvSecret").value.trim()) payload.naver.clientSecret = $("#nvSecret").value.trim();
  return payload;
}
async function saveSettings(payload) {
  try {
    const s = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
    applySettings(s);
    toast("환경설정", "저장되었습니다.");
    loadLive();
  } catch (e) {
    toast("환경설정 저장 실패", e.message, { alert: true });
  }
}
$("#settingsForm").onsubmit = (e) => { e.preventDefault(); saveSettings(collectSettings()); };

function applySettings(s) {
  state.settings = s;
  state.draft = structuredClone(s);
  const ids = enabledIds();
  state.dBasins = new Set(ids);
  state.nBasins = new Set(ids);
  basinChecks($("#dBasins"), state.dBasins, renderDisaster);
  basinChecks($("#nBasins"), state.nBasins, () => {});
  const temp = state.newsKeywords.filter((k) => k.temp);
  state.newsKeywords = [...s.keywords.map((t) => ({ text: t, on: true })), ...temp.filter((k) => !s.keywords.includes(k.text))];
  $("#nRegionQuery").checked = s.news.regionInQuery;
  renderNewsKeywords();
  fillSettings();
  renderHeader();
  renderDashboard();
  renderDisaster();
}

// ------------------------------------------------------------------ 데이터 로드 / 실시간
async function loadLive() {
  try {
    const [live, sched] = await Promise.all([api("/api/live"), api("/api/news/scheduled")]);
    state.live = live.items;
    state.scheduled = sched.items;
    state.status = live.status;
    renderDashboard();
    renderDisaster();
  } catch (e) { console.warn(e); }
}

function connectEvents() {
  const es = new EventSource("/api/events");
  const sse = $("#sseState");
  es.onopen = () => { sse.className = "dot on"; sse.textContent = "실시간 연결됨"; };
  es.onerror = () => { sse.className = "dot off"; sse.textContent = "재연결 중…"; };
  es.addEventListener("status", (e) => {
    state.status = JSON.parse(e.data);
    renderStatus();
    if (state.dMode === "live") renderDisaster();
  });
  es.addEventListener("disaster", (e) => {
    const { items } = JSON.parse(e.data);
    const known = new Set(state.live.map((m) => m.sn));
    const added = items.filter((m) => !known.has(m.sn));
    if (!added.length) return;
    state.live = [...added, ...state.live].sort((a, b) => (b.createdAt || "").localeCompare(a.createdAt || ""));
    added.forEach((m) => state.fresh.add(m.sn));
    setTimeout(() => added.forEach((m) => state.fresh.delete(m.sn)), 3000);
    const alerts = added.filter((m) => m.alert);
    if (alerts.length) {
      beep();
      for (const m of alerts.slice(0, 3)) {
        const title = `[재난문자] ${m.categories.map((c) => CAT[c]).join("·") || m.disasterType || "신규"} — ${m.regions[0]?.region || m.region}`;
        toast(title, m.message, { alert: true, onClick: () => showTab("disaster") });
        notify(title, m.message);
      }
      if (state.tab !== "disaster") { state.unseen += alerts.length; updateUnseen(); }
    }
    renderDashboard();
    renderDisaster();
  });
  es.addEventListener("news", (e) => {
    const { items } = JSON.parse(e.data);
    const known = new Set(state.scheduled.map((n) => n.id));
    const added = items.filter((n) => !known.has(n.id));
    state.scheduled = [...added, ...state.scheduled].sort((a, b) => (b.publishedAt || "").localeCompare(a.publishedAt || ""));
    for (const n of added.filter((x) => x.categories.length).slice(0, 3)) {
      const title = `[뉴스] ${n.categories.map((c) => CAT[c]).join("·")} — ${n.regions[0]?.region || ""}`;
      toast(title, n.title, { alert: true, onClick: () => window.open(n.link, "_blank", "noopener") });
      notify(title, n.title);
    }
    renderDashboard();
  });
}

(async function init() {
  const today = todayKst();
  $("#dFrom").value = today; $("#dTo").value = today;
  $("#nFrom").value = ymd(addDays(new Date(today + "T00:00"), -6)); $("#nTo").value = today;
  try {
    applySettings(await api("/api/settings"));
  } catch (e) {
    toast("서버 연결 실패", e.message, { alert: true });
    return;
  }
  await loadLive();
  connectEvents();
})();
