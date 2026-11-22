// Review decisions live in the visitor's browser. This is a demo: a real deployment would store them,
// with the signed-in clinician, in the database behind an audited API.
import { useCallback, useEffect, useState } from "react";

export type Decision =
  | { status: "approved" }
  | { status: "edited"; text: string }
  | { status: "rejected"; reason: string };

export interface AuditEvent {
  at: string;
  action: string;
  detail?: string;
}

export interface ReviewState {
  decisions: Record<number, Decision>;
  approvedAt: string | null;
  events: AuditEvent[];
}

const EMPTY: ReviewState = { decisions: {}, approvedAt: null, events: [] };
const keyFor = (briefKey: string) => `idt-review:${briefKey}`;

function read(briefKey: string): ReviewState {
  try {
    const raw = localStorage.getItem(keyFor(briefKey));
    return raw ? { ...EMPTY, ...JSON.parse(raw) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function write(briefKey: string, state: ReviewState) {
  try {
    localStorage.setItem(keyFor(briefKey), JSON.stringify(state));
  } catch {
    /* storage unavailable: the review still works for this visit */
  }
}

export function reviewStatus(briefKey: string, itemCount: number): "not_started" | "in_review" | "approved" {
  const s = read(briefKey);
  if (s.approvedAt) return "approved";
  return Object.keys(s.decisions).length > 0 || itemCount === 0 && s.events.length > 0 ? "in_review" : "not_started";
}

export function useReview(briefKey: string) {
  const [state, setState] = useState<ReviewState>(() => read(briefKey));
  useEffect(() => setState(read(briefKey)), [briefKey]);

  const update = useCallback(
    (fn: (s: ReviewState) => ReviewState) =>
      setState((prev) => {
        const next = fn(prev);
        write(briefKey, next);
        return next;
      }),
    [briefKey],
  );

  const log = (s: ReviewState, action: string, detail?: string): ReviewState => ({
    ...s,
    events: [{ at: new Date().toISOString(), action, detail }, ...s.events],
  });

  return {
    state,
    decide: (index: number, decision: Decision, label: string) =>
      update((s) => {
        const verb = decision.status === "approved" ? "Approved" : decision.status === "edited" ? "Edited" : "Rejected";
        const detail = decision.status === "rejected" && decision.reason ? `${label}. Reason: ${decision.reason}` : label;
        return log({ ...s, approvedAt: null, decisions: { ...s.decisions, [index]: decision } }, `${verb} item`, detail);
      }),
    undo: (index: number, label: string) =>
      update((s) => {
        const decisions = { ...s.decisions };
        delete decisions[index];
        return log({ ...s, approvedAt: null, decisions }, "Reopened item", label);
      }),
    approveBrief: () => update((s) => log({ ...s, approvedAt: new Date().toISOString() }, "Approved brief")),
    reset: () => update(() => log(EMPTY, "Started a new review")),
  };
}
