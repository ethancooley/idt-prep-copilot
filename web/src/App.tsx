import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import AdminPage from "./components/AdminPage";
import BriefPage from "./components/BriefPage";
import Dashboard from "./components/Dashboard";
import EvaluationPage from "./components/EvaluationPage";
import HowItWorks from "./components/HowItWorks";
import { LIVE_API_URL, loadIndex, longDate, REPO_URL } from "./lib";
import type { Index } from "./types";

export default function App() {
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const { pathname } = useLocation();

  useEffect(() => {
    loadIndex().then(setIndex, (e: Error) => setError(e.message));
  }, []);
  useEffect(() => {
    window.scrollTo(0, 0);
    setMenuOpen(false);
  }, [pathname]);

  return (
    <div className="app">
      <a className="skip" href="#main">Skip to content</a>

      <aside className={`rail${menuOpen ? " is-open" : ""}`}>
        <div className="rail-top">
          <Link to="/" className="wordmark" aria-label="IDT Prep, review queue">
            <span className="wordmark-mark" aria-hidden="true" />
            <span>IDT Prep</span>
          </Link>
          <button type="button" className="rail-menu" aria-expanded={menuOpen} aria-controls="rail-nav"
                  onClick={() => setMenuOpen((o) => !o)}>
            {menuOpen ? "Close" : "Menu"}
          </button>
        </div>
        <nav id="rail-nav" aria-label="Main" className="rail-nav">
          <NavLink to="/" end><QueueIcon />Review queue</NavLink>
          <NavLink to="/evaluation"><GaugeIcon />Evaluation</NavLink>
          <NavLink to="/how-it-works"><FlowIcon />How it works</NavLink>
          <a href={REPO_URL} target="_blank" rel="noreferrer"><CodeIcon />Source code</a>
        </nav>
        <div className="rail-foot">
          <p className="rail-synthetic">
            <strong>Synthetic data only.</strong> Every participant and note here was generated for testing. No real
            patient data is used.
          </p>
          <p>Built by <a href="https://ethancooley.com">Ethan Cooley</a></p>
        </div>
      </aside>

      <div className="workspace">
        <header className="topbar">
          <p className="topbar-context">
            {index?.review_date ? (
              <>Interdisciplinary team review <strong>{longDate(index.review_date)}</strong></>
            ) : "Interdisciplinary team review"}
          </p>
          <div className="topbar-status">
            {index && (
              <span className="status-chip">
                <i className={index.source === "claude" ? "dot-ok" : "dot-muted"} aria-hidden="true" />
                {index.source === "claude" ? "Briefs drafted by Claude" : "Sample briefs"}
              </span>
            )}
            <span className="status-chip">
              <i className={LIVE_API_URL ? "dot-ok" : "dot-muted"} aria-hidden="true" />
              {LIVE_API_URL ? "Live runs available" : "Live runs off"}
            </span>
          </div>
        </header>

        <main id="main" tabIndex={-1}>
          {error && <p className="notice">{error} Refresh the page to try again.</p>}
          {!error && !index && <p className="loading">Loading the review queue</p>}
          {index && (
            <Routes>
              <Route path="/" element={<Dashboard index={index} />} />
              <Route path="/p/:id" element={<BriefPage index={index} />} />
              <Route path="/evaluation" element={<EvaluationPage index={index} />} />
              <Route path="/how-it-works" element={<HowItWorks index={index} />} />
              <Route path="/admin" element={<AdminPage />} />
              <Route path="*" element={<p className="notice">That page does not exist. <Link to="/">Go to the review queue</Link>.</p>} />
            </Routes>
          )}
        </main>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- navigation icons (decorative)

const Icon = ({ d }: { d: string }) => (
  <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" className="nav-icon">
    <path d={d} fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const QueueIcon = () => <Icon d="M3 5h14M3 10h14M3 15h9" />;
const GaugeIcon = () => <Icon d="M3.5 14a6.5 6.5 0 1 1 13 0M10 14l3.2-4.2M3.5 14h1.5M15 14h1.5" />;
const FlowIcon = () => <Icon d="M3 4h5v4H3zM12 12h5v4h-5zM5.5 8v3a2 2 0 0 0 2 2H12" />;
const CodeIcon = () => <Icon d="M7 6 3 10l4 4M13 6l4 4-4 4" />;
