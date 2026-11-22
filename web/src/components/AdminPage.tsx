// The admin console: make personal access codes for live runs, see how each is used, and turn them off.
// Not linked from the navigation; open /#/admin. Everything here needs the admin password, which is kept
// only for this browser tab (sessionStorage) and sent to the live-run API as a bearer token.
import { useCallback, useEffect, useState } from "react";
import { LIVE_API_URL, longDate } from "../lib";
import { Meter } from "./charts";

interface CodeRecord {
  id: number;
  label: string;
  max_runs: number;
  max_cost_usd: number;
  runs_used: number;
  cost_used_usd: number;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  last_used_at: string | null;
  state: "active" | "used_up" | "expired" | "revoked";
}
interface RunRecord {
  created_at: string;
  status: string;
  cost_usd: number | null;
  seconds: number | null;
  participant: string | null;
  code_label: string;
}
interface RunsResponse { runs: RunRecord[]; today: { runs: number; cost_usd: number; limit: number } }

const STATE_LABEL: Record<CodeRecord["state"], string> = {
  active: "Active", used_up: "Used up", expired: "Expired", revoked: "Turned off",
};
const TOKEN_KEY = "idt-admin-token";

function readToken(): string {
  try { return sessionStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}
function saveToken(t: string) {
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* fine */ }
}
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "Never");
const money = (x: number) => `$${x.toFixed(2)}`;

