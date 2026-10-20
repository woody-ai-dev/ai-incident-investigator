import { useId, useRef, useState } from "react";
import type { InvestigationReport } from "../../api/contracts";
import styles from "./SourceFlow.module.css";

interface SourceFlowProps {
  phase: "idle" | "loading" | "success" | "error";
  report?: InvestigationReport;
}

const sources = [
  {
    name: "Logs",
    source: "log",
    y: 18,
    description:
      "Historical JSONL records matching the requested service, environment, and incident window.",
  },
  {
    name: "Metrics",
    source: "metric",
    y: 90,
    description:
      "Historical Prometheus observations for the incident window. Aggregated metrics do not identify an individual request.",
  },
  {
    name: "Actuator",
    source: "actuator",
    y: 162,
    description:
      "Current application identity and health snapshots. Their retrieval times can fall outside the incident window.",
  },
] as const;
type Source = (typeof sources)[number]["source"];
const paths = [
  "M182 44 C250 44 250 116 310 116",
  "M182 116 H310",
  "M182 188 C250 188 250 116 310 116",
  "M454 116 H510",
];
const analysisLabels = {
  not_requested: "LLM disabled",
  skipped: "LLM skipped",
  completed: "LLM completed",
  failed: "LLM failed",
};

function evidenceCount(count: number) {
  return count === 0 ? "No evidence" : `${count} evidence item${count === 1 ? "" : "s"}`;
}

