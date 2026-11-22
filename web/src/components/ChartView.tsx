// Step 1: the chart the agent read. Every note and record for the review period, readable in full.
import { useState } from "react";
import { disciplineOf, longDate, shortDate } from "../lib";
import type { Bundle, Note } from "../types";
import { RecordView } from "./EvidencePane";
import WindowStrip from "./WindowStrip";

const RECORDS = [
  ["record:vitals", "Weight and blood pressure"],
  ["record:encounters", "ED visits and hospital stays"],
  ["record:medications", "Medication changes"],
  ["record:immunizations", "Immunizations"],
] as const;

export default function ChartView({ bundle, cited }: { bundle: Bundle; cited: Set<string> }) {
  const p = bundle.participant;
  const [onlyCited, setOnlyCited] = useState(false);
  const [focus, setFocus] = useState<string | null>(null);
  const shown = onlyCited ? bundle.notes.filter((n) => cited.has(n.id)) : bundle.notes;
  const citedCount = bundle.notes.filter((n) => cited.has(n.id)).length;

  const jump = (id: string) => {
    setOnlyCited(false);
    setFocus(id);
    requestAnimationFrame(() => document.getElementById(`note-${id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }));
  };

  return (
    <div className="chart-view">
      <p className="step-lead">
        This is {p.first_name}’s chart from {longDate(p.window_start)} to {longDate(p.review_date)}, the period
        since the last team review: {bundle.notes.length} notes written by the care team, plus the structured
        records on the right. It is the same information the agent could look up, and all of it is synthetic.
      </p>

      <WindowStrip windowStart={p.window_start} reviewDate={p.review_date} notes={bundle.notes} cited={cited}
                   selectedNote={focus} onSelect={jump} />

      <div className="chart-grid">
        <section aria-labelledby="notes-heading">
          <div className="chart-notes-head">
            <h2 id="notes-heading" className="section-title">Care team notes</h2>
            <label className="toggle">
              <input type="checkbox" checked={onlyCited} onChange={(e) => setOnlyCited(e.target.checked)} />
              Only the {citedCount} the brief cites
            </label>
          </div>
          <p className="chart-key">
            <span className="cited-tag">Cited in the brief</span> marks the notes the agent used as evidence.
          </p>
          <ol className="chart-notes">
            {shown.map((n) => <ChartNote key={n.id} note={n} cited={cited.has(n.id)} focused={focus === n.id} />)}
          </ol>
        </section>

        <aside className="chart-side" aria-label={`About ${p.first_name}`}>
          <section className="side-block">
            <h2 className="section-title">About {p.first_name}</h2>
            <p>{p.age}, {p.sex === "F" ? "female" : "male"}, {p.city}. Enrolled in PACE {longDate(p.enrollment_date)}.</p>
            <h3>Conditions</h3>
            <ul>{p.conditions.map((c) => <li key={c.description}>{c.description}</li>)}</ul>
            <h3>Medications</h3>
            <ul>{p.active_medications.map((m) => <li key={m.description}>{m.description}</li>)}</ul>
            {p.allergies.length > 0 && (
              <>
                <h3>Allergies</h3>
                <ul>{p.allergies.map((a) => <li key={a.description}>{a.description}{a.reaction ? ` (${a.reaction})` : ""}</li>)}</ul>
              </>
            )}
          </section>
          {RECORDS.map(([cite, title]) => (
            <section key={cite} className="side-block">
              <h2 className="section-title">
                {title}
                {cited.has(cite) && <span className="cited-tag">Cited in the brief</span>}
              </h2>
              <RecordView bundle={bundle} cite={cite} />
            </section>
          ))}
        </aside>
      </div>
    </div>
  );
}

function ChartNote({ note, cited, focused }: { note: Note; cited: boolean; focused: boolean }) {
  const d = disciplineOf(note.author_role);
  return (
    <li id={`note-${note.id}`} className={`chart-note d-border-${d}${cited ? " is-cited" : ""}${focused ? " is-focused" : ""}`}>
      <p className="chart-note-meta">
        <time dateTime={note.note_date}>{shortDate(note.note_date)}</time>
        <span className="chart-note-role">{note.author_role}</span>
        <span className="chart-note-type">{note.note_type}</span>
        {cited && <span className="cited-tag">Cited in the brief</span>}
      </p>
      <p className="chart-note-text">{note.text}</p>
    </li>
  );
}
