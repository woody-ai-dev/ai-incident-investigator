import { useCallback, useState } from "react";
import { Link } from "react-router";
import { getUsage, type UsageSort, type UsageDashboardData } from "../../api/usage";
import { useReadResource } from "../history/useReadResource";
import { UsageChart } from "./UsageChart";
import { dollars, duration } from "./presentation";
import styles from "./Usage.module.css";

export function UsageDashboard() {
  const [days, setDays] = useState(7);
  const [sort, setSort] = useState<UsageSort>("tokens");
  const load = useCallback((signal: AbortSignal) => getUsage(days, sort, signal), [days, sort]);
  const result = useReadResource(`${days}/${sort}`, load);
  const [snapshot, setSnapshot] = useState<{ days: number; data: UsageDashboardData } | null>(null);
  if (result.status === "success" && (result.data !== snapshot?.data || snapshot.days !== days)) {
    setSnapshot({ days, data: result.data });
  }
  const data =
    result.status === "success" ? result.data : snapshot?.days === days ? snapshot.data : null;
  const number = (value: number) => value.toLocaleString("en-US");
  return (
    <div className={styles.page}>
      <div className={styles.heading}>
        <div>
          <h1>Usage</h1>
          <p>Model usage recorded in saved investigations.</p>
        </div>
        <div className={styles.toggle} aria-label="Usage period">
          {[7, 30].map((value) => (
            <button key={value} aria-pressed={days === value} onClick={() => setDays(value)}>
              Last {value} days
            </button>
          ))}
        </div>
      </div>
      {result.status === "loading" && data === null && (
        <p className={styles.panel} role="status">
          Loading usage…
        </p>
      )}
      {result.status === "error" && (
        <div className={styles.panel}>
          <p role="alert">{result.error.message}</p>
          <button onClick={result.retry}>Try again</button>
        </div>
      )}
      {data !== null && (
        <>
          <div className={styles.cards}>
            <article className={styles.card}>
              <span>Estimated cost</span>
              <strong>
                {dollars(
                  data.totals.priced_calls === 0 && data.totals.calls > 0
                    ? null
                    : data.totals.estimated_cost_usd,
                )}
              </strong>
              <small>
                {data.totals.priced_calls} of {data.totals.calls} calls priced · USD
              </small>
            </article>
            <article className={styles.card}>
              <span>Tokens</span>
              <strong>
                {data.totals.reported_calls === 0 && data.totals.calls > 0
                  ? "Not available"
                  : number(data.totals.total_tokens)}
              </strong>
              <small>
                {data.totals.reported_calls === 0 && data.totals.calls > 0 ? (
                  "Token counts were not returned"
                ) : (
                  <>
                    {number(data.totals.input_tokens)} input · {number(data.totals.output_tokens)}{" "}
                    output
                    {data.totals.reported_calls < data.totals.calls &&
                      ` · ${data.totals.reported_calls} of ${data.totals.calls} calls reported`}
                  </>
                )}
              </small>
            </article>
            <article className={styles.card}>
              <span>Model calls</span>
              <strong>{number(data.totals.calls)}</strong>
              <small>Includes unsuccessful analysis attempts</small>
            </article>
          </div>
          {data.totals.calls === 0 ? (
            <section className={styles.panel}>
              <h2>No recorded model calls</h2>
              <p>Run an investigation with AI analysis enabled to start collecting usage.</p>
              <Link to="/">New investigation →</Link>
            </section>
          ) : (
            <>
              <UsageChart key={days} daily={data.daily} />
              <section
                className={styles.panel}
                aria-label="Largest analyses"
                aria-busy={result.status === "loading"}
              >
                <div className={styles.panelHeader}>
                  <div>
                    <h2>Largest analyses</h2>
                    <p>Find the requests behind your usage.</p>
                  </div>
                  <div className={styles.toggle} aria-label="Rank analyses by">
                    {(["tokens", "cost", "duration"] as const).map((value) => (
                      <button
                        key={value}
                        aria-pressed={sort === value}
                        onClick={() => setSort(value)}
                      >
                        {value === "duration" ? "Time" : value === "tokens" ? "Tokens" : "Cost"}
                      </button>
                    ))}
                  </div>
                </div>
                {result.status !== "success" ? (
                  <p role="status">
                    {result.status === "loading"
                      ? "Updating ranking…"
                      : "Ranking could not be updated."}
                  </p>
                ) : data.largest.length === 0 ? (
                  <p>No calls have data for this ranking.</p>
                ) : (
                  <div className={styles.tableWrap}>
                    <table className={styles.table}>
                      <caption>Top five model calls · times in UTC</caption>
                      <thead>
                        <tr>
                          <th scope="col">Investigation</th>
                          <th scope="col">Tokens</th>
                          <th scope="col">Cost</th>
                          <th scope="col">Time</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.largest.map((item) => (
                          <tr key={item.investigation_id}>
                            <td>
                              <Link to={`/investigations/${item.investigation_id}`}>
                                {item.service} →
                              </Link>
                              <small>
                                {item.environment} ·{" "}
                                {new Date(item.started_at).toLocaleString("en-GB", {
                                  timeZone: "UTC",
                                })}
                              </small>
                            </td>
                            <td>
                              {item.total_tokens === null
                                ? "Not available"
                                : number(item.total_tokens)}
                            </td>
                            <td>{dollars(item.estimated_cost_usd)}</td>
                            <td>{duration(item.duration_ms)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}
          <p className={styles.note}>
            Estimates cover saved calls from this application, not your provider invoice. Older
            investigations without usage are excluded.
          </p>
        </>
      )}
    </div>
  );
}
