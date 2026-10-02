import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import AnalysisTab from "./components/AnalysisTab.jsx";
import Dashboard from "./components/Dashboard.jsx";
import DisasterTab from "./components/DisasterTab.jsx";
import NewsTab from "./components/NewsTab.jsx";
import SettingsTab from "./components/SettingsTab.jsx";
import { CAT, api, beep, byTimeDesc, clockText, notify } from "./utils.js";

const TABS = [
  { id: "dashboard", label: "대시보드" },
  { id: "analysis", label: "사고 분석" },
  { id: "disaster", label: "재난문자" },
  { id: "news", label: "뉴스 조회" },
  { id: "settings", label: "환경설정" },
];

function Clock() {
  const [now, setNow] = useState(clockText());
  useEffect(() => {
    const t = setInterval(() => setNow(clockText()), 1000);
    return () => clearInterval(t);
  }, []);
  return <span className="muted mono">{now}</span>;
}

function Toasts({ toasts, dismiss }) {
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast${t.alert ? " alert" : ""}`}
          onClick={() => { dismiss(t.id); t.onClick?.(); }}>
          <strong>{t.title}</strong>{String(t.body || "").slice(0, 200)}
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [settings, setSettings] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [live, setLive] = useState([]);
  const [scheduled, setScheduled] = useState([]);
  const [status, setStatus] = useState(null);
  const [connected, setConnected] = useState(false);
  const [fresh, setFresh] = useState(() => new Set());
  const [unseen, setUnseen] = useState(0);
  const [toasts, setToasts] = useState([]);
  const tabRef = useRef(tab);
  tabRef.current = tab;

  const dismiss = useCallback((id) => setToasts((ts) => ts.filter((t) => t.id !== id)), []);
  const toast = useCallback((title, body, opts = {}) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((ts) => [{ id, title, body, ...opts }, ...ts].slice(0, 5));
    setTimeout(() => dismiss(id), opts.alert ? 15000 : 5000);
  }, [dismiss]);

  const loadLive = useCallback(async () => {
    try {
      const [l, s] = await Promise.all([api("/api/live"), api("/api/news/scheduled")]);
      setLive(l.items);
      setScheduled(s.items);
      setStatus(l.status);
    } catch (e) {
      console.warn(e);
    }
  }, []);

  // 최초 로드
  useEffect(() => {
    api("/api/settings").then(setSettings).catch((e) => setLoadError(e.message));
    loadLive();
  }, [loadLive]);

  // 첫 클릭 시 브라우저 알림 권한 요청
  useEffect(() => {
    const ask = () => {
      if ("Notification" in window && Notification.permission === "default") Notification.requestPermission();
    };
    document.addEventListener("click", ask, { once: true });
    return () => document.removeEventListener("click", ask);
  }, []);

  // 실시간 이벤트(SSE)
  useEffect(() => {
    const es = new EventSource("/api/events");
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.addEventListener("status", (e) => setStatus(JSON.parse(e.data)));
    es.addEventListener("disaster", (e) => {
      const { items } = JSON.parse(e.data);
      setLive((prev) => {
        const known = new Set(prev.map((m) => m.sn));
        const added = items.filter((m) => !known.has(m.sn));
        return added.length ? [...added, ...prev].sort(byTimeDesc("createdAt")) : prev;
      });
      const sns = items.map((m) => m.sn);
      setFresh((f) => new Set([...f, ...sns]));
      setTimeout(() => setFresh((f) => new Set([...f].filter((sn) => !sns.includes(sn)))), 3000);
      const alerts = items.filter((m) => m.alert);
      if (alerts.length) {
        beep();
        for (const m of alerts.slice(0, 3)) {
          const title = `[재난문자] ${m.categories.map((c) => CAT[c]).join("·") || m.disasterType || "신규"} — ${m.regions[0]?.region || m.region}`;
          toast(title, m.message, { alert: true, onClick: () => setTab("disaster") });
          notify(title, m.message);
        }
        if (tabRef.current !== "disaster") setUnseen((n) => n + alerts.length);
      }
    });
    es.addEventListener("news", (e) => {
      const { items } = JSON.parse(e.data);
      setScheduled((prev) => {
        const known = new Set(prev.map((n) => n.id));
        return [...items.filter((n) => !known.has(n.id)), ...prev].sort(byTimeDesc("publishedAt"));
      });
      for (const n of items.filter((x) => x.categories.length).slice(0, 3)) {
        const title = `[뉴스] ${n.categories.map((c) => CAT[c]).join("·")} — ${n.regions[0]?.region || ""}`;
        toast(title, n.title, { alert: true, onClick: () => window.open(n.link, "_blank", "noopener") });
        notify(title, n.title);
      }
    });
    return () => es.close();
  }, [toast]);

  const goTab = (id) => {
    setTab(id);
    if (id === "disaster") setUnseen(0);
  };

  const enabledBasins = useMemo(() => (settings?.basins || []).filter((b) => b.enabled), [settings]);

  if (loadError) {
    return <main><div className="error-box">서버 연결 실패: {loadError}. Python 서버(python app.py)가 실행 중인지 확인하세요.</div></main>;
  }
  if (!settings) return <main><p className="muted">불러오는 중…</p></main>;

  const shared = { settings, live, scheduled, status, toast, goTab };

  return (
    <>
      <header className="topbar">
        <div className="brand">
          <span className="logo" aria-hidden="true">💧</span>
          <div>
            <h1>유역 상수도·풍수해 모니터링</h1>
            <p className="sub">뉴스(구글·네이버) · 행정안전부 긴급재난문자 실시간</p>
          </div>
        </div>
        <div className="top-status">
          {settings.demo && <span className="badge warn">데모 모드</span>}
          <span className="muted">
            {enabledBasins.length ? `타겟: ${enabledBasins.map((b) => b.name).join(", ")}` : "타겟 유역 없음(전국)"}
          </span>
          <span className={`dot ${connected ? "on" : "off"}`} title="실시간 연결 상태">
            {connected ? "실시간 연결됨" : "재연결 중…"}
          </span>
          <Clock />
        </div>
      </header>

      <nav className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id}
            className={tab === t.id ? "active" : ""} onClick={() => goTab(t.id)}>
            {t.label}
            {t.id === "disaster" && unseen > 0 && <> <span className="pill">{unseen}</span></>}
          </button>
        ))}
      </nav>

      <main>
        {/* 탭 전환 시 조회 결과·입력값이 유지되도록 모두 마운트한 채 숨김 처리 */}
        <section className="tab active" hidden={tab !== "dashboard"}><Dashboard {...shared} /></section>
        <section className="tab active" hidden={tab !== "analysis"}>
          <AnalysisTab {...shared} active={tab === "analysis"} />
        </section>
        <section className="tab active" hidden={tab !== "disaster"}><DisasterTab {...shared} fresh={fresh} /></section>
        <section className="tab active" hidden={tab !== "news"}><NewsTab {...shared} /></section>
        <section className="tab active" hidden={tab !== "settings"}>
          <SettingsTab settings={settings} toast={toast}
            onSaved={(s) => { setSettings(s); loadLive(); }} />
        </section>
      </main>

      <Toasts toasts={toasts} dismiss={dismiss} />
    </>
  );
}