export default function AdminPage() {
  const [token, setToken] = useState(readToken);
  const [codes, setCodes] = useState<CodeRecord[] | null>(null);
  const [runs, setRuns] = useState<RunsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<{ code: string; record: CodeRecord } | null>(null);

  const call = useCallback(async (method: string, path: string, body?: unknown) => {
    const r = await fetch(`${LIVE_API_URL}${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (r.status === 401) { saveToken(""); setToken(""); }
    if (!r.ok) throw new Error(data.error ?? `The request failed (status ${r.status}).`);
    return data;
  }, [token]);

  const refresh = useCallback(async () => {
    try {
      const [c, r] = await Promise.all([call("GET", "/admin/codes"), call("GET", "/admin/runs")]);
      setCodes(c.codes);
      setRuns(r);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [call]);

  useEffect(() => { if (token && LIVE_API_URL) void refresh(); }, [token, refresh]);

  if (!LIVE_API_URL) {
    return (
      <div className="page admin">
        <header className="page-head"><div><h1>Access codes</h1></div></header>
        <p className="notice">The admin console needs the live-run API. Build the site with VITE_LIVE_API_URL set.</p>
      </div>
    );
  }
  if (!token) return <SignIn onSignIn={(t) => { saveToken(t); setToken(t); }} error={error} />;

  const active = codes?.filter((c) => c.state === "active").length ?? 0;
  const spentAll = codes?.reduce((a, c) => a + c.cost_used_usd, 0) ?? 0;

  return (
    <div className="page admin">
      <header className="page-head">
        <div>
          <h1>Access codes</h1>
          <p className="page-sub">Give each person their own code for live runs, with its own limits. Turn any code off at any time.</p>
        </div>
        <div className="brief-tools">
          <button type="button" className="button-quiet" onClick={refresh}>Refresh</button>
          <button type="button" className="button-quiet" onClick={() => { saveToken(""); setToken(""); setCodes(null); }}>Sign out</button>
        </div>
      </header>

      {error && <p className="notice" role="alert">{error}</p>}

      <section className="tiles" aria-label="Live runs at a glance">
        <div className="tile tile-hero">
          <p className="tile-label">Active codes</p>
          <p className="tile-hero-value">{codes ? active : "–"}</p>
          <p className="tile-note">of {codes?.length ?? 0} made</p>
        </div>
        <div className="tile">
          <p className="tile-label">Live runs today</p>
          <p className="tile-value">{runs?.today.runs ?? "–"}<span className="tile-of"> of {runs?.today.limit ?? 20}</span></p>
          {runs && <Meter value={runs.today.runs} max={runs.today.limit} label="Live runs used today" />}
          <p className="tile-note">The daily limit covers every code</p>
        </div>
        <div className="tile">
          <p className="tile-label">Spent today</p>
          <p className="tile-value">{runs ? money(runs.today.cost_usd) : "–"}</p>
          <p className="tile-note">Claude usage for live runs</p>
        </div>
        <div className="tile">
          <p className="tile-label">Spent on codes</p>
          <p className="tile-value">{codes ? money(spentAll) : "–"}</p>
          <p className="tile-note">across every personal code</p>
        </div>
      </section>

      <div className="admin-grid">
        <CreateCode onCreate={async (input) => {
          const data = await call("POST", "/admin/codes", input);
          setCreated(data);
          void refresh();
        }} />
        {created ? <NewCode code={created.code} record={created.record} onDone={() => setCreated(null)} /> : (
          <section className="panel" aria-labelledby="send-heading">
            <div className="panel-head">
              <h2 id="send-heading">Sending a code</h2>
              <p>A new code shows here once, with a message ready to paste. Only a fingerprint of each code is stored, so it can’t be looked up later. If someone loses theirs, make a new one.</p>
            </div>
          </section>
        )}
      </div>

      <section className="queue-section" aria-labelledby="codes-heading">
        <div className="queue-top"><h2 id="codes-heading">Codes</h2></div>
        <div className="table-wrap admin-table">
          <table className="queue-table">
            <thead>
              <tr>
                <th scope="col">For</th>
                <th scope="col">Status</th>
                <th scope="col">Runs</th>
                <th scope="col">Spending</th>
                <th scope="col">Expires</th>
                <th scope="col">Last used</th>
                <th scope="col"><span className="visually-hidden">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {codes?.map((c) => (
                <tr key={c.id} className="no-link">
                  <td data-label="For"><strong>{c.label}</strong><span className="cell-sub">Made {when(c.created_at)}</span></td>
                  <td data-label="Status"><span className={`review-chip code-${c.state}`}>{STATE_LABEL[c.state]}</span></td>
                  <td data-label="Runs">
                    <span className="usage">{c.runs_used} of {c.max_runs}</span>
                    <Meter value={c.runs_used} max={c.max_runs} label={`Runs used by ${c.label}`} />
                  </td>
                  <td data-label="Spending">
                    <span className="usage">{money(c.cost_used_usd)} of {money(c.max_cost_usd)}</span>
                    <Meter value={c.cost_used_usd} max={c.max_cost_usd} label={`Spending by ${c.label}`} />
                  </td>
                  <td data-label="Expires">{c.expires_at ? longDate(c.expires_at.slice(0, 10)) : "Never"}</td>
                  <td data-label="Last used">{when(c.last_used_at)}</td>
                  <td data-label="Actions">
                    {c.state !== "revoked" && <RevokeButton label={c.label} onRevoke={async () => {
                      await call("POST", `/admin/codes/${c.id}/revoke`);
                      void refresh();
                    }} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {codes?.length === 0 && <div className="table-empty"><p>No codes yet. Make the first one above.</p></div>}
        </div>
      </section>

      <section className="queue-section admin-runs" aria-labelledby="runs-heading">
        <div className="queue-top"><h2 id="runs-heading">Recent live runs</h2></div>
        <div className="table-wrap admin-table">
          <table className="queue-table">
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Participant</th>
                <th scope="col">Code</th>
                <th scope="col">Result</th>
                <th scope="col" className="num">Time</th>
                <th scope="col" className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {runs?.runs.map((r, i) => (
                <tr key={i} className="no-link">
                  <td data-label="When">{when(r.created_at)}</td>
                  <td data-label="Participant">{r.participant ?? "Unknown"}</td>
                  <td data-label="Code">{r.code_label}</td>
                  <td data-label="Result">{r.status === "ok" ? "Finished" : r.status === "failed" ? "Failed" : "Running"}</td>
                  <td data-label="Time" className="num">{r.seconds ? `${r.seconds.toFixed(0)} s` : "–"}</td>
                  <td data-label="Cost" className="num">{r.cost_usd != null ? `$${r.cost_usd.toFixed(3)}` : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {runs?.runs.length === 0 && <div className="table-empty"><p>No live runs yet.</p></div>}
        </div>
      </section>
    </div>
  );
}

// ---------------------------------------------------------------- pieces

function SignIn({ onSignIn, error }: { onSignIn: (t: string) => void; error: string | null }) {
  const [value, setValue] = useState("");
  return (
    <div className="page admin">
      <form className="panel signin" onSubmit={(e) => { e.preventDefault(); if (value.trim()) onSignIn(value.trim()); }}>
        <h1>Admin sign in</h1>
        <p className="page-sub">Enter the admin password to manage access codes for live runs. It’s kept only until you close this tab.</p>
        <label htmlFor="admin-token">Admin password</label>
        <input id="admin-token" type="password" autoComplete="current-password" value={value} onChange={(e) => setValue(e.target.value)} />
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="submit" className="button" disabled={!value.trim()}>Sign in</button>
      </form>
    </div>
  );
}

interface NewCodeInput { label: string; max_runs: number; max_cost_usd: number; expires_in_days: number | null }

function CreateCode({ onCreate }: { onCreate: (input: NewCodeInput) => Promise<void> }) {
  const [label, setLabel] = useState("");
  const [runs, setRuns] = useState(3);
  const [cost, setCost] = useState(5);
  const [days, setDays] = useState<string>("30");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <form className="panel admin-form" aria-labelledby="create-heading" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      setError(null);
      try {
        await onCreate({ label, max_runs: runs, max_cost_usd: cost, expires_in_days: days === "never" ? null : Number(days) });
        setLabel("");
      } catch (err) {
        setError((err as Error).message);
      } finally {
        setBusy(false);
      }
    }}>
      <div className="panel-head">
        <h2 id="create-heading">Make a code</h2>
        <p>A brief costs about $0.04, so $5 covers far more runs than most people use.</p>
      </div>
      <label className="field field-wide">
        <span>Who it’s for</span>
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. Emily Wang, Habitat Health" maxLength={80} required />
      </label>
      <label className="field">
        <span>Live runs</span>
        <input type="number" min={1} max={100} value={runs} onChange={(e) => setRuns(Number(e.target.value))} required />
      </label>
      <label className="field">
        <span>Spending limit ($)</span>
        <input type="number" min={0.1} max={50} step="any" value={cost} onChange={(e) => setCost(Number(e.target.value))} required />
      </label>
      <label className="field">
        <span>Expires</span>
        <select value={days} onChange={(e) => setDays(e.target.value)}>
          <option value="7">In 7 days</option>
          <option value="30">In 30 days</option>
          <option value="90">In 90 days</option>
          <option value="never">Never</option>
        </select>
      </label>
      {error && <p className="form-error field-wide" role="alert">{error}</p>}
      <div className="field-wide">
        <button type="submit" className="button" disabled={busy || !label.trim()}>{busy ? "Making the code" : "Make code"}</button>
      </div>
    </form>
  );
}

function NewCode({ code, record, onDone }: { code: string; record: CodeRecord; onDone: () => void }) {
  const site = `${window.location.origin}${window.location.pathname}`;
  const until = record.expires_at ? ` until ${longDate(record.expires_at.slice(0, 10))}` : "";
  const message =
    `Here's a personal access code to watch the IDT Prep agent build a brief live: ${code}\n\n` +
    `Open ${site}, pick any participant, and choose "Watch the agent build one live". ` +
    `It's good for ${record.max_runs} run${record.max_runs === 1 ? "" : "s"}${until}.`;
  const [copied, setCopied] = useState<"code" | "message" | null>(null);
  const copy = async (text: string, what: "code" | "message") => {
    try { await navigator.clipboard.writeText(text); setCopied(what); } catch { setCopied(null); }
  };
  return (
    <section className="panel new-code" aria-labelledby="new-heading" aria-live="polite">
      <div className="panel-head">
        <h2 id="new-heading">Code for {record.label}</h2>
        <p>This is the only time it’s shown. Copy it now.</p>
      </div>
      <p className="new-code-value"><span>{code}</span></p>
      <div className="brief-tools new-code-actions">
        <button type="button" className="button" onClick={() => copy(code, "code")}>{copied === "code" ? "Code copied" : "Copy code"}</button>
        <button type="button" className="button-quiet" onClick={() => copy(message, "message")}>{copied === "message" ? "Message copied" : "Copy message"}</button>
        <button type="button" className="link-button" onClick={onDone}>Done</button>
      </div>
      <label className="field field-wide">
        <span>Message to send</span>
        <textarea readOnly rows={5} value={message} onFocus={(e) => e.currentTarget.select()} />
      </label>
    </section>
  );
}

function RevokeButton({ label, onRevoke }: { label: string; onRevoke: () => Promise<void> }) {
  const [confirming, setConfirming] = useState(false);
  if (!confirming) {
    return <button type="button" className="link-button" onClick={() => setConfirming(true)}>Turn off</button>;
  }
  return (
    <span className="revoke-confirm">
      <button type="button" className="button-small button-danger" onClick={() => onRevoke()}>Turn off {label.split(",")[0]}’s code</button>
      <button type="button" className="link-button" onClick={() => setConfirming(false)}>Cancel</button>
    </span>
  );
}
