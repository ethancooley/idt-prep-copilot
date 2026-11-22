import { Link } from "react-router-dom";
import { REPO_URL, modelLabel } from "../lib";
import type { Index } from "../types";

export default function HowItWorks({ index }: { index: Index }) {
  const m = index.models ?? {};
  return (
    <div className="page how">
      <header className="page-head">
        <div>
          <h1>How it works</h1>
          <p className="page-sub">
            PACE care teams review each participant at least every six months. Before that meeting, someone has to read
            every note since the last one, from nursing, therapy, social work, nutrition, the day center, and home care,
            to find what changed. IDT Prep does that first read and shows its work, so the team can trust it or correct it.
          </p>
        </div>
      </header>

      <section className="panel method" aria-labelledby="steps-heading">
        <div className="panel-head">
          <h2 id="steps-heading">How each brief is made</h2>
          <p>An agent built with LangGraph runs these steps for every participant. A person approves the result.</p>
        </div>
        <ol className="method-steps">
          <li>
            <strong>Plan</strong>
            <p>{modelLabel(m.plan, "A fast Claude model")} reads the participant’s conditions and medications and writes a checklist: falls, hospital visits, weight, function, mood, caregivers, and anything specific to their diagnoses.</p>
          </li>
          <li>
            <strong>Read the chart</strong>
            <p>The agent looks up the chart one piece at a time through read-only tools served over the Model Context Protocol (MCP). Code makes sure the essential lookups always happen and that every call stays on the right participant.</p>
          </li>
          <li>
            <strong>Write</strong>
            <p>{modelLabel(m.draft, "A stronger Claude model")} drafts a structured brief. Every line must cite the note or record that supports it, and events from before the last review are left out.</p>
          </li>
          <li>
            <strong>Check</strong>
            <p>Code rejects citations that don’t exist. Then each line is checked against only its cited sources. Lines that fail go back for more evidence once, and are removed if they still can’t be supported.</p>
          </li>
        </ol>
      </section>

      <div className="overview">
        <section className="panel" aria-labelledby="trust-heading">
          <div className="panel-head">
            <h2 id="trust-heading">Why a team can trust it</h2>
          </div>
          <ul className="plain-list">
            <li><strong>No line without a source.</strong> Select any citation to read the note it came from, with the relevant sentences highlighted.</li>
            <li><strong>A second check on every line.</strong> Unsupported lines never reach the team, and are listed for audit.</li>
            <li><strong>It reads, it never writes.</strong> The agent can only look things up, and only in one participant’s chart.</li>
            <li><strong>A clinician makes the final call.</strong> Every approval, edit, and rejection is logged.</li>
            <li><strong>Nothing is hidden.</strong> Every participant page shows the chart, a replay of the agent’s run, and how it scored.</li>
          </ul>
        </section>
        <section className="panel" aria-labelledby="not-heading">
          <div className="panel-head">
            <h2 id="not-heading">What it doesn’t do</h2>
          </div>
          <ul className="plain-list">
            <li>It doesn’t diagnose, recommend treatment, or make decisions. It prepares a draft for the team.</li>
            <li>It hasn’t been tested on real charts. Every participant here is synthetic, built from Synthea records and generated notes.</li>
            <li>It isn’t connected to an EHR. A real deployment would read from the PACE organization’s records and keep the review log on a server.</li>
          </ul>
          <p className="panel-links">
            <Link to="/evaluation">See how it was tested</Link>
            <a href={REPO_URL}>Read the source code</a>
          </p>
        </section>
      </div>

      <section className="panel" aria-labelledby="live-heading">
        <div className="panel-head">
          <h2 id="live-heading">Watch it work</h2>
          <p>
            On any participant’s page, <strong>Watch the agent build one live</strong> runs every step from scratch and
            streams each one as it happens: the plan, every chart lookup and what came back, the draft, and the check of
            every line. Live runs need an access code.
          </p>
        </div>
      </section>
    </div>
  );
}
