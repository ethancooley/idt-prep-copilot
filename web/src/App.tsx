import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import BriefPage from "./components/BriefPage";
import HowItWorks from "./components/HowItWorks";
import Queue from "./components/Queue";
import { loadIndex, REPO_URL } from "./lib";
import type { Index } from "./types";

export default function App() {
  const [index, setIndex] = useState<Index | null>(null);
  const [error, setError] = useState<string | null>(null);
  const { pathname } = useLocation();

  useEffect(() => {
    loadIndex().then(setIndex, (e: Error) => setError(e.message));
  }, []);
  useEffect(() => window.scrollTo(0, 0), [pathname]);

  return (
    <>
      <a className="skip" href="#main">Skip to content</a>
      <p className="synthetic">
        Every participant here is synthetic. No real patient data is used.
      </p>
      <header className="site-header">
        <Link to="/" className="wordmark" aria-label="IDT Prep home">
          <span className="wordmark-mark" aria-hidden="true" />
          IDT Prep
        </Link>
        <nav aria-label="Main">
          <NavLink to="/" end>Review queue</NavLink>
          <NavLink to="/how-it-works">How it works</NavLink>
          <a href={REPO_URL}>Source code</a>
        </nav>
      </header>
      <main id="main">
        {error && <p className="notice">{error} Refresh the page to try again.</p>}
        {!error && !index && <p className="loading">Loading the review queue</p>}
        {index && (
          <Routes>
            <Route path="/" element={<Queue index={index} />} />
            <Route path="/p/:id" element={<BriefPage index={index} />} />
            <Route path="/how-it-works" element={<HowItWorks index={index} />} />
            <Route path="*" element={<p className="notice">That page does not exist. <Link to="/">Go to the review queue</Link>.</p>} />
          </Routes>
        )}
      </main>
      <footer className="site-footer">
        <p>
          Built by Ethan Cooley as a portfolio project. Synthetic PACE participants generated with Synthea.
          Briefs drafted by Claude, checked against their sources, and approved by a person.
        </p>
      </footer>
    </>
  );
}
