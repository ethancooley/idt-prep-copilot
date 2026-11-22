// Small hand-built charts for the dashboard. Thin marks, one hue per job, hover and keyboard tooltips that
// never gate a value (every value is also printed or in a table), and text in ink, never in the data color.
import { createContext, useContext, useState, type ReactNode } from "react";
import type { Severity } from "../types";

// ---------------------------------------------------------------- tooltip

interface Tip { x: number; y: number; value: string; label: string }
const TipContext = createContext<(t: Tip | null) => void>(() => {});

/** Wrap a chart so its marks can show a tooltip positioned relative to the wrapper. */
export function TipFrame({ children, className = "" }: { children: ReactNode; className?: string }) {
  const [tip, setTip] = useState<Tip | null>(null);
  return (
    <TipContext.Provider value={setTip}>
      <div className={`tip-frame ${className}`} onPointerLeave={() => setTip(null)}>
        {children}
        {tip && (
          <div className="tip" role="presentation" style={{ left: tip.x, top: tip.y }}>
            <strong>{tip.value}</strong>
            <span>{tip.label}</span>
          </div>
        )}
      </div>
    </TipContext.Provider>
  );
}

/** Props that make any element a tooltip target, by pointer or keyboard focus. */
export function useTip(value: string, label: string) {
  const setTip = useContext(TipContext);
  const show = (el: Element) => {
    const frame = el.closest(".tip-frame")!.getBoundingClientRect();
    const r = el.getBoundingClientRect();
    setTip({ x: r.left - frame.left + r.width / 2, y: r.top - frame.top, value, label });
  };
  return {
    onPointerEnter: (e: React.PointerEvent) => show(e.currentTarget),
    onFocus: (e: React.FocusEvent) => show(e.currentTarget),
    onBlur: () => setTip(null),
  };
}

// ---------------------------------------------------------------- severity

export const SEVERITY_LABEL: Record<Severity, string> = { high: "High", medium: "Medium", low: "Low" };

/** Severity is a status: a colored dot plus the word, never color alone. */
export function SeverityTag({ severity, count }: { severity: Severity; count?: number }) {
  return (
    <span className={`sev-tag sev-${severity}`}>
      <i aria-hidden="true" />
      {count !== undefined ? `${count} ${severity}` : SEVERITY_LABEL[severity]}
    </span>
  );
}

// ---------------------------------------------------------------- ranked horizontal bars

export interface Bar { key: string; label: string; value: number; display?: string; detail?: string }

export function BarList({ bars, max, onSelect, selected, unit }: {
  bars: Bar[]; max?: number; onSelect?: (key: string) => void; selected?: string | null; unit: string;
}) {
  const top = max ?? Math.max(1, ...bars.map((b) => b.value));
  return (
    <TipFrame>
      <ol className="barlist">
        {bars.map((b) => <BarRow key={b.key} bar={b} top={top} unit={unit} onSelect={onSelect} selected={selected === b.key} />)}
      </ol>
    </TipFrame>
  );
}

