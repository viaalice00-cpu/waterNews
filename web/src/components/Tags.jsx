import { CAT } from "../utils.js";

export function CategoryTags({ categories }) {
  return (categories || []).map((c) => (
    <span key={c} className={`tag ${c}`}>{CAT[c] || c}</span>
  ));
}

export function StepTag({ step }) {
  return step ? <span className={`tag step-${step}`}>{step}</span> : null;
}

export function RegionTags({ regions, max = 4 }) {
  const byBasin = new Map();
  for (const r of regions || []) {
    if (!byBasin.has(r.basin)) byBasin.set(r.basin, []);
    byBasin.get(r.basin).push(r.region);
  }
  return [...byBasin.entries()].slice(0, max).map(([basin, rs]) => (
    <span key={basin} className="tag region" title={rs.join(", ")}>
      {basin} · {rs.slice(0, 2).join(", ")}{rs.length > 2 ? ` 외 ${rs.length - 2}` : ""}
    </span>
  ));
}

/** 키워드를 <mark>로 강조 (문자열 분할 방식이라 HTML 주입 없음) */
export function Highlight({ text, words }) {
  const list = [...new Set((words || []).filter(Boolean))].sort((a, b) => b.length - a.length);
  if (!list.length || !text) return text || "";
  const re = new RegExp(`(${list.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
  return text.split(re).map((part, i) => (i % 2 ? <mark key={i}>{part}</mark> : part));
}

export function BasinChecks({ basins, selected, onChange }) {
  if (!basins.length) return <span className="muted small">유역 없음</span>;
  const toggle = (id, on) => {
    const next = new Set(selected);
    on ? next.add(id) : next.delete(id);
    onChange(next);
  };
  return (
    <div className="checks">
      {basins.map((b) => (
        <label key={b.id} className="check">
          <input type="checkbox" checked={selected.has(b.id)} onChange={(e) => toggle(b.id, e.target.checked)} />
          {b.name}
        </label>
      ))}
    </div>
  );
}
