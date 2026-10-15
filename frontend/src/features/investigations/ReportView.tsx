import { useId, useRef, useState } from "react";
import { flushSync } from "react-dom";
import type { Evidence, InvestigationReport, InvestigationRequest } from "../../api/contracts";
import styles from "./Investigation.module.css";

const analysisLabels = {
  not_requested: "AI analysis disabled",
  skipped: "AI analysis skipped",
  completed: "AI analysis completed",
  failed: "AI analysis failed",
};

function timestamp(value: string): string {
  const formatted = new Intl.DateTimeFormat("en-GB", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: "UTC",
  }).format(new Date(value));
  // Keep source precision: Date and Intl formatting otherwise drop microseconds.
  const fraction = value.match(/\.(\d+)(?:Z|[+-])/i)?.[1]?.slice(0, 6);
  return fraction ? `${formatted}.${fraction}` : formatted;
}

function exportReport(request: InvestigationRequest, report: InvestigationReport) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify({ schema_version: 1, request, report }, null, 2)], {
      type: "application/json",
    }),
  );
  const link = document.createElement("a");
  link.href = url;
  link.download = "investigation-report.json";
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

type Props = { report: InvestigationReport; request: InvestigationRequest };

export function ReportView({ report, request }: Props) {
  const [view, setView] = useState<"evidence" | "analysis" | "gaps">("evidence");
  const [selection, setSelection] = useState<{
    report: InvestigationReport;
    id: string;
  } | null>(null);
  const detailId = useId();
  const detail = useRef<HTMLElement>(null);
  const invoker = useRef<HTMLButtonElement | null>(null);
  // Reused IDs in a new report must not reopen the previous evidence selection.
  if (selection !== null && selection.report !== report) setSelection(null);
  const selectedId = selection?.report === report ? selection.id : null;
  const selected = report.evidence.find((item) => item.id === selectedId);
  const historical = report.evidence.filter((item) => item.source !== "actuator");
  const snapshots = report.evidence.filter((item) => item.source === "actuator");

  function selectEvidence(id: string, button: HTMLButtonElement) {
    if (!report.evidence.some((item) => item.id === id)) return;
    invoker.current = button;
    // Commit the new detail content before measuring its viewport position.
    flushSync(() => setSelection({ report, id }));
    const panel = detail.current;
    if (!panel?.isConnected) return;
    panel.focus({ preventScroll: true });
    const bounds = panel.getBoundingClientRect();
    if (
      bounds.top < 0 ||
      bounds.bottom > window.innerHeight ||
      bounds.left < 0 ||
      bounds.right > window.innerWidth
    ) {
      const reduceMotion =
        typeof window.matchMedia === "function" &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      panel.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "nearest" });
    }
  }

  function closeEvidence() {
    if (invoker.current?.isConnected) invoker.current.focus();
    invoker.current = null;
    setSelection(null);
  }

  function references(ids: string[], label = "Evidence") {
    return (
      <div className={styles.references}>
        <span>{label}:</span>
        {ids.map((id) => (
          <button
            type="button"
            key={id}
            aria-pressed={selectedId === id}
            aria-controls={detailId}
            onClick={(event) => selectEvidence(id, event.currentTarget)}
          >
            {id}
          </button>
        ))}
      </div>
    );
  }

  function observations(items: Evidence[]) {
    return items.length ? (
      <ul className={styles.evidenceList}>
        {[...items]
          .sort((a, b) => Date.parse(a.start_time) - Date.parse(b.start_time))
          .map((item) => (
            <li key={item.id}>
              <button
                type="button"
                className={styles.evidenceRow}
                aria-pressed={selectedId === item.id}
                aria-controls={detailId}
                onClick={(event) => selectEvidence(item.id, event.currentTarget)}
              >
                <span className={styles.sourceBadge}>{item.source}</span>
                <span>
                  <strong>{item.summary}</strong>
                  <small>
                    {timestamp(item.start_time)} UTC · {item.id}
                  </small>
                </span>
                <span aria-hidden="true">↗</span>
              </button>
            </li>
          ))}
      </ul>
    ) : (
      <p className={styles.empty}>No observations returned.</p>
    );
  }

  return (
    <section className={styles.report} aria-label="Investigation report">
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>INVESTIGATION REPORT</span>
          <h2>
            {request.service} <span className={styles.muted}>/ {request.environment}</span>
          </h2>
        </div>
        <button
          type="button"
          className={styles.secondaryButton}
          onClick={() => exportReport(request, report)}
        >
          Export JSON
        </button>
      </div>
      <p className={styles.muted}>
        {timestamp(request.start_time)} → {timestamp(request.end_time)} UTC · end excluded
      </p>
      <span className={styles.status} data-failed={report.analysis_status === "failed"}>
        {analysisLabels[report.analysis_status]}
      </span>
      <p className={styles.summary}>{report.summary}</p>
      <nav className={styles.views} aria-label="Report sections">
        {(["evidence", "analysis", "gaps"] as const).map((item) => (
          <button
            type="button"
            key={item}
            aria-pressed={view === item}
            onClick={() => setView(item)}
          >
            {item === "gaps"
              ? `Data gaps (${report.missing_data.length})`
              : item === "evidence"
                ? `Evidence (${report.evidence.length})`
                : "Analysis & checks"}
          </button>
        ))}
      </nav>
      <div className={styles.reportLayout}>
        <div>
          {view === "evidence" && (
            <>
              <h3>Historical observations</h3>
              {observations(historical)}
              <h3>Current application context</h3>
              <p className={styles.muted}>
                Actuator describes its observation time, not the incident window.
              </p>
              {observations(snapshots)}
            </>
          )}
          {view === "analysis" && (
            <>
              <h3>Findings</h3>
              {report.findings.length ? (
                report.findings.map((item, index) => (
                  <article key={index} className={styles.conclusion}>
                    <p>{item.statement}</p>
                    {references(item.evidence_ids)}
                  </article>
                ))
              ) : (
                <p className={styles.empty}>
                  No findings returned. {analysisLabels[report.analysis_status]}.
                </p>
              )}
              <h3>Hypotheses</h3>
              {report.hypotheses.length ? (
                report.hypotheses.map((item, index) => (
                  <article key={index} className={styles.conclusion}>
                    <p>{item.statement}</p>
                    {references(item.supporting_evidence_ids, "Supports")}
                    {item.contradicting_evidence_ids.length > 0 &&
                      references(item.contradicting_evidence_ids, "Contradicts")}
                  </article>
                ))
              ) : (
                <p className={styles.empty}>No hypotheses returned.</p>
              )}
              <h3>Recommended checks</h3>
              {report.recommended_checks.length ? (
                <ol className={styles.checks}>
                  {report.recommended_checks.map((item, index) => (
                    <li key={index}>
                      <strong>{item.action}</strong>
                      <p>{item.reason}</p>
                    </li>
                  ))}
                </ol>
              ) : (
                <p className={styles.empty}>No recommended checks returned.</p>
              )}
              {report.analysis_status === "completed" && (
                <p className={styles.muted}>
                  Model conclusions require engineering review; a completed analysis does not prove
                  the cause.
                </p>
              )}
            </>
          )}
          {view === "gaps" &&
            (report.missing_data.length ? (
              <ul className={styles.gaps}>
                {report.missing_data.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            ) : (
              <p className={styles.empty}>No data gaps reported.</p>
            ))}
        </div>
        <aside
          ref={detail}
          id={detailId}
          tabIndex={-1}
          className={styles.detail}
          aria-label="Evidence details"
        >
          {selected ? (
            <>
              <div className={styles.sectionHeading}>
                <h3>Evidence details</h3>
                <button type="button" className={styles.textButton} onClick={closeEvidence}>
                  Close
                </button>
              </div>
              <span className={styles.sourceBadge}>{selected.source}</span>
              <h4>{selected.id}</h4>
              <p>{selected.summary}</p>
              <dl>
                <dt>Service</dt>
                <dd>{selected.service}</dd>
                <dt>Observed / start</dt>
                <dd>{timestamp(selected.start_time)} UTC</dd>
                {selected.end_time && (
                  <>
                    <dt>End</dt>
                    <dd>{timestamp(selected.end_time)} UTC</dd>
                  </>
                )}
                <dt>Source reference</dt>
                <dd>
                  <code>{selected.reference}</code>
                </dd>
              </dl>
              <p className={styles.muted}>
                References identify source data. Internal addresses may only work inside Compose.
              </p>
            </>
          ) : (
            <>
              <span className={styles.eyebrow}>SOURCE CONTEXT</span>
              <h3>Follow the evidence</h3>
              <p className={styles.muted}>
                Select an observation or a reference from a finding to inspect its source and
                timestamp.
              </p>
            </>
          )}
        </aside>
      </div>
    </section>
  );
}
