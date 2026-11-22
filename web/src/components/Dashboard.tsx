import { useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CATEGORY_LABELS, longDate, pct, shortDate } from "../lib";
import { reviewStatus } from "../review";
import type { Index, QueueEntry, Severity } from "../types";
import { BarList, EvidenceTimeline, Histogram, Meter, SegmentedBar, SeverityTag } from "./charts";

type Status = "not_started" | "in_review" | "approved";
const STATUS_LABEL: Record<Status, string> = { not_started: "Not reviewed", in_review: "In review", approved: "Approved" };
const STATUS_ORDER: Record<Status, number> = { not_started: 0, in_review: 1, approved: 2 };
type SortKey = "priority" | "name" | "evidence" | "status";

const priority = (p: QueueEntry) => p.counts.high * 100 + p.counts.medium * 10 + p.counts.low;
const median = (xs: number[]) => {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2;
};

export default function Dashboard({ index }: { index: Index }) {
  const people = index.participants;
  const ev = index.evaluation;
  const days = index.window_days ?? 90;
  const tableRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  const statuses = useMemo(() => Object.fromEntries(people.map((p) => [
    p.id, reviewStatus(`${p.id}:${index.generated_at}`, p.items ?? 0) as Status,
  ])), [people, index.generated_at]);

  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState<"any" | "high" | "medium">("any");
  const [status, setStatus] = useState<"any" | Status>("any");
  const [category, setCategory] = useState<string>("any");
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "priority", desc: true });

  // ------------------------------------------------------------ cohort figures (unfiltered)
  const needDiscussion = people.filter((p) => p.counts.high > 0).length;
  const lines = (["high", "medium", "low"] as Severity[]).map((s) => ({
    key: s, label: s[0].toUpperCase() + s.slice(1), value: people.reduce((a, p) => a + p.counts[s], 0),
  }));
  const totalLines = lines.reduce((a, l) => a + l.value, 0);
  const approved = people.filter((p) => statuses[p.id] === "approved").length;
  const started = people.filter((p) => statuses[p.id] !== "not_started").length;
  const byCategory = useMemo(() => {
    const n: Record<string, number> = {};
    for (const p of people) for (const c of p.categories ?? p.flags) n[c] = (n[c] ?? 0) + 1;
    return Object.entries(n).sort((a, b) => b[1] - a[1]).map(([key, value]) => ({
      key, value, label: CATEGORY_LABELS[key] ?? key,
      detail: `${CATEGORY_LABELS[key] ?? key}: ${value} of ${people.length} participants`,
    }));
  }, [people]);
  const seconds = people.map((p) => p.seconds).filter((s): s is number => !!s);
  const costs = people.map((p) => p.cost_usd).filter((c): c is number => !!c);
  const lookups = people.map((p) => p.lookups ?? 0).filter(Boolean);
  const cited = people.reduce((a, p) => a + (p.cited_notes ?? 0), 0);
  const notesRead = people.reduce((a, p) => a + (p.notes ?? 0), 0);

  // ------------------------------------------------------------ the filtered, sorted queue
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = people.filter((p) =>
      (!q || p.name.toLowerCase().includes(q) || p.headline.toLowerCase().includes(q)) &&
      (severity === "any" || (severity === "high" ? p.counts.high > 0 : p.counts.high + p.counts.medium > 0)) &&
      (status === "any" || statuses[p.id] === status) &&
      (category === "any" || (p.categories ?? p.flags).includes(category)));
    const value = (p: QueueEntry): number | string => {
      switch (sort.key) {
        case "name": return p.name;
        case "evidence": return p.cited_notes ?? 0;
        case "status": return STATUS_ORDER[statuses[p.id]];
        default: return priority(p);
      }
    };
    return [...rows].sort((a, b) => {
      const va = value(a), vb = value(b);
      const c = typeof va === "string" ? va.localeCompare(vb as string) : (va as number) - (vb as number);
      return (sort.desc ? -c : c) || a.name.localeCompare(b.name);
    });
  }, [people, query, severity, status, category, sort, statuses]);

  const filtered = query || severity !== "any" || status !== "any" || category !== "any";
  const clear = () => { setQuery(""); setSeverity("any"); setStatus("any"); setCategory("any"); };
  const pickCategory = (key: string) => {
    setCategory((c) => (c === key ? "any" : key));
    requestAnimationFrame(() => tableRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };
  const sortBy = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== "name" }));
  const ariaSort = (key: SortKey) => (sort.key === key ? (sort.desc ? "descending" : "ascending") : "none");

  return (
    <div className="page dashboard">
      <header className="page-head">
        <div>
          <h1>Review queue</h1>
          <p className="page-sub">
            {people.length} participants due for review on {index.review_date ? longDate(index.review_date) : "the next IDT date"}.
            Each brief covers everything since the last review
            {index.window_start ? `, ${shortDate(index.window_start)} onward` : ""}.
          </p>
        </div>
        {index.source === "sample" && (
          <p className="page-flag">Sample briefs built from the answer keys. Run the agent to replace them.</p>
        )}
      </header>

      {/* ------------------------------------------------------------ stat tiles */}
      <section className="tiles" aria-label="This review at a glance">
        <div className="tile tile-hero">
          <p className="tile-label">Need team discussion</p>
          <p className="tile-hero-value">{needDiscussion}</p>
          <p className="tile-note">of {people.length} participants have at least one high-severity change</p>
        </div>
        <div className="tile tile-wide">
          <p className="tile-label">Lines in the briefs</p>
          <p className="tile-value">{totalLines}</p>
          <SegmentedBar parts={lines} label="Lines by severity" />
        </div>
        <div className="tile">
          <p className="tile-label">Approved by you</p>
          <p className="tile-value">{approved}<span className="tile-of"> of {people.length}</span></p>
          <Meter value={approved} max={people.length} label="Briefs approved" />
          <p className="tile-note">{started - approved > 0 ? `${started - approved} in review. ` : ""}Saved in this browser</p>
        </div>
        <Link to="/evaluation" className="tile tile-link">
          <p className="tile-label">Answer-key recall</p>
          <p className="tile-value">{ev ? pct(ev.recall) : "Not run"}</p>
          <p className="tile-note">
            {ev ? `${pct(ev.high_severity_recall)} of high-severity events. ${ev.distractor_violations === 0 ? "No" : ev.distractor_violations} old events reported as new` : "Evaluate the agent to see recall"}
          </p>
        </Link>
      </section>

      {/* ------------------------------------------------------------ overview panels */}
      <div className="overview">
        <section className="panel" aria-labelledby="concerns-heading">
          <div className="panel-head">
            <h2 id="concerns-heading">Concerns across the cohort</h2>
            <p>Participants with each kind of change. Select one to filter the queue.</p>
          </div>
          <BarList bars={byCategory} max={people.length} unit="participants" onSelect={pickCategory}
                   selected={category === "any" ? null : category} />
        </section>

        <section className="panel" aria-labelledby="runs-heading">
          <div className="panel-head">
            <h2 id="runs-heading">How the agent ran</h2>
            <p>One run per participant: plan, read the chart, draft, and check every line.</p>
          </div>
          <dl className="facts">
            <div><dt>Notes read</dt><dd>{notesRead.toLocaleString()}</dd><dd className="facts-sub">{cited} cited as evidence</dd></div>
            <div><dt>Median time</dt><dd>{seconds.length ? `${Math.round(median(seconds))} s` : "–"}</dd><dd className="facts-sub">{ev?.seconds_p90 ? `90% under ${Math.round(ev.seconds_p90)} s` : "per brief"}</dd></div>
            <div><dt>Cost per brief</dt><dd>{costs.length ? `$${median(costs).toFixed(3)}` : "–"}</dd><dd className="facts-sub">median</dd></div>
            <div><dt>Chart lookups</dt><dd>{lookups.length ? Math.round(median(lookups)) : "–"}</dd><dd className="facts-sub">median per brief</dd></div>
          </dl>
          <h3 className="panel-sub">Time per brief</h3>
          <Histogram values={seconds} bin={2} unit="briefs" label="Number of briefs by time to generate, in seconds"
                     format={(a, b) => (a === b ? `${a} s` : `${a} to ${b} s`)} />
        </section>
      </div>

      {/* ------------------------------------------------------------ filters, then the queue */}
      <section className="queue-section" aria-labelledby="queue-heading" ref={tableRef}>
        <div className="queue-top">
          <h2 id="queue-heading">Participants</h2>
          <p className="queue-hint">
            Open anyone to see the chart the agent read, a replay of its run, the brief, and how it scored.
          </p>
        </div>

        <div className="filters" role="search" aria-label="Filter participants">
          <label className="filter-search">
            <span className="visually-hidden">Search by name or change</span>
            <input type="search" placeholder="Search name or change" value={query} onChange={(e) => setQuery(e.target.value)} />
          </label>
          <label className="filter">
            <span>Severity</span>
            <select value={severity} onChange={(e) => setSeverity(e.target.value as typeof severity)}>
              <option value="any">Any</option>
              <option value="high">Has a high</option>
              <option value="medium">Medium or higher</option>
            </select>
          </label>
          <label className="filter">
            <span>Concern</span>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="any">Any</option>
              {byCategory.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
          </label>
          <label className="filter">
            <span>Review</span>
            <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)}>
              <option value="any">Any</option>
              {(Object.keys(STATUS_LABEL) as Status[]).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </label>
          <p className="filter-count" aria-live="polite">
            Showing {shown.length} of {people.length}
            {filtered && <button type="button" className="link-button" onClick={clear}>Clear filters</button>}
          </p>
        </div>

        <div className="table-wrap">
          <table className="queue-table">
            <thead>
              <tr>
                <th scope="col" aria-sort={ariaSort("name")}>
                  <button type="button" onClick={() => sortBy("name")}>Participant<SortMark k="name" sort={sort} /></button>
                </th>
                <th scope="col">What changed</th>
                <th scope="col" aria-sort={ariaSort("priority")}>
                  <button type="button" onClick={() => sortBy("priority")}>Severity<SortMark k="priority" sort={sort} /></button>
                </th>
                <th scope="col" aria-sort={ariaSort("evidence")}>
                  <button type="button" onClick={() => sortBy("evidence")}>Evidence<SortMark k="evidence" sort={sort} /></button>
                </th>
                <th scope="col">Answer key</th>
                <th scope="col" aria-sort={ariaSort("status")}>
                  <button type="button" onClick={() => sortBy("status")}>Review<SortMark k="status" sort={sort} /></button>
                </th>
              </tr>
            </thead>
            <tbody>
              {shown.map((p) => (
                <tr key={p.id} onClick={(e) => {
                  if (!(e.target as HTMLElement).closest("a")) navigate(`/p/${p.id}`);
                }}>
                  <td data-label="Participant">
                    <Link to={`/p/${p.id}`} className="row-link">{p.name}</Link>
                    <span className="cell-sub">{p.age}, {p.sex === "F" ? "female" : "male"}, {p.city}</span>
                  </td>
                  <td data-label="What changed" className="cell-headline"><span>{p.headline}</span></td>
                  <td data-label="Severity">
                    <span className="sev-stack">
                      {(["high", "medium", "low"] as Severity[]).map((s) => p.counts[s] ? <SeverityTag key={s} severity={s} count={p.counts[s]} /> : null)}
                      {p.counts.high + p.counts.medium + p.counts.low === 0 && <span className="cell-sub">No changes</span>}
                    </span>
                  </td>
                  <td data-label="Evidence">
                    {p.timeline && <EvidenceTimeline timeline={p.timeline} days={days} />}
                    <span className="cell-sub">{p.cited_notes ?? 0} of {p.notes ?? 0} notes cited</span>
                  </td>
                  <td data-label="Answer key">
                    {p.planted !== undefined ? (
                      <span className={`key-cell${p.caught === p.planted && !p.old_reported ? " is-ok" : " is-miss"}`}>
                        <strong>{p.caught} of {p.planted}</strong>
                        <span className="cell-sub">{p.old_reported ? `${p.old_reported} old event reported` : "caught"}</span>
                      </span>
                    ) : <span className="cell-sub">None</span>}
                  </td>
                  <td data-label="Review">
                    <span className={`review-chip review-${statuses[p.id]}`}>{STATUS_LABEL[statuses[p.id]]}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && (
            <div className="table-empty">
              <p>No participants match these filters.</p>
              <button type="button" className="button-quiet" onClick={clear}>Clear filters</button>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function SortMark({ k, sort }: { k: SortKey; sort: { key: SortKey; desc: boolean } }) {
  const active = sort.key === k;
  return (
    <svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true" className={`sort-mark${active ? " is-active" : ""}`}>
      <path d={active && !sort.desc ? "M2 6.5 5 3.5 8 6.5" : "M2 3.5 5 6.5 8 3.5"} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
