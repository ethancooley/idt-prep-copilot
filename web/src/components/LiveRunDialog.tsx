import { useEffect, useMemo, useRef, useState } from "react";
import { CATEGORY_LABELS, LIVE_API_URL, shortDate } from "../lib";
import type { Bundle, Severity, Verdict } from "../types";

// ---------------------------------------------------------------- events from /live-run/stream

type ToolArgs = Record<string, unknown>;
type AgentEvent =
  | { type: "start"; name: string; runs_left_today: number; models: Record<string, string> }
  | { type: "heartbeat" }
  | { type: "step"; step: "plan" | "gather" | "draft" | "verify" | "finalize"; t: number; cost_usd: number;
      model?: string; attempt?: number; notes?: number; items?: number; kept?: number; removed?: number }
  | { type: "plan"; checks: string[]; t: number; cost_usd: number }
  | { type: "tool_start"; tool: string; args: ToolArgs; by: string; t: number; cost_usd: number }
  | { type: "tool_end"; tool: string; args: ToolArgs; by: string; ok: boolean; summary: string; t: number;
      cost_usd: number }
  | { type: "draft"; headline: string; t: number; cost_usd: number;
      items: { severity: Severity; category: string; statement: string; citations: string[] }[] }
  | { type: "verdicts"; attempt: number; retry: boolean; t: number; cost_usd: number;
      results: { index: number; verdict: Verdict; reason: string; statement: string }[] }
  | { type: "done"; bundle: Bundle }
  | { type: "error"; message: string };

// ---------------------------------------------------------------- the run, shaped for display

interface ToolRow { tool: string; args: ToolArgs; by: string; summary?: string; ok?: boolean }
interface DraftItem { severity: Severity; category: string; statement: string; verdict?: Verdict; reason?: string }
type Stage =
  | { kind: "plan"; model?: string; tools: ToolRow[]; checks: string[] }
  | { kind: "gather"; model?: string; attempt: number; tools: ToolRow[] }
  | { kind: "draft"; model?: string; notes: number; headline?: string; items: DraftItem[] }
  | { kind: "verify"; model?: string; count: number; done: boolean; retry: boolean;
      tally?: Record<Verdict, number> }
  | { kind: "finalize"; kept: number; removed: number };

interface Run {
  stages: Stage[];
  cost: number;
  serverT: number;
  bundle?: Bundle;
  error?: string;
}

function reduce(run: Run, e: AgentEvent): Run {
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
      if (e.step === "draft") stages.push({ kind: "draft", model: e.model, notes: e.notes ?? 0, items: [] });
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
      // Mark up the draft this verifier pass checked: the signature moment of the run.
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
    case "done":
      next.bundle = e.bundle;
      break;
    case "error":
      next.error = e.message;
      break;
  }
  return next;
}

// ---------------------------------------------------------------- plain-language labels

const modelName = (id?: string) =>
  id ? id.replace(/^claude-/, "").replace(/-(\d+)-(\d+)$/, " $1.$2").replace(/^\w/, (c) => c.toUpperCase()) : "";

