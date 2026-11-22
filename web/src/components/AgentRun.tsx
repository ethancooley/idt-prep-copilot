// What the agent did, step by step. Used both for live runs (events arrive over the network) and for
// replaying a saved run (events come from brief.run.trace).
import { CATEGORY_LABELS, shortDate } from "../lib";
import type { AgentEvent, Brief, Severity, ToolArgs, Verdict } from "../types";

// ---------------------------------------------------------------- the run, shaped for display

export interface ToolRow { tool: string; args: ToolArgs; by: string; summary?: string; ok?: boolean }
export interface DraftItem { severity: Severity; category: string; statement: string; verdict?: Verdict; reason?: string }
export type Stage =
  | { kind: "plan"; model?: string; tools: ToolRow[]; checks: string[] }
  | { kind: "gather"; model?: string; attempt: number; tools: ToolRow[] }
  | { kind: "draft"; model?: string; notes: number; headline?: string; items: DraftItem[]; attempt: number }
  | { kind: "verify"; model?: string; count: number; done: boolean; retry: boolean;
      tally?: Record<Verdict, number> }
  | { kind: "finalize"; kept: number; removed: number };

export interface Run {
  stages: Stage[];
  cost: number;
  serverT: number;
}

export const EMPTY_RUN: Run = { stages: [], cost: 0, serverT: 0 };

export function reduce(run: Run, e: AgentEvent): Run {
  const stages = [...run.stages];
  const last = () => stages[stages.length - 1];
  const replaceLast = (s: Stage) => (stages[stages.length - 1] = s);
  const next: Run = { ...run, stages };
  if ("cost_usd" in e) next.cost = e.cost_usd;
  if ("t" in e) next.serverT = e.t;

  switch (e.type) {
    case "step":
      if (e.step === "plan") stages.push({ kind: "plan", model: e.model, tools: [], checks: [] });
      if (e.step === "gather") stages.push({ kind: "gather", model: e.model, attempt: e.attempt ?? 1, tools: [] });
      if (e.step === "draft") {
        const attempt = stages.filter((s) => s.kind === "draft").length + 1;
        stages.push({ kind: "draft", model: e.model, notes: e.notes ?? 0, items: [], attempt });
      }
      if (e.step === "verify")
        stages.push({ kind: "verify", model: e.model, count: e.items ?? 0, done: false, retry: false });
      if (e.step === "finalize") stages.push({ kind: "finalize", kept: e.kept ?? 0, removed: e.removed ?? 0 });
      break;
    case "plan": {
      const s = last();
      if (s?.kind === "plan") replaceLast({ ...s, checks: e.checks });
      break;
    }
    case "tool_start": {
      const s = last();
      if (s?.kind === "plan" || s?.kind === "gather")
        replaceLast({ ...s, tools: [...s.tools, { tool: e.tool, args: e.args, by: e.by }] });
      break;
    }
    case "tool_end": {
      const s = last();
      if (s?.kind === "plan" || s?.kind === "gather") {
        const tools = [...s.tools];
        const i = tools.map((t) => t.tool).lastIndexOf(e.tool);
        if (i >= 0) tools[i] = { ...tools[i], summary: e.summary, ok: e.ok };
        replaceLast({ ...s, tools });
      }
      break;
    }
    case "draft": {
      const s = last();
      if (s?.kind === "draft")
        replaceLast({ ...s, headline: e.headline, items: e.items.map(({ severity, category, statement }) =>
          ({ severity, category, statement })) });
      break;
    }
    case "verdicts": {
      // Mark up the draft this verifier pass checked.
      const v = last();
      const d = stages.length > 1 ? stages[stages.length - 2] : undefined;
      const tally = { supported: 0, partially_supported: 0, unsupported: 0 } as Record<Verdict, number>;
      e.results.forEach((r) => (tally[r.verdict] += 1));
      if (v?.kind === "verify") replaceLast({ ...v, done: true, retry: e.retry, tally });
      if (d?.kind === "draft") {
        const items = d.items.map((item, i) => {
          const r = e.results.find((x) => x.index === i);
          return r ? { ...item, verdict: r.verdict, reason: r.reason } : item;
        });
        stages[stages.length - 2] = { ...d, items };
      }
      break;
    }
  }
  return next;
}

