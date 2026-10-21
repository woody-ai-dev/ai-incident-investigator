import { useCallback } from "react";
import { Link, useSearchParams } from "react-router";
import { listInvestigations } from "../../api/history";
import { analysisLabels, savedTime } from "./presentation";
import { useReadResource } from "./useReadResource";
import styles from "./History.module.css";
import { HistoryFilters } from "./HistoryFilters";

export function InvestigationHistory() {
  const [params] = useSearchParams();
  const search = params.toString();
  const load = useCallback((signal: AbortSignal) => listInvestigations(search, signal), [search]);
  const result = useReadResource(search, load);
  const next = new URLSearchParams(params);
  if (result.status === "success" && result.data.next_cursor)
    next.set("cursor", result.data.next_cursor);
  const first = new URLSearchParams(params);
  first.delete("cursor");
  return (
    <>
      <div className={styles.heading}>
        <h1>Investigations</h1>
        <p>
          Saved reports, newest first. Opening a report reads its snapshot and does not call the
          model.
        </p>
      </div>
      <HistoryFilters key={search} items={result.status === "success" ? result.data.items : []} />
      {result.status === "loading" && (
        <p role="status" className={styles.card}>
          Loading investigations…
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
          {result.data.items.length === 0 ? (
            <div className={styles.card}>
              <h2>No saved investigations</h2>
              <p className={styles.hint}>
                Try different filters or create an investigation with PostgreSQL storage enabled.
              </p>
              <Link to="/">New investigation</Link>
            </div>
          ) : (
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <caption className={styles.hint}>
                  Saved investigations · creation times in your browser timezone
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Created</th>
                    <th scope="col">Service / environment</th>
                    <th scope="col">Analysis</th>
                    <th scope="col">Report</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.items.map((item) => (
                    <tr key={item.id}>
                      <td data-label="Created">
                        <time dateTime={item.created_at}>{savedTime(item.created_at)}</time>
                        <small>{item.duration_ms.toLocaleString()} ms</small>
                      </td>
                      <td data-label="Service / environment">
                        {item.service}
                        <small>{item.environment}</small>
                      </td>
                      <td data-label="Analysis">
                        <span className={styles.status}>
                          {analysisLabels[item.analysis_status]}
                        </span>
                        <small>{item.configured_model ?? "No configured model"}</small>
                      </td>
                      <td className={styles.summary} data-label="Report">
                        <Link
                          to={`/investigations/${item.id}?${search}`}
                          aria-label={`Open investigation ${item.id}`}
                        >
                          Open report →
                        </Link>
                        <small className={styles.excerpt}>{item.summary}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <nav className={styles.pagination} aria-label="History pages">
            <span>
              {params.has("cursor") ? (
                <Link to={`?${first}`}>Newest results</Link>
              ) : (
                `${result.data.items.length} saved investigation(s)`
              )}
            </span>
            {result.data.next_cursor && <Link to={`?${next}`}>Older investigations →</Link>}
          </nav>
          <p className={styles.hint}>
            “Analysis completed” means a model response was accepted. It does not confirm that its
            conclusions are correct. A configured model may not have been called.
          </p>
        </>
      )}
    </>
  );
}
