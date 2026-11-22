// Step 2: what the agent did, replayed from the run's recorded steps.
import { useEffect, useMemo, useRef, useState } from "react";
import type { Bundle } from "../types";
import { EMPTY_RUN, RunStages, modelName, reduce, runFromEvents, traceOf } from "./AgentRun";

export default function AgentReplay({ bundle }: { bundle: Bundle }) {
  const { brief, participant: p } = bundle;
  const run = brief.run;
  const { events, recorded } = useMemo(() => traceOf(brief), [brief]);
  const full = useMemo(() => runFromEvents(events), [events]);
  const [shownCount, setShownCount] = useState<number | null>(null); // null: show the whole run
  const timer = useRef<number | null>(null);

  useEffect(() => () => { if (timer.current) window.clearTimeout(timer.current); }, []);
  useEffect(() => { setShownCount(null); }, [brief]);

  if (run.sample) {
    return (
      <div className="agent-view">
        <p className="step-lead">
          This is a sample brief built straight from the answer key, so there is no agent run to show. Run the
          agent to replace the samples with real briefs and their recorded steps.
        </p>
      </div>
    );
  }

  const replay = () => {
    if (timer.current) window.clearTimeout(timer.current);
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduceMotion) return setShownCount(null);
    const step = (i: number) => {
      setShownCount(i);
      if (i >= events.length) {
        timer.current = window.setTimeout(() => setShownCount(null), 400);
        return;
      }
      const now = "t" in events[i - 1] ? (events[i - 1] as { t: number }).t : 0;
      const next = "t" in events[i] ? (events[i] as { t: number }).t : now;
      // Real timing, four times faster, so long model calls still read as waits.
      const wait = Math.min(1600, Math.max(140, ((next - now) * 1000) / 4));
      timer.current = window.setTimeout(() => step(i + 1), wait);
    };
    step(1);
  };

  const shown = shownCount === null ? full : events.slice(0, shownCount).reduce(reduce, EMPTY_RUN);
  const replaying = shownCount !== null;
  const lookups = (run.tool_calls?.length ?? 0) + 1;
  const drafts = run.draft_attempts ?? 1;
  const models = run.models ?? {};

  return (
    <div className="agent-view">
      <p className="step-lead">
        {recorded
          ? `This is the agent’s run for ${p.first_name}, recorded step by step as it made the brief. `
          : `This brief was made before runs were recorded step by step, so this view rebuilds the lookups and the checker’s verdicts from the saved brief. `}
        Two Claude models share the work: {modelName(models.plan)} plans and reads the chart, and{" "}
        {modelName(models.draft)} writes the brief and checks it.
      </p>

      <dl className="run-facts">
        <div><dt>Chart lookups</dt><dd>{lookups}</dd></div>
        <div><dt>Drafts</dt><dd>{drafts}</dd></div>
        <div><dt>Model calls</dt><dd>{run.llm_calls ?? "–"}</dd></div>
        <div><dt>Time</dt><dd>{run.seconds ? `${Math.round(run.seconds)} s` : "–"}</dd></div>
        <div><dt>Cost</dt><dd>{run.cost_usd != null ? `$${run.cost_usd.toFixed(3)}` : "–"}</dd></div>
      </dl>

      {recorded && (
        <div className="replay-bar">
          <button type="button" className="button" onClick={replay} disabled={replaying}>
            {replaying ? "Replaying" : "Replay the run"}
          </button>
          {replaying && <button type="button" className="button-quiet" onClick={() => {
            if (timer.current) window.clearTimeout(timer.current);
            setShownCount(null);
          }}>Show the whole run</button>}
          <span className="live-meter replay-meter">
            <span>{shown.serverT.toFixed(1)} s</span>
            <span>${shown.cost.toFixed(3)}</span>
          </span>
        </div>
      )}

      <div className="agent-stages" aria-live={replaying ? "polite" : "off"}>
        <RunStages run={shown} activeIndex={replaying ? shown.stages.length - 1 : -1} explain />
      </div>
    </div>
  );
}
