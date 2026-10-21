import { useEffect, useRef } from "react";
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from "react-router";
import { Logo } from "./components/Logo";
import { InvestigationWorkspace } from "./features/investigations/InvestigationWorkspace";
import { InvestigationHistory } from "./features/history/InvestigationHistory";
import { SavedInvestigation } from "./features/history/SavedInvestigation";
import { UsageDashboard } from "./features/usage/UsageDashboard";
import styles from "./App.module.css";

function WorkspaceRoutes() {
  const location = useLocation();
  const main = useRef<HTMLElement>(null);
  const previousPath = useRef(location.pathname);
  useEffect(() => {
    if (previousPath.current !== location.pathname) {
      main.current?.focus();
      window.scrollTo(0, 0);
      previousPath.current = location.pathname;
    }
    document.title =
      location.pathname === "/"
        ? "Incident Investigator"
        : location.pathname === "/usage"
          ? "Usage · Incident Investigator"
          : "Investigations · Incident Investigator";
  }, [location.pathname]);
  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">
        Skip to content
      </a>
      <aside className={styles.sidebar}>
        <div className={styles.brand}>
          <Logo />
          <span>
            Incident
            <br />
            Investigator
          </span>
        </div>
        <nav aria-label="Main navigation">
          <NavLink to="/" end>
            ↗ <span>New investigation</span>
          </NavLink>
          <NavLink to="/investigations">
            ≡ <span>Investigations</span>
          </NavLink>
          <NavLink to="/usage">
            ▥ <span>Usage</span>
          </NavLink>
        </nav>
        <div className={styles.sidebarFooter}>
          <span className={styles.localDot} /> Local demo
          <p>
            Evidence first.
            <br />
            Conclusions with context.
          </p>
        </div>
      </aside>
      <main id="main" ref={main} tabIndex={-1} className={styles.main}>
        <header className={styles.header}>
          <span>WORKSPACE / LOCAL</span>
          <span>Read-only investigation</span>
        </header>
        <Routes>
          <Route path="/" element={<InvestigationWorkspace />} />
          <Route path="/investigations" element={<InvestigationHistory />} />
          <Route path="/investigations/:id" element={<SavedInvestigation />} />
          <Route path="/usage" element={<UsageDashboard />} />
          <Route
            path="*"
            element={
              <div className={styles.notFound}>
                <h1>Page not found</h1>
                <Link to="/">Start a new investigation</Link>
              </div>
            }
          />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <WorkspaceRoutes />
    </BrowserRouter>
  );
}
