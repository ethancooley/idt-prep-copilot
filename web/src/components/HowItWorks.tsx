import { Link } from "react-router-dom";
import { REPO_URL, pct } from "../lib";
import type { Index } from "../types";

export default function HowItWorks({ index }: { index: Index }) {
  const ev = index.evaluation;
  return (
    <div className="page prose-page">
      <h1>How IDT Prep works</h1>
      <p className="lede">
        PACE care teams meet regularly to review each participant. Before that meeting, someone has to read weeks of
        notes from nursing, therapy, social work, nutrition, the day center, and home care to find what changed. IDT
        Prep does that first read and shows its work, so the team can trust it or correct it.
      </p>

      <h2>Four steps for every brief</h2>
      <ol className="steps">
        <li>
          <h3>Plan</h3>
          <p>Claude reads the participant's conditions and medications and decides what to check: falls, hospital
            visits, weight, function, mood, caregivers, and anything specific to their diagnoses.</p>
        </li>
        <li>
          <h3>Gather</h3>
          <p>Claude reads the chart only through a set of read-only tools served over the Model Context Protocol (MCP).
            Code makes sure the essential tools always run and that every call stays on the right participant.</p>
        </li>
        <li>
          <h3>Draft</h3>
          <p>Claude writes a structured brief. Every line must cite the notes or records that support it, and events
            from before the last review must not be reported as new.</p>
        </li>
        <li>
          <h3>Verify</h3>
          <p>Code rejects citations that do not exist. Then Claude checks each line against only its cited sources.
            Lines that fail go back for more evidence once, and are removed if they still cannot be supported.</p>
        </li>
      </ol>
      <p>A clinician then approves, edits, or rejects each line, and every decision is recorded.</p>
      <p>
        On any participant’s page, <strong>Watch the agent build one live</strong> runs these four steps from
        scratch and streams each one as it happens: the plan, every chart lookup and what it returned, the draft,
        and the verifier highlighting the claims it confirmed and striking the ones it could not. Live runs need
        an access code.
      </p>

      <h2>How it was tested</h2>
      <p>
        The 40 participants are synthetic. Their base records come from Synthea, and a generator adds 90 days of
        interdisciplinary notes with known events: falls, ED visits, medication changes, weight loss, new confusion,
        and more, plus older events that should not be reported as new. Because the generator knows what it planted,
        every participant has an answer key.
      </p>
      <p>
        A brief gets credit for an item only when one of its lines cites a note that proves it, so scoring is
        automatic and cannot be gamed by vague wording.
      </p>
      {ev ? (
        <table className="results">
          <caption>Latest evaluation across {ev.participants} participants</caption>
          <tbody>
            <tr><th scope="row">Answer-key items caught</th><td>{pct(ev.recall)}</td></tr>
            <tr><th scope="row">High-severity items caught</th><td>{pct(ev.high_severity_recall)}</td></tr>
            <tr><th scope="row">Briefs that caught everything</th><td>{ev.perfect_briefs} of {ev.participants}</td></tr>
            <tr><th scope="row">Old events reported as new</th><td>{ev.distractor_violations}</td></tr>
            <tr><th scope="row">Claims removed by the verifier</th><td>{ev.removed_claims}</td></tr>
            <tr><th scope="row">Cost per brief</th><td>${ev.cost_usd_per_brief.toFixed(3)}</td></tr>
            <tr><th scope="row">Time per brief (median)</th><td>{Math.round(ev.seconds_median)} seconds</td></tr>
          </tbody>
        </table>
      ) : (
        <p className="notice">Evaluation results appear here after the agent is run against the answer keys.</p>
      )}

      <h2>What it does not do</h2>
      <p>
        IDT Prep surfaces information for the team. It does not diagnose, recommend treatment, or make decisions, and
        nothing reaches the meeting packet until a person approves it.
      </p>

      <p className="prose-links">
        <Link to="/">Open the review queue</Link> or read the <a href={REPO_URL}>source code and evaluation details</a>.
      </p>
    </div>
  );
}
