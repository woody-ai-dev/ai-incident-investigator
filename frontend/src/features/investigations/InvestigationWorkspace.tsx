import { Link } from "react-router";
import { Logo } from "../../components/Logo";
import { SourceFlow } from "./SourceFlow";
import { InvestigationForm } from "./InvestigationForm";
import { ReportView } from "./ReportView";
import { useInvestigation } from "./useInvestigation";
import styles from "./InvestigationWorkspace.module.css";

export function InvestigationWorkspace() {
  const { state, lastResult, submit, cancel } = useInvestigation();
  return (
    <>
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
          {lastResult.id ? (
            <p className={styles.savedLink}>
              Saved to history.{" "}
              <Link to={`/investigations/${lastResult.id}`}>Open saved investigation →</Link>
            </p>
          ) : (
            <p className={styles.savedLink}>
              This report has no saved link. Enable PostgreSQL storage to keep future
              investigations.
            </p>
          )}
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
    </>
  );
}