export const runFromEvents = (events: AgentEvent[]) => events.reduce(reduce, EMPTY_RUN);

/** For briefs saved before runs were recorded step by step: rebuild what can be known from the brief. */
export function eventsFromBrief(brief: Brief): AgentEvent[] {
  const run = brief.run;
  const m = run.models ?? {};
  const all = [...brief.items, ...brief.removed_claims];
  const base = { t: 0, cost_usd: run.cost_usd ?? 0 };
  const events: AgentEvent[] = [{ type: "step", step: "plan", model: m.plan, ...base }];
  events.push({ type: "step", step: "gather", model: m.gather, attempt: 1, ...base });
  for (const c of run.tool_calls ?? []) {
    const args = Object.fromEntries(Object.entries(c.args).filter(([k]) => k !== "participant_id"));
    events.push({ type: "tool_start", tool: c.tool, args, by: c.by, ...base });
    events.push({ type: "tool_end", tool: c.tool, args, by: c.by, ok: true, summary: "looked up", ...base });
  }
  events.push({ type: "step", step: "draft", model: m.draft, ...base });
  events.push({ type: "draft", headline: brief.headline, items: all.map((i) => ({ ...i })), ...base });
  events.push({ type: "step", step: "verify", model: m.verify, items: all.length, ...base });
  events.push({
    type: "verdicts", attempt: run.draft_attempts ?? 1, retry: false, ...base,
    results: all.map((i, index) => ({ index, verdict: i.verdict ?? "supported", reason: i.verifier_note ?? "",
                                       statement: i.statement })),
  });
  events.push({ type: "step", step: "finalize", kept: brief.items.length, removed: brief.removed_claims.length, ...base });
  return events;
}

export const traceOf = (brief: Brief) =>
  brief.run.trace?.length ? { events: brief.run.trace, recorded: true } : { events: eventsFromBrief(brief), recorded: false };

// ---------------------------------------------------------------- plain-language labels

export const modelName = (id?: string) =>
  id ? id.replace(/^claude-/, "Claude ").replace(/-(\d+)-(\d+)$/, " $1.$2").replace(/ (\w)/, (_, c: string) => ` ${c.toUpperCase()}`) : "";

export function toolLabel(tool: string, args: ToolArgs): string {
  const role = typeof args.author_role === "string" ? ` from the ${args.author_role}` : "";
  const since = typeof args.start_date === "string" ? ` since ${shortDate(args.start_date)}` : "";
  switch (tool) {
    case "get_participant_summary": return "Participant summary";
    case "get_notes": return `Notes${role}${since}`;
    case "search_notes": return args.query ? `Search notes for “${String(args.query)}”` : "Search notes (no search words given)";
    case "get_note": return `Open one note`;
    case "get_vitals": return args.kind && args.kind !== "all" ? `Vitals: ${String(args.kind)}` : "Vitals";
    case "get_encounters": return "ED visits and hospital stays";
    case "get_medication_changes": return "Medication changes";
    case "get_immunizations": return "Immunizations";
    default: return tool;
  }
}

const VERDICT_WORDS: Record<Verdict, string> = {
  supported: "supported",
  partially_supported: "partly supported",
  unsupported: "not supported",
};

// Shown under each step when the run is explained to someone new (the replay on each participant page).
const EXPLAIN = {
  plan: "A small, fast model reads who the participant is and writes a checklist of what to look for.",
  gather: "The agent asks for parts of the chart one at a time, through read-only lookups. It can only see what it asks for. Lookups marked “added by the code check” are ones the code made sure happened even though the model did not ask.",
  regather: "The checker rejected a claim, so the agent goes back to the chart to look for evidence before writing again.",
  draft: "A stronger model writes the brief from what was gathered. Every line has to point to the note or record it came from.",
  verify: "A second pass reads each line next to only the sources it points to. Highlighted lines are confirmed. Struck lines are not supported and never reach the team.",
  finalize: "Confirmed lines go to the clinician for review. Anything unsupported is removed and listed for audit.",
};

// ---------------------------------------------------------------- views