function BarRow({ bar, top, unit, onSelect, selected }: {
  bar: Bar; top: number; unit: string; onSelect?: (key: string) => void; selected: boolean;
}) {
  const tip = useTip(bar.display ?? String(bar.value), bar.detail ?? `${bar.label}, ${unit}`);
  const body = (
    <>
      <span className="barlist-label">{bar.label}</span>
      <span className="barlist-track" aria-hidden="true">
        <span className="barlist-bar" style={{ width: `${(bar.value / top) * 100}%` }} />
      </span>
      <span className="barlist-value">{bar.display ?? bar.value}</span>
    </>
  );
  return (
    <li className={selected ? "is-selected" : undefined}>
      {onSelect ? (
        <button type="button" className="barlist-row" aria-pressed={selected} {...tip}
                aria-label={`${bar.label}: ${bar.display ?? bar.value} ${unit}. Filter the queue`}
                onClick={() => onSelect(bar.key)}>
          {body}
        </button>
      ) : (
        <div className="barlist-row" tabIndex={0} {...tip} aria-label={`${bar.label}: ${bar.display ?? bar.value} ${unit}`}>
          {body}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------- columns (a histogram)

export function Histogram({ values, bin, unit, format, label }: {
  values: number[]; bin: number; unit: string; format: (lo: number, hi: number) => string; label: string;
}) {
  if (!values.length) return <p className="chart-empty">No runs to show yet.</p>;
  const lo = Math.floor(Math.min(...values) / bin) * bin;
  const hi = Math.floor(Math.max(...values) / bin) * bin + bin;
  const bins: { from: number; to: number; n: number }[] = [];
  for (let b = lo; b < hi; b += bin) bins.push({ from: b, to: b + bin, n: values.filter((v) => v >= b && v < b + bin).length });
  const top = Math.max(...bins.map((b) => b.n));
  const ticks = [0, Math.ceil(top / 2), top].filter((t, i, a) => a.indexOf(t) === i);
  return (
    <figure className="histogram" aria-label={label}>
      <TipFrame>
        <div className="histo-plot">
          <div className="histo-grid" aria-hidden="true">
            {ticks.map((t) => <span key={t} style={{ bottom: `${(t / top) * 100}%` }}><em>{t}</em></span>)}
          </div>
          <div className="histo-cols">
            {bins.map((b) => <Column key={b.from} n={b.n} top={top} label={`${format(b.from, b.to)}`} unit={unit} />)}
          </div>
        </div>
      </TipFrame>
      <div className="histo-axis" aria-hidden="true">
        <span>{format(lo, lo)}</span>
        <span>{format(hi, hi)}</span>
      </div>
      <details className="chart-table">
        <summary>Show as a table</summary>
        <table>
          <thead><tr><th scope="col">Range</th><th scope="col">{unit}</th></tr></thead>
          <tbody>{bins.map((b) => <tr key={b.from}><td>{format(b.from, b.to)}</td><td>{b.n}</td></tr>)}</tbody>
        </table>
      </details>
    </figure>
  );
}

function Column({ n, top, label, unit }: { n: number; top: number; label: string; unit: string }) {
  const tip = useTip(`${n} ${unit}`, label);
  return (
    <span className="histo-col" tabIndex={0} {...tip} aria-label={`${label}: ${n} ${unit}`}>
      <span style={{ height: `${(n / top) * 100}%` }} />
    </span>
  );
}

// ---------------------------------------------------------------- one whole, split into parts

export function SegmentedBar({ parts, label }: {
  parts: { key: Severity; label: string; value: number }[]; label: string;
}) {
  const total = parts.reduce((a, p) => a + p.value, 0) || 1;
  return (
    <TipFrame className="segbar-frame">
      <div className="segbar" role="img" aria-label={`${label}: ${parts.map((p) => `${p.value} ${p.label.toLowerCase()}`).join(", ")}`}>
        {parts.filter((p) => p.value > 0).map((p) => <Segment key={p.key} part={p} share={p.value / total} />)}
      </div>
      <ul className="segbar-legend">
        {parts.map((p) => (
          <li key={p.key}><i className={`sev-dot sev-${p.key}`} aria-hidden="true" />{p.label}</li>
        ))}
      </ul>
    </TipFrame>
  );
}

function Segment({ part, share }: { part: { key: Severity; label: string; value: number }; share: number }) {
  const tip = useTip(`${part.value} ${part.label.toLowerCase()}`, `${Math.round(share * 100)}% of all lines`);
  return (
    <span className={`segbar-part sev-fill-${part.key}`} style={{ flexGrow: share }} tabIndex={0} {...tip}>
      {share >= 0.12 && <b>{part.value}</b>}
    </span>
  );
}

// ---------------------------------------------------------------- a thin meter

export function Meter({ value, max, label }: { value: number; max: number; label: string }) {
  return (
    <span className="meter" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} aria-label={label}>
      <span style={{ width: `${max ? (value / max) * 100 : 0}%` }} />
    </span>
  );
}

// ---------------------------------------------------------------- the evidence timeline (queue rows)

/** The review window in miniature: one tick per note, with a highlighter mark on each note the brief cites. */
export function EvidenceTimeline({ timeline, days }: { timeline: [number, number][]; days: number }) {
  const W = 156, H = 26, PAD = 3;
  const x = (d: number) => PAD + (Math.min(Math.max(d, 0), days) / days) * (W - 2 * PAD);
  const cited = timeline.filter(([, c]) => c).length;
  return (
    <svg className="evtl" viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img"
         aria-label={`${timeline.length} notes in the review window, ${cited} cited in the brief`}>
      <line x1={PAD} x2={W - PAD} y1={H - 4} y2={H - 4} className="evtl-axis" />
      {timeline.filter(([, c]) => c).map(([d], i) => (
        <rect key={`m${i}`} x={x(d) - 4} y={2} width={8} height={H - 6} rx={1.5} className="evtl-mark" />
      ))}
      {timeline.map(([d, c], i) => (
        <rect key={i} x={x(d) - 1} y={c ? 5 : 11} width={2} height={c ? H - 9 : H - 15} rx={1}
              className={c ? "evtl-tick is-cited" : "evtl-tick"} />
      ))}
    </svg>
  );
}
