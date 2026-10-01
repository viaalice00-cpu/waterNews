import { useEffect, useMemo, useState } from "react";
import { api, fmtTime, post, todayKst } from "../utils.js";
import { BasinChecks, CategoryTags, Highlight, RegionTags, StepTag } from "./Tags.jsx";

function Message({ m, keywords, fresh }) {
  const cls = ["msg", m.relevant && "relevant", m.categories[0] && `cat-${m.categories[0]}`, fresh && "fresh"]
    .filter(Boolean).join(" ");
  return (
    <article className={cls}>
      <div className="meta">
        <span className="mono">{fmtTime(m.createdAt)}</span>
        <StepTag step={m.step} />
        {m.disasterType && <span className="tag src">{m.disasterType}</span>}
        <CategoryTags categories={m.categories} />
        {m.keywordHits.map((k) => <span key={k} className="tag kw">#{k}</span>)}
        <RegionTags regions={m.regions} />
        <span className="muted">SN {m.sn}</span>
      </div>
      <div className="body"><Highlight text={m.message} words={keywords} /></div>
      <div className="rgn">수신지역: {m.region}</div>
    </article>
  );
}

export default function DisasterTab({ settings, live, status, toast, fresh }) {
  const [mode, setMode] = useState("live");
  const [from, setFrom] = useState(todayKst());
  const [to, setTo] = useState(todayKst());
  const [rgnNm, setRgnNm] = useState("");
  const [range, setRange] = useState(null);       // { items, info } | null
  const [rangeError, setRangeError] = useState("");
  const [loading, setLoading] = useState(false);
  const [basinSel, setBasinSel] = useState(() => new Set());
  const [waterOnly, setWaterOnly] = useState(true);
  const [unmatched, setUnmatched] = useState(false);
  const [q, setQ] = useState("");

  // 설정이 바뀌면 유역 필터를 활성 유역으로 초기화
  useEffect(() => {
    setBasinSel(new Set(settings.basins.filter((b) => b.enabled).map((b) => b.id)));
  }, [settings]);

  const source = mode === "live" ? live : (range?.items || []);
  const items = useMemo(() => source.filter((m) =>
    (unmatched || !basinSel.size || m.regions.some((r) => basinSel.has(r.basinId))) &&
    (!waterOnly || m.relevant) &&
    (!q || m.message.includes(q) || m.region.includes(q))), [source, basinSel, waterOnly, unmatched, q]);

  const search = async () => {
    const params = new URLSearchParams({ from, to, basins: "", includeUnmatched: "1" });
    if (rgnNm.trim()) params.set("rgnNm", rgnNm.trim());
    setLoading(true);
    setRangeError("");
    try {
      const res = await api(`/api/disaster?${params}`);
      setRange({ items: res.items, info: `${res.start} ~ ${res.end} · 수신 ${res.fetched}건` });
    } catch (e) {
      setRange({ items: [], info: "" });
      setRangeError(e.message);
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    await post("/api/live/refresh", { target: "disaster" });
    toast("재난문자", "즉시 조회를 요청했습니다.");
  };

  const st = status?.disaster;
  const info = mode === "live"
    ? `실시간 · 최근 3일 보관분 ${live.length}건 중 ${items.length}건 표시` +
      (st?.lastSuccess ? ` · 마지막 조회 ${fmtTime(st.lastSuccess)}` : "") + (st?.error ? ` · 오류: ${st.error}` : "")
    : range ? `${range.info} · ${items.length}건 표시` : "";

  return (
    <div className="card">
      <div className="card-head">
        <h2>긴급재난문자 <span className="muted small">행정안전부 · 재난안전데이터 공유플랫폼 DSSP-IF-00247</span></h2>
        <button className="btn" onClick={refresh}>즉시 조회</button>
      </div>
      <div className="filters">
        <div className="seg">
          <button className={mode === "live" ? "active" : ""} onClick={() => setMode("live")}>실시간</button>
          <button className={mode === "range" ? "active" : ""} onClick={() => setMode("range")}>기간 조회</button>
        </div>
        {mode === "range" && (
          <div className="row gap wrap">
            <label>시작일 <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
            <label>종료일 <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
            <label>지역명(rgnNm) <input type="text" value={rgnNm} size={14} placeholder="예: 충청남도, 정읍시"
              onChange={(e) => setRgnNm(e.target.value)} /></label>
            <button className="btn primary" disabled={loading} onClick={search}>{loading ? "조회 중…" : "조회"}</button>
          </div>
        )}
        <div className="row gap wrap">
          <span className="muted small">유역</span>
          <BasinChecks basins={settings.basins} selected={basinSel} onChange={setBasinSel} />
        </div>
        <div className="row gap wrap">
          <label className="check"><input type="checkbox" checked={waterOnly} onChange={(e) => setWaterOnly(e.target.checked)} /> 상수도·단수·풍수해 관련만</label>
          <label className="check"><input type="checkbox" checked={unmatched} onChange={(e) => setUnmatched(e.target.checked)} /> 대상 지역 외 포함</label>
          <input type="search" className="grow" placeholder="내용/지역 검색" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <p className="muted small">{info}</p>
      {rangeError && mode === "range" && <div className="error-box">{rangeError}</div>}
      <div className="msg-list">
        {items.length === 0 ? (
          <div className="empty">{mode === "range" && !range ? "기간을 선택하고 조회하세요." : "조건에 맞는 재난문자가 없습니다."}</div>
        ) : items.slice(0, 500).map((m) => (
          <Message key={m.sn} m={m} keywords={[...settings.keywords, ...m.keywordHits]} fresh={fresh.has(m.sn)} />
        ))}
      </div>
    </div>
  );
}
