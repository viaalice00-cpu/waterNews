import { useState } from "react";
import { splitList } from "../utils.js";

/** 뉴스 조회용 그룹 선택: 그룹 단위 일괄 선택 + 키워드 개별 선택 */
export function KeywordGroupPicker({ groups, selected, onChange }) {
  const toggle = (k) => {
    const next = new Set(selected);
    next.has(k) ? next.delete(k) : next.add(k);
    onChange(next);
  };
  const setGroup = (g, on) => {
    const next = new Set(selected);
    g.keywords.forEach((k) => (on ? next.add(k) : next.delete(k)));
    onChange(next);
  };
  return (
    <div className="kg-grid">
      {groups.map((g) => {
        const n = g.keywords.filter((k) => selected.has(k)).length;
        const all = g.keywords.length > 0 && n === g.keywords.length;
        return (
          <div key={g.id} className={`kg-card ${n ? "on" : ""}`}>
            <div className="kg-head">
              <span className="kg-icon" aria-hidden="true">{g.icon || "🔖"}</span>
              <div className="kg-title">
                <strong>{g.name}</strong>
                {g.description && <span className="muted small">{g.description}</span>}
              </div>
              <button type="button" className={`btn small ${all ? "" : "primary-soft"}`}
                disabled={!g.keywords.length} onClick={() => setGroup(g, !all)}>
                {all ? "그룹 해제" : "그룹 선택"}
              </button>
            </div>
            <div className="chips">
              {g.keywords.length === 0 && <span className="muted small">키워드 없음 — 환경설정에서 추가</span>}
              {g.keywords.map((k) => (
                <button type="button" key={k} className={`chip toggle ${selected.has(k) ? "sel" : ""}`}
                  aria-pressed={selected.has(k)} onClick={() => toggle(k)}>
                  {selected.has(k) ? "✓ " : ""}{k}
                </button>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function TermEditor({ label, hint, values, onChange, placeholder }) {
  const [input, setInput] = useState("");
  const add = () => {
    onChange([...values, ...splitList(input).filter((v) => !values.includes(v))]);
    setInput("");
  };
  return (
    <div className="kg-terms">
      <div className="small"><strong>{label}</strong> <span className="muted">{hint}</span></div>
      <div className="chips">
        {values.length === 0 && <span className="muted small">없음</span>}
        {values.map((v) => (
          <span key={v} className="chip">{v}
            <button type="button" aria-label={`${v} 삭제`} onClick={() => onChange(values.filter((x) => x !== v))}>×</button>
          </span>
        ))}
      </div>
      <div className="row gap">
        <input type="text" className="grow" placeholder={placeholder} value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        <button type="button" className="btn small" onClick={add}>추가</button>
      </div>
    </div>
  );
}

/** 환경설정용 그룹 편집기 */
export function KeywordGroupEditor({ groups, onChange }) {
  const [newName, setNewName] = useState("");
  const update = (i, patch) => onChange(groups.map((g, j) => (j === i ? { ...g, ...patch } : g)));
  const remove = (i) => {
    if (confirm(`'${groups[i].name}' 그룹을 삭제할까요?`)) onChange(groups.filter((_, j) => j !== i));
  };
  const add = () => {
    if (!newName.trim()) return;
    onChange([...groups, { id: "", name: newName.trim(), icon: "🔖", description: "", keywords: [],
      contextTerms: [], minTerms: 2, scheduled: true }]);
    setNewName("");
  };
  return (
    <>
      <div className="kg-grid">
        {groups.map((g, i) => (
          <div key={g.id || `new-${i}`} className="kg-card on">
            <div className="kg-head">
              <input className="kg-icon-input" value={g.icon || ""} maxLength={4} title="아이콘(이모지)"
                onChange={(e) => update(i, { icon: e.target.value })} />
              <div className="kg-title grow">
                <input type="text" value={g.name} onChange={(e) => update(i, { name: e.target.value })} />
                <input type="text" className="small" placeholder="설명" value={g.description || ""}
                  onChange={(e) => update(i, { description: e.target.value })} />
              </div>
              <button type="button" className="btn small danger" onClick={() => remove(i)}>삭제</button>
            </div>
            <TermEditor label="검색 키워드" hint="뉴스 검색어 · 그룹 선택 시 일괄 선택" values={g.keywords}
              placeholder="예: 단수, 상수도관 파열" onChange={(v) => update(i, { keywords: v })} />
            <TermEditor label="맥락 단어" hint={`기사에 서로 다른 단어가 ${g.minTerms || 2}개 이상이면 이 그룹 맥락으로 판단`}
              values={g.contextTerms || []} placeholder="예: 급수, 정수장, 수돗물"
              onChange={(v) => update(i, { contextTerms: v })} />
            <div className="row gap wrap small">
              <label className="check"><input type="checkbox" checked={g.scheduled !== false}
                onChange={(e) => update(i, { scheduled: e.target.checked })} /> 예약(자동) 조회에 포함</label>
              <label className="check">맥락 판단 최소 단어 수
                <input type="number" min={1} max={5} value={g.minTerms || 2} style={{ width: 56 }}
                  onChange={(e) => update(i, { minTerms: Number(e.target.value) })} /></label>
            </div>
          </div>
        ))}
      </div>
      <div className="row gap" style={{ marginTop: 10 }}>
        <input type="text" size={24} placeholder="새 그룹 이름 (예: 가뭄 그룹)" value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }} />
        <button type="button" className="btn" onClick={add}>그룹 추가</button>
      </div>
    </>
  );
}

/** 기사의 그룹 맥락 표시 */
export function GroupBadges({ groups, contextMatch, max = 2 }) {
  if (!contextMatch) return <span className="tag ctx-none" title="어느 그룹의 맥락 단어도 충분히 나오지 않음">맥락 불명확</span>;
  return groups.slice(0, max).map((g) => (
    <span key={g.id} className={`tag ctx-group ctx-${g.id}`} title={`맥락 단어: ${g.terms.join(", ")}`}>
      {g.icon} {g.name.replace(/\s*\(.*\)$/, "")}
    </span>
  ));
}
