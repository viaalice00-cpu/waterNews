import { useMemo } from "react";
import { byTimeDesc, fmtTime, post, todayKst } from "../utils.js";
import { CategoryTags, RegionTags, StepTag } from "./Tags.jsx";

function StatusList({ status }) {
  if (!status) return null;
  const d = status.disaster, n = status.news;
  const state = !d.keySet ? "인증키 미설정" : !d.enabled ? "중지됨" : d.error ? "오류" : "정상";
  return (
    <dl className="status-list">
      <dt>재난문자</dt><dd>{state} · {d.intervalSec}초 주기 · 보관 {d.liveCount}건</dd>
      <dt>마지막 조회</dt><dd className="mono">{fmtTime(d.lastSuccess)} (다음 {fmtTime(d.nextPoll, false)})</dd>
      {d.error && <><dt>오류</dt><dd className="err">{d.error}</dd></>}
      <dt>예약 뉴스</dt>
      <dd>{n.enabled ? `${n.intervalMin}분 주기 · ${n.count}건 · 마지막 ${fmtTime(n.lastRun)}` : "꺼짐"}</dd>
      {n.error && <><dt>뉴스 경고</dt><dd className="err">{n.error}</dd></>}
    </dl>
  );
}

export default function Dashboard({ settings, live, scheduled, status, toast, goTab }) {
  const enabled = useMemo(() => settings.basins.filter((b) => b.enabled), [settings]);

  const { today, water } = useMemo(() => {
    const day = todayKst();
    const ids = new Set(enabled.map((b) => b.id));
    const today = live.filter((m) => (m.createdAt || "").startsWith(day) &&
      (!ids.size || m.regions.some((r) => ids.has(r.basinId))));
    return { today, water: today.filter((m) => m.relevant) };
  }, [live, enabled]);

  const newsHits = useMemo(() => scheduled.filter((n) => n.categories.length), [scheduled]);
  const outage = water.filter((m) => m.categories.includes("outage")).length +
    scheduled.filter((n) => n.categories.includes("outage")).length;

  const feed = useMemo(() => [
    ...water.map((m) => ({ key: `d${m.sn}`, kind: "문자", time: m.createdAt, cats: m.categories, regions: m.regions, text: m.message, sub: m.region, step: m.step })),
    ...newsHits.map((n) => ({ key: `n${n.id}`, kind: "뉴스", time: n.publishedAt, cats: n.categories, regions: n.regions, text: n.title, sub: n.press, link: n.link })),
  ].sort(byTimeDesc("time")).slice(0, 50), [water, newsHits]);

  const missing = [];
  if (!settings.safetydata.serviceKeySet) missing.push("재난문자 포털 인증키");
  if (!settings.naver.clientIdSet) missing.push("네이버 검색 API 키");

  const refresh = async () => {
    await post("/api/live/refresh", { target: "all" });
    toast("갱신 요청", "재난문자·예약 뉴스를 다시 조회합니다.");
  };

  return (
    <>
      {missing.length > 0 && (
        <div className="notice">
          {missing.join(", ")}가 설정되지 않았습니다. <a onClick={() => goTab("settings")}>환경설정</a>에서 입력하세요.
          (구글 뉴스는 키 없이 조회됩니다)
        </div>
      )}

      <div className="kpis">
        <div className="kpi"><span className="kpi-label">오늘 재난문자 (대상 지역)</span><span className="kpi-value">{today.length}</span></div>
        <div className="kpi alert"><span className="kpi-label">상수도·풍수해 관련 문자</span><span className="kpi-value">{water.length}</span></div>
        <div className="kpi"><span className="kpi-label">단수 감지 (문자+뉴스)</span><span className="kpi-value">{outage}</span></div>
        <div className="kpi"><span className="kpi-label">예약 키워드 뉴스</span>
          <span className="kpi-value">{settings.news.scheduleEnabled ? scheduled.length : "꺼짐"}</span></div>
      </div>

      <div className="grid2">
        <div className="card">
          <div className="card-head"><h2>유역별 감지 현황 <span className="muted small">(오늘 재난문자 + 예약조회 뉴스)</span></h2></div>
          <table className="table" id="basinTable">
            <thead><tr><th>유역</th><th>단수</th><th>상수도 사고</th><th>풍수해</th><th>합계</th></tr></thead>
            <tbody>
              {enabled.length === 0 ? (
                <tr><td colSpan={5} className="muted">환경설정에서 타겟 유역을 선택하세요.</td></tr>
              ) : enabled.map((b) => {
                const mine = [...water, ...newsHits].filter((it) => it.regions.some((r) => r.basinId === b.id));
                const c = (k) => mine.filter((it) => it.categories.includes(k)).length;
                return (
                  <tr key={b.id}><td>{b.name}</td><td>{c("outage")}</td><td>{c("water_accident")}</td>
                    <td>{c("flood")}</td><td><strong>{mine.length}</strong></td></tr>
                );
              })}
            </tbody>
          </table>
          <div className="card-head" style={{ marginTop: 16 }}><h2>연계 상태</h2></div>
          <StatusList status={status} />
          <button className="btn" onClick={refresh}>지금 갱신</button>
        </div>

        <div className="card">
          <div className="card-head">
            <h2>최근 감지 피드</h2>
            <span className="muted small">상수도·단수·풍수해 관련만</span>
          </div>
          <ul className="feed">
            {feed.length === 0 && <li className="empty">감지된 항목이 없습니다.</li>}
            {feed.map((f) => (
              <li key={f.key}>
                <div className="meta">
                  <span className="tag src">{f.kind}</span>
                  <span className="mono">{fmtTime(f.time)}</span>
                  <StepTag step={f.step} />
                  <CategoryTags categories={f.cats} />
                  <RegionTags regions={f.regions} max={2} />
                </div>
                <div>{f.link ? <a href={f.link} target="_blank" rel="noopener noreferrer">{f.text}</a> : f.text}</div>
                <div className="desc">{f.sub}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </>
  );
}
