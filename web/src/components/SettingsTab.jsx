import { useEffect, useState } from "react";
import { api, fmtTime, post, splitList } from "../utils.js";

const EMPTY_SECRETS = { serviceKey: "", clientId: "", clientSecret: "", aiKey: "" };

function KeywordEditor({ keywords, onChange, placeholder = "키워드 입력 후 Enter (쉼표로 여러 개)" }) {
  const [input, setInput] = useState("");
  const add = () => {
    onChange([...keywords, ...splitList(input).filter((k) => !keywords.includes(k))]);
    setInput("");
  };
  return (
    <div className="row gap wrap">
      <div className="chips">
        {keywords.length === 0 && <span className="muted small">키워드 없음</span>}
        {keywords.map((k) => (
          <span key={k} className="chip">{k}
            <button type="button" aria-label={`${k} 삭제`} onClick={() => onChange(keywords.filter((x) => x !== k))}>×</button>
          </span>
        ))}
      </div>
      <input type="text" size={28} placeholder={placeholder} value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
      <button type="button" className="btn" onClick={add}>추가</button>
    </div>
  );
}

function BasinCard({ basin, onChange, onRemove }) {
  const [input, setInput] = useState("");
  const addRegions = () => {
    onChange({ ...basin, regions: [...basin.regions, ...splitList(input).filter((r) => !basin.regions.includes(r))] });
    setInput("");
  };
  return (
    <div className={`basin ${basin.enabled ? "on" : ""}`}>
      <div className="basin-head">
        <input type="checkbox" title="타겟 사용" checked={basin.enabled}
          onChange={(e) => onChange({ ...basin, enabled: e.target.checked })} />
        <input type="text" className="grow" value={basin.name} onChange={(e) => onChange({ ...basin, name: e.target.value })} />
        <span className="muted small">{basin.regions.length}곳</span>
        <button type="button" className="btn small danger"
          onClick={() => confirm(`'${basin.name}' 유역을 삭제할까요?`) && onRemove()}>유역 삭제</button>
      </div>
      <div className="chips">
        {basin.regions.length === 0 && <span className="muted small">지자체 없음</span>}
        {basin.regions.map((r) => (
          <span key={r} className="chip">{r}
            <button type="button" aria-label={`${r} 삭제`}
              onClick={() => onChange({ ...basin, regions: basin.regions.filter((x) => x !== r) })}>×</button>
          </span>
        ))}
      </div>
      <div className="row gap">
        <input type="text" className="grow" placeholder="지자체 추가 (예: 정읍시, 완주군) — 쉼표로 여러 개" value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addRegions(); } }} />
        <button type="button" className="btn small" onClick={addRegions}>추가</button>
      </div>
    </div>
  );
}