function toolLabel(tool: string, args: ToolArgs): string {
  const role = typeof args.author_role === "string" ? ` from the ${args.author_role}` : "";
  const since = typeof args.start_date === "string" ? ` since ${shortDate(args.start_date)}` : "";
  switch (tool) {
    case "get_participant_summary": return "Participant summary";
    case "get_notes": return `Notes${role}${since}`;
    case "search_notes": return `Search notes for “${String(args.query ?? "")}”`;
    case "get_note": return `Open note ${String(args.note_id ?? "")}`;
    case "get_vitals": return args.kind && args.kind !== "all" ? `Vitals: ${String(args.kind)}` : "Vitals";
    case "get_encounters": return "Visits and hospital encounters";
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

// ---------------------------------------------------------------- dialog

interface Props {
  participantId: string;
  name: string;
  onClose: () => void;
  onDone: (bundle: Bundle) => void;
}

const EMPTY: Run = { stages: [], cost: 0, serverT: 0 };

export default function LiveRunDialog({ participantId, name, onClose, onDone }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  const abort = useRef<AbortController | null>(null);
  const follow = useRef(true);
  const [code, setCode] = useState("");
  const [phase, setPhase] = useState<"ask" | "running" | "finished">("ask");
  const [formError, setFormError] = useState<string | null>(null);
  const [run, setRun] = useState<Run>(EMPTY);
  const [started, setStarted] = useState(0);
  const [now, setNow] = useState(0);
  const [runsLeft, setRunsLeft] = useState<number | null>(null);

  useEffect(() => {
    ref.current?.showModal();
    return () => abort.current?.abort();
  }, []);

  useEffect(() => {
    if (phase !== "running") return;
    const t = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(t);
  }, [phase]);

  // Follow the newest step unless the reader has scrolled up to look at something.
  useEffect(() => {
    const el = logRef.current;
    if (el && follow.current) el.scrollTop = el.scrollHeight;
  }, [run]);
  const onLogScroll = () => {
    const el = logRef.current;
    if (el) follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const controller = new AbortController();
    abort.current = controller;
    let response: Response;
    try {
      response = await fetch(`${LIVE_API_URL}/live-run/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ participant_id: participantId, access_code: code.trim() }),
        signal: controller.signal,
      });
    } catch {
      setFormError("Could not reach the live-run server. Saved briefs are still available.");
      return;
    }
    if (!response.ok || !response.body) {
      const body = await response.json().catch(() => ({}));
      setFormError(body.error ?? `The live run could not start (status ${response.status}).`);
      return;
    }

    setRun(EMPTY);
    setStarted(performance.now());
    setNow(performance.now());
    setPhase("running");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffered = "";
    let current = EMPTY;
    const apply = (event: AgentEvent) => {
      if (event.type === "heartbeat") return;
      if (event.type === "start") return setRunsLeft(event.runs_left_today);
      current = reduce(current, event);
      setRun(current);
    };
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffered += decoder.decode(value, { stream: true });
        const lines = buffered.split("\n");
        buffered = lines.pop() ?? "";
        for (const line of lines) if (line.trim()) apply(JSON.parse(line) as AgentEvent);
      }
      if (buffered.trim()) apply(JSON.parse(buffered) as AgentEvent);
      if (!current.bundle && !current.error) {
        current = { ...current, error: "The connection closed before the brief was finished." };
        setRun(current);
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      current = { ...current, error: err instanceof Error ? `The stream broke: ${err.message}` : "The stream broke." };
      setRun(current);
    }
    setNow(performance.now());
    setPhase("finished");
  }

  const seconds = phase === "ask" ? 0 : Math.max(run.serverT, (now - started) / 1000);
  const activeIndex = phase === "running" ? run.stages.length - 1 : -1;
  const removedCount = useMemo(() => run.bundle?.brief.removed_claims.length ?? 0, [run.bundle]);

  return (
    <dialog ref={ref} className={`dialog${phase === "ask" ? "" : " dialog-live"}`} onClose={onClose}
            aria-labelledby="live-title">
      {phase === "ask" ? (
        <form onSubmit={start}>
          <h2 id="live-title">Watch Claude build a brief for {name}</h2>
          <p>
            The agent reads {name}’s chart from scratch and writes a new brief while you watch: its plan, every
            chart lookup, the draft, and the verifier checking each claim against its source. It takes about 30
            seconds. Live runs need an access code and are limited each day.
          </p>
          <label htmlFor="access-code">Access code</label>
          <input id="access-code" type="password" autoComplete="off" value={code}
                 onChange={(e) => setCode(e.target.value)} required />
          {formError && <p className="form-error" role="alert">{formError}</p>}
          <div className="dialog-actions">
            <button type="button" className="button-quiet" onClick={() => ref.current?.close()}>Cancel</button>
            <button type="submit" className="button" disabled={!code.trim()}>Start the agent</button>
          </div>
        </form>
      ) : (
        <div className="live">
          <header className="live-head">
            <h2 id="live-title">
              {phase === "running" ? `Building a brief for ${name}` : run.error ? "The run stopped" : `Brief ready for ${name}`}
            </h2>
            <p className="live-meter" aria-label="Elapsed time and cost">
              <span>{seconds.toFixed(1)} s</span>
              <span>${run.cost.toFixed(3)}</span>
            </p>
          </header>

          <div className="live-log" ref={logRef} onScroll={onLogScroll} aria-live="polite" aria-busy={phase === "running"}>
            {run.stages.length === 0 && <p className="live-wait">Connecting to the agent</p>}
            <ol className="stages">
              {run.stages.map((s, i) => (
                <StageView key={i} stage={s} active={i === activeIndex} />
              ))}
            </ol>
            {run.error && <p className="form-error" role="alert">{run.error}</p>}
          </div>

          <footer className="live-foot">
            <p className="live-note">
              {phase === "running" && "Closing this window does not stop the run; it still counts toward today’s limit."}
              {phase === "finished" && run.bundle &&
                `${run.bundle.brief.items.length} items kept${removedCount ? `, ${removedCount} removed by the verifier` : ""}.` +
                (runsLeft !== null ? ` ${runsLeft} live run${runsLeft === 1 ? "" : "s"} left today.` : "")}
            </p>
            <div className="dialog-actions">
              {phase === "running" && (
                <button type="button" className="button-quiet" onClick={() => ref.current?.close()}>Stop watching</button>
              )}
              {phase === "finished" && (
                <>
                  <button type="button" className="button-quiet" onClick={() => ref.current?.close()}>Close</button>
                  {run.bundle && (
                    <button type="button" className="button" autoFocus onClick={() => onDone(run.bundle!)}>
                      Open the brief
                    </button>
                  )}
                </>
              )}
            </div>
          </footer>
        </div>
      )}
    </dialog>
  );
}

// ---------------------------------------------------------------- one stage of the run

function StageView({ stage, active }: { stage: Stage; active: boolean }) {
  const cls = `stage stage-${stage.kind}${active ? " is-active" : " is-done"}`;
  switch (stage.kind) {
    case "plan":
      return (
        <li className={cls}>
          <StageTitle title="Plan what to check" model={stage.model} active={active} />
          <Tools rows={stage.tools} />
          {stage.checks.length > 0 && (
            <ul className="checks">{stage.checks.map((c, i) => <li key={i}>{c}</li>)}</ul>
          )}
        </li>
      );
    case "gather":
      return (
        <li className={cls}>
          <StageTitle title={stage.attempt > 1 ? "Go back to the chart for evidence" : "Read the chart through MCP tools"}
                      model={stage.model} active={active} />
          {stage.attempt > 1 && <p className="stage-why">The verifier rejected a claim, so the agent looks for evidence before redrafting.</p>}
          <Tools rows={stage.tools} />
        </li>
      );
    case "draft":
      return (
        <li className={cls}>
          <StageTitle title={`Draft the brief from ${stage.notes} notes and the records`} model={stage.model} active={active} />
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
          <StageTitle title={`Check ${stage.count} claims against their cited sources`} model={stage.model} active={active} />
          {stage.tally && (
            <p className="stage-why">
              {stage.tally.supported} supported, {stage.tally.partially_supported} partly supported,{" "}
              {stage.tally.unsupported} not supported.
              {stage.retry && " Sending the rejected claims back for another pass."}
            </p>
          )}
        </li>
      );
    case "finalize":
      return (
        <li className={cls}>
          <StageTitle title="Keep what the sources support" active={false} />
          <p className="stage-why">
            {stage.kept} items kept{stage.removed ? `; ${stage.removed} removed and listed for audit` : ""}.
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
