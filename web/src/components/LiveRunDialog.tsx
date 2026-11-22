import { useEffect, useMemo, useRef, useState } from "react";
import { LIVE_API_URL } from "../lib";
import type { AgentEvent, Bundle } from "../types";
import { EMPTY_RUN, reduce, RunStages, type Run as AgentRun } from "./AgentRun";

interface Run extends AgentRun {
  bundle?: Bundle;
  error?: string;
}

function applyEvent(run: Run, e: AgentEvent): Run {
  if (e.type === "done") return { ...run, bundle: e.bundle };
  if (e.type === "error") return { ...run, error: e.message };
  return { ...run, ...reduce(run, e) };
}

// ---------------------------------------------------------------- dialog

interface Props {
  participantId: string;
  name: string;
  onClose: () => void;
  onDone: (bundle: Bundle) => void;
}

const EMPTY: Run = EMPTY_RUN;

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
  const [personal, setPersonal] = useState(false);

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
      if (event.type === "start") {
        setPersonal(!!event.code);
        return setRunsLeft(event.code ? event.code.runs_left : event.runs_left_today);
      }
      current = applyEvent(current, event);
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
            <RunStages run={run} activeIndex={activeIndex} />
            {run.error && <p className="form-error" role="alert">{run.error}</p>}
          </div>

          <footer className="live-foot">
            <p className="live-note">
              {phase === "running" && "Closing this window does not stop the run; it still counts toward today’s limit."}
              {phase === "finished" && run.bundle &&
                `${run.bundle.brief.items.length} items kept${removedCount ? `, ${removedCount} removed by the verifier` : ""}.` +
                (runsLeft !== null ? ` ${runsLeft} live run${runsLeft === 1 ? "" : "s"} left ${personal ? "on your code" : "today"}.` : "")}
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