export default function SettingsTab({ settings, toast, onSaved }) {
  const [draft, setDraft] = useState(() => structuredClone(settings));
  const [secrets, setSecrets] = useState(EMPTY_SECRETS);
  const [showKey, setShowKey] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState(null);
  const [newBasin, setNewBasin] = useState("");

  useEffect(() => {
    setDraft(structuredClone(settings));
    setSecrets(EMPTY_SECRETS);
    setDirty(false);
  }, [settings]);

  // draft.section.field 갱신 헬퍼
  const set = (section, field) => (value) => {
    setDraft((d) => ({ ...d, [section]: { ...d[section], [field]: value } }));
    setDirty(true);
  };
  const setTop = (field) => (value) => { setDraft((d) => ({ ...d, [field]: value })); setDirty(true); };
  const num = (fn) => (e) => fn(Number(e.target.value));
  const chk = (fn) => (e) => fn(e.target.checked);
  const setSecret = (k) => (e) => { setSecrets((s) => ({ ...s, [k]: e.target.value })); setDirty(true); };

  const save = async (payload) => {
    setSaving(true);
    try {
      const s = await api("/api/settings", { method: "PUT", body: JSON.stringify(payload) });
      onSaved(s);
      toast("환경설정", "저장되었습니다.");
    } catch (e) {
      toast("환경설정 저장 실패", e.message, { alert: true });
    } finally {
      setSaving(false);
    }
  };

  const submit = (e) => {
    e.preventDefault();
    const { safetydata: sd, news: ns } = draft;
    const payload = {
      safetydata: {
        apiUrl: sd.apiUrl, numOfRows: sd.numOfRows, maxPages: sd.maxPages, rgnNm: sd.rgnNm,
        verifySsl: sd.verifySsl, pollEnabled: sd.pollEnabled, pollIntervalSec: sd.pollIntervalSec,
      },
      naver: {},
      news: {
        scheduleEnabled: ns.scheduleEnabled, scheduleIntervalMin: ns.scheduleIntervalMin,
        scheduleLookbackHours: ns.scheduleLookbackHours, naverMaxPages: ns.naverMaxPages,
        sources: ns.sources, regionInQuery: ns.regionInQuery,
      },
      alerts: draft.alerts,
      ai: { model: draft.ai.model },
      keywords: draft.keywords,
      excludeKeywords: draft.excludeKeywords,
      basins: draft.basins,
    };
    if (secrets.serviceKey.trim()) payload.safetydata.serviceKey = secrets.serviceKey.trim();
    if (secrets.clientId.trim()) payload.naver.clientId = secrets.clientId.trim();
    if (secrets.clientSecret.trim()) payload.naver.clientSecret = secrets.clientSecret.trim();
    if (secrets.aiKey.trim()) payload.ai.apiKey = secrets.aiKey.trim();
    save(payload);
  };

  const clearSecrets = (list) => {
    if (confirm("저장된 인증키를 삭제할까요?")) save({ clearSecrets: list });
  };

  const runTest = async () => {
    setTest({ pending: true });
    try {
      setTest(await post("/api/disaster/test", { serviceKey: secrets.serviceKey.trim() }));
    } catch (e) {
      setTest({ ok: false, message: e.message });
    }
  };

  const updateBasin = (i) => (b) => setTop("basins")(draft.basins.map((x, j) => (j === i ? b : x)));
  const removeBasin = (i) => () => setTop("basins")(draft.basins.filter((_, j) => j !== i));
  const addBasin = () => {
    if (!newBasin.trim()) return;
    setTop("basins")([...draft.basins, { id: "", name: newBasin.trim(), enabled: true, regions: [] }]);
    setNewBasin("");
  };

  const toggleSource = (src) => (e) => {
    const cur = new Set(draft.news.sources);
    e.target.checked ? cur.add(src) : cur.delete(src);
    set("news", "sources")(["google", "naver"].filter((s) => cur.has(s)));
  };

  const sd = draft.safetydata, nv = draft.naver, ns = draft.news;
  const placeholder = (isSet) => (isSet ? "설정됨 (변경 시에만 입력)" : "미설정");

  return (
    <form onSubmit={submit} autoComplete="off">
      <div className="grid2">
        <div className="card">
          <div className="card-head"><h2>행정안전부 긴급재난문자 API</h2></div>
          <p className="muted small">재난안전데이터 공유플랫폼(safetydata.go.kr) → 행정안전부_긴급재난문자 → 이용신청 후 발급받은 서비스키를 입력하세요.</p>
          <label className="field">포털 인증키 (serviceKey)
            <div className="row gap">
              <input type={showKey ? "text" : "password"} className="grow" placeholder={placeholder(sd.serviceKeySet)}
                value={secrets.serviceKey} onChange={setSecret("serviceKey")} />
              <button type="button" className="btn" onClick={() => setShowKey(!showKey)}>{showKey ? "숨김" : "표시"}</button>
            </div>
            <span className="muted small">{sd.serviceKeySet ? `저장된 키: ${sd.serviceKeyHint}` : "저장된 키 없음"}</span>
          </label>
          <div className="row gap">
            <button type="button" className="btn" onClick={runTest}>연결 테스트</button>
            <button type="button" className="btn ghost" onClick={() => clearSecrets(["safetydata.serviceKey"])}>키 삭제</button>
          </div>
          {test && (
            <div className="small">
              {test.pending ? "연결 확인 중…" : test.ok ? (
                <>
                  <span style={{ color: "var(--ok)" }}>✔ {test.message}</span>
                  {(test.sample || []).map((m) => (
                    <div key={m.sn} className="desc">{fmtTime(m.createdAt)} {m.region} — {m.message.slice(0, 60)}</div>
                  ))}
                </>
              ) : <div className="error-box">✖ {test.message}</div>}
            </div>
          )}
          <details>
            <summary>고급 설정</summary>
            <label className="field">API URL <input type="url" value={sd.apiUrl} onChange={(e) => set("safetydata", "apiUrl")(e.target.value)} /></label>
            <div className="row gap wrap">
              <label className="field">페이지당 개수(numOfRows) <input type="number" min={10} max={1000} value={sd.numOfRows} onChange={num(set("safetydata", "numOfRows"))} /></label>
              <label className="field">최대 페이지 <input type="number" min={1} max={50} value={sd.maxPages} onChange={num(set("safetydata", "maxPages"))} /></label>
            </div>
            <label className="field">서버측 지역 필터(rgnNm)
              <input type="text" placeholder="비우면 전국 조회 후 앱에서 지역 필터" value={sd.rgnNm} onChange={(e) => set("safetydata", "rgnNm")(e.target.value)} />
            </label>
            <label className="check"><input type="checkbox" checked={sd.verifySsl} onChange={chk(set("safetydata", "verifySsl"))} /> SSL 인증서 검증 (기관망 인증서 오류 시 해제)</label>
          </details>
          <hr />
          <label className="check"><input type="checkbox" checked={sd.pollEnabled} onChange={chk(set("safetydata", "pollEnabled"))} /> 실시간 조회 사용</label>
          <label className="field">조회 주기(초)
            <input type="number" min={30} max={3600} value={sd.pollIntervalSec} onChange={num(set("safetydata", "pollIntervalSec"))} />
            <span className="muted small">일일 호출 한도를 고려하세요 (120초 = 하루 약 720회)</span>
          </label>
          <label className="check"><input type="checkbox" checked={draft.alerts.waterOnly} onChange={chk(set("alerts", "waterOnly"))} /> 상수도·단수·풍수해 관련 문자만 알림</label>
        </div>

        <div className="card">
          <div className="card-head"><h2>네이버 검색 API</h2></div>
          <p className="muted small">developers.naver.com → 애플리케이션 등록(검색 API) 후 Client ID/Secret 입력. 구글 뉴스는 인증키 없이 사용합니다.</p>
          <label className="field">Client ID
            <input type="text" placeholder={placeholder(nv.clientIdSet)} value={secrets.clientId} onChange={setSecret("clientId")} />
            {nv.clientIdSet && <span className="muted small">저장됨: {nv.clientIdHint}</span>}
          </label>
          <label className="field">Client Secret
            <input type="password" placeholder={placeholder(nv.clientSecretSet)} value={secrets.clientSecret} onChange={setSecret("clientSecret")} />
            {nv.clientSecretSet && <span className="muted small">저장됨: {nv.clientSecretHint}</span>}
          </label>
          <button type="button" className="btn ghost" onClick={() => clearSecrets(["naver.clientId", "naver.clientSecret"])}>키 삭제</button>
          <hr />
          <h3>조회 예약 (자동 뉴스 감시)</h3>
          <label className="check"><input type="checkbox" checked={ns.scheduleEnabled} onChange={chk(set("news", "scheduleEnabled"))} /> 예약 키워드로 주기적 뉴스 조회</label>
          <div className="row gap wrap">
            <label className="field">주기(분) <input type="number" min={5} max={1440} value={ns.scheduleIntervalMin} onChange={num(set("news", "scheduleIntervalMin"))} /></label>
            <label className="field">조회 범위(최근 N시간) <input type="number" min={1} max={168} value={ns.scheduleLookbackHours} onChange={num(set("news", "scheduleLookbackHours"))} /></label>
            <label className="field">네이버 최대 페이지(100건/페이지) <input type="number" min={1} max={10} value={ns.naverMaxPages} onChange={num(set("news", "naverMaxPages"))} /></label>
          </div>
          <div className="row gap wrap">
            <label className="check"><input type="checkbox" checked={ns.sources.includes("google")} onChange={toggleSource("google")} /> 구글</label>
            <label className="check"><input type="checkbox" checked={ns.sources.includes("naver")} onChange={toggleSource("naver")} /> 네이버</label>
            <label className="check"><input type="checkbox" checked={ns.regionInQuery} onChange={chk(set("news", "regionInQuery"))} /> 검색어에 지자체명 결합(구글)</label>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head"><h2>AI 브리핑 (선택)</h2><span className="muted small">사고 분석 탭의 사건별 AI 요약</span></div>
        <p className="muted small">
          Anthropic API 키(console.anthropic.com 발급)를 입력하면 사건별로 상황 요약·경과·쟁점·대응 시사점 브리핑을 생성합니다.
          처음 한 번 명령 프롬프트에서 <code>pip install anthropic</code> 실행이 필요합니다. 생성할 때마다 해당 사건의
          뉴스 제목·요약과 재난문자 내용이 Claude API로 전송되며 API 사용료가 발생합니다. 키가 없어도 규칙 기반 브리핑은 동작합니다.
        </p>
        <div className="row gap wrap">
          <label className="field grow">Anthropic API 키
            <input type="password" placeholder={placeholder(draft.ai.apiKeySet)} value={secrets.aiKey} onChange={setSecret("aiKey")} />
            {draft.ai.apiKeySet && <span className="muted small">저장됨: {draft.ai.apiKeyHint}</span>}
          </label>
          <label className="field">모델
            <select value={draft.ai.model} onChange={(e) => set("ai", "model")(e.target.value)}>
              {Object.entries(settings.aiModels || {}).map(([id, label]) => <option key={id} value={id}>{label}</option>)}
            </select>
          </label>
        </div>
        <button type="button" className="btn ghost" onClick={() => clearSecrets(["ai.apiKey"])}>키 삭제</button>
      </div>

      <div className="card">
        <div className="card-head"><h2>조회 예약 키워드</h2><span className="muted small">뉴스 검색 기본값 · 재난문자 키워드 강조 · 예약 조회에 사용</span></div>
        <KeywordEditor keywords={draft.keywords} onChange={setTop("keywords")} />
      </div>

      <div className="card">
        <div className="card-head"><h2>뉴스 제외 키워드</h2><span className="muted small">동음이의어 오탐 제외 (예: 단수 공천·단수 임명)</span></div>
        <p className="muted small">
          기사 제목·요약에 아래 단어가 있으면 조회 결과와 알림에서 제외합니다. 단, 상수도·수돗물·급수·정수장·누수 등
          상수도 맥락 단어가 함께 있으면 실제 단수 기사로 보고 제외하지 않습니다. 제외된 기사는 뉴스 조회의
          "제외된 기사 보기"로 확인할 수 있습니다.
        </p>
        <KeywordEditor keywords={draft.excludeKeywords} onChange={setTop("excludeKeywords")}
          placeholder="제외할 단어 입력 후 Enter (예: 공천, 당협)" />
      </div>

      <div className="card">
        <div className="card-head">
          <h2>지역 타겟팅</h2>
          <div className="row gap">
            <input type="text" size={22} placeholder="새 유역 이름 (예: 새만금유역)" value={newBasin}
              onChange={(e) => setNewBasin(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addBasin(); } }} />
            <button type="button" className="btn" onClick={addBasin}>유역 추가</button>
          </div>
        </div>
        <p className="muted small">체크된 유역의 지자체가 실시간 감시·알림 대상입니다. 시(市)·광역시는 '정읍'처럼 핵심 지명으로, 군·구는 '완주군'처럼 전체 명칭으로 뉴스가 매칭됩니다. '서울시'로 입력해도 재난문자 '서울특별시'와 매칭됩니다.</p>
        <div className="basins">
          {draft.basins.length === 0 && <div className="empty">등록된 유역이 없습니다.</div>}
          {draft.basins.map((b, i) => (
            <BasinCard key={b.id || `new-${i}`} basin={b} onChange={updateBasin(i)} onRemove={removeBasin(i)} />
          ))}
        </div>
      </div>

      <div className="savebar">
        <span className="muted small">{dirty ? "저장되지 않은 변경사항이 있습니다." : ""}</span>
        <button type="button" className="btn" onClick={() => { setDraft(structuredClone(settings)); setSecrets(EMPTY_SECRETS); setDirty(false); }}>되돌리기</button>
        <button type="submit" className="btn primary" disabled={saving}>{saving ? "저장 중…" : "설정 저장"}</button>
      </div>
    </form>
  );
}
