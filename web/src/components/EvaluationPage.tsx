import { Link } from "react-router-dom";
import { CATEGORY_LABELS, longDate, pct } from "../lib";
import type { Index } from "../types";
import { BarList, Histogram } from "./charts";

export default function EvaluationPage({ index }: { index: Index }) {
  const ev = index.evaluation;
  const people = index.participants;
  const scored = people.filter((p) => p.planted !== undefined);
  const generated = index.generated_at.slice(0, 10);

  return (
    <div className="page evaluation">
      <header className="page-head">
        <div>
          <h1>Evaluation</h1>
          <p className="page-sub">
            How the agent scored against answer keys planted in {ev?.participants ?? people.length} synthetic charts.
            Results from the run published {longDate(generated)}.
          </p>
        </div>
      </header>

      {!ev ? (
        <p className="notice">
          Evaluation results appear here after the agent is run against the answer keys. The briefs on this site are
          samples built from those keys.
        </p>
      ) : (
        <>
          <section className="tiles tiles-6" aria-label="Headline results">
            <div className="tile tile-hero">
              <p className="tile-label">Planted events caught</p>
              <p className="tile-hero-value">{pct(ev.recall)}</p>
              <p className="tile-note">credited only when a line cites the note that proves it</p>
            </div>
            <Tile label="High-severity caught" value={pct(ev.high_severity_recall)} note="falls, ED visits, weight loss, new confusion" />
            <Tile label="Briefs that caught everything" value={`${ev.perfect_briefs}`} of={ev.participants} />
            <Tile label="Old events reported as new" value={`${ev.distractor_violations}`} note="events from before the review period" />
            {ev.extra_item_rate !== undefined && (
              <Tile label="Lines not tied to a planted event" value={pct(ev.extra_item_rate)} note={`of ${ev.items_per_brief ?? ""} lines per brief on average`} />
            )}
            {ev.partially_supported_items !== undefined && (
              <Tile label="Lines flagged partly supported" value={`${ev.partially_supported_items}`} note={`${ev.removed_claims} removed as unsupported`} />
            )}
          </section>

          <div className="overview">
            <section className="panel" aria-labelledby="cat-heading">
              <div className="panel-head">
                <h2 id="cat-heading">Recall by kind of event</h2>
                <p>Share of planted events of each kind that a brief caught and cited correctly.</p>
              </div>
              {ev.recall_by_category ? (
                <BarList unit="caught" max={100} bars={Object.entries(ev.recall_by_category)
                  .sort((a, b) => b[1].total - a[1].total)
                  .map(([k, v]) => ({
                    key: k, label: CATEGORY_LABELS[k] ?? k, value: v.recall * 100,
                    display: `${v.caught} of ${v.total}`, detail: `${CATEGORY_LABELS[k] ?? k}: ${pct(v.recall)} caught`,
                  }))} />
              ) : <p className="chart-empty">Not in this run’s results.</p>}
            </section>

            <section className="panel" aria-labelledby="cost-heading">
              <div className="panel-head">
                <h2 id="cost-heading">Time and cost</h2>
                <p>Every brief is one full agent run with two Claude models.</p>
              </div>
              <dl className="facts">
                <div><dt>Median time</dt><dd>{Math.round(ev.seconds_median)} s</dd>{ev.seconds_p90 && <dd className="facts-sub">90% under {Math.round(ev.seconds_p90)} s</dd>}</div>
                <div><dt>Cost per brief</dt><dd>${ev.cost_usd_per_brief.toFixed(3)}</dd>{ev.cost_usd_total && <dd className="facts-sub">${ev.cost_usd_total.toFixed(2)} for all {ev.participants}</dd>}</div>
                <div><dt>Lines per brief</dt><dd>{ev.items_per_brief ?? "–"}</dd><dd className="facts-sub">average</dd></div>
                <div><dt>Errors</dt><dd>{ev.errors ?? 0}</dd><dd className="facts-sub">runs that failed</dd></div>
              </dl>
              <h3 className="panel-sub">Time per brief</h3>
              <Histogram values={people.map((p) => p.seconds).filter((s): s is number => !!s)} bin={2} unit="briefs"
                         label="Number of briefs by time to generate, in seconds"
                         format={(a, b) => (a === b ? `${a} s` : `${a} to ${b} s`)} />
            </section>
          </div>
        </>
      )}

      <section className="panel method" aria-labelledby="method-heading">
        <div className="panel-head">
          <h2 id="method-heading">How the test works</h2>
          <p>The scoring is automatic, so it can be rerun on every change.</p>
        </div>
        <ol className="method-steps">
          <li>
            <strong>Plant events</strong>
            <p>A generator writes 90 days of care team notes for each synthetic participant and plants known events: falls, ED visits, medication changes, weight loss, new confusion, a missing flu vaccine.</p>
          </li>
          <li>
            <strong>Add older events</strong>
            <p>Some charts also mention an event from before the last review. The team already discussed it, so a good brief leaves it out.</p>
          </li>
          <li>
            <strong>Run the agent blind</strong>
            <p>The agent never sees the answer key. It reads the chart through the same read-only tools it uses for any participant.</p>
          </li>
          <li>
            <strong>Score on evidence</strong>
            <p>An event counts as caught only when a line of the brief cites a note that proves it. A line that just sounds right gets no credit.</p>
          </li>
        </ol>
      </section>

      {scored.length > 0 && (
        <section className="queue-section" aria-labelledby="per-heading">
          <div className="queue-top">
            <h2 id="per-heading">Every participant</h2>
            <p className="queue-hint">Open anyone to see their answer key next to the brief.</p>
          </div>
          <div className="table-wrap">
            <table className="queue-table results-table">
              <thead>
                <tr>
                  <th scope="col">Participant</th>
                  <th scope="col" className="num">Planted events caught</th>
                  <th scope="col" className="num">Old events reported</th>
                  <th scope="col" className="num">Lines</th>
                  <th scope="col" className="num">Partly supported</th>
                  <th scope="col" className="num">Time</th>
                  <th scope="col" className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {[...scored].sort((a, b) => a.name.localeCompare(b.name)).map((p) => (
                  <tr key={p.id}>
                    <td data-label="Participant"><Link to={`/p/${p.id}?step=key`} className="row-link">{p.name}</Link></td>
                    <td data-label="Caught" className="num">
                      <span className={p.caught === p.planted ? "num-ok" : "num-miss"}>{p.caught} of {p.planted}</span>
                    </td>
                    <td data-label="Old events" className="num">{p.old_reported ?? 0}</td>
                    <td data-label="Lines" className="num">{p.items ?? "–"}</td>
                    <td data-label="Partly supported" className="num">{p.partial ?? 0}</td>
                    <td data-label="Time" className="num">{p.seconds ? `${p.seconds.toFixed(1)} s` : "–"}</td>
                    <td data-label="Cost" className="num">{p.cost_usd ? `$${p.cost_usd.toFixed(3)}` : "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function Tile({ label, value, of, note }: { label: string; value: string; of?: number; note?: string }) {
  return (
    <div className="tile">
      <p className="tile-label">{label}</p>
      <p className="tile-value">{value}{of !== undefined && <span className="tile-of"> of {of}</span>}</p>
      {note && <p className="tile-note">{note}</p>}
    </div>
  );
}
