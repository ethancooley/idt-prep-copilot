import { DISCIPLINE_LABELS, dayNumber, disciplineOf, shortDate, shortRole, type Discipline } from "../lib";
import type { Note } from "../types";

interface Props {
  windowStart: string;
  reviewDate: string;
  notes: Note[];
  cited: Set<string>;
  selectedNote: string | null;
  onSelect: (noteId: string) => void;
}

const W = 1000;
const H = 74;
const PAD = 8;

/** The review window as a strip: one mark per note, colored by discipline. Cited notes stand taller. */
export default function WindowStrip({ windowStart, reviewDate, notes, cited, selectedNote, onSelect }: Props) {
  const start = dayNumber(windowStart);
  const end = dayNumber(reviewDate);
  const x = (iso: string) => PAD + ((dayNumber(iso) - start) / (end - start)) * (W - 2 * PAD);
  const inWindow = notes.filter((n) => n.note_date >= windowStart && n.note_date <= reviewDate);
  const months: string[] = [];
  for (let d = start; d <= end; d++) {
    const iso = new Date(d * 86_400_000).toISOString().slice(0, 10);
    if (iso.endsWith("-01")) months.push(iso);
  }
  const present = [...new Set(inWindow.map((n) => disciplineOf(n.author_role)))] as Discipline[];

  return (
    <figure className="strip">
      <figcaption className="strip-caption">
        <span>
          {inWindow.length} notes since the last review. Taller marks are cited in the brief; select one to read it.
        </span>
        <span className="strip-legend">
          {present.map((d) => (
            <span key={d} className="legend-item">
              <span className={`swatch d-${d}`} aria-hidden="true" />
              {DISCIPLINE_LABELS[d]}
            </span>
          ))}
        </span>
      </figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="strip-svg" role="group"
           aria-label="Notes since the last review">
        <line x1={PAD} x2={W - PAD} y1={52} y2={52} className="strip-axis" />
        {months.map((m) => (
          <line key={m} x1={x(m)} x2={x(m)} y1={46} y2={58} className="strip-tick" />
        ))}
        {inWindow.map((n) => {
          const isCited = cited.has(n.id);
          const isSelected = selectedNote === n.id;
          const cx = x(n.note_date);
          const top = isCited ? 6 : 26;
          return (
            <g key={n.id} className={`strip-note${isSelected ? " is-selected" : ""}`} tabIndex={0} role="button"
               aria-label={`${shortRole(n.author_role)} note, ${shortDate(n.note_date)}${isCited ? ", cited" : ""}`}
               aria-pressed={isSelected}
               onClick={() => onSelect(n.id)}
               onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(n.id))}>
              <title>{`${n.author_role}, ${shortDate(n.note_date)}: ${n.note_type}`}</title>
              {isCited && <rect x={cx - 7} y={top - 3} width={14} height={52 - top + 3} className="strip-cited" rx={2} />}
              <rect x={cx - 2.5} y={top} width={5} height={52 - top} className={`strip-mark d-${disciplineOf(n.author_role)}`} rx={1} />
              <rect x={cx - 9} y={0} width={18} height={60} className="strip-hit" />
            </g>
          );
        })}
      </svg>
      <div className="strip-dates" aria-hidden="true">
        <span className="strip-start">Last review, {shortDate(windowStart)}</span>
        {months.filter((m) => m !== windowStart).map((m) => (
          <span key={m} style={{ left: `${(x(m) / W) * 100}%` }} className="strip-month">{shortDate(m).split(" ")[0]}</span>
        ))}
        <span className="strip-end">Review, {shortDate(reviewDate)}</span>
      </div>
    </figure>
  );
}
