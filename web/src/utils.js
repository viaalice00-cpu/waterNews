export const CAT = { outage: "단수", water_accident: "상수도 사고", flood: "풍수해" };
export const SRC = { google: "구글", naver: "네이버" };

const pad = (n) => String(n).padStart(2, "0");
export const ymd = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const addDays = (d, n) => { const x = new Date(d); x.setDate(x.getDate() + n); return x; };
/** 브라우저 시간대와 무관하게 한국시간(KST) 기준 Date */
export const nowKst = () => new Date(Date.now() + (9 * 60 + new Date().getTimezoneOffset()) * 60000);
export const todayKst = () => ymd(nowKst());
export const daysAgo = (n) => ymd(addDays(new Date(todayKst() + "T00:00"), -n));
export const clockText = () => {
  const d = nowKst();
  return `${ymd(d)} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())} KST`;
};

export function fmtTime(iso, withDate = true) {
  if (!iso) return "-";
  const m = iso.match(/^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d)/);
  if (!m) return iso;
  return withDate ? `${m[2]}-${m[3]} ${m[4]}:${m[5]}` : `${m[4]}:${m[5]}`;
}

export const byTimeDesc = (key) => (a, b) => (b[key] || "").localeCompare(a[key] || "");
export const splitList = (text) => text.split(/[,\n]/).map((x) => x.trim()).filter(Boolean);

export async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}
export const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body ?? {}) });

let audioCtx;
export function beep() {
  try {
    audioCtx ||= new (window.AudioContext || window.webkitAudioContext)();
    const o = audioCtx.createOscillator(), g = audioCtx.createGain();
    o.frequency.value = 880; g.gain.value = 0.06;
    o.connect(g).connect(audioCtx.destination);
    o.start(); o.stop(audioCtx.currentTime + 0.25);
  } catch { /* 오디오 미지원 */ }
}
export function notify(title, body) {
  if ("Notification" in window && Notification.permission === "granted") {
    try { new Notification(title, { body, tag: title + body.slice(0, 20) }); } catch { /* 무시 */ }
  }
}

export function downloadCsv(filename, rows) {
  const cell = (v) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const blob = new Blob(["﻿" + rows.map((r) => r.map(cell).join(",")).join("\r\n")],
    { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
