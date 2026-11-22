import { Link } from "react-router-dom";
import { CATEGORY_LABELS, longDate, pct } from "../lib";
import { reviewStatus } from "../review";
import type { Index } from "../types";

const STATUS_LABEL = { not_started: "Not reviewed", in_review: "In review", approved: "Approved" } as const;

export default function Queue({ index }: { index: Index }) {
  const ev = index.evaluation;
  const people = index.participants;
  const reviewDate = index.review_date ? longDate(index.review_date) : "the next review";

  return (
    <div className="page queue-page">
      <section className="intro">
        <h1>Know what changed before the IDT meeting.</h1>
        <p className="lede">
          IDT Prep reads each participant's chart since their last interdisciplinary team review, drafts a
          one-page brief, and links every line to the note it came from. A clinician checks each line and
          approves the brief before the meeting.
        </p>
        {ev ? (
          <p className="proof">
            Tested on {ev.participants} synthetic participants with known answers, the briefs caught{" "}
            <strong>{pct(ev.recall)}</strong> of the changes the team needed to hear about, including{" "}
            <strong>{pct(ev.high_severity_recall)}</strong> of high-severity ones, and reported{" "}
            {ev.distractor_violations === 0 ? "no" : ev.distractor_violations} old events as new. Each brief
            took about {Math.round(ev.seconds_median)} seconds and cost about ${ev.cost_usd_per_brief.toFixed(2)}.{" "}
            <Link to="/how-it-works">How it was tested</Link>
          </p>
        ) : index.source === "sample" ? (
          <p className="proof">
            These are sample briefs built from the test answer keys so the interface can be explored. Run the
            agent to replace them with briefs drafted by Claude.
          </p>
        ) : null}
      </section>

      <section aria-labelledby="flow-heading" className="flow">
        <h2 id="flow-heading">Open any participant to see four things</h2>
        <ol className="flow-steps">
          <li>
            <span className="story-num" aria-hidden="true">1</span>
            <strong>The chart</strong>
            <p>Every note and record from the care team since the last review. This is what the agent had to work with.</p>
          </li>
          <li>
            <span className="story-num" aria-hidden="true">2</span>
            <strong>What the agent did</strong>
            <p>Each step, replayed: its checklist, every chart lookup and what came back, its draft, and the check of every line.</p>
          </li>
          <li>
            <span className="story-num" aria-hidden="true">3</span>
            <strong>The brief</strong>
            <p>What changed and what to discuss, with each line linked to its source, for a clinician to approve or fix.</p>
          </li>
          <li>
            <span className="story-num" aria-hidden="true">4</span>
            <strong>The answer key</strong>
            <p>The events planted in that chart for testing, and whether the brief caught each one.</p>
          </li>
        </ol>
      </section>

      <section aria-labelledby="queue-heading" className="queue">
        <div className="queue-heading">
          <h2 id="queue-heading">Due for review {reviewDate}</h2>
          <p>{people.length} participants, most urgent first</p>
        </div>
        <ol className="queue-list">
          {people.map((p) => {
            const status = reviewStatus(`${p.id}:${index.generated_at}`, p.counts.high + p.counts.medium + p.counts.low);
            return (
              <li key={p.id}>
                <Link to={`/p/${p.id}`} className="queue-row">
                  <span className="queue-name">
                    {p.name}
                    <span className="queue-age">{p.age}</span>
                  </span>
                  <span className="queue-counts" aria-label={`${p.counts.high} high, ${p.counts.medium} medium, ${p.counts.low} low`}>
                    {(["high", "medium", "low"] as const).map((s) =>
                      p.counts[s] ? (
                        <span key={s} className={`count sev-${s}`}>
                          {p.counts[s]} {s}
                        </span>
                      ) : null,
                    )}
                  </span>
                  <span className="queue-flags">
                    {p.flags.length ? p.flags.map((f) => CATEGORY_LABELS[f] ?? f).join(", ") : "No high-severity changes"}
                  </span>
                  <span className={`queue-status status-${status}`}>{STATUS_LABEL[status]}</span>
                </Link>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}
