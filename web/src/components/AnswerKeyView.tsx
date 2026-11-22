// Step 4: the brief checked against the answer key the test generator wrote.
import { Link } from "react-router-dom";
import { CATEGORY_LABELS, disciplineOf, longDate, pct, shortDate } from "../lib";
import type { Bundle, Evaluation, Note } from "../types";

export default function AnswerKeyView({ bundle, evaluation }: { bundle: Bundle; evaluation: Evaluation | null }) {
  const { answer_key: key, brief, participant: p } = bundle;
  if (!key) {
    return <p className="step-lead">There is no answer key for this brief.</p>;
  }
  const notes = new Map<string, Note>([...bundle.notes, ...(bundle.older_notes ?? [])].map((n) => [n.id, n]));
  const caught = key.must_surface.filter((t) => t.caught_by.length).length;
  const leftOut = key.old_events.filter((d) => !d.reported_by.length).length;
  const perfect = caught === key.must_surface.length && leftOut === key.old_events.length;

  return (
    <div className="key-view">
      <p className="step-lead">
        Before the agent ever ran, the test generator planted events in {p.first_name}’s chart and wrote them
        down as an answer key. The agent never sees this key. An event only counts as caught when a line of the
        brief cites a note that proves it, so a line that just sounds right does not count.
      </p>

      <p className={`key-verdict${perfect ? " is-perfect" : ""}`}>
        Caught {caught} of {key.must_surface.length} planted event{key.must_surface.length === 1 ? "" : "s"}
        {key.old_events.length > 0 &&
          `, and left out ${leftOut} of ${key.old_events.length} older event${key.old_events.length === 1 ? "" : "s"} that should not be reported as new`}.
      </p>

      <section aria-labelledby="planted-heading">
        <h2 id="planted-heading" className="section-title">Events planted in the review period</h2>
        <ol className="key-list">
          {key.must_surface.map((t) => {
            const hit = t.caught_by.length > 0;
            return (
              <li key={t.id} className={`key-item ${hit ? "is-caught" : "is-missed"}`}>
                <p className="key-status">
                  <span className="key-pill">{hit ? "Caught" : "Missed"}</span>
                  <span className={`sev sev-${t.severity}`}>{t.severity}</span>
                  <span className="item-category">{CATEGORY_LABELS[t.category] ?? t.category}</span>
                  {t.event_date && <span className="key-date">{longDate(t.event_date)}</span>}
                </p>
                <p className="key-summary">{t.summary}</p>
                {hit && (
                  <div className="key-match">
                    <p className="key-label">The brief’s line</p>
                    {t.caught_by.map((i) => <blockquote key={i}>{brief.items[i]?.statement}</blockquote>)}
                  </div>
                )}
                <ProofNotes ids={t.note_ids} notes={notes} label={t.note_ids.length ? "Notes that prove it" : ""} />
                {!t.note_ids.length && <p className="key-label">Proved by the immunization record: no flu vaccine this season.</p>}
              </li>
            );
          })}
        </ol>
      </section>

      {key.old_events.length > 0 && (
        <section aria-labelledby="old-heading">
          <h2 id="old-heading" className="section-title">Older events to leave out</h2>
          <p className="step-sub">
            These happened before {longDate(key.window_start)} and were covered at the last review. Bringing them
            up again as new would waste the team’s time, so the test checks that the brief leaves them out.
          </p>
          <ol className="key-list">
            {key.old_events.map((d) => {
              const ok = d.reported_by.length === 0;
              return (
                <li key={d.id} className={`key-item ${ok ? "is-caught" : "is-missed"}`}>
                  <p className="key-status">
                    <span className="key-pill">{ok ? "Left out" : "Reported as new"}</span>
                  </p>
                  <p className="key-summary">{d.reason}</p>
                  {!ok && d.reported_by.map((i) => <blockquote key={i}>{brief.items[i]?.statement}</blockquote>)}
                  <ProofNotes ids={d.note_ids} notes={notes} label="The older note" />
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {evaluation && (
        <p className="key-overall">
          Across all {evaluation.participants} participants, the briefs caught {pct(evaluation.recall)} of planted
          events, including {pct(evaluation.high_severity_recall)} of high-severity ones, and reported{" "}
          {evaluation.distractor_violations === 0 ? "no" : evaluation.distractor_violations} older events as new.{" "}
          <Link to="/how-it-works">How the test works</Link>
        </p>
      )}
    </div>
  );
}

function ProofNotes({ ids, notes, label }: { ids: string[]; notes: Map<string, Note>; label: string }) {
  const found = ids.map((id) => notes.get(id)).filter((n): n is Note => !!n);
  if (!found.length) return null;
  return (
    <div className="proof-notes">
      <p className="key-label">{label}</p>
      {found.map((n) => (
        <details key={n.id} className={`proof-note d-border-${disciplineOf(n.author_role)}`}>
          <summary>{shortDate(n.note_date)}, {n.author_role}, {n.note_type}</summary>
          <p>{n.text}</p>
        </details>
      ))}
    </div>
  );
}
