import { useEffect, useMemo, useRef, useState } from "react";
import { CAT, SRC, api, daysAgo, downloadCsv, fmtTime, splitList, todayKst } from "../utils.js";
import { GroupBadges, KeywordGroupPicker } from "./KeywordGroups.jsx";
import { BasinChecks, CategoryTags, Highlight, RegionTags } from "./Tags.jsx";

const QUICK = [["오늘", 0], ["3일", 2], ["7일", 6], ["30일", 29]];

export default function NewsTab({ settings }) {
  // 키워드: 환경설정의 키워드 그룹에서 선택 + 이 화면에서 임시로 추가한 키워드
  const [selected, setSelected] = useState(() => new Set());
  const [temp, setTemp] = useState([]);
  const [kwInput, setKwInput] = useState("");
  const [groupFilter, setGroupFilter] = useState("all");   // all | <그룹 id> | none(맥락 불명확)
  const prevKeywords = useRef([]);
  const inited = useRef(false);
  const [from, setFrom] = useState(daysAgo(6));
  const [to, setTo] = useState(todayKst());
  const [sources, setSources] = useState({ google: true, naver: true });
  const [basinSel, setBasinSel] = useState(() => new Set());
  const [regionInQuery, setRegionInQuery] = useState(true);
  const [unmatched, setUnmatched] = useState(false);
  const [waterOnly, setWaterOnly] = useState(false);
  const [showExcluded, setShowExcluded] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    // 처음엔 모든 그룹 키워드 선택, 이후 설정이 바뀌면 사라진 키워드만 정리 + 새 키워드는 선택
    setSelected((prev) => {
      if (!inited.current) { inited.current = true; return new Set(settings.keywords); }
      const next = new Set([...prev].filter((k) => settings.keywords.includes(k) || temp.includes(k)));
      settings.keywords.forEach((k) => { if (!prev.has(k) && !prevKeywords.current.includes(k)) next.add(k); });
      return next;
    });
    prevKeywords.current = settings.keywords;
    setBasinSel(new Set(settings.basins.filter((b) => b.enabled).map((b) => b.id)));
    setRegionInQuery(settings.news.regionInQuery);
  }, [settings]);

  const addKeywords = () => {
    const words = splitList(kwInput);
    setTemp((p) => [...p, ...words.filter((w) => !p.includes(w) && !settings.keywords.includes(w))]);
    setSelected((p) => new Set([...p, ...words]));
    setKwInput("");
  };
  const tempGroup = temp.length ? [{ id: "_temp", name: "이번 조회에만 추가", icon: "➕",
    description: "아래 입력칸에서 추가한 키워드 (저장되지 않음)", keywords: temp }] : [];

  const items = useMemo(() => {
    let list = result?.items || [];
    if (!showExcluded) list = list.filter((n) => !n.excludedBy?.length);
    if (groupFilter === "none") list = list.filter((n) => !n.contextMatch && !n.excludedBy?.length);
    else if (groupFilter !== "all") list = list.filter((n) => n.groups?.some((g) => g.id === groupFilter));
    return waterOnly ? list.filter((n) => n.categories.length || n.excludedBy?.length) : list;
  }, [result, waterOnly, showExcluded, groupFilter]);

  // 결과의 그룹 맥락 분포 (필터 버튼에 건수 표시)
  const groupCounts = useMemo(() => {
    const c = { none: 0 };
    for (const n of result?.items || []) {
      if (n.excludedBy?.length) continue;
      if (!n.contextMatch) c.none += 1;
      for (const g of n.groups || []) c[g.id] = (c[g.id] || 0) + 1;
    }
    return c;
  }, [result]);

  const submit = async (e) => {
    e.preventDefault();
    const kws = [...settings.keywords, ...temp].filter((k) => selected.has(k));
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
    const rows = [["일시", "제목", "언론사", "맥락 그룹", "맥락 단어", "분류", "유역", "지자체", "출처", "검색어", "링크"]];
    for (const n of items) {
      const cat = n.excludedBy?.length ? `제외(${n.excludedBy.join("/")})` : n.categories.map((c) => CAT[c]).join("/");
      const grp = n.contextMatch ? n.groups.map((g) => g.name).join("/") : "맥락 불명확";
      rows.push([n.publishedAt, n.title, n.press, grp, (n.groups?.[0]?.terms || []).join("/"), cat,
        [...new Set(n.regions.map((r) => r.basin))].join("/"), n.regions.map((r) => r.region).join("/"),
        n.sources.map((s) => SRC[s]).join("/"), n.queries.join("/"), n.link]);
    }
    downloadCsv(`뉴스모니터링_${result.start}_${result.end}.csv`, rows);
  };

  return (
    <div className="card">
      <div className="card-head"><h2>뉴스 조회 <span className="muted small">구글 뉴스 · 네이버 뉴스</span></h2></div>
      <form className="filters" onSubmit={submit}>
        <div className="kg-section">
          <div className="row gap wrap">
            <strong>관심 키워드 그룹별 선택</strong>
            <span className="muted small">그룹을 일괄 선택하거나 키워드를 개별 선택하세요 · 선택 {[...settings.keywords, ...temp].filter((k) => selected.has(k)).length}개</span>
            <span className="grow" />
            <button type="button" className="btn small" onClick={() => setSelected(new Set([...settings.keywords, ...temp]))}>전체 선택</button>
            <button type="button" className="btn small" onClick={() => setSelected(new Set())}>전체 해제</button>
          </div>
          <KeywordGroupPicker groups={[...settings.keywordGroups, ...tempGroup]} selected={selected} onChange={setSelected} />
          <div className="row gap">
            <input type="text" size={28} placeholder="이번 조회에만 쓸 키워드 추가 후 Enter" value={kwInput}
              onChange={(e) => setKwInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addKeywords(); } }} />
            {temp.length > 0 && <button type="button" className="btn small ghost" onClick={() => setTemp([])}>임시 키워드 지우기</button>}
          </div>
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
          <label className="check" title="환경설정의 제외 키워드(공천·당협 등)에 걸린 기사">
            <input type="checkbox" checked={showExcluded} onChange={(e) => setShowExcluded(e.target.checked)} />
            제외된 기사 보기{result ? ` (${result.excludedCount}건)` : ""}
          </label>
          <span className="grow" />
          <button type="submit" className="btn primary" disabled={loading}>{loading ? "조회 중…" : "조회"}</button>
          <button type="button" className="btn" disabled={!items.length} onClick={exportCsv}>CSV 저장</button>
        </div>
      </form>

      <p className="muted small">
        {loading ? "구글·네이버 뉴스를 조회하고 있습니다…" : result &&
          `${result.start} ~ ${result.end} · 키워드 ${result.keywords.join(", ")} · 요청 ${result.requestCount}회 · 수집 ${result.rawCount}건 → 기간 밖 ${result.dropped?.date ?? 0}건 · 지역 불일치 ${result.dropped?.region ?? 0}건 · 제외 ${result.excludedCount}건 → 표시 ${items.length}건`}
      </p>
      {result && (
        <div className="row gap wrap ctx-filter">
          <span className="muted small">맥락 그룹</span>
          <div className="seg">
            <button type="button" className={groupFilter === "all" ? "active" : ""} onClick={() => setGroupFilter("all")}>전체</button>
            {settings.keywordGroups.filter((g) => g.contextTerms?.length).map((g) => (
              <button type="button" key={g.id} className={groupFilter === g.id ? "active" : ""} onClick={() => setGroupFilter(g.id)}>
                {g.icon} {g.name.replace(/\s*\(.*\)$/, "")} {groupCounts[g.id] || 0}
              </button>
            ))}
            <button type="button" className={groupFilter === "none" ? "active" : ""} onClick={() => setGroupFilter("none")}
              title="검색어는 들어 있지만 그룹 맥락 단어가 부족한 기사 (예: '협상 파열', '단수 공천')">맥락 불명확 {groupCounts.none}</button>
          </div>
        </div>
      )}
      {error && <div className="error-box">{error}</div>}
      {result?.errors.map((e) => <div key={e} className="error-box">{e}</div>)}

      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr><th style={{ width: 130 }}>일시</th><th>제목</th><th style={{ width: 190 }}>맥락 · 분류</th>
              <th style={{ width: 170 }}>지역</th><th style={{ width: 110 }}>출처</th></tr>
          </thead>
          <tbody>
            {result && items.length === 0 && <tr><td colSpan={5} className="empty">검색 결과가 없습니다.</td></tr>}
            {items.map((n) => (
              <tr key={n.id} className={n.excludedBy?.length ? "excluded" : ""}>
                <td className="mono">{fmtTime(n.publishedAt)}</td>
                <td className="title-cell">
                  <a href={n.link} target="_blank" rel="noopener noreferrer"><Highlight text={n.title} words={result.keywords} /></a>
                  {n.description && <div className="desc"><Highlight text={n.description} words={result.keywords} /></div>}
                </td>
                <td>
                  {n.excludedBy?.length
                    ? <span className="tag excluded" title="상수도 맥락 단어 없이 제외 키워드가 포함됨">제외: {n.excludedBy.join(", ")}</span>
                    : <div className="ctx-cell">
                        <div><GroupBadges groups={n.groups || []} contextMatch={n.contextMatch} /></div>
                        {n.contextMatch && <div className="muted small">{n.groups[0].terms.slice(0, 4).join(" · ")}</div>}
                        <div><CategoryTags categories={n.categories} /></div>
                      </div>}
                </td>
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