export function RunStages({ run, activeIndex, explain = false }: { run: Run; activeIndex: number; explain?: boolean }) {
  return (
    <ol className="stages">
      {run.stages.map((s, i) => {
        // Explain each kind of step once, the first time it appears.
        const first = run.stages.findIndex((x) => x.kind === s.kind && (x.kind !== "gather" || (s.kind === "gather" && x.attempt > 1) === (s.kind === "gather" && s.attempt > 1)));
        return <StageView key={i} stage={s} active={i === activeIndex} explain={explain && first === i} />;
      })}
    </ol>
  );
}

function StageView({ stage, active, explain }: { stage: Stage; active: boolean; explain: boolean }) {
  const cls = `stage stage-${stage.kind}${active ? " is-active" : " is-done"}`;
  const why = (text: string) => explain && <p className="stage-explain">{text}</p>;
  switch (stage.kind) {
    case "plan":
      return (
        <li className={cls}>
          <StageTitle title="Plan what to check" model={stage.model} active={active} />
          {why(EXPLAIN.plan)}
          <Tools rows={stage.tools} />
          {stage.checks.length > 0 && (
            <>
              <p className="stage-sub">The checklist it wrote</p>
              <ul className="checks">{stage.checks.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </>
          )}
        </li>
      );
    case "gather":
      return (
        <li className={cls}>
          <StageTitle title={stage.attempt > 1 ? "Go back to the chart for evidence" : "Read the chart"}
                      model={stage.model} active={active} />
          {why(stage.attempt > 1 ? EXPLAIN.regather : EXPLAIN.gather)}
          {!explain && stage.attempt > 1 && <p className="stage-why">{EXPLAIN.regather}</p>}
          <Tools rows={stage.tools} />
        </li>
      );
    case "draft":
      return (
        <li className={cls}>
          <StageTitle title={stage.attempt > 1 ? "Write the brief again" : "Write the brief"} model={stage.model} active={active} />
          {why(EXPLAIN.draft)}
          {stage.headline && <p className="draft-headline">{stage.headline}</p>}
          {stage.items.length > 0 && (
            <ul className="draft-items">
              {stage.items.map((item, i) => (
                <li key={i} className={item.verdict ? `v-${item.verdict}` : undefined}>
                  <span className={`sev sev-${item.severity}`}>{item.severity}</span>
                  <span className="draft-cat">{CATEGORY_LABELS[item.category] ?? item.category}</span>
                  <span className="draft-text"><span className="draft-mark">{item.statement}</span></span>
                  {item.verdict && item.verdict !== "supported" && (
                    <span className="draft-reason">{VERDICT_WORDS[item.verdict]}: {item.reason}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </li>
      );
    case "verify":
      return (
        <li className={cls}>
          <StageTitle title={`Check ${stage.count} line${stage.count === 1 ? "" : "s"} against their sources`} model={stage.model} active={active} />
          {why(EXPLAIN.verify)}
          {stage.tally && (
            <p className="stage-why">
              {stage.tally.supported} supported, {stage.tally.partially_supported} partly supported,{" "}
              {stage.tally.unsupported} not supported.
              {stage.retry && " The rejected lines go back for another pass."}
            </p>
          )}
        </li>
      );
    case "finalize":
      return (
        <li className={cls}>
          <StageTitle title="Keep what the sources support" active={false} />
          {why(EXPLAIN.finalize)}
          <p className="stage-why">
            {stage.kept} line{stage.kept === 1 ? "" : "s"} kept for the team
            {stage.removed ? `; ${stage.removed} removed and listed for audit` : ""}.
          </p>
        </li>
      );
  }
}

function StageTitle({ title, model, active }: { title: string; model?: string; active: boolean }) {
  return (
    <p className="stage-title">
      <span className="stage-dot" aria-hidden="true" />
      <span>{title}</span>
      {model && <span className="stage-model">{modelName(model)}</span>}
      {active && <span className="visually-hidden"> (in progress)</span>}
    </p>
  );
}

function Tools({ rows }: { rows: ToolRow[] }) {
  if (!rows.length) return null;
  return (
    <ul className="tools">
      {rows.map((r, i) => (
        <li key={i} className={r.summary === undefined ? "is-pending" : r.ok === false ? "is-error" : undefined}>
          <span className="tool-name">
            {toolLabel(r.tool, r.args)}
            {r.by === "safety_net" && <span className="tool-by"> added by the code check</span>}
          </span>
          <span className="tool-result">{r.summary ?? "reading"}</span>
        </li>
      ))}
    </ul>
  );
}
