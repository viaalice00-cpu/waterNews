import { useEffect, useMemo, useState } from "react";
import { CAT, SRC, api, daysAgo, downloadCsv, fmtTime, splitList, todayKst } from "../utils.js";
import { BasinChecks, CategoryTags, Highlight, RegionTags } from "./Tags.jsx";

const QUICK = [["오늘", 0], ["3일", 2], ["7일", 6], ["30일", 29]];

export default function NewsTab({ settings }) {
  // 키워드: 예약 키워드(설정) + 이 화면에서 임시로 추가한 키워드
  const [keywords, setKeywords] = useState([]);   // [{ text, on, temp }]
  const [kwInput, setKwInput] = useState("");
  const [from, setFrom] = useState(daysAgo(6));
  const [to, setTo] = useState(todayKst());
  const [sources, setSources] = useState({ google: true, naver: true });
  const [basinSel, setBasinSel] = useState(() => new Set());
  const [regionInQuery, setRegionInQuery] = useState(true);
  const [unmatched, setUnmatched] = useState(false);
  const [waterOnly, setWaterOnly] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setKeywords((prev) => [
      ...settings.keywords.map((text) => ({ text, on: prev.find((k) => k.text === text)?.on ?? true })),
      ...prev.filter((k) => k.temp && !settings.keywords.includes(k.text)),
    ]);
    setBasinSel(new Set(settings.basins.filter((b) => b.enabled).map((b) => b.id)));
    setRegionInQuery(settings.news.regionInQuery);
  }, [settings]);

  const addKeywords = () => {
    const words = splitList(kwInput);
    setKeywords((prev) => {
      const next = prev.map((k) => (words.includes(k.text) ? { ...k, on: true } : k));
      for (const w of words) if (!next.some((k) => k.text === w)) next.push({ text: w, on: true, temp: true });
      return next;
    });
    setKwInput("");
  };

  const items = useMemo(() => {
    const list = result?.items || [];
    return waterOnly ? list.filter((n) => n.categories.length) : list;
  }, [result, waterOnly]);

  const submit = async (e) => {
    e.preventDefault();
    const kws = keywords.filter((k) => k.on).map((k) => k.text);
    const srcs = Object.keys(sources).filter((s) => sources[s]);
    if (!kws.length) return setError("키워드를 1개 이상 선택하세요.");
    if (!srcs.length) return setError("구글 또는 네이버를 선택하세요.");
    const params = new URLSearchParams({
      keywords: kws.join(","), from, to, sources: srcs.join(","), basins: [...basinSel].join(","),
      regionInQuery: regionInQuery ? "1" : "0", includeUnmatched: unmatched ? "1" : "0",
    });
    setLoading(true);
    setError("");
    try {
      setResult(await api(`/api/news?${params}`));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const exportCsv = () => {
    const rows = [["일시", "제목", "언론사", "분류", "유역", "지자체", "출처", "검색어", "링크"]];
    for (const n of items) {
      rows.push([n.publishedAt, n.title, n.press, n.categories.map((c) => CAT[c]).join("/"),
        [...new Set(n.regions.map((r) => r.basin))].join("/"), n.regions.map((r) => r.region).join("/"),
        n.sources.map((s) => SRC[s]).join("/"), n.queries.join("/"), n.link]);
    }
    downloadCsv(`뉴스모니터링_${result.start}_${result.end}.csv`, rows);
  };

  return (
    <div className="card">
      <div className="card-head"><h2>뉴스 조회 <span className="muted small">구글 뉴스 · 네이버 뉴스</span></h2></div>
      <form className="filters" onSubmit={submit}>
        <div className="row gap wrap">
          <span className="muted small">키워드</span>
          <div className="chips">
            {keywords.map((k, i) => (
              <span key={k.text} className={`chip toggle ${k.on ? "" : "off"}`} title="클릭하여 선택/해제"
                onClick={() => setKeywords((p) => p.map((x, j) => (j === i ? { ...x, on: !x.on } : x)))}>
                {k.on ? "✓ " : ""}{k.text}
                {k.temp && (
                  <button type="button" aria-label="삭제"
                    onClick={(e) => { e.stopPropagation(); setKeywords((p) => p.filter((_, j) => j !== i)); }}>×</button>
                )}
              </span>
            ))}
          </div>
          <input type="text" size={16} placeholder="키워드 추가 후 Enter" value={kwInput}
            onChange={(e) => setKwInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addKeywords(); } }} />
        </div>
        <div className="row gap wrap">
          <label>시작일 <input type="date" required value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label>종료일 <input type="date" required value={to} onChange={(e) => setTo(e.target.value)} /></label>
          <div className="seg">
            {QUICK.map(([label, n]) => (
              <button key={label} type="button" onClick={() => { setFrom(daysAgo(n)); setTo(todayKst()); }}>{label}</button>
            ))}
          </div>
          {["google", "naver"].map((s) => (
            <label key={s} className="check">
              <input type="checkbox" checked={sources[s]} onChange={(e) => setSources({ ...sources, [s]: e.target.checked })} /> {SRC[s]}
            </label>
          ))}
        </div>
        <div className="row gap wrap">
          <span className="muted small">지역 타겟팅</span>
          <BasinChecks basins={settings.basins} selected={basinSel} onChange={setBasinSel} />
        </div>
        <div className="row gap wrap">
          <label className="check"><input type="checkbox" checked={regionInQuery} onChange={(e) => setRegionInQuery(e.target.checked)} /> 검색어에 지자체명 결합(구글)</label>
          <label className="check"><input type="checkbox" checked={unmatched} onChange={(e) => setUnmatched(e.target.checked)} /> 대상 지역 외 기사 포함</label>
          <label className="check"><input type="checkbox" checked={waterOnly} onChange={(e) => setWaterOnly(e.target.checked)} /> 상수도·풍수해 분류 기사만</label>
          <span className="grow" />
          <button type="submit" className="btn primary" disabled={loading}>{loading ? "조회 중…" : "조회"}</button>
          <button type="button" className="btn" disabled={!items.length} onClick={exportCsv}>CSV 저장</button>
        </div>
      </form>

      <p className="muted small">
        {loading ? "구글·네이버 뉴스를 조회하고 있습니다…" : result &&
          `${result.start} ~ ${result.end} · 키워드 ${result.keywords.join(", ")} · 요청 ${result.requestCount}회 · 수집 ${result.rawCount}건 → 표시 ${items.length}건`}
      </p>
      {error && <div className="error-box">{error}</div>}
      {result?.errors.map((e) => <div key={e} className="error-box">{e}</div>)}

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th style={{ width: 130 }}>일시</th><th>제목</th><th style={{ width: 150 }}>분류</th>
              <th style={{ width: 170 }}>지역</th><th style={{ width: 110 }}>출처</th></tr>
          </thead>
          <tbody>
            {result && items.length === 0 && <tr><td colSpan={5} className="empty">검색 결과가 없습니다.</td></tr>}
            {items.map((n) => (
              <tr key={n.id}>
                <td className="mono">{fmtTime(n.publishedAt)}</td>
                <td className="title-cell">
                  <a href={n.link} target="_blank" rel="noopener noreferrer"><Highlight text={n.title} words={result.keywords} /></a>
                  {n.description && <div className="desc"><Highlight text={n.description} words={result.keywords} /></div>}
                </td>
                <td>{n.categories.length ? <CategoryTags categories={n.categories} /> : <span className="muted small">-</span>}</td>
                <td>{n.regions.length ? <RegionTags regions={n.regions} max={3} /> : <span className="muted small">지역 미확인</span>}</td>
                <td><div>{n.press}</div>{n.sources.map((s) => <span key={s} className="tag src">{SRC[s] || s}</span>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
