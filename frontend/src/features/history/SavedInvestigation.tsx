import { useCallback, useState } from "react";
import { Link, useLocation, useParams } from "react-router";
import { getInvestigation } from "../../api/history";
import { ReportView } from "../investigations/ReportView";
import { SourceFlow } from "../investigations/SourceFlow";
import { analysisLabels, savedTime } from "./presentation";
import { useReadResource } from "./useReadResource";
import styles from "./History.module.css";

export function SavedInvestigation() {
  const { id = "" } = useParams();
  return <SavedInvestigationPage key={id} id={id} />;
}

function SavedInvestigationPage({ id }: { id: string }) {
  const location = useLocation();
  const load = useCallback((signal: AbortSignal) => getInvestigation(id, signal), [id]);
  const result = useReadResource(id, load);
  const [copyStatus, setCopyStatus] = useState("");
  return (
    <>
      <div className={styles.heading}>
        <Link className={styles.backLink} to={`/investigations${location.search}`}>
          ← Back to investigations
        </Link>
        <h1>Saved investigation</h1>
        <p>This is the original saved snapshot. Sources and model analysis are not refreshed.</p>
      </div>
      {result.status === "loading" && (
        <p role="status" className={styles.card}>
          Loading saved investigation…
        </p>
      )}
      {result.status === "error" && (
        <div className={styles.card}>
          <p role="alert">{result.error.message}</p>
          <button onClick={result.retry}>Try again</button>
        </div>
      )}
      {result.status === "success" && (
        <>
          <div className={styles.share}>
            <button
              className={styles.copy}
              onClick={() => {
                const link = new URL(`/investigations/${id}`, window.location.origin).href;
                void navigator.clipboard?.writeText(link).then(
                  () => {
                    setCopyStatus("Link copied.");
                  },
                  () => {
                    setCopyStatus("Could not copy. Copy the address from your browser.");
                  },
                );
                if (!navigator.clipboard) setCopyStatus("Copy the address from your browser.");
              }}
            >
              Copy report link
            </button>
            <span role="status">{copyStatus}</span>
          </div>
          <section className={styles.card} aria-label="Saved metadata">
            <dl className={styles.metadata}>
              <div>
                <dt>Investigation ID</dt>
                <dd>{result.data.id}</dd>
              </div>
              <div>
                <dt>Saved at</dt>
                <dd>
                  <time dateTime={result.data.created_at}>{savedTime(result.data.created_at)}</time>
                </dd>
              </div>
              <div>
                <dt>Execution duration</dt>
                <dd>{result.data.duration_ms.toLocaleString()} ms</dd>
              </div>
              <div>
                <dt>Analysis</dt>
                <dd>{analysisLabels[result.data.report.analysis_status]}</dd>
              </div>
              <div>
                <dt>Configured model</dt>
                <dd>{result.data.configured_model ?? "None"}</dd>
              </div>
              <div>
                <dt>Prompt SHA-256</dt>
                <dd>{result.data.prompt_sha256 ?? "None"}</dd>
              </div>
            </dl>
          </section>
          <SourceFlow phase="success" report={result.data.report} />
          <ReportView key={id} request={result.data.request} report={result.data.report} />
        </>
      )}
    </>
  );
}
