import { CATEGORY_LABELS, RECORD_LABELS, disciplineOf, highlightSentences, longDate, shortDate } from "../lib";
import type { BriefItem, Bundle, Note } from "../types";

interface Props {
  bundle: Bundle;
  notes: Map<string, Note>;
  cite: string | null;
  claim: BriefItem | null;
  citedBy: BriefItem[];
  onClose: () => void;
}

export default function EvidencePane({ bundle, notes, cite, claim, citedBy, onClose }: Props) {
  if (!cite) {
    return (
      <div className="evidence-empty">
        <h2>Evidence</h2>
        <p>Select a citation under any line of the brief to read the note or record it comes from.</p>
      </div>
    );
  }
  const note = notes.get(cite);
  return (
    <div className="evidence-body">
      <div className="evidence-top">
        <h2>{note ? "Source note" : RECORD_LABELS[cite] ?? "Source"}</h2>
        <button type="button" className="link-button evidence-close" onClick={onClose}>Close</button>
      </div>
      {note ? <NoteView note={note} claim={claim} /> : <RecordView bundle={bundle} cite={cite} />}
      {citedBy.length > 0 && (
        <p className="cited-by">
          Cited for: {citedBy.map((i) => CATEGORY_LABELS[i.category] ?? i.category).join(", ")}
        </p>
      )}
    </div>
  );
}

function NoteView({ note, claim }: { note: Note; claim: BriefItem | null }) {
  const parts = claim ? highlightSentences(note.text, claim.statement) : [{ text: note.text, match: false }];
  const discipline = disciplineOf(note.author_role);
  return (
    <article className="note">
      <header className={`note-head d-border-${discipline}`}>
        <p className="note-role">{note.author_role}</p>
        <p className="note-meta">
          {note.note_type}, {longDate(note.note_date)}
        </p>
      </header>
      <p className="note-text">
        {parts.map((p, i) => (p.match ? <mark key={i}>{p.text}</mark> : <span key={i}>{p.text}</span>))}
      </p>
      {claim && parts.some((p) => p.match) && (
        <p className="note-hint">Highlighted: the sentences that share the most detail with the selected line.</p>
      )}
      <p className="note-id">Note {note.id}</p>
    </article>
  );
}

function RecordView({ bundle, cite }: { bundle: Bundle; cite: string }) {
  const r = bundle.records;
  if (cite === "record:vitals") {
    const w = r["record:vitals"].weight;
    const bp = r["record:vitals"].blood_pressure;
    return (
      <div className="record">
        {w && w.readings.length > 0 && (
          <>
            <h3>Weight</h3>
            <Sparkline values={w.readings.map((x) => x.lb)} label="Weight in pounds" />
            <table>
              <tbody>
                {w.readings.map((x) => (
                  <tr key={x.obs_date}><th scope="row">{shortDate(x.obs_date)}</th><td>{x.lb} lb</td><td>{x.kg} kg</td></tr>
                ))}
              </tbody>
            </table>
            {w.change && (
              <p className="record-sum">
                Change: {w.change.lb > 0 ? "+" : ""}{w.change.lb} lb ({w.change.percent > 0 ? "+" : ""}{w.change.percent}%)
              </p>
            )}
          </>
        )}
        {bp && bp.readings.length > 0 && (
          <>
            <h3>Blood pressure</h3>
            <table>
              <tbody>
                {bp.readings.map((x) => {
                  const high = x.systolic >= 140 || x.diastolic >= 90;
                  return (
                    <tr key={x.obs_date} className={high ? "is-high" : undefined}>
                      <th scope="row">{shortDate(x.obs_date)}</th>
                      <td>{x.systolic}/{x.diastolic}</td>
                      <td>{high ? "Elevated" : ""}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </div>
    );
  }
  if (cite === "record:encounters") {
    const list = r["record:encounters"];
    return (
      <div className="record">
        {list.length === 0 ? <p>No ED visits or admissions since the last review.</p> : (
          <ul>{list.map((e) => <li key={e.id}><strong>{longDate(e.start_date)}</strong>: {e.description}{e.reason ? `, ${e.reason}` : ""}</li>)}</ul>
        )}
      </div>
    );
  }
  if (cite === "record:medications") {
    const m = r["record:medications"];
    return (
      <div className="record">
        <h3>Started</h3>
        {m.started.length === 0 ? <p>None since the last review.</p> : (
          <ul>{m.started.map((x) => <li key={x.description}>{x.description}, {shortDate(x.start_date)}{x.note ? `. ${x.note}` : ""}</li>)}</ul>
        )}
        <h3>Stopped</h3>
        {m.stopped.length === 0 ? <p>None since the last review.</p> : (
          <ul>{m.stopped.map((x) => <li key={x.description}>{x.description}, {x.stop_date ? shortDate(x.stop_date) : ""}</li>)}</ul>
        )}
      </div>
    );
  }
  if (cite === "record:immunizations") {
    const im = r["record:immunizations"];
    return (
      <div className="record">
        <p className="record-sum">
          {im.flu_vaccine_this_season
            ? "Flu vaccine documented this season."
            : `No flu vaccine documented since ${longDate(im.flu_season_start)}.`}
        </p>
        <ul>{im.records_last_two_years.map((x, i) => <li key={i}>{longDate(x.imm_date)}: {x.description}</li>)}</ul>
      </div>
    );
  }
  return <p>This citation does not point to a known note or record.</p>;
}

function Sparkline({ values, label }: { values: number[]; label: string }) {
  if (values.length < 2) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 200},${50 - ((v - min) / span) * 44 - 3}`).join(" ");
  return (
    <svg viewBox="0 0 200 50" className="sparkline" role="img" aria-label={`${label}: ${values.join(", ")}`}>
      <polyline points={pts} />
    </svg>
  );
}
