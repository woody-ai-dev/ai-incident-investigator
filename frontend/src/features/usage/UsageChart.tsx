import { useState, type CSSProperties } from "react";
import type { UsageDashboardData } from "../../api/usage";
import { dollars } from "./presentation";
import styles from "./Usage.module.css";

type Props = { daily: UsageDashboardData["daily"] };

export function UsageChart({ daily }: Props) {
  const [metric, setMetric] = useState<"cost" | "tokens">("cost");
  const values = daily.map((day) =>
    metric === "cost" ? Number(day.estimated_cost_usd) : day.total_tokens,
  );
  const maximum = Math.max(...values, 0);
  const format = (value: number) =>
    metric === "cost" ? dollars(value) : value.toLocaleString("en-US");
  return (
    <section className={styles.panel} aria-label="Daily usage">
      <div className={styles.panelHeader}>
        <div>
          <h2>Usage over time</h2>
          <p>Daily totals · UTC · today is still in progress</p>
        </div>
        <div className={styles.toggle} aria-label="Chart metric">
          {(["cost", "tokens"] as const).map((value) => (
            <button key={value} aria-pressed={metric === value} onClick={() => setMetric(value)}>
              {value === "cost" ? "Cost" : "Tokens"}
            </button>
          ))}
        </div>
      </div>
      <div className={styles.chart} key={metric}>
        <div className={styles.axis} aria-hidden="true">
          <span>{format(maximum)}</span>
          <span>{format(0)}</span>
        </div>
        <div className={styles.plot}>
          {daily.map((day, index) => {
            const value = values[index] ?? 0;
            const known = metric === "cost" ? day.priced_calls : day.reported_calls;
            const missing = day.calls - known;
            const label = `${day.day}: ${known === 0 && day.calls > 0 ? "not available" : format(value)}${missing > 0 ? `; ${missing} call(s) missing data` : ""}`;
            const height = maximum === 0 ? 0 : (value / maximum) * 100;
            return (
              <div
                className={styles.column}
                key={day.day}
                style={
                  { "--position": `${((index + 0.5) / daily.length) * 100}%` } as CSSProperties
                }
              >
                <button type="button" className={styles.barTarget} aria-label={label}>
                  <span
                    className={styles.bar}
                    data-missing={missing > 0}
                    style={{ height: `${height}%`, "--delay": `${index * 18}ms` } as CSSProperties}
                  />
                  {missing > 0 && (
                    <span className={styles.missingMark} aria-hidden="true">
                      ·
                    </span>
                  )}
                  <span className={styles.tooltip} role="tooltip">
                    {label}
                  </span>
                </button>
                <span className={styles.day} aria-hidden="true">
                  {daily.length <= 7 || index % 5 === 0 || index === daily.length - 1
                    ? day.day.slice(5)
                    : ""}
                </span>
              </div>
            );
          })}
        </div>
      </div>
      {daily.some(
        (day) => day.calls > (metric === "cost" ? day.priced_calls : day.reported_calls),
      ) && (
        <p className={styles.note}>
          Dotted bars indicate incomplete totals. Missing usage is not counted as zero.
        </p>
      )}
    </section>
  );
}
