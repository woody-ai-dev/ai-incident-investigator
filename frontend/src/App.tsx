import { Logo } from "./components/Logo";
import { SourceFlow } from "./features/investigations/SourceFlow";
import { InvestigationForm } from "./features/investigations/InvestigationForm";
import { ReportView } from "./features/investigations/ReportView";
import { useInvestigation } from "./features/investigations/useInvestigation";
import styles from "./App.module.css";

export default function App() {
  const { state, lastResult, submit, cancel } = useInvestigation();
  return (
    <div className={styles.shell}>
      <a className={styles.skip} href="#main">
        Skip to investigation
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
          <a href="#main" aria-current="page">
            ↗ <span>Investigation</span>
          </a>
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
      <main id="main" className={styles.main}>
        <header className={styles.header}>
          <span>WORKSPACE / LOCAL</span>
          <span>Read-only investigation</span>
        </header>
        <div className={styles.title}>
          <p>FROM SIGNAL TO CONTEXT</p>
          <h1>Understand what happened.</h1>
          <span>Collect service evidence and inspect the reasoning behind each conclusion.</span>
        </div>
        <div className={styles.workspace}>
          <InvestigationForm
            phase={state.phase}
            evidenceCount={state.phase === "success" ? state.report.evidence.length : null}
            error={state.phase === "error" ? state.error : null}
            onSubmit={(request) => {
              void submit(request);
            }}
            onCancel={cancel}
          />
          <section aria-label="Evidence flow" className={styles.flowPanel}>
            <p className={styles.srOnly} role="status">
              {state.phase === "loading"
                ? "Waiting for the investigation report."
                : state.phase === "success"
                  ? "Investigation report received."
                  : ""}
            </p>
            <SourceFlow
              phase={state.phase}
              {...(state.phase === "success" ? { report: state.report } : {})}
            />
          </section>
        </div>
        {lastResult ? (
          <div>
            <p className={styles.resultStatus} role="status">
              {state.phase === "loading"
                ? "Showing the previous report while the new investigation runs."
                : state.phase === "error"
                  ? "The new investigation failed. Showing the last received report."
                  : state.phase === "idle"
                    ? "Investigation stopped. Showing the last received report."
                    : "Latest received report"}
            </p>
            <ReportView request={lastResult.request} report={lastResult.report} />
          </div>
        ) : (
          <div className={styles.placeholder}>
            <Logo />
            <h2>
              {state.phase === "loading"
                ? "Waiting for the investigation report…"
                : "Your evidence will appear here."}
            </h2>
            <p>
              {state.phase === "loading"
                ? "You can stop waiting. The server may still finish processing the request."
                : "Choose a service and time window to begin."}
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
