import { useCallback, useEffect, useState } from "react";
import { api, fmtTime, post } from "../utils.js";
import { BasinChecks } from "./Tags.jsx";

const WINDOWS = [["24시간", 24], ["3일", 72], ["7일", 168], ["30일", 720]];
const SEVERITY_CLS = { 높음: "sev-high", 보통: "sev-mid", 낮음: "sev-low" };
const STATUS_CLS = { 발생: "st-new", "대응 중": "st-active", "복구 완료": "st-done", 소강: "st-quiet" };

/** 영역별 태그 빈도: 단일 계열 가로 막대 (값·라벨은 텍스트 색, 막대만 강조색) */
function ContextBars({ title, rows }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  return (
    <div className="ctx-dim">
      <h3>{title}</h3>
      {rows.length === 0 ? <p className="muted small">언급 없음</p> : (
        <ul className="bars">
          {rows.map((r) => (
            <li key={r.tag} title={`${title} · ${r.tag}: ${r.count}건`}>
              <span className="bar-label">{r.tag}</span>
              <span className="bar-track"><span className="bar-fill" style={{ width: `${(r.count / max) * 100}%` }} /></span>
              <span className="bar-value mono">{r.count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** AI 응답(마크다운 일부: ##, -, 문단)을 안전하게 렌더링 */
function MiniMarkdown({ text }) {
  const blocks = [];
  let list = null;
  text.split("\n").forEach((raw, i) => {
    const line = raw.trimEnd();
    if (/^\s*[-*]\s+/.test(line)) {
      list ||= [];
      list.push(<li key={i}>{line.replace(/^\s*[-*]\s+/, "")}</li>);
      return;
    }
    if (list) { blocks.push(<ul key={`u${i}`}>{list}</ul>); list = null; }
    if (/^#{1,4}\s/.test(line)) blocks.push(<h4 key={i}>{line.replace(/^#+\s*/, "")}</h4>);
    else if (line.trim()) blocks.push(<p key={i}>{line}</p>);
  });
  if (list) blocks.push(<ul key="last">{list}</ul>);
  return <div className="ai-text">{blocks}</div>;
}

function Insights({ items }) {
  if (!items?.length) return null;
  return (
    <ul className="insights">
      {items.map((x, i) => (
        <li key={i} className={x.level === "주의" ? "warn" : ""}>
          <span className={`tag ${x.level === "주의" ? "lvl-warn" : "src"}`}>{x.level}</span> {x.text}
        </li>
      ))}
    </ul>
  );
}

function ClusterCard({ c, open, onToggle, ai, onAi, aiEnabled }) {
  const ctxTags = Object.entries(c.contexts).flatMap(([dim, rows]) =>
    rows.slice(0, 3).map((r) => ({ dim, ...r })));
  return (
    <article className={`cluster ${SEVERITY_CLS[c.severity]}`}>
      <div className="cluster-head">
        <span className={`tag sev ${SEVERITY_CLS[c.severity]}`}>심각도 {c.severity}</span>
        <span className={`tag st ${STATUS_CLS[c.status]}`}>{c.status}</span>
        {c.group && <span className={`tag ctx-group ctx-${c.group.id}`}>{c.group.icon} {c.group.name.replace(/\s*\(.*\)$/, "")}</span>}
        <strong>{c.region} · {c.incidentType}</strong>
        <span className="muted small">
          {fmtTime(c.start)}{c.end !== c.start ? ` ~ ${fmtTime(c.end)}` : ""} · 뉴스 {c.counts.news} · 재난문자 {c.counts.disaster}
          {c.basins.length > 0 && ` · ${c.basins.join(", ")}`}
        </span>
      </div>
      <div className="cluster-title">{c.title}</div>

      <div className="cluster-grid">
        <div>
          <h4>요약 브리핑 <span className="muted small">(규칙 기반)</span></h4>
          <ul className="briefing">{c.briefing.map((l, i) => <li key={i}>{l}</li>)}</ul>
          <div className="chips small-chips">
            {ctxTags.map((t) => <span key={t.dim + t.tag} className="chip" title={t.dim}>{t.tag} {t.count}</span>)}
          </div>
        </div>
        <div>
          <h4>인사이트</h4>
          {c.insights.length ? <Insights items={c.insights} /> : <p className="muted small">특이 신호 없음</p>}
        </div>
      </div>

      {(ai?.text || ai?.error || ai?.loading) && (
        <div className="ai-box">
          <h4>AI 브리핑 {ai.model && <span className="muted small">({ai.model})</span>}</h4>
          {ai.loading && <p className="muted">AI가 브리핑을 작성하고 있습니다… (최대 1~2분)</p>}
          {ai.error && <div className="error-box">{ai.error}</div>}
          {ai.text && <MiniMarkdown text={ai.text} />}
        </div>
      )}

      <div className="row gap wrap" style={{ marginTop: 8 }}>
        <button className="btn small" onClick={onToggle}>{open ? "사건 일지 접기 ▴" : `사건 일지 보기 (${c.timeline.length}) ▾`}</button>
        <button className="btn small" disabled={ai?.loading || !aiEnabled} onClick={() => onAi(!!ai?.text)}
          title={aiEnabled ? "" : "환경설정에서 Anthropic API 키를 입력하면 사용할 수 있습니다"}>
          {ai?.text ? "AI 브리핑 다시 생성" : "AI 브리핑 생성"}
        </button>
      </div>

      {open && (
        <div className="timeline-wrap">
          <h4>사건 일지</h4>
          <ol className="timeline">
            {c.timeline.map((e, i) => (
              <li key={i} className={`ph-${e.phase}`}>
                <span className="mono tl-time">{fmtTime(e.time)}</span>
                <span className={`tag phase ph-${e.phase}`}>{e.phase}</span>
                <span className="tag src">{e.kind === "news" ? "뉴스" : "재난문자"}</span>
                <span className="tl-body">
                  {e.link ? <a href={e.link} target="_blank" rel="noopener noreferrer">{e.title}</a> : e.title}
                  <span className="muted small"> — {e.source}</span>
                  {e.tags.length > 0 && <span className="muted small"> · {e.tags.join(", ")}</span>}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </article>
  );
}

export default function AnalysisTab({ settings, active, toast, live, scheduled }) {
  const [hours, setHours] = useState(72);
  const [basinSel, setBasinSel] = useState(() => new Set());
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(() => new Set());
  const [ai, setAi] = useState({});      // clusterId → {loading, text, model, error}
  const [showDone, setShowDone] = useState(true);

  useEffect(() => {
    setBasinSel(new Set(settings.basins.filter((b) => b.enabled).map((b) => b.id)));
  }, [settings]);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await api(`/api/analysis?${new URLSearchParams({ hours, basins: [...basinSel].join(",") })}`);
      setData(res);
      // 서버에 캐시된 AI 브리핑 반영
      setAi((prev) => {
        const next = { ...prev };
        for (const c of res.clusters) if (c.ai && !next[c.id]?.text) next[c.id] = c.ai;
        return next;
      });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [hours, basinSel]);

  // 탭이 보일 때, 조건이 바뀔 때, 새 재난문자·예약 뉴스가 들어올 때 다시 분석
  useEffect(() => { if (active) load(); }, [active, load, live.length, scheduled.length]);

  const collect = async () => {
    await post("/api/analysis/collect");
    toast("데이터 수집", "재난문자·예약 키워드 뉴스를 수집합니다. 잠시 후 자동으로 반영됩니다.");
    setTimeout(load, 5000);
  };

  const runAi = async (c, refresh) => {
    setAi((p) => ({ ...p, [c.id]: { loading: true } }));
    try {
      const r = await post("/api/analysis/ai", { clusterId: c.id, hours, basins: [...basinSel].join(","), refresh });
      setAi((p) => ({ ...p, [c.id]: r.ok ? { text: r.text, model: r.model } : { error: r.message } }));
    } catch (e) {
      setAi((p) => ({ ...p, [c.id]: { error: e.message } }));
    }
  };

  const toggle = (id) => setOpen((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const clusters = (data?.clusters || []).filter((c) => showDone || !["복구 완료", "소강"].includes(c.status));
  const aiEnabled = settings.ai?.apiKeySet;
  const storeTotal = data ? Object.values(data.store).reduce((a, b) => a + b.count, 0) : 0;
  const lastSeen = data ? Object.values(data.store).map((x) => x.lastSeen).sort().pop() : null;

  return (
    <>
      <div className="card">
        <div className="card-head">
          <h2><span className="step">1</span> 실시간 데이터 수집</h2>
          <div className="row gap">
            <button className="btn" onClick={collect}>지금 수집</button>
            <button className="btn primary" disabled={loading} onClick={load}>{loading ? "분석 중…" : "다시 분석"}</button>
          </div>
        </div>
        <div className="filters">
          <div className="row gap wrap">
            <span className="muted small">분석 기간</span>
            <div className="seg">
              {WINDOWS.map(([label, h]) => (
                <button key={h} className={hours === h ? "active" : ""} onClick={() => setHours(h)}>{label}</button>
              ))}
            </div>
            <span className="muted small" style={{ marginLeft: 8 }}>유역</span>
            <BasinChecks basins={settings.basins} selected={basinSel} onChange={setBasinSel} />
          </div>
        </div>
        {data && (
          <p className="small">
            분석 대상: <strong>뉴스 {data.collected.news}건 · 재난문자 {data.collected.disaster}건</strong>
            <span className="muted"> (직전 같은 기간 {data.collected.previous}건) · 누적 저장 {storeTotal}건 · 마지막 수집 {fmtTime(lastSeen)}</span>
          </p>
        )}
        <p className="muted small">
          재난문자 실시간 조회, 예약 키워드 뉴스 조회, 뉴스 조회 탭의 검색 결과 중 상수도·풍수해로 분류된 항목이 자동으로 누적됩니다
          (제외 키워드 기사 제외). 예약 조회를 켜 두면 별도 조작 없이 분석 자료가 쌓입니다.
        </p>
        {error && <div className="error-box">{error}</div>}
      </div>

      {data && (
        <>
          <div className="card">
            <div className="card-head"><h2>종합 인사이트</h2></div>
            {data.insights.length ? <Insights items={data.insights} /> : <p className="muted">분석 기간 내 감지된 수도 사고가 없습니다.</p>}
          </div>

          <div className="card">
            <div className="card-head">
              <h2><span className="step">2</span> 이해 영역 맥락 카운팅</h2>
              <span className="muted small">기사·문자 1건에 해당 맥락이 언급되면 1회 집계</span>
            </div>
            {data.groups && (
              <div className="ctx-groups">
                <ContextBars title="키워드 그룹 맥락" rows={data.groups.map((g) => ({ tag: `${g.icon} ${g.name}`.trim(), count: g.count }))} />
                <p className="muted small">기사·문자가 어느 관심 키워드 그룹의 맥락(맥락 단어 2개 이상)으로 쓰였는지 집계했습니다.</p>
              </div>
            )}
            <div className="ctx-grid">
              {Object.entries(data.contexts).map(([dim, rows]) => <ContextBars key={dim} title={dim} rows={rows} />)}
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h2><span className="step">3</span> 맥락 군집 요약 브리핑 <span className="step">4</span> 사건 일지 &amp; 인사이트</h2>
              <label className="check small"><input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} /> 복구 완료·소강 사건 포함</label>
            </div>
            <p className="muted small">같은 지역에서 48시간 안에 이어진 같은 유형의 보도·문자를 하나의 사건으로 묶었습니다. 진행 중·심각도 높은 사건이 위에 표시됩니다.</p>
            {!aiEnabled && <p className="muted small">AI 브리핑은 환경설정에서 Anthropic API 키를 입력하면 사용할 수 있습니다(선택).</p>}
            <div className="clusters">
              {clusters.length === 0 && <div className="empty">표시할 사건이 없습니다.</div>}
              {clusters.map((c) => (
                <ClusterCard key={c.id} c={c} open={open.has(c.id)} onToggle={() => toggle(c.id)}
                  ai={ai[c.id]} onAi={(refresh) => runAi(c, refresh)} aiEnabled={aiEnabled} />
              ))}
            </div>
          </div>
        </>
      )}
    </>
  );
}