export function SourceFlow({ phase, report }: SourceFlowProps) {
  const captionId = useId();
  const [hovered, setHovered] = useState<Source | null>(null);
  const [focused, setFocused] = useState<{ source: Source; keyboard: boolean } | null>(null);
  const pointerFocus = useRef<string | null>(null);
  const active = hovered ?? focused?.source ?? null;
  const current = phase === "success" ? report : undefined;
  const [receipt, setReceipt] = useState({ report: current, revision: 0 });
  // A fresh response remounts the CSS signal even when loading was too brief to render.
  if (current && receipt.report !== current) {
    setReceipt({ report: current, revision: receipt.revision + 1 });
  }
  const pending =
    phase === "loading" ? "Awaiting report" : phase === "error" ? "No report" : "Not requested";
  const counts = sources.map((source) => {
    const count = current?.evidence.filter((item) => item.source === source.source).length ?? 0;
    return { ...source, count, label: current ? evidenceCount(count) : pending };
  });
  const signalPaths = paths
    .map((path, index) => ({
      path,
      source: sources[index]?.source ?? "report",
      count: index === 3 ? (current?.evidence.length ?? 0) : (counts[index]?.count ?? 0),
    }))
    .filter((item) => phase === "loading" || item.count > 0);
  const total = current ? evidenceCount(current.evidence.length) : pending;
  const analysis = current ? analysisLabels[current.analysis_status] : pending;
  const activeSource = counts.find((item) => item.source === active);
  const stateLabel = {
    idle: "Ready to investigate",
    loading: "Awaiting response",
    success: "Report received",
    error: "Request failed",
  }[phase];
  const phaseDescription = {
    idle: "Start an investigation to collect evidence from the configured sources.",
    loading:
      "Waiting for the API. Moving signals show a pending request, not individual source progress.",
    success:
      "The signal highlights the returned evidence. “No evidence” does not mean a source is offline.",
    error: "No report was received; source availability cannot be inferred.",
  }[phase];

  function clearHover() {
    setHovered(null);
    if (pointerFocus.current && pointerFocus.current !== "touch") {
      setFocused(null);
      pointerFocus.current = null;
    }
  }

  function startPointerFocus(pointerType: string, source?: Source) {
    pointerFocus.current = pointerType || "mouse";
    setFocused(pointerType === "touch" && source ? { source, keyboard: false } : null);
  }

  return (
    <figure className={styles.card} aria-describedby={captionId}>
      <div className={styles.heading}>
        <div>
          <span className={styles.eyebrow}>SOURCE CONTEXT</span>
          <h2>Evidence flow</h2>
        </div>
        <span className={styles.badge}>{stateLabel}</span>
      </div>
      <svg
        className={`${styles.diagram} ${phase === "loading" ? styles.loading : ""}`}
        viewBox="0 0 660 232"
        role="img"
        aria-label={`${counts.map((item) => `${item.name}: ${item.label}`).join(". ")}. Evidence: ${total}. Report: ${analysis}.`}
      >
        {paths.map((path, index) => (
          <path
            key={path}
            d={path}
            className={styles.path}
            data-source={sources[index]?.source ?? "report"}
            data-active={active !== null && (index === 3 || active === sources[index]?.source)}
          />
        ))}
        {(phase === "loading" || current) && (
          <g
            key={phase === "loading" ? "pending" : receipt.revision}
            aria-hidden="true"
            data-flow-signal={phase === "loading" ? "pending" : "received"}
          >
            {signalPaths.map((item) => (
              <path
                key={`signal-${item.path}`}
                d={item.path}
                pathLength="100"
                data-signal-source={item.source}
                className={`${styles.signal} ${current ? styles.receipt : styles.pending}`}
              />
            ))}
          </g>
        )}
        {counts.map((item) => (
          <g
            key={item.source}
            data-source={item.source}
            className={styles.sourceGroup}
            onPointerEnter={() => setHovered(item.source)}
            onPointerLeave={clearHover}
            onPointerDown={(event) => startPointerFocus(event.pointerType)}
          >
            <title>
              {item.name}: {item.label}. {item.description}
            </title>
            <rect
              x="18"
              y={item.y}
              width="164"
              height="52"
              rx="10"
              className={styles.node}
              data-active={active === item.source}
            />
            <circle
              cx="34"
              cy={item.y + 20}
              r="3"
              className={styles.dot}
              data-empty={Boolean(current) && item.count === 0}
            />
            <text x="46" y={item.y + 24} className={styles.title}>
              {item.name}
            </text>
            <text x="34" y={item.y + 42} className={styles.detail}>
              {item.label}
            </text>
          </g>
        ))}
        <rect
          x="310"
          y="90"
          width="144"
          height="52"
          rx="10"
          className={styles.node}
          data-active={active !== null}
        />
        <text x="382" y="113" textAnchor="middle" className={styles.title}>
          Evidence
        </text>
        <text x="382" y="132" textAnchor="middle" className={styles.detail}>
          {total}
        </text>
        <rect
          x="510"
          y="90"
          width="132"
          height="52"
          rx="10"
          className={styles.reportNode}
          data-active={active !== null}
        />
        <text x="576" y="113" textAnchor="middle" className={styles.title}>
          Report
        </text>
        <text x="576" y="132" textAnchor="middle" className={styles.detail}>
          {analysis}
        </text>
      </svg>
      <figcaption id={captionId} className={styles.caption}>
        <p className={styles.counts}>
          {counts.map((item) => (
            <button
              key={item.source}
              type="button"
              className={styles.sourceControl}
              aria-label={`${item.name}: ${item.label}. Show source details.`}
              aria-describedby={`${captionId}-${item.source}`}
              data-active={active === item.source}
              data-focus-visible={focused?.source === item.source && focused.keyboard}
              onPointerEnter={() => setHovered(item.source)}
              onPointerLeave={clearHover}
              onPointerDown={(event) => startPointerFocus(event.pointerType, item.source)}
              onFocus={(event) => {
                if (
                  pointerFocus.current === "touch" ||
                  (!pointerFocus.current && event.currentTarget.matches(":focus-visible"))
                ) {
                  setHovered(null);
                  setFocused({ source: item.source, keyboard: pointerFocus.current !== "touch" });
                }
              }}
              onBlur={() => {
                pointerFocus.current = null;
                setFocused(null);
              }}
              onKeyDown={() => {
                pointerFocus.current = null;
                setHovered(null);
                setFocused({ source: item.source, keyboard: true });
              }}
            >
              <strong>{item.name}:</strong> {item.label}
            </button>
          ))}
        </p>
        {counts.map((item) => (
          <span key={item.source} id={`${captionId}-${item.source}`} className={styles.srOnly}>
            {item.description}
          </span>
        ))}
        <div className={styles.context} role="note" aria-label="Source context">
          {activeSource ? (
            <>
              <strong>
                {activeSource.name} · {activeSource.label}
              </strong>
              <p>{activeSource.description}</p>
            </>
          ) : (
            <>
              <strong>Explore the sources</strong>
              <p>
                Hover over a source, focus its button with Tab, or tap it to explore the context.
              </p>
            </>
          )}
        </div>
        <p>Logs and metrics cover the incident window. Actuator provides current snapshots.</p>
        <p className={styles.phaseDescription}>{phaseDescription}</p>
      </figcaption>
    </figure>
  );
}
